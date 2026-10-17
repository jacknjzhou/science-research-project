"""契约注册表加载与匹配（替代 Go oapi/passthrough 的契约索引角色）。

- design/*.openapi.yaml 为接口真源；
- stub 层据此对"命中契约但未手工实现"的端点返回合规占位响应；
- 契约测试据此断言全站路由覆盖率。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

_HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


@dataclass
class ContractOp:
    method: str
    template: str  # 含 /api/v1 前缀的完整模板
    operation_id: str
    domain: str  # 契约文件名（域）
    regex: re.Pattern


def _server_path(doc: dict) -> str:
    for s in doc.get("servers") or []:
        url = s.get("url", "")
        m = re.search(r"(https?://[^/]+)?(/.*)", url)
        if m:
            return m.group(2).rstrip("/")
    return "/api/v1"


def _compile(template: str) -> re.Pattern:
    parts = re.split(r"(\{[^}]+\})", template)
    pattern = "".join(
        r"[^/]+" if p.startswith("{") else re.escape(p) for p in parts
    )
    return re.compile("^" + pattern + "$")


def load_registry() -> list[ContractOp]:
    contract_dir = Path(settings.BASE_DIR).parent / "design"
    ops: list[ContractOp] = []
    for f in sorted(contract_dir.glob("*.openapi.yaml")):
        try:
            doc = yaml_safe(f)
        except Exception:
            continue
        base = _server_path(doc)
        for path, item in (doc.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            for method, op in item.items():
                if method.lower() not in _HTTP_METHODS or not isinstance(op, dict):
                    continue
                template = base + path
                ops.append(
                    ContractOp(
                        method=method.upper(),
                        template=template,
                        operation_id=str(op.get("operationId", "")),
                        domain=f.stem,
                        regex=_compile(template),
                    )
                )
    return ops


def yaml_safe(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


_CACHED: list[ContractOp] | None = None


def registry() -> list[ContractOp]:
    global _CACHED
    if _CACHED is None:
        _CACHED = load_registry()
    return _CACHED


def match(method: str, path: str) -> ContractOp | None:
    """匹配请求；优先返回长模板（更具体路径）。"""
    candidates = [
        op
        for op in registry()
        if op.method == method.upper() and op.regex.match(path)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda op: len(op.template))
