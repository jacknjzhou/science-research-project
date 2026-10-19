"""Casbin 装配与能力派生（对齐 Go auth/casbin.go + caps.go）。

策略来源（Django 权限管理风格，Phase 4.y 起）：
- DB 为唯一权威：SysRolePermission × SysPermission（角色-权限指派）。
- 数据迁移 0003 已把 config/casbin/policy.csv 灌入 DB；运行时若 DB 为空则自动兜底同步。
- 管理端授权/回收（PUT /admin/roles/{code}/permissions）后调用 reload_policy() 热生效。
- 铁律兜底：R-ADMIN 通配规则始终硬编码加载（防止误回收把管理员锁在门外）。
"""
from __future__ import annotations

import threading
import time

import casbin
from django.conf import settings

_lock = threading.Lock()
_watcher_lock = threading.Lock()
_watcher_started = threading.Event()
_enforcer: casbin.Enforcer | None = None

# 多实例一致性：权限变更后向 Redis 频道广播，所有 worker 进程订阅重载
RELOAD_CHANNEL = "ark:casbin:reload"

# 铁律兜底：超级管理员全域读写（不依赖 DB，防锁死）
_ADMIN_BASE_RULES = [
    ("R-ADMIN", "/api/v1/*", "GET"),
    ("R-ADMIN", "/api/v1/*", "POST"),
    ("R-ADMIN", "/api/v1/*", "PUT"),
    ("R-ADMIN", "/api/v1/*", "DELETE"),
]


class DbAdapter(casbin.persist.Adapter):
    """从 sys_role_permission × sys_permission 动态加载 casbin 策略。"""

    def load_policy(self, model) -> None:
        from apps.sysadmin.models import SysRolePermission

        qs = (
            SysRolePermission.objects.select_related("role", "permission")
            .values_list("role__code", "permission__obj", "permission__act")
            .order_by("id")
        )
        for role_code, obj, act in qs.iterator():
            casbin.persist.load_policy_line(f"p, {role_code}, {obj}, {act}", model)
        for rule in _ADMIN_BASE_RULES:
            casbin.persist.load_policy_line(f"p, {rule[0]}, {rule[1]}, {rule[2]}", model)

    def save_policy(self, model) -> bool:
        raise NotImplementedError("策略由管理 API 维护，不支持整体回写")


def get_enforcer() -> casbin.Enforcer:
    global _enforcer
    if _enforcer is None:
        with _lock:
            if _enforcer is None:
                _ensure_seeded()
                _enforcer = casbin.Enforcer(
                    settings.CASBIN_MODEL_PATH, DbAdapter(), True
                )
                _ensure_watcher()
    return _enforcer


def _ensure_seeded() -> None:
    """DB 权限目录为空时从 policy.csv 兜底同步（正常路径是数据迁移 0003）。"""
    from apps.sysadmin.models import SysPermission
    from apps.sysadmin.permissions import sync_permissions_from_csv

    if not SysPermission.objects.exists():
        sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


def reload_policy() -> None:
    """当前进程内热重载（本地开发 / 测试 / 单实例足够）。"""
    get_enforcer().load_policy()


def broadcast_reload() -> None:
    """本进程立即重载 + 广播 Redis 频道（多实例部署所有 worker 热生效）。"""
    reload_policy()
    try:
        from core import redis_util

        redis_util.get_client().publish(RELOAD_CHANNEL, str(time.time()))
    except Exception:
        pass  # Redis 不可用时退化为仅本进程重载（多实例场景需轮询兜底，见 README）


def _watch_loop() -> None:
    """订阅重载频道；断线 5s 退避重连（daemon 线程）。"""
    from core import redis_util

    while True:
        try:
            pubsub = redis_util.get_client().pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(RELOAD_CHANNEL)
            for _ in pubsub.listen():
                try:
                    reload_policy()
                except Exception:
                    continue
        except Exception:
            time.sleep(5)


def _ensure_watcher() -> None:
    """懒启动订阅线程（每进程一次；独立锁避免与 enforcer 创建锁互相死锁）。"""
    if _watcher_started.is_set():
        return
    with _watcher_lock:
        if _watcher_started.is_set():
            return
        threading.Thread(target=_watch_loop, daemon=True,
                         name="casbin-reload-watcher").start()
        _watcher_started.set()


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
