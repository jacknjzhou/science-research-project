"""svc-ai FastAPI 微服务测试（降级契约逐字对齐 spec §七）。

核心断言：ARK_LLM_BASE_URL 未配置 / 上游不可达 →
{verdict:"REVIEW", confidence:0, reasons:["llm-unavailable"]} 且 HTTP 200（不阻塞业务）。
"""
import base64
import json

import pytest
from fastapi.testclient import TestClient

from svc_ai.main import app, _pdf_text, chat_json


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ARK_LLM_BASE_URL", raising=False)
    return TestClient(app)


@pytest.fixture
def dead_llm_client(monkeypatch):
    """配置了但上游不可达 → 同样降级。"""
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ARK_LLM_TIMEOUT_SEC", "1")
    return TestClient(app)


def _assert_degrade(body: dict):
    assert body["verdict"] == "REVIEW"
    assert body["confidence"] == 0
    assert body["reasons"] == ["llm-unavailable"]


# ---------------------------------------------------------------------------
# healthz
# ---------------------------------------------------------------------------


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["llmConfigured"] is False


# ---------------------------------------------------------------------------
# 降级契约：未配置 / 上游不可达 → HTTP 200 + REVIEW
# ---------------------------------------------------------------------------


def test_degrade_when_llm_unconfigured(client):
    for url, payload in [
        ("/ai/expense/review", {"expense": {"amount": 100, "invoice_id": 1}}),
        ("/ai/contract/risk", {"clauses": [{"title": "付款条款"}, {"title": "验收条款"}]}),
        ("/ai/rag/qa", {"question": "差旅费报销标准是多少？"}),
    ]:
        r = client.post(url, json=payload)
        assert r.status_code == 200
        _assert_degrade(r.json())


def test_degrade_when_upstream_unreachable(dead_llm_client):
    r = dead_llm_client.post("/ai/expense/review",
                             json={"expense": {"amount": 100, "invoice_id": 1}})
    assert r.status_code == 200
    _assert_degrade(r.json())
    assert dead_llm_client.get("/healthz").json()["llmConfigured"] is True


def test_chat_json_returns_none_on_garbage(monkeypatch):
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://127.0.0.1:1")
    assert chat_json("sys", "user") is None


# ---------------------------------------------------------------------------
# 确定性规则引擎（无 LLM 也可解释输出）
# ---------------------------------------------------------------------------


def test_expense_rule_engine(client):
    # 缺发票 → REVIEW（规则命中，非降级）
    r = client.post("/ai/expense/review", json={"expense": {"amount": 500}})
    body = r.json()
    assert body["verdict"] == "REVIEW" and "missing-invoice" in body["reasons"]
    assert body["degraded"] is False
    # 超限无审批链
    r = client.post("/ai/expense/review",
                    json={"expense": {"amount": 200000, "invoice_id": 1}})
    assert "over-limit-no-approval" in r.json()["reasons"]
    # 金额非法
    r = client.post("/ai/expense/review",
                    json={"expense": {"amount": 0, "invoice_id": 1}})
    assert "invalid-amount" in r.json()["reasons"]


def test_contract_rule_risks(client):
    r = client.post("/ai/contract/risk",
                    json={"clauses": [{"title": "第一条 付款"}, {"title": "验收"}]})
    body = r.json()
    _assert_degrade(body)  # LLM 未配置整体降级 REVIEW，但规则风险仍返回
    levels = {x["clause"]: x for x in body["risks"]}
    assert "保密条款" in levels and "付款条款" not in levels


# ---------------------------------------------------------------------------
# 任务书解析
# ---------------------------------------------------------------------------


def test_taskbook_no_input(client):
    r = client.post("/ai/taskbook/parse", json={})
    body = r.json()
    assert body["verdict"] == "REVIEW" and body["reasons"] == ["no-input"]
    assert body["fallback"] == "MANUAL_ENTRY"


def test_taskbook_degrade_with_text(client):
    r = client.post("/ai/taskbook/parse", json={"text": "项目名称：高效催化"})
    body = r.json()
    _assert_degrade(body)
    assert body["fallback"] == "MANUAL_ENTRY"


def test_pdf_text_extraction_missing_dep(monkeypatch):
    # pdfplumber 未安装 → None 走降级，不抛异常
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "pdfplumber":
            raise ImportError("no pdfplumber")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _pdf_text(base64.b64encode(b"%PDF-fake").decode()) is None


# ---------------------------------------------------------------------------
# LLM 配置后的正常路径（mock 网关响应）
# ---------------------------------------------------------------------------


def test_expense_pass_with_mocked_llm(client, monkeypatch):
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://mock:3002")
    monkeypatch.setattr("svc_ai.main.chat_json", lambda s, u: {
        "verdict": "PASS", "confidence": 0.92, "reasons": []})
    r = client.post("/ai/expense/review",
                    json={"expense": {"amount": 100, "invoice_id": 1}})
    body = r.json()
    assert body["verdict"] == "PASS" and body["degraded"] is False
    assert body["confidence"] == 0.92


# ---------------------------------------------------------------------------
# 发票 OCR 网关（A1/F-08）：LLM → 规则 → 降级，HTTP 200 恒定，不写业务库
# ---------------------------------------------------------------------------


VAT_TEXT = (
    "增值税电子普通发票\n"
    "发票号码：12500000287102539401\n"
    "发票代码：125002200281\n"
    "开票日期：2026年11月01日\n"
    "购买方名称：某研究院   纳税人识别号：12100000MB0P00888A\n"
    "销售方名称：某某科技有限公司   纳税人识别号：91110000MA01T00X9B\n"
    "金额合计￥900.00  税额合计￥100.00\n"
    "价税合计（大写）壹仟元整（小写）￥1000.00"
)


def test_invoice_ocr_degrades_when_no_llm_no_text(client):
    """仅 fileUrl、无 LLM → 降级骨架，HTTP 200 恒定（spec OCR 流程 5）。"""
    r = client.post("/ai/invoice/ocr", json={"fileUrl": "https://f.example/inv.pdf"})
    assert r.status_code == 200
    body = r.json()
    assert body["fields"] == {} and body["confidence"] == 0
    assert "ocr-engine-unavailable" in body["reasons"]


def test_invoice_ocr_rule_parse_without_llm(client):
    """无 LLM、有 text → 规则引擎兜底抽出字段（与 Django 同源实现）。"""
    r = client.post("/ai/invoice/ocr", json={"text": VAT_TEXT})
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["number"] == "12500000287102539401"
    assert body["fields"]["totalAmount"] == "1000.00"
    assert body["fields"]["issueDate"] == "2026-11-01"
    assert body["warnings"] == []


def test_invoice_ocr_llm_failure_falls_back_to_rules(dead_llm_client):
    """LLM 已配置但上游不可达 → chat_json None → 回落规则解析。"""
    r = dead_llm_client.post("/ai/invoice/ocr", json={"text": VAT_TEXT})
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["number"] == "12500000287102539401"
    assert body["fields"]["amountExclTax"] == "900.00"


def test_invoice_ocr_empty_body_is_200(client):
    r = client.post("/ai/invoice/ocr", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["fields"] == {} and body["confidence"] == 0
    assert body["reasons"]


def test_invoice_ocr_never_imports_django():
    """svc_ai/main.py 不得 import Django（AI 微服务边界：不直连业务库）。"""
    import ast
    import os
    src = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "svc_ai", "main.py")
    tree = ast.parse(open(src, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("django") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("django")
