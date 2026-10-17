"""Casbin 装配与能力派生（对齐 Go auth/casbin.go + caps.go）。

model.conf 与 policy.csv 从 Go 版零修改复制（config/casbin/）；
策略语义：逐角色 enforce，任一命中即放行。
"""
from __future__ import annotations

import threading
from functools import lru_cache

import casbin
from django.conf import settings

_lock = threading.Lock()
_enforcer: casbin.Enforcer | None = None


def get_enforcer() -> casbin.Enforcer:
    global _enforcer
    if _enforcer is None:
        with _lock:
            if _enforcer is None:
                _enforcer = casbin.Enforcer(
                    settings.CASBIN_MODEL_PATH, settings.CASBIN_POLICY_PATH
                )
    return _enforcer


def enforce_any(roles: list[str], path: str, method: str) -> bool:
    """逐角色判定，命中即放行（对齐 middleware.Auth 循环）。"""
    enf = get_enforcer()
    for role in roles:
        try:
            if enf.enforce(role, path, method):
                return True
        except Exception:
            continue
    return False


def build_caps(roles: list[str]) -> list[str]:
    """依角色从策略集派生能力集合："<obj模板> <METHOD>"，排序输出（对齐 BuildCaps）。"""
    if not roles:
        return []
    enf = get_enforcer()
    in_roles = set(roles)
    found: set[str] = set()
    try:
        rules = enf.get_policy()
    except Exception:
        return []
    for p in rules:
        if len(p) < 3 or p[0] not in in_roles:
            continue
        found.add(f"{p[1].strip()} {p[2].upper()}")
    return sorted(found)
