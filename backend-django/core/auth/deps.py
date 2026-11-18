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


def _assert_account_active(user_id: int) -> None:
    """库内存在该账号时要求 ACTIVE 且未删除（不存在=虚拟主体，维持令牌语义）。"""
    if user_id <= 0:
        return
    from apps.sysadmin.models import SysUser

    row = (
        SysUser.objects.filter(id=user_id)
        .values_list("status", "deleted")
        .first()
    )
    if row is None:
        return
    status_, deleted = row
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
    # 外部角色是"独占"口径（终审 r2 I-1 / r3 N-2，M2-c 扩为允许集）：
    # 令内只要出现任一外部角色，内部角色一律剥掉，只保留 EXTERNAL_ROLES ∩ roles，
    # 杜绝"外部身份 + 内部角色并集"越权；外部专家因此能保住 R-EXPERT。
    from core.org_scope import external_roles_of, has_external_role

    if has_external_role(roles):
        roles = external_roles_of(roles)
    # 账号状态即时生效（M2-c / M2-b 遗留 I-3）：停用/删除后存量令牌立刻失效，
    # 不等 2h 过期。仅当库内确有该账号时判定（虚拟 uid 的集成令牌维持原语义）。
    _assert_account_active(int(claims.get("uid", 0) or 0))
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
