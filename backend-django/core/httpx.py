"""统一响应信封与业务错误码（对齐 Go httpx/envelope.go）。

信封：{"code","message","data","traceId","timestamp"}，timestamp 为 Unix 毫秒。
HTTP 状态表达传输层，code 表达业务错误（PRD 2.5）。
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any

from django.http import HttpRequest, JsonResponse

# ---------------------------------------------------------------------------
# 错误码段（沿用 Go 版已用值，新增必须登记）
# ---------------------------------------------------------------------------
CODE_OK = 0
CODE_BAD_REQUEST = 40001  # 参数校验失败
CODE_UNKNOWN_PARAM = 40002  # 未知角色码等参数语义错误
CODE_UNAUTHENTICATED = 40101  # 未认证（无 Bearer）
CODE_BAD_CREDENTIALS = 40102  # 账号或密码错误 / 令牌无效或过期
CODE_FORBIDDEN = 40301  # Casbin 拒绝
CODE_ACCOUNT_DISABLED = 40302  # 账号已停用或锁定
CODE_NOT_FOUND = 40401  # 资源不存在
CODE_ROLE_NOT_FOUND = 40402  # 角色不存在或跨租户
CODE_CONFLICT = 40901  # 状态机/唯一键冲突
CODE_IDEM_IN_PROGRESS = 40909  # 相同幂等键正在处理中
CODE_STUB_UNAVAILABLE = 50301  # 依赖缺失（如 Storage 未配置）
CODE_INTERNAL = 50001  # 内部错误

HEADER_TRACE = "X-Trace-Id"


def new_trace_id() -> str:
    """对齐 Go httpx.NewTraceID：前缀 + 16 hex。"""
    return "py-" + secrets.token_hex(8)


def envelope_ok_data(data: Any, trace_id: str) -> dict:
    return {
        "code": CODE_OK,
        "message": "ok",
        "data": data,
        "traceId": trace_id,
        "timestamp": int(time.time() * 1000),
    }


def envelope_err_data(code: int, message: str, trace_id: str) -> dict:
    return {
        "code": code,
        "message": message,
        "data": None,
        "traceId": trace_id,
        "timestamp": int(time.time() * 1000),
    }


def ok(request: HttpRequest, data: Any = None, status: int = 200) -> JsonResponse:
    """成功信封（code=0）。"""
    return JsonResponse(
        envelope_ok_data(data, trace_of(request)),
        status=status,
        headers={HEADER_TRACE: trace_of(request)},
    )


def err(request: HttpRequest, status: int, code: int, msg: str) -> JsonResponse:
    """业务错误信封。"""
    trace = trace_of(request)
    return JsonResponse(
        envelope_err_data(code, msg, trace),
        status=status,
        headers={HEADER_TRACE: trace},
    )


def trace_of(request: HttpRequest) -> str:
    return getattr(request, "trace_id", "") or new_trace_id()


def read_json(request: HttpRequest, msg: str = "请求参数错误") -> dict:
    """解析 JSON body；非法 body 抛 40001（对齐 Go binding 失败语义）。"""
    try:
        data = json.loads(request.body or b"{}")
    except Exception:
        raise ApiError(400, CODE_BAD_REQUEST, msg) from None
    if not isinstance(data, dict):
        raise ApiError(400, CODE_BAD_REQUEST, msg)
    return data


def dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


class ApiError(Exception):
    """业务异常：任何 handler 只抛此异常，由 ninja 异常处理器转信封。"""

    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
