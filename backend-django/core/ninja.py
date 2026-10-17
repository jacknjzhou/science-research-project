"""ninja API 实例 + ApiError 异常处理（统一信封）。"""
from __future__ import annotations

import ninja

from core.httpx import ApiError, err

api = ninja.NinjaAPI(
    title="Ark API",
    version="1.0.0",
    docs_url=None,
    openapi_url=None,
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
