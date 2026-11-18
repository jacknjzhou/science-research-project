"""外部机构作用域（M2-b）：单一入口，避免各域各写一份角色/机构判定。

JWT claims 里没有 org_id（`core/auth/jwt_util.py` 的 gen_token 只签
uid/tenant_id/legal_entity_id/security_level/roles），因此机构 id 按需查一次
`sys_user.org_id` —— 每个请求至多一次轻量查询。
"""
from __future__ import annotations

_EXTERNAL_ROLE = "R-PARTNER"


def current_org_id(d) -> int | None:
    """当前用户所属外部机构 id；院内用户/无 org 返回 None。"""
    uid = getattr(d, "user_id", 0) or 0
    if uid <= 0:
        return None
    from apps.sysadmin.models import SysUser

    return (
        SysUser.objects.filter(id=uid, deleted=0)
        .values_list("org_id", flat=True)
        .first()
    )


def is_external_only(d) -> bool:
    """纯外部身份：角色集恰为 {R-PARTNER}（与 apps/p/api.py 的指南口径同源）。

    无角色（异常态）不在此判定内——调用方应各自 fail-closed。
    """
    roles = [r for r in (getattr(d, "roles", None) or []) if r]
    return roles == [_EXTERNAL_ROLE]
