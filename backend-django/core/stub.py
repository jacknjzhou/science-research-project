"""契约 stub 兜底层（替代 Go oapi.Passthrough）。

命中契约但未手工实现的端点 → 返回契约合规的最小信封 + X-Stub: true，
保证前端全站不白屏（plan §四/§五.2）。
data 形状按契约 200 响应 schema 推断：object→{}，array→[]，否则 {}。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.http import HttpRequest

from core import contract
from core.httpx import CODE_NOT_FOUND, err, ok


def _response_schema(op: contract.ContractOp) -> dict[str, Any] | None:
    """取 operation 200 响应的 data schema（信封内的 data 字段）。"""
    f = Path(settings.BASE_DIR).parent / "design" / f"{op.domain}.yaml"
    if not f.exists():
        return None
    try:
        doc = contract.yaml_safe(f)
    except Exception:
        return None
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        m = item.get(op.method.lower())
        if not isinstance(m, dict) or m.get("operationId") != op.operation_id:
            continue
        resp = (m.get("responses") or {}).get("200") or {}
        content = (resp.get("content") or {}).get("application/json") or {}
        schema = content.get("schema") or {}
        # 信封：解 data 字段
        props = schema.get("properties") or {}
        data_schema = props.get("data") or {}
        # 解 $ref（组件内 ApiResponse.data → XxxData）
        ref = data_schema.get("$ref")
        if ref:
            node = doc
            for seg in ref.lstrip("#/").split("/"):
                node = (node or {}).get(seg, {})
            data_schema = node if isinstance(node, dict) else {}
        return data_schema
    return None


def _minimal_data(op: contract.ContractOp) -> Any:
    schema = _response_schema(op)
    if not schema:
        return {}
    if schema.get("type") == "array":
        return []
    return {}


def stub_view(request: HttpRequest, rest: str = ""):
    op = contract.match(request.method, request.path)
    if op is None:
        return err(request, 404, CODE_NOT_FOUND, "接口不存在")
    resp = ok(request, _minimal_data(op))
    resp["X-Stub"] = "true"
    resp["X-Stub-Op"] = op.operation_id
    return resp
