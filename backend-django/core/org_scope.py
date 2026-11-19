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


_MISS = object()


def _account_row(d):
    """请求内一次性取 (org_id, user_source)，缓存在 Domain 上——单请求至多一次查询。

    P 域一个 handler 里 `is_external_account`/`current_org_id` 常有 2-3 次判定，
    不缓存就会把一个轻量查询放大成 3 次（终审 r3 关注点）。
    """
    cached = getattr(d, "_org_scope_row", _MISS)
    if cached is not _MISS:
        return cached
    uid = getattr(d, "user_id", 0) or 0
    row = None
    if uid > 0:
        from apps.sysadmin.models import SysUser

        row = (
            SysUser.objects.filter(id=uid, deleted=0)
            .values_list("org_id", "user_source")
            .first()
        )
    try:
        setattr(d, "_org_scope_row", row)
    except Exception:  # noqa: BLE001 —— 非 dataclass 宿主退化为不缓存
        pass
    return row


def current_org_id(d) -> int | None:
    """当前用户所属外部机构 id；院内用户/无 org 返回 None。"""
    row = _account_row(d)
    return None if row is None else row[0]


def user_source_of(d) -> str | None:
    """当前账号的来源（INTERNAL/EXTERNAL）；无库内账号返回 None。"""
    row = _account_row(d)
    if row is None:
        return None
    return (row[1] or "").upper() or None


def is_external_account(d) -> bool:
    """按**账号来源**判定外部身份（M2-c 终审 r2 N-4）。

    判定顺序（先硬后软）：
    1. 令牌里出现 **R-PARTNER** → 恒为外部（不看 user_source）。R-PARTNER 就是
       "外部机构用户"的身份标签，来源字段写错也不能让它走内部分支；
    2. 否则看 `sys_user.user_source`：EXTERNAL → 外部，INTERNAL → 院内；
    3. 账号不在库里（虚拟/集成令牌）→ 回退到角色判定。
    这样院内专家（R-STAFF+R-EXPERT）不会被当成外部挡住自己的申报，
    而"来源院内 + 角色机构"的两义账号仍按外部收口（fail-closed）。
    """
    roles = [r for r in (getattr(d, "roles", None) or []) if r]
    # R-PARTNER 语义就是"外部机构用户"——不论 user_source 写成什么，一律按外部
    # （终审 r3 I-1：管理端可造出 user_source=INTERNAL + R-PARTNER 的账号，
    #  若只看来源就会让它在 P 域走内部分支、跨机构读写并伪造 PI/机构）。
    if "R-PARTNER" in roles:
        return True
    src = user_source_of(d)
    if src:
        return src == "EXTERNAL"
    return has_external_role(roles)
