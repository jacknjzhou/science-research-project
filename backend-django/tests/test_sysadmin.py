"""用户/角色/字典/页面矩阵端点测试（移植 Go sysadmin handler 测试语义）。"""
import json

from django.test import Client

from tests.conftest import bearer


def _c():
    return Client()


# ---------------------------------------------------------------------------
# 用户管理
# ---------------------------------------------------------------------------
def test_create_and_list_users(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/admin/users",
        data=json.dumps(
            {"username": "alice", "real_name": "爱丽丝", "password": "Secret@1",
             "roles": ["R-STAFF", "UNKNOWN_ROLE"]}
        ),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    u = r.json()["data"]
    assert u["username"] == "alice"
    assert u["roles"] == ["R-STAFF"]  # 未知角色码忽略
    assert "password_hash" not in u  # 铁律：口令哈希永不外泄

    r = c.get("/api/v1/admin/users", **bearer(1, ["R-ADMIN"]))
    body = r.json()["data"]
    assert body["total"] == 3
    assert body["page"] == 1 and body["size"] == 20


def test_create_user_dup_username_409(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/admin/users",
        data=json.dumps({"username": "admin", "real_name": "重复", "password": "x"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    assert r.json()["message"] == "用户名已存在或写入冲突"


def test_update_user_merge_and_password(seed_auth):
    c = _c()
    r = c.put(
        "/api/v1/admin/users/2",
        data=json.dumps({"real_name": "改名", "password": "NewP@ss"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["real_name"] == "改名"
    # 新口令可登录
    r2 = c.post(
        "/api/v1/auth/login",
        data={"username": "staff", "password": "NewP@ss"},
        content_type="application/json",
    )
    assert r2.status_code == 200


def test_delete_user_soft(seed_auth):
    c = _c()
    r = c.delete("/api/v1/admin/users/2", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"] == {"id": 2, "deleted": True}
    from apps.sysadmin.models import SysUser

    u = SysUser.objects.get(id=2)
    assert u.deleted == 1 and u.status == "DISABLED"
    # 软删后列表/详情均不可见
    r = c.get("/api/v1/admin/users/2", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 404


def test_get_user_404(seed_auth):
    c = _c()
    r = c.get("/api/v1/admin/users/9999", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 404
    assert r.json()["code"] == 40401


# ---------------------------------------------------------------------------
# 角色目录
# ---------------------------------------------------------------------------
def test_list_roles(seed_auth):
    c = _c()
    r = c.get("/api/v1/admin/roles", **bearer(1, ["R-ADMIN"]))
    codes = [x["code"] for x in r.json()["data"]["list"]]
    # 顺序无关：角色行可能由数据迁移 0003（policy.csv 顺序）或 seed_auth 创建
    assert sorted(codes) == sorted(["R-STAFF", "R-MANAGER", "R-LEADER", "R-FINANCE",
                                    "R-AUDITOR", "R-EXPERT", "R-ETHICS", "R-ADMIN"])


def test_create_update_delete_role(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/admin/roles",
        data=json.dumps({"code": "R-CUSTOM", "name": "自定义"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["is_builtin"] is False
    rid = r.json()["data"]["id"]

    r = c.put(
        f"/api/v1/admin/roles/{rid}",
        data=json.dumps({"name": "改名"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["name"] == "改名"

    r = c.delete(f"/api/v1/admin/roles/{rid}", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"] == {"id": rid, "deleted": True}


def test_create_role_dup_409(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/admin/roles",
        data=json.dumps({"code": "R-STAFF", "name": "重复"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 409
    assert r.json()["message"] == "角色编码已存在"


def test_delete_builtin_role_409(seed_auth):
    c = _c()
    r = c.delete("/api/v1/admin/roles/1", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409
    assert r.json()["message"] == "内置角色不可删除"


def test_delete_bound_role_409(seed_auth):
    """自定义角色已绑定用户 → 409 可读报错（内置角色走 builtin 分支）。"""
    c = _c()
    from apps.sysadmin.models import SysRole, SysUserRole

    role = SysRole.objects.create(code="R-CUSTOM", name="自定义", is_builtin=False, tenant_id=1)
    SysUserRole.objects.create(user_id=2, role=role, tenant_id=1)
    r = c.delete(f"/api/v1/admin/roles/{role.id}", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409
    assert "已绑定 1 个用户" in r.json()["message"]


def test_assign_revoke_role(seed_auth):
    c = _c()
    from apps.sysadmin.models import SysRole

    fid = SysRole.objects.filter(code="R-FINANCE").first().id
    r = c.post(
        "/api/v1/admin/users/2/roles",
        data=json.dumps({"role_id": fid}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert sorted(r.json()["data"]["roles"]) == ["R-FINANCE", "R-STAFF"]

    # 幂等绑定
    r = c.post(
        "/api/v1/admin/users/2/roles",
        data=json.dumps({"role_id": fid}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["roles"].count("R-FINANCE") == 1

    r = c.delete(f"/api/v1/admin/users/2/roles/{fid}", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"]["roles"] == ["R-STAFF"]


def test_assign_role_cross_tenant_404(seed_auth):
    c = _c()
    from apps.sysadmin.models import SysRole

    SysRole.objects.create(code="R-OTHER", name="别租户", tenant_id=2)
    rid = SysRole.objects.filter(code="R-OTHER").first().id
    r = c.post(
        "/api/v1/admin/users/2/roles",
        data=json.dumps({"role_id": rid}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 40402


# ---------------------------------------------------------------------------
# 数据字典
# ---------------------------------------------------------------------------
def test_dict_crud_flow(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/admin/dicts",
        data=json.dumps({"code": "project_type", "name": "项目类型", "remark": "R"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    did = r.json()["data"]["id"]

    # upsert 按 code 更新
    r = c.post(
        "/api/v1/admin/dicts",
        data=json.dumps({"code": "project_type", "name": "项目类型改"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["id"] == did
    assert r.json()["data"]["name"] == "项目类型改"

    # 条目 upsert
    r = c.post(
        f"/api/v1/admin/dicts/{did}/items",
        data=json.dumps({"item_code": "NSFC", "item_label": "国家自然科学基金",
                         "ext": {"icon": "自", "color": "#2C6E49"}, "sort_no": 1}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    item = r.json()["data"]
    assert item["ext"] == {"icon": "自", "color": "#2C6E49"}

    # 全员只读（R-STAFF 可拉下拉数据）
    r = c.get("/api/v1/dicts/project_type", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 1 and items[0]["item_code"] == "NSFC"

    # 详情含全部条目
    r = c.get(f"/api/v1/admin/dicts/{did}", **bearer(1, ["R-ADMIN"]))
    assert len(r.json()["data"]["items"]) == 1

    # 条目删除
    r = c.delete(
        f"/api/v1/admin/dicts/{did}/items/{item['id']}", **bearer(1, ["R-ADMIN"])
    )
    assert r.json()["data"] == {"id": item["id"], "deleted": True}

    # 字典软删
    r = c.delete(f"/api/v1/admin/dicts/{did}", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"] == {"id": did, "deleted": True}

    # 软删后同码可重建
    r = c.post(
        "/api/v1/admin/dicts",
        data=json.dumps({"code": "project_type", "name": "重建"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["id"] != did


def test_get_dict_by_code_404(seed_auth):
    c = _c()
    r = c.get("/api/v1/dicts/nope", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 404
    assert r.json()["code"] == 40401


def test_dict_effective_window(seed_auth):
    """/dicts/{code} 只返回 active 且生效期内的条目（PRD 2.8）。"""
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    from apps.sysadmin.models import SysDict, SysDictItem

    d = SysDict.objects.create(code="eff", name="生效期", tenant_id=1)
    today = dj_tz.localdate()
    SysDictItem.objects.create(dict=d, item_code="A", item_label="永久", tenant_id=1)
    SysDictItem.objects.create(dict=d, item_code="B", item_label="停用", active=False, tenant_id=1)
    SysDictItem.objects.create(
        dict=d, item_code="C", item_label="未来", effective_from=today + timedelta(days=1), tenant_id=1
    )
    SysDictItem.objects.create(
        dict=d, item_code="D", item_label="过期", effective_to=today - timedelta(days=1), tenant_id=1
    )
    c = _c()
    r = c.get("/api/v1/dicts/eff", **bearer(2, ["R-STAFF"]))
    codes = [i["item_code"] for i in r.json()["data"]["items"]]
    assert codes == ["A"]


# ---------------------------------------------------------------------------
# 页面可见性矩阵
# ---------------------------------------------------------------------------
def test_page_grants_list_and_replace(seed_auth, seed_pages):
    c = _c()
    r = c.get("/api/v1/page-grants", **bearer(2, ["R-STAFF"]))
    grants = r.json()["data"]["grants"]
    assert {"page_name": "dash", "role_code": "*"} in grants
    assert {"page_name": "bigscreen", "role_code": "R-LEADER"} in grants

    new_grants = [{"page_name": "only-page", "role_code": "*"},
                  {"page_name": "funding-config", "role_code": "R-MANAGER"}]
    r = c.put(
        "/api/v1/admin/page-grants",
        data=json.dumps({"grants": new_grants}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    got = r.json()["data"]["grants"]
    assert sorted(map(json.dumps, got)) == sorted(map(json.dumps, new_grants))


def test_page_grants_unknown_role_400(seed_auth):
    c = _c()
    r = c.put(
        "/api/v1/admin/page-grants",
        data=json.dumps({"grants": [{"page_name": "x", "role_code": "R-GHOST"}]}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 400
    assert r.json()["code"] == 40002
    assert "R-GHOST" in r.json()["message"]


# ---------------------------------------------------------------------------
# seed_demo 幂等播种
# ---------------------------------------------------------------------------
def test_seed_demo_idempotent(db):
    from django.core.management import call_command

    call_command("seed_demo")
    call_command("seed_demo")  # 二次执行零新增
    from apps.sysadmin.models import SysDict, SysDictItem, SysRole, SysUser

    assert SysRole.objects.count() == 8
    assert SysUser.objects.count() == 4
    assert SysDict.objects.count() == 5
    assert SysDictItem.objects.count() == 26
    # 演示账号可登录
    c = _c()
    r = c.post(
        "/api/v1/auth/login",
        data={"username": "manager", "password": "Manager@123456"},
        content_type="application/json",
    )
    assert r.status_code == 200
