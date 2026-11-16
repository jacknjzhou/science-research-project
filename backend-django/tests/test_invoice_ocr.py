"""Task 7：发票 OCR 三级回落（A1/F-08）测试。

Part 1  core.invoice_ocr.parse_invoice_text —— 纯规则解析（无 DB、无三方依赖）；
Part 2  funding POST /invoices/ocr —— LLM→规则→降级三级回落端点（django_db）。

TDD：Part 1 先红（模块未建）→ 实现 core/invoice_ocr.py → 绿；
     Part 2 先红（路由未注册 404）→ 实现 invoice_ocr + 注册路由 → 绿。
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.test import Client, override_settings

from apps.funding.models import FInvoice
from core.invoice_ocr import parse_invoice_text
from tests.conftest import bearer

# 增值税电子普票 OCR 样例（含 发票号码/发票代码/开票日期/价税合计/税额/购销方 labels；
# 全角空格 U+3000 模拟真实 OCR 排版；金额自洽 total=excl+tax）
VAT_TEXT = (
    "电子发票（普通发票）\n"
    "发票号码：24312000000123456789\n"
    "发票代码：044032600111\n"
    "开票日期：2026年11月01日\n"
    "购买方名称：某研究院\n"
    "购买方统一社会信用代码/纳税人识别号：12100000XXXXXXXXXX\n"
    "销售方名称：某某科技有限公司\n"
    "销售方统一社会信用代码/纳税人识别号：91440300MA5XXXXX00\n"
    "*信息技术服务*测试服务费　　金额900.00　　税率1%　　税额100.00\n"
    "合　计　￥900.00　￥100.00\n"
    "价税合计（大写）壹仟圆整　（小写）￥1000.00\n"
    "备注：测试样例\n"
    "销售方（章）\n"
)
# 价税合计与（金额+税额）不一致的样例
VAT_TEXT_BAD_TOTAL = VAT_TEXT.replace("￥1000.00", "￥1200.00")


# ---------------------------------------------------------------------------
# Part 1：core 规则解析器
# ---------------------------------------------------------------------------
def test_parse_vat_invoice_full_fields():
    fields, conf, warnings = parse_invoice_text(VAT_TEXT)
    assert fields["invoiceType"] == "ELECTRONIC"
    assert fields["number"] == "24312000000123456789"
    assert fields["invoiceCode"] == "044032600111"
    assert fields["sellerName"] == "某某科技有限公司"
    assert fields["sellerTaxId"] == "91440300MA5XXXXX00"
    assert fields["buyerName"] == "某研究院"
    assert fields["buyerTaxId"] == "12100000XXXXXXXXXX"
    # 金额一律两位小数字符串（无 float）
    assert fields["amountExclTax"] == "900.00"
    assert fields["taxAmount"] == "100.00"
    assert fields["totalAmount"] == "1000.00"
    assert fields["issueDate"] == "2026-11-01"
    assert conf >= 0.85
    assert warnings == []


def test_parse_consistent_amounts_confidence_at_least_085():
    fields, conf, _ = parse_invoice_text(VAT_TEXT)
    assert Decimal(fields["totalAmount"]) == (
        Decimal(fields["amountExclTax"]) + Decimal(fields["taxAmount"]))
    assert conf >= 0.85


def test_parse_inconsistent_amounts_warns_and_lowers_confidence():
    fields, conf, warnings = parse_invoice_text(VAT_TEXT_BAD_TOTAL)
    assert any("金额自洽" in w for w in warnings)
    assert conf < 0.85


def test_parse_empty_text():
    fields, conf, warnings = parse_invoice_text("")
    assert fields == {}
    assert conf == 0
    assert len(warnings) >= 1
    fields, conf, warnings = parse_invoice_text("   \n　\n")
    assert fields == {} and conf == 0 and len(warnings) >= 1


def test_parse_partial_fields_no_amount_trio_no_warning():
    # 只抽出号码+价税合计（金额不全）→ 不做自洽校验、无告警，覆盖率低置信 <0.85
    text = "发票号码：24312000000123456789\n价税合计（小写）￥500.00\n"
    fields, conf, warnings = parse_invoice_text(text)
    assert fields["number"] == "24312000000123456789"
    assert fields["totalAmount"] == "500.00"
    assert conf < 0.85
    assert warnings == []


def test_parse_invoice_type_variants():
    assert parse_invoice_text("增值税专用发票\n发票号码：12345678\n")[0]["invoiceType"] == "SPECIAL"
    assert parse_invoice_text("增值税普通发票\n发票号码：12345678\n")[0]["invoiceType"] == "GENERAL"
    assert parse_invoice_text("航空运输电子客票行程单\n发票号码：12345678\n")[0]["invoiceType"] == "ITINERARY"


# ---------------------------------------------------------------------------
# Part 2：funding POST /invoices/ocr —— LLM→规则→降级三级回落端点
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_ocr_degrades_when_no_llm_and_no_text(settings):
    """①无 LLM 无 text → HTTP 200 降级骨架：DRAFT + reasons=["ocr-engine-unavailable"]。"""
    settings.LLM_BASE_URL = ""
    c = Client()
    r = c.post("/api/v1/invoices/ocr", data=json.dumps({"fileUrl": "https://oss.example.com/inv.pdf"}),
               content_type="application/json", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "DRAFT"
    assert d["ocrConfidence"] == "0"
    # 契约响应体无 ocrRawJson；降级原因持久化在模型 ocr_raw_json.reasons
    assert FInvoice.objects.get(id=d["id"]).ocr_raw_json["reasons"] == ["ocr-engine-unavailable"]
    assert d["ocrWarnings"] == ["ocr-engine-unavailable"]
    assert d["checkResult"] == "PENDING"
    # 骨架发票已落库
    inv = FInvoice.objects.get(id=d["id"])
    assert inv.status == "DRAFT"
    assert inv.ocr_raw_json["reasons"] == ["ocr-engine-unavailable"]


@pytest.mark.django_db
@override_settings(LLM_BASE_URL=None)
def test_ocr_rule_parse_lands_fields_and_marks_duplicate():
    """②LLM_BASE_URL=None + text → 规则解析落库 conf≥0.85 → OCR_DONE + is_duplicated 生效。"""
    c = Client()
    r = c.post("/api/v1/invoices/ocr", data=json.dumps({"text": VAT_TEXT}),
               content_type="application/json", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "OCR_DONE"
    assert float(d["ocrConfidence"]) >= 0.85
    assert d["number"] == "24312000000123456789"
    assert d["totalAmount"] == "1000.00"
    assert d["issueDate"] == "2026-11-01"
    assert d["ocrWarnings"] == []
    inv = FInvoice.objects.get(id=d["id"])
    assert inv.status == "OCR_DONE"
    assert inv.ocr_confidence is not None and inv.ocr_confidence >= Decimal("0.85")
    assert inv.amount_excl_tax == Decimal("900.00")
    assert inv.tax_amount == Decimal("100.00")
    assert inv.total_amount == Decimal("1000.00")
    assert inv.issue_date.isoformat() == "2026-11-01"
    assert inv.code.startswith("INV-")
    # is_duplicated 生效：再 OCR 一次同文本 → 第二张标记重复
    r2 = c.post("/api/v1/invoices/ocr", data=json.dumps({"text": VAT_TEXT}),
                content_type="application/json", **bearer(1, ["R-FINANCE"]))
    assert r2.json()["data"]["isDuplicated"] is True


@pytest.mark.django_db
def test_ocr_llm_failure_falls_back_to_rule_parse(settings, monkeypatch):
    """③LLM 配置但 chat_json 抛异常 → 回落规则解析，字段仍落库。"""
    settings.LLM_BASE_URL = "http://llm.example.invalid"
    from core import llm as llm_mod

    def boom(system, user):
        raise RuntimeError("llm down")

    monkeypatch.setattr(llm_mod, "chat_json", boom)
    c = Client()
    r = c.post("/api/v1/invoices/ocr", data=json.dumps({"text": VAT_TEXT}),
               content_type="application/json", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "OCR_DONE"
    assert d["number"] == "24312000000123456789"
    # 回落路径记录 LLM 失败原因 + 金额自洽通过
    raw = FInvoice.objects.get(id=d["id"]).ocr_raw_json
    assert any("llm-failed" in str(x) for x in raw.get("reasons", []))


@pytest.mark.django_db
@override_settings(LLM_BASE_URL=None)
def test_ocr_low_confidence_stays_draft():
    """规则解析成功但置信 <0.85 → 落库但保持 DRAFT。"""
    partial = "发票号码：24312000000123456789\n价税合计（小写）￥500.00\n"
    c = Client()
    r = c.post("/api/v1/invoices/ocr", data=json.dumps({"text": partial}),
               content_type="application/json", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "DRAFT"
    assert float(d["ocrConfidence"]) < 0.85
    assert d["ocrWarnings"] == []


@pytest.mark.django_db
@override_settings(LLM_BASE_URL=None)
def test_ocr_contract_full_coverage_tolerates_empty_body():
    """test_contract_full_coverage 会以 data={} 打到本端点 → 必须以空骨架应答而非 4xx。"""
    c = Client()
    r = c.post("/api/v1/invoices/ocr", data="{}", content_type="application/json",
               **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "DRAFT"
