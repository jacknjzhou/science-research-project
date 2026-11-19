"""ninja API 实例 + ApiError 异常处理（统一信封）。"""
from __future__ import annotations

import os

import ninja
from django.conf import settings

from core.httpx import ApiError, err

# 在线文档开关（E-8）：默认全关。
#   ARK_API_DOCS=1 → 强制开（内网排障，需临时启用）
#   ARK_API_DOCS=0 → 强制关（连本地 dev 也关）
#   未设置        → 仅 DEBUG=True（本地 dev 形态）时开
# 生产配置（config.settings.prod）DEBUG=False，因此不设变量就是关着的。
def docs_enabled() -> bool:
    flag = os.environ.get("ARK_API_DOCS")
    if flag == "1":
        return True
    if flag == "0":
        return False
    return bool(getattr(settings, "DEBUG", False))


_DOCS = docs_enabled()

api = ninja.NinjaAPI(
    title="Ark API",
    version="1.0.0",
    docs_url="/docs" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
    urls_namespace="ark-api",
)


@api.exception_handler(ApiError)
def api_error_handler(request, exc: ApiError):
    if exc.data is not None:
        from core.httpx import envelope_ok_data
        body = envelope_ok_data(exc.data, err_trace := getattr(request, "trace_id", "") or "")
        body["code"] = exc.code
        body["message"] = exc.message
        from django.http import JsonResponse
        resp = JsonResponse(body, status=exc.status)
        resp["X-Trace-Id"] = err_trace
        return resp
    return err(request, exc.status, exc.code, exc.message)
