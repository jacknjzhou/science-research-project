"""登录端点（对齐 Go auth/login.go）。

- reader 可用：username+tenant_id 取回身份，bcrypt 校验，命中签发真实数据域 claims；
- dev 回退：ark/ark 通过即签发固定数据域（冒烟/前端直连零回归）；
- 失败码统一，避免用户名枚举：40102。
"""
from __future__ import annotations

import bcrypt
from django.http import HttpRequest

from apps.sysadmin.models import SysUser
from core.auth.jwt_util import gen_token
from core.httpx import (
    CODE_ACCOUNT_DISABLED,
    CODE_BAD_CREDENTIALS,
    CODE_BAD_REQUEST,
    CODE_INTERNAL,
    ApiError,
    ok,
    read_json,
)

DEV_USER = "ark"
DEV_PASSWORD = "ark"


def login(request: HttpRequest) -> object:
    body = read_json(request, msg="用户名/密码必填")
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise ApiError(400, CODE_BAD_REQUEST, "用户名/密码必填")

    tenant_id = body.get("tenant_id") or 1
    user = None
    if username != DEV_USER or password != DEV_PASSWORD:
        user = (
            SysUser.objects.filter(
                username=username, tenant_id=tenant_id, deleted=0
            ).first()
        )
        if user is None or not user.password_hash or not _check_pw(
            password, user.password_hash
        ):
            raise ApiError(401, CODE_BAD_CREDENTIALS, "账号或密码错误")
        if user.status != "ACTIVE":
            raise ApiError(403, CODE_ACCOUNT_DISABLED, "账号已停用或锁定")

    if user is None:
        # dev 回退（对齐 Go reader==nil 路径）
        claims = _issue(request, 1, 1, 0, "INTERNAL", ["R-STAFF", "R-MANAGER"])
    else:
        from apps.sysadmin.models import SysUserRole

        roles = list(
            SysUserRole.objects.filter(user_id=user.id)
            .values_list("role__code", flat=True)
        )
        claims = _issue(
            request,
            user.id,
            user.tenant_id,
            user.legal_entity_id or 0,
            user.security_level,
            [r for r in roles if r],
        )
    return claims


def _issue(
    request: HttpRequest,
    user_id: int,
    tenant_id: int,
    legal_entity_id: int,
    security_level: str,
    roles: list[str],
) -> dict:
    from django.conf import settings

    try:
        tok = gen_token(user_id, tenant_id, legal_entity_id, security_level, roles)
    except Exception:
        raise ApiError(500, CODE_INTERNAL, "签发令牌失败") from None
    return ok(
        request,
        {"token_type": "Bearer", "access_token": tok, "expires_in": settings.JWT_TTL_SEC},
    )


def _check_pw(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
