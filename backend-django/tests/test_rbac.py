"""RBAC 专项测试：角色定义 × 权限指派驱动前后端访问控制（Django 权限管理风格）。

覆盖：
- 后端接口访问：casbin 判权（路径+方法 × 角色），无权 → 40301
- 权限目录与角色-权限指派的查询 / 授权 / 回收（热生效）
- /auth/me caps 派生（前端按钮级控制的数据源）
- 页面可见性矩阵（前端路由守卫的数据源）
"""
from __future__ import annotations

import json

from django.test import Client

from core.auth.casbin_util import reload_policy
from tests.conftest import bearer


def _c():
    return Client()


def _json(r):
    return r.json()


DEAL_CODE = "deal.post"          # POST /api/v1/deal（T 域创建交易）
AUDIT_WRITE_CODE = None          # 运行时按 obj+act 反查


def _perm_code(obj: str, act: str) -> str | None:
    from apps.sysadmin.models import SysPermission
    p = SysPermission.objects.filter(obj=obj, act=act).first()
    return p.code if p else None


def _reset_enforcer():
    """测试隔离：从当前 DB 重新加载策略（事务回滚后内存策略也归零）。"""
    reload_policy()


# ===========================================================================
# 1. 后端接口访问控制（casbin 路径+方法判权）
# ===========================================================================

