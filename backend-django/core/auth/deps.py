"""请求域上下文（对齐 Go auth.DomainFrom）：认证成功后注入 request.domain。"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.http import HttpRequest

from core.auth.casbin_util import enforce_any
from core.auth.jwt_util import TokenError, parse_token
from core.httpx import (
    ApiError,
    CODE_ACCOUNT_DISABLED,
    CODE_BAD_CREDENTIALS,
    CODE_FORBIDDEN,
    CODE_UNAUTHENTICATED,
)


@dataclass
class Domain:
    user_id: int
    tenant_id: int
    legal_entity_id: int | None
    security_level: str
    roles: list[str] = field(default_factory=list)


def domain_from(request: HttpRequest) -> Domain:
    return getattr(request, "domain", None) or Domain(
        user_id=0, tenant_id=1, legal_entity_id=None, security_level="", roles=[]
    )


def _load_account(user_id: int) -> tuple[str, int, str] | None:
    """读账号状态与来源；库内不存在返回 None（虚拟主体，维持令牌语义）。"""
    if user_id <= 0:
        return None
    from apps.sysadmin.models import SysUser

    return (
        SysUser.objects.filter(id=user_id)
        .values_list("status", "deleted", "user_source")
        .first()
    )


def _assert_account_active(user_id: int) -> None:
    """库内存在该账号时要求 ACTIVE 且未删除（不存在=虚拟主体，维持令牌语义）。"""
    row = _load_account(user_id)
    if row is None:
        return
    status_, deleted, _source = row
    if deleted or status_ != "ACTIVE":
        raise ApiError(403, CODE_ACCOUNT_DISABLED, "账号已停用")


def ark_auth(request: HttpRequest) -> dict:
    """ninja 全局鉴权依赖：Bearer JWT → 数据域注入 → Casbin 判权（任一角色命中即放行）。"""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, CODE_UNAUTHENTICATED, "未认证")
    try:
        claims = parse_token(header[len("Bearer ") :])
    except TokenError:
        raise ApiError(401, CODE_BAD_CREDENTIALS, "令牌无效或过期") from None

    roles = [str(r) for r in claims.get("roles", [])]
    # 角色归一 + 账号状态即时生效（M2-c 终审 I-2 / M2-b 遗留 I-3）：
    # 按账号来源裁剪——外部账号只留外部允许集（杜绝"外部+内部"并集越权），
    # 院内账号保留内部角色、只剥 R-PARTNER（院内 R-EXPERT 专家不被降权）。
    # 停用/删除后存量令牌立刻失效，不等 2h 过期；库内无该 uid 视为虚拟主体保持原语义。
    from core.org_scope import normalize_roles_for_account

    uid = int(claims.get("uid", 0) or 0)
    row = _load_account(uid)
    if row is not None:
        status_, deleted, source = row
        if deleted or status_ != "ACTIVE":
            raise ApiError(403, CODE_ACCOUNT_DISABLED, "账号已停用")
        roles = normalize_roles_for_account(roles, source)
    else:
        roles = normalize_roles_for_account(roles, None)
    if not enforce_any(roles, request.path, request.method):
        raise ApiError(403, CODE_FORBIDDEN, "无权限")

    request.domain = Domain(
        user_id=int(claims.get("uid", 0)),
        tenant_id=int(claims.get("tenant_id", 1)),
        legal_entity_id=claims.get("legal_entity_id"),
        security_level=str(claims.get("security_level", "")),
        roles=roles,
    )
    return claims
