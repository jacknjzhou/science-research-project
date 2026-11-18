"""M2-a 外部机构注册与门户（C1）测试。

覆盖：机构模型与用户归属列（Task 1）、注册/审核/门户（Task 3-6）。
"""
from __future__ import annotations

import pytest

from apps.sysadmin.models import SysPartnerOrg, SysUser

pytestmark = pytest.mark.django_db


def _org(**kw):
    base = dict(
        code="PTN-2026-000001",
        tenant_id=1,
        name="示例大学",
        credit_code="91310000MA1K3XY12A",
        org_type="UNIVERSITY",
        contact_name="张三",
        contact_phone="13800000000",
        contact_email="z@example.edu.cn",
        creator_id=1,
    )
    base.update(kw)
    return SysPartnerOrg.objects.create(**base)


def test_partner_org_defaults():
    o = _org()
    assert o.status == "PENDING"  # 注册即待审
    assert o.qualification_json == []
    assert o.deleted == 0
    assert o.audit_user_id is None


def test_user_carries_org_and_source():
    o = _org()
    u = SysUser.objects.create(
        username="p1",
        real_name="外部用户",
        status="LOCKED",
        tenant_id=1,
        creator_id=1,
        org_id=o.id,
        user_source="EXTERNAL",
    )
    assert u.org_id == o.id
    assert u.user_source == "EXTERNAL"
    internal = SysUser.objects.create(
        username="i1", real_name="内部用户", tenant_id=1, creator_id=1
    )
    assert internal.user_source == "INTERNAL"


# ===========================================================================
# Task 3：自助注册（公开端点）
# ===========================================================================

import json

from django.test import Client

from tests.conftest import bearer

REGISTER_URL = "/api/v1/portal/register"


def _register_body(**kw):
    body = {
        "org_name": "示例大学",
        "credit_code": "91310000MA1K3XY12A",
        "org_type": "UNIVERSITY",
        "contact_name": "张三",
        "contact_phone": "13800000000",
        "contact_email": "z@example.edu.cn",
        "username": "p_example",
        "password": "Partner@2026",
        "real_name": "张三",
    }
    body.update(kw)
    return body


def _post(url, body, roles=None, uid=1):
    kw = {} if roles is None else bearer(uid, list(roles))
    return Client().post(
        url, data=json.dumps(body), content_type="application/json", **kw
    )


def _data(resp):
    return json.loads(resp.content)["data"]


def test_register_creates_pending_org_and_locked_user():
    resp = _post(REGISTER_URL, _register_body())
    assert resp.status_code == 200, resp.content
    data = _data(resp)
    assert data["status"] == "PENDING" and data["code"].startswith("PTN-")
    org = SysPartnerOrg.objects.get(id=data["id"])
    u = SysUser.objects.get(username="p_example")
    assert u.status == "LOCKED" and u.org_id == org.id and u.user_source == "EXTERNAL"
    assert u.password_hash and u.password_hash.startswith("$2")


def test_register_rejects_duplicate_credit_code_and_username():
    assert _post(REGISTER_URL, _register_body()).status_code == 200
    dup_credit = _post(REGISTER_URL, _register_body(username="other_user"))
    assert dup_credit.status_code == 409
    assert json.loads(dup_credit.content)["code"] == 40901
    dup_user = _post(REGISTER_URL, _register_body(credit_code="91110000MA2C4AB34B"))
    assert dup_user.status_code == 409
    assert json.loads(dup_user.content)["code"] == 40901


def test_register_rejects_weak_password_and_bad_input():
    base = _register_body()
    for bad in (
        {**base, "password": "12345678"},  # 纯数字
        {**base, "password": "Ab1!"},  # 太短
        {**base, "contact_email": ""},  # 必填缺失
        {**base, "credit_code": "abc"},  # 信用代码长度错
        {**base, "org_type": "NOT_A_TYPE"},  # 枚举外
    ):
        r = _post(REGISTER_URL, bad)
        assert r.status_code == 400, bad
        assert json.loads(r.content)["code"] == 40001


def test_locked_user_cannot_login_until_approved():
    _post(REGISTER_URL, _register_body())
    r = _post(
        "/api/v1/auth/login", {"username": "p_example", "password": "Partner@2026"}
    )
    assert r.status_code == 403
    assert json.loads(r.content)["code"] == 40302  # CODE_ACCOUNT_DISABLED


# ===========================================================================
# Task 5：机构审核（R-MANAGER）
# ===========================================================================

AUDIT_URL = "/api/v1/partner-orgs/{id}/audit"


def _register_then_approve(action="APPROVE", reason=None, **kw):
    oid = _data(_post(REGISTER_URL, _register_body(**kw)))["id"]
    body = {"action": action} if reason is None else {"action": action, "reason": reason}
    return oid, _post(AUDIT_URL.format(id=oid), body, roles=("R-MANAGER",))


def test_approve_activates_user_grants_role_and_notifies(seed_auth):
    oid, resp = _register_then_approve()
    assert resp.status_code == 200, resp.content
    data = _data(resp)
    assert data["status"] == "APPROVED" and data["audit_user_id"]
    u = SysUser.objects.get(username="p_example")
    assert u.status == "ACTIVE"
    from apps.sysadmin.models import SysUserRole

    assert SysUserRole.objects.filter(user_id=u.id, role__code="R-PARTNER").count() == 1
    from apps.notify.models import SysNotification

    assert SysNotification.objects.filter(user_id=u.id, typ="ANNOUNCE").exists()


def test_approve_twice_is_idempotent(seed_auth):
    oid, _ = _register_then_approve()
    resp = _post(AUDIT_URL.format(id=oid), {"action": "APPROVE"}, roles=("R-MANAGER",))
    assert resp.status_code == 200
    u = SysUser.objects.get(username="p_example")
    from apps.sysadmin.models import SysUserRole

    assert SysUserRole.objects.filter(user_id=u.id, role__code="R-PARTNER").count() == 1


def test_reject_requires_reason_and_keeps_user_locked(seed_auth):
    oid, bad = _register_then_approve(action="REJECT")
    assert bad.status_code == 400 and json.loads(bad.content)["code"] == 40001
    _, ok_resp = _register_then_approve(
        action="REJECT", reason="资质不全", username="p_two",
        credit_code="91310000MA1K3XY12B",
    )
    assert _data(ok_resp)["status"] == "REJECTED"
    assert SysUser.objects.get(username="p_two").status == "LOCKED"


def test_audit_unknown_org_is_404(seed_auth):
    r = _post(AUDIT_URL.format(id=99999), {"action": "APPROVE"}, roles=("R-MANAGER",))
    assert r.status_code == 404
