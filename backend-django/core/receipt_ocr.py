"""银行回单 OCR 纯规则解析器（A8/F-15，M1-c Task 4）。

三级回落中的第二级：LLM 不可用/失败时，对回单 OCR 文本做正则抽取。
约束（brief）：纯正则、无第三方依赖、无 Django 依赖 —— 镜像 core/invoice_ocr.py
（A1/F-08）的三级回落范式，可被 backend-django funding 端点复用。

接口：
    parse_receipt_text(text: str) -> tuple[dict, float, list[str]]
返回 (fields, confidence, warnings)：
    fields 键为 camelCase：payerName / amount / receiptDate(YYYY-MM-DD) /
    bankFlowNo / purpose；金额一律两位小数字符串
    （契约 Money=string，全程 Decimal，无 float）。
    confidence ∈ [0, 0.99]：字段覆盖加权（无金额自洽三元组，故无自洽罚分）。
    warnings：中文告警。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = ["parse_receipt_text", "FIELD_WEIGHTS"]

# 5 个标签族权重（和恰为 1.00）：金额/流水号最重，日期其次
FIELD_WEIGHTS: dict[str, float] = {
    "payerName": 0.15,
    "amount": 0.30,
    "receiptDate": 0.20,
    "bankFlowNo": 0.25,
    "purpose": 0.10,
}

_MONEY = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
# 流水号：数字/字母混合长串（10-40 位），容忍行内空格分隔
_FLOW = r"([0-9A-Za-z](?:[0-9A-Za-z\- ]{8,38}[0-9A-Za-z])?)"

# 置信度上限：永不给出 1.0（机器识别留有不确定性）
_CONFIDENCE_CAP = 0.99


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


def _parse_receipt_date(text: str) -> str | None:
    m = re.search(
        r"(?:收付款日期|交易日期|收\/付款日期|回单日期|日期)[:：]\s*"
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}"
    m = re.search(
        r"(?:收付款日期|交易日期|收\/付款日期|回单日期|日期)[:：]\s*"
        r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def parse_receipt_text(text: str) -> tuple[dict, float, list[str]]:
    """规则解析回单 OCR 文本 → (fields, confidence, warnings)。"""
    warnings: list[str] = []
    raw = text or ""
    if not raw.strip():
        return {}, 0.0, ["receipt-text-empty：未提供可解析的回单文本"]

    # 归一化：仅折叠水平空白（含全角空格），保留换行
    t = re.sub(r"[^\S\n]+", " ", raw)

    fields: dict[str, str] = {}
    payer_name = _first(t, [
        r"付款人(?:户名|名称|账号户名)[:：]\s*([^\s，,；;（(]{2,})",
        r"付款户名[:：]\s*([^\s，,；;（(]{2,})",
        r"付款人[:：]\s*([^\s，,；;（(]{2,})",
    ])
    if payer_name:
        fields["payerName"] = payer_name
    amount_raw = _first(t, [
        r"交易金额[:：]\s*[¥￥人民币\s]*" + _MONEY,
        r"[¥￥]\s*" + _MONEY,
        r"金额[:：]\s*[¥￥人民币\s]*" + _MONEY,
        r"人民币[:：\s]*" + _MONEY,
    ])
    amount = _money_str(_dec(amount_raw))
    if amount:
        fields["amount"] = amount
    receipt_date = _parse_receipt_date(t)
    if receipt_date:
        fields["receiptDate"] = receipt_date
    flow_no = _first(t, [
        r"(?:交易流水号|交易流水|流水号)[:：]\s*" + _FLOW,
        r"凭证号(?:码)?[:：]\s*" + _FLOW,
    ])
    if flow_no:
        fields["bankFlowNo"] = flow_no
    purpose = _first(t, [
        r"摘要[:：]\s*([^\s\n]{2,})",
        r"用途[:：]\s*([^\s\n]{2,})",
    ])
    if purpose:
        fields["purpose"] = purpose

    confidence = sum(w for k, w in FIELD_WEIGHTS.items() if fields.get(k))
    if not fields:
        warnings.append("receipt-no-fields：未识别到任何回单字段")
        confidence = 0.0
    return fields, round(min(confidence, _CONFIDENCE_CAP), 2), warnings
