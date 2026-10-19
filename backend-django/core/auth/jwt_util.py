"""JWT 签发/校验（对齐 Go auth/jwt.go：HS256，claims 含 uid/tenant_id/legal_entity_id/security_level/roles）。"""
from __future__ import annotations

import time
from typing import Any

import jwt
from django.conf import settings


class TokenError(Exception):
    pass


def gen_token(
    user_id: int,
    tenant_id: int,
    legal_entity_id: int,
    security_level: str,
    roles: list[str],
    ttl_sec: int | None = None,
) -> str:
    now = int(time.time())
    ttl = ttl_sec if ttl_sec is not None else settings.JWT_TTL_SEC
    payload: dict[str, Any] = {
        "uid": user_id,
        "tenant_id": tenant_id,
        "legal_entity_id": legal_entity_id,
        "security_level": security_level,
        "roles": roles,
        "exp": now + ttl,
        "iat": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def parse_token(raw: str) -> dict[str, Any]:
    """校验并返回 claims；任何失败抛 TokenError（调用方转 40102）。"""
    try:
        claims = jwt.decode(
            raw,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "iat"]},
        )
    except Exception as exc:  # PyJWT 各类异常统一归为无效令牌
        raise TokenError(str(exc)) from exc
    return claims
