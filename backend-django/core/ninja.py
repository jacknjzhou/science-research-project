"""ninja API 实例 + ApiError 异常处理（统一信封）。"""
from __future__ import annotations

import os

import ninja
from django.conf import settings

from core.httpx import ApiError, err

# 在线文档开关：DEBUG（dev）默认开；生产须显式 ARK_API_DOCS=1（内网排障用）
_DOCS = bool(getattr(settings, "DEBUG", False)) or os.environ.get("ARK_API_DOCS") == "1"

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
