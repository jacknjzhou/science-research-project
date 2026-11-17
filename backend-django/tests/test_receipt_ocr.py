"""M1-c Task 4：银行回单 OCR 规则解析器（A8/F-15）测试。

core.receipt_ocr.parse_receipt_text —— 纯规则解析（无 DB、无三方依赖）；
端点三级回落集成测试（POST /incomes/ocr-receipt）在 tests/test_funding_m1c.py。

TDD：先红（模块未建）→ 实现 core/receipt_ocr.py → 绿。
"""
from __future__ import annotations

from core.receipt_ocr import parse_receipt_text

# 银行电子回单 OCR 样例（含 付款人/金额/日期/流水号/用途 标签族；
# 全角空格 U+3000 模拟真实 OCR 排版）
RECEIPT_TEXT = (
    "中国建设银行　电子回单\n"
    "收/付款日期：2026年11月15日\n"
    "付款人户名：某某科技有限公司\n"
    "付款人账号：6222 0000 1111 2222\n"
    "收款人户名：某研究院\n"
    "交易金额：￥50000.00\n"
    "交易流水号：20261115000012345678\n"
    "凭证种类：电子回单\n"
    "摘要：课题测试服务费\n"
    "用途：测试服务费\n"
)
# 仅流水号+金额（字段不全）→ 低置信样例
RECEIPT_TEXT_PARTIAL = "交易流水号：20261115000012345678\n交易金额：￥50000.00\n"


# ---------------------------------------------------------------------------
# Part 1：core 规则解析器
# ---------------------------------------------------------------------------
def test_parse_receipt_full_fields():
    fields, conf, warnings = parse_receipt_text(RECEIPT_TEXT)
    assert fields["payerName"] == "某某科技有限公司"
    assert fields["amount"] == "50000.00"
    assert fields["receiptDate"] == "2026-11-15"
    assert fields["bankFlowNo"] == "20261115000012345678"
    assert fields["purpose"] == "课题测试服务费"
    assert conf >= 0.85
    assert warnings == []


def test_parse_receipt_confidence_cap_099():
    _, conf, _ = parse_receipt_text(RECEIPT_TEXT)
    assert conf <= 0.99


def test_parse_receipt_amount_variants():
    # 千分位 + 小写金额标签 + 人民币字样
    text = (
        "付款人户名：测试甲\n"
        "交易金额：人民币 1,234.56\n"
        "交易流水号：FLOW0001\n"
        "交易日期：2026-11-15\n"
    )
    fields, _, _ = parse_receipt_text(text)
    assert fields["amount"] == "1234.56"


def test_parse_receipt_iso_date():
    text = RECEIPT_TEXT.replace("2026年11月15日", "2026-11-15")
    fields, _, _ = parse_receipt_text(text)
    assert fields["receiptDate"] == "2026-11-15"


def test_parse_receipt_flow_no_variants():
    # 「凭证号」标签同样命中流水号族
    text = RECEIPT_TEXT.replace("交易流水号", "凭证号")
    assert parse_receipt_text(text)[0]["bankFlowNo"] == "20261115000012345678"
    text2 = RECEIPT_TEXT.replace("交易流水号", "交易流水")
    assert parse_receipt_text(text2)[0]["bankFlowNo"] == "20261115000012345678"


def test_parse_receipt_purpose_variants():
    # 无「摘要」时回退「用途」标签
    text = RECEIPT_TEXT.replace("摘要：课题测试服务费\n", "")
    fields, conf, warnings = parse_receipt_text(text)
    assert fields["purpose"] == "测试服务费"
    # 用途标签仍在 → 字段全覆盖，置信度不受影响
    assert conf >= 0.85 and warnings == []


def test_parse_receipt_empty_text():
    fields, conf, warnings = parse_receipt_text("")
    assert fields == {}
    assert conf == 0
    assert len(warnings) >= 1
    fields, conf, warnings = parse_receipt_text("   \n　\n")
    assert fields == {} and conf == 0 and len(warnings) >= 1
    assert any("receipt-text-empty" in w for w in warnings)


def test_parse_receipt_partial_fields_no_warning():
    # 只抽出流水号+金额 → 覆盖率低置信 <0.85，无告警
    fields, conf, warnings = parse_receipt_text(RECEIPT_TEXT_PARTIAL)
    assert fields["bankFlowNo"] == "20261115000012345678"
    assert fields["amount"] == "50000.00"
    assert conf < 0.85
    assert warnings == []


def test_parse_receipt_no_fields():
    fields, conf, warnings = parse_receipt_text("完全无关的文本\n没有任何回单标签")
    assert fields == {}
    assert conf == 0
    assert any("receipt-no-fields" in w for w in warnings)


def test_receipt_field_weights_sum_one():
    from core.receipt_ocr import FIELD_WEIGHTS

    assert set(FIELD_WEIGHTS) == {"payerName", "amount", "receiptDate", "bankFlowNo", "purpose"}
    assert round(sum(FIELD_WEIGHTS.values()), 2) == 1.00


def test_receipt_ocr_module_no_django_import():
    """AST 断言：core/receipt_ocr.py 零 Django import（同 test_svc_ai.py 范式）。"""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "core" / "receipt_ocr.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("django") for a in node.names), node.names
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("django"), node.module
