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
    return err(request, exc.status, exc.code, exc.message)
