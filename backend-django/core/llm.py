"""LLM 网关客户端（NewAPI OpenAI 兼容，对齐 Go platform/llm）。

settings.LLM_BASE_URL 未配置时调用方自行降级（AI 端点 → REVIEW，任务书 → 人工录入）。
"""
from __future__ import annotations

import json
import urllib.request

from django.conf import settings


def _chat(system: str, user: str) -> str:
    """OpenAI 兼容 /chat/completions 调用，返回首 choice 文本。"""
    req = urllib.request.Request(
        settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
        method="POST")
    req.add_header("Content-Type", "application/json")
    if settings.LLM_API_KEY:
        req.add_header("Authorization", f"Bearer {settings.LLM_API_KEY}")
    payload = json.dumps({
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }).encode()
    with urllib.request.urlopen(req, payload, timeout=settings.LLM_TIMEOUT_SEC) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"]


def chat_json(system: str, user: str) -> dict:
    """严格 JSON 建议输出：剥掉 markdown 围栏后解析；解析失败视为服务异常由调用方降级。"""
    text = _chat(system, user).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def extract_taskbook(text: str) -> dict:
    """任务书解析（P-13）：结构化字段抽取。失败抛异常由调用方降级人工录入。"""
    system = (
        "你是科研任务书解析助手。从任务书文本抽取字段，只输出 JSON 对象："
        '{"title":"...","project_type":"...","duration_months":12,'
        '"total_budget":"0.00","research_target":"...","technical_route":"...",'
        '"expected_output":"...","confidence":0到1}，缺失字段用 null。不要输出其它文字。')
    return chat_json(system, text[:8000])
