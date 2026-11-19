"""外部机构作用域（M2-b）：单一入口，避免各域各写一份角色/机构判定。

JWT claims 里没有 org_id（`core/auth/jwt_util.py` 的 gen_token 只签
uid/tenant_id/legal_entity_id/security_level/roles），因此机构 id 按需查一次
`sys_user.org_id` —— 每个请求至多一次轻量查询。
"""
from __future__ import annotations

# 外部允许集（M2-c）：外部机构用户 + 外部评审专家。两者都是"外部身份"，
# 运行期一律按外部（更严）口径处理；内部角色即使残留在令牌里也被 deps 剥掉。
EXTERNAL_ROLES: tuple[str, ...] = ("R-PARTNER", "R-EXPERT")


def external_roles_of(roles: list[str] | None) -> list[str]:
    """保留外部允许集内的角色（保序去重）；调用方负责丢弃其余内部角色。"""
    out: list[str] = []
    for r in roles or []:
        if r in EXTERNAL_ROLES and r not in out:
            out.append(r)
    return out


def has_external_role(roles: list[str] | None) -> bool:
    return bool(set(roles or []) & set(EXTERNAL_ROLES))


def normalize_roles_for_account(roles: list[str] | None, user_source: str | None) -> list[str]:
    """按角色语义 + 账号来源裁剪角色（M2-c 终审 I-2 修复）。

    规则（从严到宽）：
    1. 令牌里有 **R-PARTNER** → 恒按外部口径，只留外部允许集（剥掉全部内部角色）。
       R-PARTNER 语义就是"外部机构用户"，院内账号不该持有；存量脏数据一律不外溢。
    2. 只有 **R-EXPERT** 且账号来源是 EXTERNAL → 只留外部允许集（外部专家不得兼内部角色）。
    3. 只有 R-EXPERT 且账号来源是院内/未知 → 原样保留（院内专家是合法形态，不降权）。
    4. 无外部角色 → 原样保留。
    """
    codes = [str(r) for r in (roles or []) if r]
    if "R-PARTNER" in codes:
        return external_roles_of(codes)
    if (user_source or "").upper() == "EXTERNAL" and has_external_role(codes):
        return external_roles_of(codes)
    return codes


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
    return has_external_role(roles)
