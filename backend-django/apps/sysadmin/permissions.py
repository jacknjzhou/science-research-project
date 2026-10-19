"""接口权限目录与角色-权限指派的同步逻辑（Django 权限管理风格）。

- `sync_permissions_from_csv()`：把 config/casbin/policy.csv 的策略规则
  （p, role, obj, act）灌入 SysPermission（唯一 obj+act 权限目录）与
  SysRolePermission（角色-权限指派）。幂等，可重复执行。
- 数据迁移 0003 与 casbin_util 的空库兜底都复用本模块。
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings

from apps.sysadmin.models import SysPermission, SysRole, SysRolePermission


def slug_obj(obj: str) -> str:
    """路径模板 → 权限码片段：/api/v1/activities/*/submit → activities.x.submit。"""
    s = obj.removeprefix("/api/v1/").strip("/")
    s = s.replace("/", ".").replace("*", "x")
    return s or "root"


def sync_permissions_from_csv(policy_path: str | None = None) -> tuple[int, int]:
    """同步 policy.csv → SysPermission/SysRolePermission。返回 (新增权限数, 新增指派数)。"""
    path = Path(policy_path or settings.CASBIN_POLICY_PATH)
    perm_created = link_created = 0

    role_cache: dict[str, SysRole] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4 or parts[0] != "p":
            continue
        _, role_code, obj, act = parts

        role = role_cache.get(role_code)
        if role is None:
            role, _ = SysRole.objects.get_or_create(
                code=role_code, tenant_id=1,
                defaults={"name": role_code, "is_builtin": True},
            )
            role_cache[role_code] = role

        perm, created = SysPermission.objects.get_or_create(
            obj=obj, act=act,
            defaults={
                "code": f"{slug_obj(obj)}.{act.lower()}",
                "name": f"{act} {obj}",
                "domain": slug_obj(obj).split(".")[0],
                "tenant_id": 1,
            },
        )
        perm_created += int(created)

        _, link_created_flag = SysRolePermission.objects.get_or_create(
            role=role, permission=perm
        )
        link_created += int(link_created_flag)

    return perm_created, link_created
