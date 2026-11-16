"""发票 OCR 纯规则解析器（A1/F-08，Task 7）。

三级回落中的第二级：LLM 不可用/失败时，对 OCR 文本做正则抽取。
约束（brief）：纯正则、无第三方依赖、无 Django 依赖 —— 故可同时被
backend-django（funding 端点）与 svc_ai（/ai/invoice/ocr 网关）复用。

接口：
    parse_invoice_text(text: str) -> tuple[dict, float, list[str]]
返回 (fields, confidence, warnings)：
    fields 键为 camelCase：invoiceType / number / invoiceCode / sellerName /
    sellerTaxId / buyerName / buyerTaxId / amountExclTax / taxAmount /
    totalAmount / issueDate(YYYY-MM-DD)；金额一律两位小数字符串
    （契约 Money=string，全程 Decimal，无 float）。
    confidence ∈ [0, 0.99]：字段覆盖加权 + 金额自洽校验（|total-(excl+tax)|≤0.01）。
    warnings：中文告警（含「金额自洽」字样的自洽校验未通过告警）。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = ["parse_invoice_text", "FIELD_WEIGHTS"]

# 11 个契约字段权重（和恰为 1.00）：号码/价税合计最重，日期其次
FIELD_WEIGHTS: dict[str, float] = {
    "number": 0.18,
    "totalAmount": 0.14,
    "issueDate": 0.08,
    "amountExclTax": 0.10,
    "taxAmount": 0.10,
    "invoiceCode": 0.06,
    "sellerName": 0.07,
    "sellerTaxId": 0.07,
    "buyerName": 0.07,
    "buyerTaxId": 0.07,
    "invoiceType": 0.06,
}

_TAX_ID = r"[0-9A-Z]{15,20}"
_MONEY = r"([0-9][0-9,]*(?:\.[0-9]+)?)"

# 自洽容差：0.01 元（plan OCR 流程步骤 2）
_CONSISTENCY_TOLERANCE = Decimal("0.01")
# 置信度上限：永不给出 1.0（机器识别留有不确定性）
_CONFIDENCE_CAP = 0.99
# 金额自洽校验未通过时的置信度罚减
_INCONSISTENT_PENALTY = 0.25


def _dec(raw: str | None) -> Decimal | None:
    """金额字符串（去千分位）→ Decimal；非法返回 None。"""
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _money_str(d: Decimal | None) -> str | None:
    """Decimal → 两位小数字符串（Money=string 契约，无 float）。"""
    if d is None:
        return None
    return str(d.quantize(Decimal("0.01")))


def _first(text: str, patterns: list[str]) -> str | None:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


def _detect_invoice_type(text: str) -> str | None:
    # 票种判定顺序：行程单 → 专用 → 电子发票（数电票）→ 普通发票
    if "行程单" in text and "客票" in text:
        return "ITINERARY"
    if "专用发票" in text:
        return "SPECIAL"
    if "电子发票" in text:
        return "ELECTRONIC"
    if "普通发票" in text:
        return "GENERAL"
    return None


def _parse_issue_date(text: str) -> str | None:
    m = re.search(
        r"开票日期[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}"
    m = re.search(r"开票日期[:：]\s*(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _parse_tax_ids(text: str) -> tuple[str | None, str | None]:
    """纳税人识别号：优先带「购买方/销售方」前缀的行内标签；
    缺失时回退到按出现顺序的通用标签（第 1 个→购买方，第 2 个→销售方）。"""
    buyer = _first(text, [
        r"购买方(?:名称)?(?:统一社会信用代码/?纳税人识别号|纳税人识别号)[:：]\s*(" + _TAX_ID + r")",
        r"购买方[^\n:：]{0,24}[:：]\s*(" + _TAX_ID + r")",
    ])
    seller = _first(text, [
        r"销售方(?:名称)?(?:统一社会信用代码/?纳税人识别号|纳税人识别号)[:：]\s*(" + _TAX_ID + r")",
        r"销售方[^\n:：]{0,24}[:：]\s*(" + _TAX_ID + r")",
    ])
    if buyer is None or seller is None:
        generic = re.findall(
            r"(?:统一社会信用代码/?纳税人识别号|纳税人识别号)[:：]\s*(" + _TAX_ID + r")",
            text)
        if buyer is None and generic:
            buyer = generic[0]
        if seller is None and len(generic) > (0 if buyer is None else 1):
            seller = generic[-1]
    return buyer, seller


def _parse_amounts(text: str) -> tuple[str | None, str | None, str | None]:
    """(amountExclTax, taxAmount, totalAmount)，两位小数字符串或 None。

    金额/税额取「金额/税额」标签；缺失时回退「合计」行的前两个 ¥ 金额
    （第一个=不含税金额，第二个=税额）。价税合计取「（小写）」标注，
    缺失时取价税合计行最后一个 ¥ 金额。
    """
    excl_raw = _first(text, [r"金额\s*[:：]?\s*[¥￥]?\s*" + _MONEY])
    tax_raw = _first(text, [r"税额\s*[:：]?\s*[¥￥]?\s*" + _MONEY])
    if excl_raw is None or tax_raw is None:
        m = re.search(r"合\s*计([^\n]*)", text)
        if m:
            amts = re.findall(r"[¥￥]?\s*" + _MONEY, m.group(1))
            if len(amts) >= 2:
                if excl_raw is None:
                    excl_raw = amts[0]
                if tax_raw is None:
                    tax_raw = amts[1]
    total_raw = _first(text, [
        r"价税合计[^\n]*?[（(]\s*小写\s*[)）]\s*[¥￥]?\s*" + _MONEY,
        r"[（(]\s*小写\s*[)）]\s*[¥￥]?\s*" + _MONEY,
    ])
    if total_raw is None:
        m = re.search(r"价税合计([^\n]*)", text)
        if m:
            amts = re.findall(r"[¥￥]?\s*" + _MONEY, m.group(1))
            if amts:
                total_raw = amts[-1]
    return _money_str(_dec(excl_raw)), _money_str(_dec(tax_raw)), _money_str(_dec(total_raw))


def parse_invoice_text(text: str) -> tuple[dict, float, list[str]]:
    """规则解析 OCR 文本 → (fields, confidence, warnings)。"""
    warnings: list[str] = []
    raw = text or ""
    if not raw.strip():
        return {}, 0.0, ["ocr-text-empty：未提供可解析的发票文本"]

    # 归一化：仅折叠水平空白（含全角空格），保留换行
    t = re.sub(r"[^\S\n]+", " ", raw)

    fields: dict[str, str] = {}
    invoice_type = _detect_invoice_type(t)
    if invoice_type:
        fields["invoiceType"] = invoice_type
    for key, value in (
        ("number", _first(t, [r"发票号码[:：]\s*([0-9]{8,20})", r"No[.：:]\s*([0-9]{8,20})"])),
        ("invoiceCode", _first(t, [r"发票代码[:：]\s*([0-9]{10,12})"])),
        ("issueDate", _parse_issue_date(t)),
        ("totalAmount", None),
        ("amountExclTax", None),
        ("taxAmount", None),
    ):
        if value:
            fields[key] = value
    buyer_tax_id, seller_tax_id = _parse_tax_ids(t)
    if seller_tax_id:
        fields["sellerTaxId"] = seller_tax_id
    if buyer_tax_id:
        fields["buyerTaxId"] = buyer_tax_id
    seller_name = _first(t, [
        r"销售方名称[:：]\s*([^\s，,；;（(]{2,})",
        r"销售方[:：]\s*([^\s，,；;（(]{2,})",
    ])
    if seller_name:
        fields["sellerName"] = seller_name
    buyer_name = _first(t, [
        r"购买方名称[:：]\s*([^\s，,；;（(]{2,})",
        r"购买方[:：]\s*([^\s，,；;（(]{2,})",
    ])
    if buyer_name:
        fields["buyerName"] = buyer_name
    excl, tax, total = _parse_amounts(t)
    for key, value in (("amountExclTax", excl), ("taxAmount", tax), ("totalAmount", total)):
        if value:
            fields[key] = value

    # 金额自洽校验（|total−(excl+tax)|≤0.01）：通过不加不减，未通过罚减+告警
    excl_d, tax_d, total_d = _dec(excl), _dec(tax), _dec(total)
    consistent: bool | None = None
    if None not in (excl_d, tax_d, total_d):
        if abs(total_d - (excl_d + tax_d)) <= _CONSISTENCY_TOLERANCE:
            consistent = True
        else:
            consistent = False
            warnings.append("金额自洽校验未通过：价税合计 ≠ 金额 + 税额")

    confidence = sum(w for k, w in FIELD_WEIGHTS.items() if fields.get(k))
    if consistent is False:
        confidence = max(0.0, confidence - _INCONSISTENT_PENALTY)
    if not fields:
        warnings.append("ocr-no-fields：未识别到任何发票字段")
        confidence = 0.0
    return fields, round(min(confidence, _CONFIDENCE_CAP), 2), warnings
