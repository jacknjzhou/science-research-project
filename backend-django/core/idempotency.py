"""幂等中间件（对齐 Go middleware.Idempotency）。

- 仅对带 Idempotency-Key 的非安全方法生效；其余直接放行，绝不触碰 Redis；
- 命中缓存 → 回放首次响应体（恒 HTTP 200，与 Go c.Data(200) 一致）；
- SETNX 抢占处理中标记，并发重复 → 409/40909；
- 完成后写入结果并清锁；Redis 不可用静默放行。
"""
from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from core import redis_util
from core.httpx import CODE_IDEM_IN_PROGRESS, err


class IdempotencyMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return self.get_response(request)
        key = request.headers.get("Idempotency-Key", "")
        if not key:
            return self.get_response(request)

        rdb = redis_util.get_client()
        if rdb is None:
            return self.get_response(request)

        cache_key = f"idem:{request.method}:{request.path}:{key}"
        try:
            cached = rdb.get(cache_key)
            if cached:
                return JsonResponse(
                    __import__("json").loads(cached),
                    status=200,
                    safe=False,
                )
            acquired = rdb.set(f"{cache_key}:lock", "1", nx=True, ex=settings.IDEMPOTENCY_TTL_SEC)
            if not acquired:
                return err(request, 409, CODE_IDEM_IN_PROGRESS, "相同幂等键正在处理中")
        except Exception:
            return self.get_response(request)

        response = self.get_response(request)
        try:
            rdb.set(cache_key, response.content, ex=settings.IDEMPOTENCY_TTL_SEC)
            rdb.delete(f"{cache_key}:lock")
        except Exception:
            pass
        return response
