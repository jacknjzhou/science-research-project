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
    """外部身份判定：**只要持有 R-PARTNER 即按外部口径处理（fail-closed）**。

    终审 M2-b I2：早期实现用「角色集恰为 {R-PARTNER}」精确比较，导致
    `R-PARTNER + R-STAFF` 这类混合账号走内部分支，从而可伪造 pi_user_id /
    applicant_org_id（实测 200）。混合角色在业务上不是合法形态（见
    `apps/sysadmin/api.py` 的授权一致性校验），运行期一律按外部（更严）处理：
    调用方只给本机构数据、跨机构一律 404。
    """
    roles = [r for r in (getattr(d, "roles", None) or []) if r]
    return _EXTERNAL_ROLE in roles
