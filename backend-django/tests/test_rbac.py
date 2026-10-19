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
