"""登录端点（对齐 Go auth/login.go）。

- reader 可用：username+tenant_id 取回身份，bcrypt 校验，命中签发真实数据域 claims；
- dev 回退：仅在 DEBUG 且显式 ARK_DEV_LOGIN=1 时生效，签发最小数据域（冒烟/前端直连）；
- 失败码统一，避免用户名枚举：40102。
"""
from __future__ import annotations

import os

import bcrypt
from django.conf import settings
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


def _dev_login_enabled() -> bool:
    """冒烟后门开关：必须同时满足 DEBUG=True 与显式 ARK_DEV_LOGIN=1（E-3）。"""
    return bool(getattr(settings, "DEBUG", False)) and os.environ.get("ARK_DEV_LOGIN") == "1"


def _dev_tenant_id() -> int:
    """冒烟后门固定数据域：取 ARK_DEV_TENANT（缺省 1），**不接受请求体指定租户**（终审 r1）。"""
    try:
        return max(1, int(os.environ.get("ARK_DEV_TENANT") or 1))
    except (TypeError, ValueError):
        return 1


def login(request: HttpRequest) -> object:
    body = read_json(request, msg="用户名/密码必填")
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise ApiError(400, CODE_BAD_REQUEST, "用户名/密码必填")

    tenant_id = body.get("tenant_id") or 1
    is_dev_login = (
        username == DEV_USER and password == DEV_PASSWORD and _dev_login_enabled()
    )
    user = None
    if not is_dev_login:
        # 后门关闭时 ark/ark 与普通账号同路径：库中无此人 → 40102（不泄露后门存在）
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

    if is_dev_login:
        # 冒烟回退：最小数据域（tenant 由环境变量固定），不授予管理角色（E-3/终审 r1）
        claims = _issue(request, 1, _dev_tenant_id(), 0, "INTERNAL", ["R-STAFF"])
    else:
        from apps.sysadmin.models import SysUserRole

        roles = list(
            SysUserRole.objects.filter(user_id=user.id)
            .values_list("role__code", flat=True)
        )
        codes = [r for r in roles if r]
        # 角色归一（M2-c 允许集 + 终审 I-2）：外部账号只留外部允许集，
        # 院内账号保留内部角色、只剥 R-PARTNER（院内 R-EXPERT 专家不被降权）
        from core.org_scope import normalize_roles_for_account

        codes = normalize_roles_for_account(codes, user.user_source)
        claims = _issue(
            request,
            user.id,
            user.tenant_id,
            user.legal_entity_id or 0,
            user.security_level,
            codes,
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
