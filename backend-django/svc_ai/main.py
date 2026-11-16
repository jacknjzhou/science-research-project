"""svc-ai FastAPI AI 微服务（spec §七）。

边界：无状态；不直连业务库；输入输出纯 JSON；Django 是唯一调用方。

端点：
- POST /ai/taskbook/parse   任务书文本/PDF → 结构化字段
- POST /ai/expense/review   报销单/发票 → {verdict, confidence, reasons[]}
- POST /ai/contract/risk    合同条款风险提示
- POST /ai/rag/qa           制度问答（pgvector 占位）
- GET  /healthz

降级契约（与 Go 版逐字对齐）：ARK_LLM_BASE_URL 未配置或上游超时/异常 →
{verdict:"REVIEW", confidence:0, reasons:["llm-unavailable"]}，HTTP 200，不阻塞业务。
LLM 网关：NewAPI OpenAI 兼容（默认 10.26.8.43:3002），ARK_LLM_MODEL 可配。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="svc-ai", version="v1")

SERVICE_VERSION = "svc-ai-v1"
DEGRADE_REASONS = ["llm-unavailable"]


# ---------------------------------------------------------------------------
# 配置（请求期读 env，便于测试 monkeypatch）
# ---------------------------------------------------------------------------


def _cfg() -> dict:
    return {
        "base_url": os.environ.get("ARK_LLM_BASE_URL", ""),
        "api_key": os.environ.get("ARK_LLM_API_KEY", ""),
        "model": os.environ.get("ARK_LLM_MODEL", "gpt-4o-mini"),
        "timeout": float(os.environ.get("ARK_LLM_TIMEOUT_SEC", "30")),
    }


def llm_configured() -> bool:
    return bool(_cfg()["base_url"])


def degrade(verdict: str = "REVIEW", extra: dict | None = None) -> dict:
    """统一降级契约：HTTP 200 + {verdict:REVIEW, confidence:0, reasons:[llm-unavailable]}。"""
    body = {"verdict": verdict, "confidence": 0, "reasons": list(DEGRADE_REASONS),
            "degraded": True, "modelVersion": "none"}
    if extra:
        body.update(extra)
    return body


# ---------------------------------------------------------------------------
# LLM 客户端（OpenAI 兼容；异常一律降级不抛出）
# ---------------------------------------------------------------------------


def chat_json(system: str, user: str) -> dict | None:
    """调用 LLM 网关；未配置/超时/解析失败返回 None（由调用方降级）。"""
    cfg = _cfg()
    if not cfg["base_url"]:
        return None
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions", method="POST")
    req.add_header("Content-Type", "application/json")
    if cfg["api_key"]:
        req.add_header("Authorization", f"Bearer {cfg['api_key']}")
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
    }).encode()
    try:
        with urllib.request.urlopen(req, payload, timeout=cfg["timeout"]) as r:
            body = json.loads(r.read())
        text = body["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TaskbookParseRequest(BaseModel):
    text: str | None = None
    pdfBase64: str | None = Field(default=None, description="任务书 PDF（base64）")


class ExpenseReviewRequest(BaseModel):
    expense: dict = Field(default_factory=dict, description="报销单/发票要素")


class ContractRiskRequest(BaseModel):
    contractId: int | None = None
    clauses: list = Field(default_factory=list, description="合同条款列表")


class RagQaRequest(BaseModel):
    question: str
    topK: int = 5


class InvoiceOcrRequest(BaseModel):
    fileUrl: str | None = Field(default=None, description="发票影像 URL（svc-ai 仅做提示，不下载）")
    text: str | None = Field(default=None, description="发票 OCR 文本（可选）")


class InvoiceOcrResponse(BaseModel):
    fields: dict = Field(default_factory=dict)
    confidence: float = 0
    warnings: list = Field(default_factory=list)
    reasons: list = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 确定性规则（规则引擎先行，LLM 仅补充语义判断）
# ---------------------------------------------------------------------------


def _expense_rule_review(expense: dict) -> dict | None:
    """确定性硬规则：命中即返回结论（无需 LLM）。"""
    reasons = []
    if not expense.get("invoice_id") and not expense.get("invoice_url"):
        reasons.append("missing-invoice")
    amount = float(expense.get("amount") or 0)
    if amount <= 0:
        reasons.append("invalid-amount")
    if amount > 100_000 and not expense.get("approval_chain"):
        reasons.append("over-limit-no-approval")
    if reasons:
        return {"verdict": "REVIEW", "confidence": 0.9, "reasons": reasons,
                "degraded": False, "modelVersion": "rules-v1"}
    return None


def _contract_rule_risk(clauses: list) -> list[dict]:
    """条款红线规则（与 Django G-14 同源语义）：缺失关键条款提示。"""
    joined = json.dumps(clauses, ensure_ascii=False)
    risks = []
    if "付款" not in joined and "payment" not in joined.lower():
        risks.append({"clause": "付款条款", "risk_type": "MISSING", "level": "HIGH",
                      "rule_hit": "RULE-G-PAY-01"})
    if "验收" not in joined and "acceptance" not in joined.lower():
        risks.append({"clause": "验收条款", "risk_type": "MISSING", "level": "MED",
                      "rule_hit": "RULE-G-ACC-01"})
    if "保密" not in joined and "nda" not in joined.lower():
        risks.append({"clause": "保密条款", "risk_type": "MISSING", "level": "MED",
                      "rule_hit": "RULE-G-NDA-01"})
    return risks


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_VERSION,
            "llmConfigured": llm_configured()}


@app.post("/ai/taskbook/parse")
def taskbook_parse(req: TaskbookParseRequest):
    text = req.text
    if not text and req.pdfBase64:
        text = _pdf_text(req.pdfBase64)
    if not text:
        return degrade("REVIEW", {"fields": None, "fallback": "MANUAL_ENTRY",
                                  "reasons": ["no-input"]})
    parsed = chat_json(
        "你是科研任务书解析助手。从任务书文本抽取字段，只输出 JSON 对象："
        '{"title":"...","project_type":"...","duration_months":12,'
        '"total_budget":"0.00","research_target":"...","technical_route":"...",'
        '"expected_output":"...","confidence":0到1}，缺失字段用 null。不要输出其它文字。',
        text[:8000])
    if parsed is None:
        return degrade("REVIEW", {"fields": None, "fallback": "MANUAL_ENTRY"})
    return {"verdict": "PASS", "confidence": float(parsed.get("confidence") or 0.5),
            "reasons": [], "degraded": False, "fields": parsed,
            "modelVersion": _cfg()["model"]}


def _pdf_text(pdf_b64: str) -> str | None:
    """pdfplumber 抽取文本（依赖缺失/解析失败返回 None 走降级）。"""
    import base64

    try:
        import io

        import pdfplumber
    except ImportError:
        return None
    try:
        raw = base64.b64decode(pdf_b64)
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        return None


@app.post("/ai/expense/review")
def expense_review(req: ExpenseReviewRequest):
    # 规则引擎先行：硬规则命中直接出结论（可解释）
    ruled = _expense_rule_review(req.expense)
    if ruled is not None:
        return ruled
    # LLM 语义审核：未配置/异常 → 降级 REVIEW 不阻塞业务
    llm = chat_json(
        "你是科研报销审核助手。审核报销单要素，只输出 JSON："
        '{"verdict":"PASS|REVIEW","confidence":0到1,"reasons":["..."]}。',
        json.dumps(req.expense, ensure_ascii=False)[:6000])
    if llm is None:
        return degrade("REVIEW")
    return {"verdict": llm.get("verdict", "REVIEW"),
            "confidence": float(llm.get("confidence") or 0),
            "reasons": llm.get("reasons") or [],
            "degraded": False, "modelVersion": _cfg()["model"]}


@app.post("/ai/contract/risk")
def contract_risk(req: ContractRiskRequest):
    risks = _contract_rule_risk(req.clauses)
    llm = chat_json(
        "你是科研合同风险审查助手。对条款给出风险提示，只输出 JSON："
        '{"risks":[{"clause":"...","risk_type":"...","level":"HIGH|MED|LOW",'
        '"suggestion":"..."}]}。不做决策，仅提示。',
        json.dumps(req.clauses, ensure_ascii=False)[:6000])
    if llm is None:
        # 降级：规则结果保留 + LLM 建议位降级 REVIEW
        return degrade("REVIEW", {"risks": risks, "suggestions": []})
    return {"verdict": "PASS", "confidence": 0.8, "reasons": [],
            "degraded": False, "risks": risks + (llm.get("risks") or []),
            "modelVersion": _cfg()["model"]}


@app.post("/ai/rag/qa")
def rag_qa(req: RagQaRequest):
    llm = chat_json(
        "你是科研制度问答助手。仅依据给定制度片段回答，不得虚构；"
        '只输出 JSON：{"answer":"...","citations":["制度名/条款号"]}。',
        req.question[:4000])
    if llm is None:
        return degrade("REVIEW", {"answer": "", "citations": []})
    return {"verdict": "PASS", "confidence": 0.7, "reasons": [],
            "degraded": False, "answer": llm.get("answer", ""),
            "citations": llm.get("citations") or [],
            "modelVersion": _cfg()["model"]}


@app.post("/ai/invoice/ocr")
def invoice_ocr(req: InvoiceOcrRequest) -> InvoiceOcrResponse:
    """发票 OCR 抽取（F-08/A1 网关侧）：LLM → 规则 → 降级，HTTP 200 恒定。

    仅建议不写业务库（Django 落库由 funding invoice_ocr 负责）；规则引擎
    core/invoice_ocr.py 与 Django 侧同一实现（延迟 import，svc-ai 保持无状态、
    不依赖 Django —— 同 _pdf_text 的函数内 import 惯例）。
    """
    text = (req.text or "").strip()
    fields: dict = {}
    warnings: list = []
    reasons: list = []
    # 第一级：LLM 抽取（未配置/异常 → None 落规则）
    if text:
        llm = chat_json(
            "你是发票 OCR 信息抽取助手。从发票文本抽取字段，只输出 JSON 对象："
            '{"invoiceType":"GENERAL|SPECIAL|ELECTRONIC|ITINERARY","number":"...",'
            '"invoiceCode":"...","sellerName":"...","sellerTaxId":"...","buyerName":"...",'
            '"buyerTaxId":"...","amountExclTax":"0.00","taxAmount":"0.00","totalAmount":"0.00",'
            '"issueDate":"YYYY-MM-DD"}，金额为两位小数字符串，未识别的键输出 null。'
            "不要输出其它文字。",
            text[:8000])
        if llm and any(v not in (None, "") for v in llm.values()):
            fields = {k: v for k, v in llm.items() if v not in (None, "")}
    # 第二级：规则引擎回落（与 Django 同源实现）
    if not fields and text:
        try:
            from core.invoice_ocr import parse_invoice_text

            fields, _, warnings = parse_invoice_text(text)
        except Exception as exc:  # 规则引擎自身异常也降级，不抛出
            reasons.append(f"rule-engine-failed：{exc}")
    if not text:
        reasons.append("ocr-text-empty：未提供可解析的发票文本")
    if not fields and not text:
        reasons.append("ocr-engine-unavailable")
    elif not fields:
        reasons.append("ocr-no-fields")
    return InvoiceOcrResponse(fields=fields, confidence=float(
        fields and 0.6 or 0), warnings=warnings, reasons=reasons)