def test_rbac_deny_and_allow_by_role(seed_auth):
    """R-AUDITOR 只读：GET 放行、POST 拒绝 40301；R-MANAGER 写放行。"""
    _reset_enforcer()
    c = _c()
    # R-AUDITOR 读交易列表 → 放行
    r = c.get("/api/v1/deal", **bearer(4, ["R-AUDITOR"]))
    assert r.status_code == 200 and _json(r)["code"] == 0
    # R-AUDITOR 写 → casbin 拒绝
    r = c.post("/api/v1/deal", data=json.dumps({}),
               content_type="application/json", **bearer(4, ["R-AUDITOR"]))
    assert r.status_code == 403 and _json(r)["code"] == 40301
    # R-STAFF 无交易创建权限（管理员专属操作面之外的策略空白）→ 40301
    r = c.post("/api/v1/deal", data=json.dumps({}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40301
    # R-MANAGER 写 → 放行（进入业务校验层，不再是 403）
    r = c.post("/api/v1/deal", data=json.dumps({}),
               content_type="application/json", **bearer(2, ["R-MANAGER"]))
    assert _json(r)["code"] != 40301


def test_rbac_unauthenticated_401(seed_auth):
    """无 Bearer 头 → 401 未认证（区别于 403 无权限）。"""
    _reset_enforcer()
    c = _c()
    r = c.get("/api/v1/deal")
    assert r.status_code == 401 and _json(r)["code"] in (40101, 40102)


def test_rbac_admin_wildcard(seed_auth):
    """R-ADMIN 通配全域读写（铁律兜底，即使 DB 指派被清空）。"""
    _reset_enforcer()
    c = _c()
    r = c.get("/api/v1/admin/permissions", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200 and _json(r)["code"] == 0


# ===========================================================================
# 2. 权限目录 / 角色指派：查询、授权、回收（热生效）
# ===========================================================================

def test_permission_catalog_and_matrix(seed_auth):
    """权限目录分页 + 指派矩阵（roles 字段）+ 域过滤。"""
    _reset_enforcer()
    c = _c()
    r = c.get("/api/v1/admin/permissions?size=50", **bearer(1, ["R-ADMIN"]))
    d = _json(r)["data"]
    assert d["total"] >= 300 and len(d["domains"]) >= 10
    r = c.get(f"/api/v1/admin/permissions?q={DEAL_CODE}", **bearer(1, ["R-ADMIN"]))
    row = next(x for x in _json(r)["data"]["items"] if x["code"] == DEAL_CODE)
    assert "R-MANAGER" in row["roles"] and "R-AUDITOR" not in row["roles"]
    # 域过滤
    r = c.get("/api/v1/admin/permissions?domain=ethics&size=5", **bearer(1, ["R-ADMIN"]))
    assert all(x["domain"] == "ethics" for x in _json(r)["data"]["items"])


def test_permission_catalog_paging_no_overlap(seed_auth):
    """分页翻页不重叠、不丢行（page_args limit 语义回归：qs[offset:offset+limit]）。"""
    _reset_enforcer()
    c = _c()
    r = c.get("/api/v1/admin/permissions?size=50&page=1", **bearer(1, ["R-ADMIN"]))
    d1 = _json(r)["data"]
    p1 = [x["code"] for x in d1["items"]]
    assert len(p1) == 50 and d1["total"] >= 300
    r = c.get("/api/v1/admin/permissions?size=50&page=2", **bearer(1, ["R-ADMIN"]))
    d2 = _json(r)["data"]
    p2 = [x["code"] for x in d2["items"]]
    assert len(p2) == 50, f"第 2 页应满 50 行（原 bug：qs[offset:limit] 返回空），实际 {len(p2)}"
    assert not set(p1) & set(p2), "第 1/2 页不应重叠"


def test_permission_catalog_role_filter_keeps_full_catalog(seed_auth):
    """role_code 过滤仅标注持有状态、不裁剪目录（前端勾选面板可跨页授权新权限）。"""
    _reset_enforcer()
    c = _c()
    r = c.get("/api/v1/admin/permissions?size=1", **bearer(1, ["R-ADMIN"]))
    full_total = _json(r)["data"]["total"]
    assert full_total >= 300
    r = c.get("/api/v1/admin/permissions?role_code=R-MANAGER&size=200", **bearer(1, ["R-ADMIN"]))
    d = _json(r)["data"]
    assert d["total"] == full_total, "角色过滤不得缩减目录 total"
    held = [x for x in d["items"] if "R-MANAGER" in x["roles"]]
    not_held = [x for x in d["items"] if x["roles"] == []]
    assert held, "R-MANAGER 已持有权限必须标注在 roles 中"
    assert not_held, "未持有权限必须保留在目录中（roles=[]，供勾选新授权）"


def test_grant_revoke_hot_reload(seed_auth):
    """授权 → 立即放行；回收 → 立即 40301（enforcer 热重载）。"""
    _reset_enforcer()
    c = _c()
    # 前置：R-STAFF 不能 POST /api/v1/deal
    r = c.post("/api/v1/deal", data=json.dumps({}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40301
    # admin 授权 R-STAFF → deal.post
    r = c.put(f"/api/v1/admin/roles/R-STAFF/permissions",
              data=json.dumps({"grants": [DEAL_CODE], "revokes": []}),
              content_type="application/json", **bearer(1, ["R-ADMIN"]))
    d = _json(r)["data"]
    assert d["granted"] == 1 and DEAL_CODE in d["permissions"]
    # 授权后放行（进入业务校验，非 403）
    r = c.post("/api/v1/deal", data=json.dumps({}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] != 40301
    # 回收 → 恢复 40301
    r = c.put(f"/api/v1/admin/roles/R-STAFF/permissions",
              data=json.dumps({"grants": [], "revokes": [DEAL_CODE]}),
              content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["data"]["revoked"] == 1
    r = c.post("/api/v1/deal", data=json.dumps({}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40301


def test_grant_revoke_validation(seed_auth):
    """未知权限码 / grants+revokes 交集 / 未知角色 → 400/404。"""
    _reset_enforcer()
    c = _c()
    r = c.put("/api/v1/admin/roles/R-STAFF/permissions",
              data=json.dumps({"grants": ["no.such.perm"], "revokes": []}),
              content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["code"] == 40007 or _json(r)["code"] == 40001 or r.status_code == 400
    r = c.put("/api/v1/admin/roles/R-GHOST/permissions",
              data=json.dumps({"grants": [], "revokes": []}),
              content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["code"] == 40401
    # 非管理员无法管理权限
    r = c.put("/api/v1/admin/roles/R-STAFF/permissions",
              data=json.dumps({"grants": [DEAL_CODE], "revokes": []}),
              content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40301


# ===========================================================================
# 3. /auth/me caps 派生（前端按钮级控制数据源）+ 页面矩阵（路由守卫数据源）
# ===========================================================================

def test_me_caps_reflect_grants(seed_auth):
    """caps 从 casbin 策略派生：授权后 caps 增加，回收后消失。"""
    from apps.sysadmin.models import SysRole, SysPermission, SysUserRole
    from core.auth.jwt_util import gen_token

    _reset_enforcer()
    # staff 用户挂 R-STAFF 角色（caps 按角色码派生）
    c = _c()
    r = c.get("/api/v1/auth/me", **bearer(2, ["R-STAFF"]))
    caps0 = _json(r)["data"]["caps"]
    assert "/api/v1/deal POST" not in caps0
    # 授权
    c.put("/api/v1/admin/roles/R-STAFF/permissions",
          data=json.dumps({"grants": [DEAL_CODE], "revokes": []}),
          content_type="application/json", **bearer(1, ["R-ADMIN"]))
    r = c.get("/api/v1/auth/me", **bearer(2, ["R-STAFF"]))
    assert "/api/v1/deal POST" in _json(r)["data"]["caps"]
    # 回收
    c.put("/api/v1/admin/roles/R-STAFF/permissions",
          data=json.dumps({"grants": [], "revokes": [DEAL_CODE]}),
          content_type="application/json", **bearer(1, ["R-ADMIN"]))
    r = c.get("/api/v1/auth/me", **bearer(2, ["R-STAFF"]))
    assert "/api/v1/deal POST" not in _json(r)["data"]["caps"]


def test_page_matrix_endpoint(seed_auth, seed_pages):
    """页面可见性矩阵（前端路由守卫唯一权威）可读、仅管理员可写。"""
    _reset_enforcer()
    c = _c()
    r = c.get("/api/v1/page-grants", **bearer(2, ["R-STAFF"]))
    grants = _json(r)["data"]["grants"]
    assert {"page_name": "bigscreen", "role_code": "R-LEADER"} in grants
    # R-STAFF 写矩阵 → 40301（PUT /admin/* 仅 R-ADMIN 通配）
    r = c.put("/api/v1/admin/page-grants",
              data=json.dumps({"grants": [{"page_name": "dash", "role_code": "*"}]}),
              content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40301
    # R-ADMIN 写 → 放行
    r = c.put("/api/v1/admin/page-grants",
              data=json.dumps({"grants": [
                  {"page_name": "dash", "role_code": "*"},
                  {"page_name": "bigscreen", "role_code": "R-LEADER"}]}),
              content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["code"] == 0


# ===========================================================================
# 4. M1-b：凭证同步/决算/成本池/平行记账策略放行（A4/A5/A7）
# ===========================================================================

import os

_POLICY_CSV = os.path.join(os.path.dirname(__file__), "..", "config", "casbin", "policy.csv")


def _policy_p_rows():
    """解析 policy.csv 中全部 p, 规则行为 (sub, obj, act) 三元组集合。"""
    rows = set()
    with open(_POLICY_CSV, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith("p,"):
                continue
            parts = [x.strip() for x in line.split(",")]
            rows.add((parts[1], parts[2], parts[3]))
    return rows


def _m1b_expected_rows():
    """M1-b F 块新增 27 行（R-FINANCE 12、R-MANAGER 8、R-LEADER 7）。

    keyMatch2 裁决：裸路径 POST 不匹配子段 /cost-pools/calculate，
    故 calculate 以显式行放行（同 /api/v1/expense/ai-invoice-review 先例）。
    """
    rows = [
        # R-MANAGER：成本池读写（calculate 显式行）、平行记账只读、决算只读
        ("R-MANAGER", "/api/v1/settlements", "GET"),
        ("R-MANAGER", "/api/v1/settlements/*", "GET"),
        ("R-MANAGER", "/api/v1/cost-pools", "GET"),
        ("R-MANAGER", "/api/v1/cost-pools", "POST"),
        ("R-MANAGER", "/api/v1/cost-pools/*", "GET"),
        ("R-MANAGER", "/api/v1/cost-pools/calculate", "POST"),
        ("R-MANAGER", "/api/v1/accounting-entries", "GET"),
        ("R-MANAGER", "/api/v1/accounting-entries/*", "GET"),
        # R-LEADER：决算只读 + 审批；成本池/平行记账只读
        ("R-LEADER", "/api/v1/settlements", "GET"),
        ("R-LEADER", "/api/v1/settlements/*", "GET"),
        ("R-LEADER", "/api/v1/settlements/*/approve", "POST"),
        ("R-LEADER", "/api/v1/cost-pools", "GET"),
        ("R-LEADER", "/api/v1/cost-pools/*", "GET"),
        ("R-LEADER", "/api/v1/accounting-entries", "GET"),
        ("R-LEADER", "/api/v1/accounting-entries/*", "GET"),
        # R-FINANCE：凭证同步/回调 + 决算全量 + 审批 + 成本池读写（calculate 显式行）+ 平行记账只读
        ("R-FINANCE", "/api/v1/vouchers/sync", "POST"),
        ("R-FINANCE", "/api/v1/vouchers/sync-callback", "POST"),
        ("R-FINANCE", "/api/v1/settlements", "GET"),
        ("R-FINANCE", "/api/v1/settlements", "POST"),
        ("R-FINANCE", "/api/v1/settlements/*", "GET"),
        ("R-FINANCE", "/api/v1/settlements/*/approve", "POST"),
        ("R-FINANCE", "/api/v1/cost-pools", "GET"),
        ("R-FINANCE", "/api/v1/cost-pools", "POST"),
        ("R-FINANCE", "/api/v1/cost-pools/*", "GET"),
        ("R-FINANCE", "/api/v1/cost-pools/calculate", "POST"),
        ("R-FINANCE", "/api/v1/accounting-entries", "GET"),
        ("R-FINANCE", "/api/v1/accounting-entries/*", "GET"),
    ]
    return rows


def test_m1b_policy_rows_exist():
    """M1-b 27 行 (role,path,action) 必须全部存在于 policy.csv。"""
    rows = _policy_p_rows()
    missing = [r for r in _m1b_expected_rows() if r not in rows]
    assert not missing, f"缺少 M1-b 策略行: {missing}"


def test_m1b_bare_and_wildcard_paired():
    """keyMatch2 铁律：裸路径永不匹配子路径，资源 GET 必须与 /* 成对放行；
    POST 仅集合根（创建）+ 显式动作行，不要求裸/通配成对。"""
    rows = _policy_p_rows()
    for role in ("R-MANAGER", "R-LEADER", "R-FINANCE"):
        for bare, wild in (
            ("/api/v1/settlements", "/api/v1/settlements/*"),
            ("/api/v1/cost-pools", "/api/v1/cost-pools/*"),
            ("/api/v1/accounting-entries", "/api/v1/accounting-entries/*"),
        ):
            # GET 必须裸/通配成对（列表 + 详情）
            assert (role, bare, "GET") in rows or (role, wild, "GET") not in rows
            if (role, bare, "GET") in rows:
                assert (role, wild, "GET") in rows, \
                    f"{role} {bare} GET 缺少配对的 {wild} GET（keyMatch2 铁律）"
    # R-FINANCE 决算 POST 也需裸/通配成对（决算明细可写）
    assert ("R-FINANCE", "/api/v1/settlements/*", "GET") in rows


def test_m1b_keymatch2_multi_segment_coverage():
    """keyMatch2 实测裁决：裸路径 POST 不匹配 /cost-pools/calculate 子段（显式行放行，
    同 /api/v1/expense/ai-invoice-review 先例）；/settlements/*/approve 两段子路径显式行。"""
    from casbin.util import key_match2
    rows = _policy_p_rows()
    # 裁决 1：calculate（子段）不被裸路径匹配 → 需显式行（铁律：裸路径永不匹配子路径）
    assert not key_match2("/api/v1/cost-pools/calculate", "/api/v1/cost-pools")
    assert key_match2("/api/v1/cost-pools/calculate", "/api/v1/cost-pools/*")
    # 裁决 2：calculate 由显式行覆盖（主管/财务可算）
    assert key_match2("/api/v1/cost-pools/calculate", "/api/v1/cost-pools/calculate")
    assert ("R-MANAGER", "/api/v1/cost-pools/calculate", "POST") in rows
    assert ("R-FINANCE", "/api/v1/cost-pools/calculate", "POST") in rows
    # 裁决 3：approve 动作路由显式成行（bare/* 行只有 GET，不带 POST）
    assert key_match2("/api/v1/settlements/1/approve", "/api/v1/settlements/*/approve")
    assert ("R-LEADER", "/api/v1/settlements/*/approve", "POST") in rows
    assert ("R-FINANCE", "/api/v1/settlements/*/approve", "POST") in rows
    # 裁决 4：sync-callback 与 sync 是不同路径，各自显式放行
    assert not key_match2("/api/v1/vouchers/sync-callback", "/api/v1/vouchers/sync")
    assert ("R-FINANCE", "/api/v1/vouchers/sync-callback", "POST") in rows
    # 负面：R-LEADER 不得写成本池 / 不得同步凭证 / 不得建决算
    assert ("R-LEADER", "/api/v1/cost-pools", "POST") not in rows
    assert ("R-LEADER", "/api/v1/cost-pools/calculate", "POST") not in rows
    assert ("R-LEADER", "/api/v1/vouchers/sync", "POST") not in rows
    assert ("R-LEADER", "/api/v1/settlements", "POST") not in rows


# ===========================================================================
# 5. M1-c：拨款/回单识别/核算开户策略放行（A6/A8/B1）
# ===========================================================================

def _m1c_expected_rows():
    """M1-c 新增 14 行（R-FINANCE 6、R-MANAGER 5、R-LEADER 3）。

    keyMatch2 裁决：裸路径 POST 不匹配子段——/disbursements/*/action（两段子路径）
    与 /disbursements/check-contract（字面静态段）、/incomes/ocr-receipt、
    /projects/*/open-account 均以显式行放行（同 M1-b cost-pools/calculate 先例）。
    """
    rows = [
        # R-FINANCE：拨款创建+列表+审批/付款动作+合同预检；回单识别；核算开户
        ("R-FINANCE", "/api/v1/disbursements", "GET"),
        ("R-FINANCE", "/api/v1/disbursements", "POST"),
        ("R-FINANCE", "/api/v1/disbursements/*/action", "POST"),
        ("R-FINANCE", "/api/v1/disbursements/check-contract", "POST"),
        ("R-FINANCE", "/api/v1/incomes/ocr-receipt", "POST"),
        ("R-FINANCE", "/api/v1/projects/*/open-account", "POST"),
        # R-MANAGER：拨款创建+列表+合同预检；回单识别；核算开户（无审批/付款动作）
        ("R-MANAGER", "/api/v1/disbursements", "GET"),
        ("R-MANAGER", "/api/v1/disbursements", "POST"),
        ("R-MANAGER", "/api/v1/disbursements/check-contract", "POST"),
        ("R-MANAGER", "/api/v1/incomes/ocr-receipt", "POST"),
        ("R-MANAGER", "/api/v1/projects/*/open-account", "POST"),
        # R-LEADER：拨款列表只读；回单识别；核算开户
        ("R-LEADER", "/api/v1/disbursements", "GET"),
        ("R-LEADER", "/api/v1/incomes/ocr-receipt", "POST"),
        ("R-LEADER", "/api/v1/projects/*/open-account", "POST"),
    ]
    return rows


def test_m1c_policy_rows_exist():
    """M1-c 14 行 (role,path,action) 必须全部存在于 policy.csv。"""
    rows = _policy_p_rows()
    missing = [r for r in _m1c_expected_rows() if r not in rows]
    assert not missing, f"缺少 M1-c 策略行: {missing}"


def test_m1c_keymatch2_coverage():
    """keyMatch2 实测裁决：裸路径 POST 不匹配 /disbursements/{id}/action 与
    /disbursements/check-contract 子段（显式行放行）；check-contract 为字面静态段
    不被 {id} 通配歧义误配；/projects/{id}/open-account 由 * 通配覆盖。"""
    from casbin.util import key_match2
    rows = _policy_p_rows()
    # 裁决 1：action 两段子路径不被裸路径匹配 → 显式行（铁律：裸路径永不匹配子路径）
    assert not key_match2("/api/v1/disbursements/1/action", "/api/v1/disbursements")
    assert key_match2("/api/v1/disbursements/1/action", "/api/v1/disbursements/*/action")
    assert ("R-FINANCE", "/api/v1/disbursements/*/action", "POST") in rows
    # 裁决 2：check-contract 字面静态段，显式行精确覆盖；不被 {id} 段歧义
    assert not key_match2("/api/v1/disbursements/check-contract", "/api/v1/disbursements")
    assert key_match2("/api/v1/disbursements/check-contract", "/api/v1/disbursements/check-contract")
    assert not key_match2("/api/v1/disbursements/check-contract", "/api/v1/disbursements/*/action")
    assert not key_match2("/api/v1/disbursements/1/action", "/api/v1/disbursements/check-contract")
    assert ("R-FINANCE", "/api/v1/disbursements/check-contract", "POST") in rows
    assert ("R-MANAGER", "/api/v1/disbursements/check-contract", "POST") in rows
    # 裁决 3：open-account 由 {id} 通配匹配任意项目 id
    assert key_match2("/api/v1/projects/5/open-account", "/api/v1/projects/*/open-account")
    assert not key_match2("/api/v1/projects/5", "/api/v1/projects/*/open-account")
    for role in ("R-FINANCE", "R-MANAGER", "R-LEADER"):
        assert (role, "/api/v1/projects/*/open-account", "POST") in rows
        assert (role, "/api/v1/incomes/ocr-receipt", "POST") in rows
    # 裁决 4：ocr-receipt 子段不被 incomes 裸路径匹配（显式行放行）
    assert not key_match2("/api/v1/incomes/ocr-receipt", "/api/v1/incomes")
    # 负面：R-LEADER 不得创建/审批拨款；R-MANAGER 不得审批/付款拨款
    assert ("R-LEADER", "/api/v1/disbursements", "POST") not in rows
    assert ("R-LEADER", "/api/v1/disbursements/*/action", "POST") not in rows
    assert ("R-LEADER", "/api/v1/disbursements/check-contract", "POST") not in rows
    assert ("R-MANAGER", "/api/v1/disbursements/*/action", "POST") not in rows


# ---------------------------------------------------------------------------
# M1-d：统一评估模板写维护（B3）
# ---------------------------------------------------------------------------
def _m1d_expected_rows():
    """M1-d 新增 3 行：评估模板写维护仅 R-MANAGER。

    读（GET 集合/详情）已由既有 `R-MANAGER /api/v1/project/* GET` 通配覆盖
    （keyMatch2 实测：`/api/v1/project/eval-templates` 被 `/api/v1/project/*` 匹配），
    故不重复加 GET 行；写（POST/PUT/DELETE）必须显式行——project/* 仅授 GET。
    """
    return [
        ("R-MANAGER", "/api/v1/project/eval-templates", "POST"),
        ("R-MANAGER", "/api/v1/project/eval-templates/*", "PUT"),
        ("R-MANAGER", "/api/v1/project/eval-templates/*", "DELETE"),
    ]


def test_m1d_policy_rows_exist():
    """M1-d 3 行 (role,path,action) 必须全部存在于 policy.csv。"""
    rows = _policy_p_rows()
    missing = [r for r in _m1d_expected_rows() if r not in rows]
    assert not missing, f"缺少 M1-d 策略行: {missing}"


def test_m1d_keymatch2_coverage():
    """keyMatch2 实测裁决：模板读由 project/* GET 通配覆盖；写需显式行；
    看板/变更版本只读同样由 project/* GET 覆盖；指南发布/关闭动作由 apply/* POST 覆盖。"""
    from casbin.util import key_match2
    rows = _policy_p_rows()

    # 裁决 1：eval-templates 集合与详情都被 project/* 的 GET 通配覆盖（读不需新行）
    assert key_match2("/api/v1/project/eval-templates", "/api/v1/project/*")
    assert key_match2("/api/v1/project/eval-templates/7", "/api/v1/project/*")
    assert ("R-MANAGER", "/api/v1/project/*", "GET") in rows

    # 裁决 2：project/* 通配仅授 GET，故模板写必须显式行（不存在隐式写放行）
    assert ("R-MANAGER", "/api/v1/project/*", "POST") not in rows
    for role, path, act in _m1d_expected_rows():
        assert (role, path, act) in rows

    # 裁决 3：模板详情写路径不被集合裸路径匹配（keyMatch2 铁律）
    assert not key_match2("/api/v1/project/eval-templates/7", "/api/v1/project/eval-templates")
    assert key_match2("/api/v1/project/eval-templates/7", "/api/v1/project/eval-templates/*")

    # 裁决 4：看板 / 变更版本只读落在 project/* GET 通配内
    assert key_match2("/api/v1/project/5/board", "/api/v1/project/*")
    assert key_match2("/api/v1/project/5/change-request/9/versions", "/api/v1/project/*")

    # 裁决 5：指南发布/关闭冒号动作由 apply/* POST 通配覆盖（无需新行）
    assert key_match2("/api/v1/apply/guidelines/3:publish", "/api/v1/apply/*")
    assert key_match2("/api/v1/apply/guidelines/3:close", "/api/v1/apply/*")
    assert ("R-MANAGER", "/api/v1/apply/*", "POST") in rows
