"""TraceID 中间件：透传入站 X-Trace-Id，否则新建；写入 request 与响应头（对齐 Go TraceID()）。"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from core.httpx import HEADER_TRACE, new_trace_id


class TraceIDMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        trace_id = request.headers.get(HEADER_TRACE, "") or new_trace_id()
        request.trace_id = trace_id
        response = self.get_response(request)
        response[HEADER_TRACE] = trace_id
        return response
