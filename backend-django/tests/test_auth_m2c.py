"""M2-c：外部角色允许集（R-PARTNER + R-EXPERT）与停用账号即时失效。"""
from __future__ import annotations

import json

from django.test import Client


def _post(path, payload, headers):
    c = Client()
    return c.post(path, data=json.dumps(payload), content_type="application/json", **headers)


def _login(username: str, password: str) -> dict:
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    return r.json()["data"]


def test_external_roles_subset_kept_internal_stripped():
    from core.org_scope import external_roles_of

    assert external_roles_of(["R-PARTNER", "R-STAFF", "R-EXPERT"]) == ["R-PARTNER", "R-EXPERT"]
    assert external_roles_of(["R-EXPERT"]) == ["R-EXPERT"]
    assert external_roles_of(["R-STAFF", "R-MANAGER"]) == []


def test_external_expert_keeps_review_role(seed_auth):
    """外部专家账号登录后必须保住 R-EXPERT，否则无法评审（Review Focus 1）。"""
    from apps.sysadmin.models import SysPartnerOrg, SysUser, SysUserRole

    org = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="协作机构X", credit_code="91310000MA1K3XY99X",
        org_type="COLLAB", status="APPROVED")
    u = SysUser.objects.create(
        username="ext_expert", real_name="外部专家", password_hash=seed_auth["admin"].password_hash,
        status="ACTIVE", tenant_id=1, creator_id=1, org_id=org.id, user_source="EXTERNAL",
        email="ext_expert@example.com",
    )
    for code in ("R-PARTNER", "R-EXPERT", "R-STAFF"):
        SysUserRole.objects.create(user=u, role=seed_auth["roles"][code], tenant_id=1)

    data = _login("ext_expert", "Admin@123456")
    from core.auth.jwt_util import parse_token

    roles = list(parse_token(data["access_token"])["roles"])
    assert roles == ["R-PARTNER", "R-EXPERT"], roles


def test_disabled_user_token_rejected_immediately(seed_auth):
    """停用账号的存量令牌必须立刻失效（Review Focus 2 / 遗留 I-3）。"""
    from apps.sysadmin.models import SysPartnerOrg, SysUser, SysUserRole

    org = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="协作机构Y", credit_code="91310000MA1K3XY88Y",
        org_type="COLLAB", status="APPROVED")
    u = SysUser.objects.create(
        username="ext_susp", real_name="待停用", password_hash=seed_auth["admin"].password_hash,
        status="ACTIVE", tenant_id=1, creator_id=1, org_id=org.id, user_source="EXTERNAL",
    )
    SysUserRole.objects.create(user=u, role=seed_auth["roles"]["R-PARTNER"], tenant_id=1)

    data = _login("ext_susp", "Admin@123456")
    tok = data["access_token"]
    headers = {"HTTP_AUTHORIZATION": f"Bearer {tok}"}

    c = Client()
    assert c.get("/api/v1/auth/me", **headers).status_code == 200

    u.status = "SUSPENDED"
    u.save(update_fields=["status"])

    r = c.get("/api/v1/auth/me", **headers)
    assert r.status_code == 403, r.content
    assert r.json()["code"] == 40302


def test_create_user_allows_partner_plus_expert(seed_auth):
    """外部账号允许 [R-PARTNER, R-EXPERT]；仅 R-EXPERT 时无需机构。"""
    from apps.sysadmin.models import SysPartnerOrg

    org = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="协作机构Z", credit_code="91310000MA1K3XY77Z",
        org_type="UNIVERSITY", status="APPROVED")
    base = {"username": "ext_both", "real_name": "双重身份", "password": "Abcdef@123"}
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_token_admin()}"}

    r = _post("/api/v1/admin/users", {**base, "roles": ["R-PARTNER", "R-EXPERT"], "org_id": org.id}, headers)
    assert r.status_code == 200, r.content
    assert sorted(r.json()["data"]["roles"]) == ["R-EXPERT", "R-PARTNER"]

    r = _post("/api/v1/admin/users", {**base, "username": "ext_only_exp", "roles": ["R-EXPERT"]}, headers)
    assert r.status_code == 200, r.content

    # 外部角色 + 内部角色仍须拒绝
    r = _post("/api/v1/admin/users", {**base, "username": "ext_bad", "roles": ["R-EXPERT", "R-STAFF"]}, headers)
    assert r.status_code == 400, r.content


def _token_admin() -> str:
    from core.auth.jwt_util import gen_token

    return gen_token(1, 1, 0, "TOP_SECRET", ["R-ADMIN"])
