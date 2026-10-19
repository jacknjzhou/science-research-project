"""请求域上下文（对齐 Go auth.DomainFrom）：认证成功后注入 request.domain。"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.http import HttpRequest

from core.auth.casbin_util import enforce_any
from core.auth.jwt_util import TokenError, parse_token
from core.httpx import (
    ApiError,
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
