"""登录与鉴权语义测试（移植 Go login_test / middleware.Auth 语义）。"""
import pytest
from django.test import Client

from tests.conftest import bearer


@pytest.mark.django_db
def test_login_dev_fallback():
    """ark/ark dev 回退：签发固定数据域。"""
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        data={"username": "ark", "password": "ark"},
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["token_type"] == "Bearer"
    assert data["access_token"]
    assert data["expires_in"] > 0


@pytest.mark.django_db
def test_login_dev_fallback_wrong():
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        data={"username": "ark", "password": "wrong"},
        content_type="application/json",
    )
    assert r.status_code == 401
    assert r.json()["code"] == 40102
    assert r.json()["message"] == "账号或密码错误"


def test_login_missing_fields():
    c = Client()
    r = c.post("/api/v1/auth/login", data={}, content_type="application/json")
    assert r.status_code == 400
    assert r.json()["code"] == 40001
    assert r.json()["message"] == "用户名/密码必填"


def test_login_db_user_ok(seed_auth):
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "Admin@123456"},
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["access_token"]


def test_login_db_user_wrong_password(seed_auth):
    """统一失败码，避免用户名枚举。"""
    c = Client()
    for username in ("admin", "nonexistent"):
        r = c.post(
            "/api/v1/auth/login",
            data={"username": username, "password": "nope"},
            content_type="application/json",
        )
        assert r.status_code == 401
        assert r.json()["code"] == 40102


def test_login_disabled_user(seed_auth):
    from apps.sysadmin.models import SysUser

    SysUser.objects.filter(username="admin").update(status="LOCKED")
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "Admin@123456"},
        content_type="application/json",
    )
    assert r.status_code == 403
    assert r.json()["code"] == 40302
    assert r.json()["message"] == "账号已停用或锁定"


@pytest.mark.django_db
def test_auth_me_caps_and_roles(seed_auth):
    """/auth/me：DB 角色 + Casbin 派生 caps；R-ADMIN 通配 → /api/v1/* GET/POST/PUT/DELETE。"""
    c = Client()
    r = c.get("/api/v1/auth/me", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["roles"] == ["R-ADMIN"]
    assert data["user"]["username"] == "admin"
    caps = data["caps"]
    assert "/api/v1/* GET" in caps
    assert "/api/v1/* POST" in caps
    assert caps == sorted(caps)


@pytest.mark.django_db
def test_auth_casbin_denies_unknown_role(seed_auth):
    """/admin/users 仅 R-ADMIN（通配）；R-STAFF → 40301。"""
    c = Client()
    r = c.get("/api/v1/admin/users", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 403
    assert r.json()["code"] == 40301
    assert r.json()["message"] == "无权限"


@pytest.mark.django_db
def test_auth_r_staff_can_read_me(seed_auth):
    c = Client()
    r = c.get("/api/v1/auth/me", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    assert r.json()["data"]["roles"] == ["R-STAFF"]


@pytest.mark.django_db
def test_auth_invalid_token():
    c = Client()
    r = c.get("/api/v1/auth/me", **{"HTTP_AUTHORIZATION": "Bearer garbage"})
    assert r.status_code == 401
    assert r.json()["code"] == 40102
    assert r.json()["message"] == "令牌无效或过期"
