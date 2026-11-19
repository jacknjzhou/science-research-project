"""M2-c 终审（REQUEST_CHANGES）回归：C-1 外部链路邮件 + I-1 门户准入 + I-2/I-3/I-4/I-5。

每个用例都对应一条评审发现，尽量走真实 HTTP 端点，避免"只断 200 不断语义"。
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone as dj_tz

from tests.conftest import bearer

pytestmark = pytest.mark.django_db


def _post(c, url, body, **kw):
    return c.post(url, data=json.dumps(body), content_type="application/json", **kw)


# --------------------------------------------------------------------------
# C-1：四条外部主链路必须真的发出邮件（评审实测 mail.outbox == 0）
# --------------------------------------------------------------------------


def test_c1_review_invite_sends_email_to_external_expert(seed_auth):
    """邀请评审 → 外部专家收到邮件（C3 验收：外部专家线上完成一次评审）。"""
    from apps.expertreview.models import NExpert, NReviewInvitation, NReviewTask

    tenant = 1
    seed_auth["staff"].email = "expert1@example.com"
    seed_auth["staff"].save(update_fields=["email"])
    expert = NExpert.objects.create(
        tenant_id=tenant, code="NEX-T-1", name="外部专家甲", source="EXTERNAL",
        status="ACTIVE", user_id=seed_auth["staff"].id, creator_id=1,
    )
    task = NReviewTask.objects.create(
        tenant_id=tenant, biz_type="PROJECT_APPLY", target_id=1,
        title="测试评审任务", status="DRAWN", plan_count=1, creator_id=1,
    )
    NReviewInvitation.objects.create(
        tenant_id=tenant, task_id=task.id, expert_id=expert.id, seat_no=1,
        response="PENDING",
    )
    mail.outbox.clear()
    c = Client()
    r = _post(c, f"/api/v1/reviews/{task.id}/invite", {}, **bearer(2, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    assert len(mail.outbox) == 1, "邀请评审必须给专家发邮件"
    assert "邀请" in mail.outbox[0].subject


def test_c1_bid_invite_sends_email_to_supplier_contact(seed_auth):
    """发标 → 受邀供应商的对接人收到邮件（C4 验收：供应商收到询价单）。"""
    from apps.procure.models import GBid, GRequisition, GSupplier
    from apps.sysadmin.models import SysPartnerOrg

    tenant = 1
    org = SysPartnerOrg.objects.create(
        tenant_id=tenant, code="PTN-T-1", name="测试供应商机构",
        credit_code="91310000MA1K3XY77Z", org_type="SUPPLIER",
        contact_name="对接人", contact_phone="13800000009",
        contact_email="sup@example.com", status="APPROVED", creator_id=1,
    )
    sup_user = seed_auth["staff"]
    sup_user.org_id = org.id
    sup_user.email = "sup@example.com"
    sup_user.user_source = "EXTERNAL"
    sup_user.save(update_fields=["org_id", "email", "user_source"])
    sup = GSupplier.objects.create(
        tenant_id=tenant, code="SUP-T-1", name="测试供应商", status="IN_LIBRARY",
        org_id=org.id, creator_id=1,
    )
    req = GRequisition.objects.create(
        tenant_id=tenant, code="REQ-T-1", project_id=1, applicant_id=1, category="设备",
        item_name="测试设备", est_amount=1000, purchase_way="询价",
        status="WAY_DECIDED", creator_id=1,
    )
    mail.outbox.clear()
    c = Client()
    r = _post(
        c, "/api/v1/procurement/bids",
        {"requisition_id": req.id, "method": "询价", "invited_supplier_ids": [sup.id]},
        **bearer(2, ["R-MANAGER"]),
    )
    assert r.status_code == 200, r.content
    assert GBid.objects.filter(requisition_id=req.id).exists()
    assert len(mail.outbox) >= 1, "发标必须通知受邀供应商"
    assert any("询价" in m.subject for m in mail.outbox)


def test_c1_quote_receipt_notifies_purchaser(seed_auth):
    """供应商应价 → 采购发起人收到回执（否则报价无人知）。"""
    from apps.procure.models import GBid, GRequisition, GSupplier
    from apps.sysadmin.models import SysPartnerOrg

    tenant = 1
    org = SysPartnerOrg.objects.create(
        tenant_id=tenant, code="PTN-T-2", name="测试机构二",
        credit_code="91310000MA1K3XY78Z", org_type="SUPPLIER",
        contact_name="对接", contact_phone="13800000008",
        contact_email="sup2@example.com", status="APPROVED", creator_id=1,
    )
    buyer = seed_auth["staff"]
    buyer.email = "buyer@example.com"
    buyer.save(update_fields=["email"])
    sup_user = None
    if sup_user is None:
        from apps.sysadmin.models import SysUser

        sup_user = SysUser.objects.create(
            tenant_id=tenant, username="sup2", real_name="供应商乙",
            email="sup2@example.com", status="ACTIVE", user_source="EXTERNAL",
            org_id=org.id, creator_id=1,
        )
    else:
        sup_user.org_id = org.id
        sup_user.user_source = "EXTERNAL"
        sup_user.save(update_fields=["org_id", "user_source"])
    sup = GSupplier.objects.create(
        tenant_id=tenant, code="SUP-T-2", name="测试供应商二", status="IN_LIBRARY",
        org_id=org.id, creator_id=1,
    )
    req = GRequisition.objects.create(
        tenant_id=tenant, code="REQ-T-2", project_id=1, applicant_id=buyer.id, category="服务",
        item_name="测试服务", est_amount=500, purchase_way="询价",
        status="BIDDING", creator_id=1,
    )
    bid = GBid.objects.create(
        tenant_id=tenant, code="BID-T-2", requisition=req, method="询价",
        status="PUBLICIZING", invited_supplier_ids=[sup.id],
        creator_id=buyer.id,
    )
    mail.outbox.clear()
    c = Client()
    r = _post(
        c, f"/api/v1/portal/supplier/inquiries/{bid.id}:quote",
        {"totalAmount": "480.00"},
        **bearer(sup_user.id, ["R-PARTNER"]),
    )
    assert r.status_code == 200, r.content
    assert len(mail.outbox) >= 1, "应价必须给采购发起人发回执"
    assert any("报价" in m.subject for m in mail.outbox)


def test_c1_decide_application_notifies_pi_by_email(seed_auth):
    """评审决议 → PI 收到邮件（外部申报人只看站内信等于没通知）。"""
    from apps.p.models import PApplication

    seed_auth["staff"].email = "pi1@example.com"
    seed_auth["staff"].save(update_fields=["email"])
    app_row = PApplication.objects.create(
        tenant_id=1, code="APP-T-1", title="测试申报", project_type="开放课题",
        pi_user_id=seed_auth["staff"].id, status="UNDER_REVIEW",
        total_budget=1000, creator_id=1,
    )
    mail.outbox.clear()
    c = Client()
    r = _post(
        c, f"/api/v1/apply/applications/{app_row.id}:decide",
        {"decision": "PUBLISHED"}, **bearer(2, ["R-MANAGER"]),
    )
    assert r.status_code == 200, r.content
    assert len(mail.outbox) >= 1, "决议必须通知 PI（邮件）"


# --------------------------------------------------------------------------
# I-1：门户准入（黑名单/资质过期/机构未批/未入库）
# --------------------------------------------------------------------------


def _supplier_ctx(seed_auth, *, status="IN_LIBRARY", blacklist=False, expired=False,
                  org_status="APPROVED", suffix="X"):
    from apps.procure.models import GBid, GRequisition, GSupplier
    from apps.sysadmin.models import SysPartnerOrg, SysUser

    tenant = 1
    org = SysPartnerOrg.objects.create(
        tenant_id=tenant, code=f"PTN-{suffix}", name=f"机构{suffix}",
        credit_code=f"91310000MA1K3XY{ord(suffix[-1]) % 10}{suffix[-1]}Z"[:18],
        org_type="SUPPLIER", contact_name="c", contact_phone="1",
        contact_email=f"{suffix}@example.com", status=org_status, creator_id=1,
    )
    u = SysUser.objects.create(
        tenant_id=tenant, username=f"u_{suffix}", real_name="u", email=f"{suffix}@example.com",
        status="ACTIVE", user_source="EXTERNAL", org_id=org.id, creator_id=1,
    )
    sup = GSupplier.objects.create(
        tenant_id=tenant, code=f"SUP-{suffix}", name=f"供应商{suffix}", status=status,
        blacklist=blacklist,
        qualification_expire_date=(dj_tz.localdate() - timedelta(days=1)) if expired else None,
        org_id=org.id, creator_id=1,
    )
    req = GRequisition.objects.create(
        tenant_id=tenant, code=f"REQ-{suffix}", project_id=1, applicant_id=1, category="设备",
        item_name="品目", est_amount=100, purchase_way="询价", status="BIDDING", creator_id=1,
    )
    bid = GBid.objects.create(
        tenant_id=tenant, code=f"BID-{suffix}", requisition=req, method="询价",
        status="PUBLICIZING", invited_supplier_ids=[sup.id], creator_id=2,
    )
    return u, sup, bid


@pytest.mark.parametrize(
    "kwargs",
    [
        {"blacklist": True},
        {"expired": True},
        {"status": "PENDING"},
        {"org_status": "PENDING"},
    ],
)
def test_i1_portal_admission_rejects_unusable_supplier(seed_auth, kwargs):
    """黑名单/过期/未入库/机构未批 → 门户看不到询价，也应不了价。"""
    u, sup, bid = _supplier_ctx(seed_auth, suffix=str(abs(hash(str(kwargs))) % 97), **kwargs)
    c = Client()
    hdr = bearer(u.id, ["R-PARTNER"])
    r = c.get("/api/v1/portal/supplier/inquiries", **hdr)
    assert r.status_code == 200
    assert r.json()["data"]["list"] == [], f"{kwargs} 不应看到询价"
    r = _post(c, f"/api/v1/portal/supplier/inquiries/{bid.id}:quote",
              {"totalAmount": "1.00"}, **hdr)
    assert r.status_code == 403, r.content


def test_i1_usable_supplier_still_passes(seed_auth):
    """对照：合规供应商仍能看到并应价（防"一刀切"修坏主链路）。"""
    u, sup, bid = _supplier_ctx(seed_auth, suffix="OK")
    c = Client()
    hdr = bearer(u.id, ["R-PARTNER"])
    r = c.get("/api/v1/portal/supplier/inquiries", **hdr)
    assert [x["id"] for x in r.json()["data"]["list"]] == [bid.id]
    r = _post(c, f"/api/v1/portal/supplier/inquiries/{bid.id}:quote",
              {"totalAmount": "88.00"}, **hdr)
    assert r.status_code == 200, r.content


# --------------------------------------------------------------------------
# I-2：院内专家的 R-EXPERT 不得被"外部角色独占"降权
# --------------------------------------------------------------------------


def test_i2_internal_expert_keeps_internal_roles_after_login(seed_auth):
    from apps.expertreview.models import NExpert
    from apps.sysadmin.models import SysRole, SysUserRole

    u = seed_auth["staff"]
    role = SysRole.objects.filter(tenant_id=1, code="R-EXPERT").first()
    SysUserRole.objects.get_or_create(user=u, role=role, tenant_id=1)
    NExpert.objects.create(tenant_id=1, code="NEX-I2", name="院内专家", source="INTERNAL",
                           status="ACTIVE", user_id=u.id, creator_id=1)

    c = Client()
    r = _post(c, "/api/v1/auth/login",
              {"username": "staff", "password": "Admin@123456"})
    assert r.status_code == 200, r.content
    tok = r.json()["data"]["access_token"]
    me = c.get("/api/v1/auth/me", HTTP_AUTHORIZATION="Bearer " + tok)
    roles = me.json()["data"]["roles"]
    assert "R-EXPERT" in roles and "R-STAFF" in roles, f"院内专家被降权：{roles}"
    # 仍能进内部域（未被裁成纯外部）
    assert c.get("/api/v1/project/mine", HTTP_AUTHORIZATION="Bearer " + tok).status_code == 200


def test_i2_external_account_still_stripped(seed_auth):
    """对照：外部账号即使令牌里带内部角色，也必须被剥到只剩外部允许集。"""
    from apps.sysadmin.models import SysUser

    u = SysUser.objects.create(
        tenant_id=1, username="ext_mix", real_name="ext", status="ACTIVE",
        user_source="EXTERNAL", org_id=None, creator_id=1,
    )
    c = Client()
    r = c.get("/api/v1/project/mine", **bearer(u.id, ["R-PARTNER", "R-STAFF"]))
    assert r.status_code == 403, r.content


# --------------------------------------------------------------------------
# I-3：专家档案的 review_count / last_review_at 会被回填
# --------------------------------------------------------------------------


def test_i3_expert_stats_refreshed_after_scoring(seed_auth):
    from apps.expertreview.models import NExpert, NReviewInvitation, NReviewTask, NReviewScore

    u = seed_auth["staff"]
    ex = NExpert.objects.create(tenant_id=1, code="NEX-I3", name="统计专家",
                                source="EXTERNAL", status="ACTIVE", user_id=u.id,
                                creator_id=1)
    task = NReviewTask.objects.create(tenant_id=1, biz_type="PROJECT_APPLY", target_id=9,
                                      title="统计任务", status="IN_REVIEW", plan_count=1,
                                      creator_id=1)
    NReviewInvitation.objects.create(tenant_id=1, task_id=task.id, expert_id=ex.id,
                                     seat_no=1, response="ACCEPT")
    c = Client()
    r = _post(c, f"/api/v1/reviews/{task.id}/scores",
              {"total_score": "88.00"}, **bearer(u.id, ["R-EXPERT"]))
    assert r.status_code == 200, r.content
    ex.refresh_from_db()
    assert ex.review_count == 1 and ex.last_review_at is not None
    assert NReviewScore.objects.filter(expert_id=ex.id).count() == 1


# --------------------------------------------------------------------------
# I-4：被驳回后可重新申请（原先任何状态都 409，等于永久封死）
# --------------------------------------------------------------------------


def test_i4_rejected_expert_can_reapply(seed_auth):
    from apps.expertreview.models import NExpert

    u = seed_auth["staff"]
    row = NExpert.objects.create(tenant_id=1, code="NEX-I4", name="旧申请",
                                 source="EXTERNAL", status="SUSPENDED", user_id=u.id,
                                 creator_id=1, remark="材料不全")
    c = Client()
    r = _post(c, "/api/v1/portal/expert-apply",
              {"name": "重新申请", "email": "x@example.com", "field_tags": ["材料科学"]},
              **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 200, r.content
    row.refresh_from_db()
    assert row.status == "CANDIDATE" and row.name == "重新申请"
    assert NExpert.objects.filter(tenant_id=1, user_id=u.id).count() == 1, "不得堆出多条档案"


def test_i4_pending_application_still_conflicts(seed_auth):
    from apps.expertreview.models import NExpert

    u = seed_auth["staff"]
    NExpert.objects.create(tenant_id=1, code="NEX-I4B", name="待审", source="EXTERNAL",
                           status="CANDIDATE", user_id=u.id, creator_id=1)
    c = Client()
    r = _post(c, "/api/v1/portal/expert-apply", {"name": "重复"},
              **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 409


# --------------------------------------------------------------------------
# I-5：审核授角色不得跨租户
# --------------------------------------------------------------------------


def test_i5_audit_rejects_cross_tenant_user_binding(seed_auth):
    from apps.expertreview.models import NExpert
    from apps.sysadmin.models import SysUser

    other = SysUser.objects.create(
        tenant_id=2, username="other_tenant", real_name="他租户", status="ACTIVE",
        creator_id=1,
    )
    row = NExpert.objects.create(tenant_id=1, code="NEX-I5", name="跨租户档案",
                                 source="EXTERNAL", status="CANDIDATE",
                                 user_id=other.id, creator_id=1)
    c = Client()
    r = _post(c, f"/api/v1/expert-applications/{row.id}/audit",
              {"action": "APPROVE"}, **bearer(2, ["R-MANAGER"]))
    assert r.status_code == 400, r.content
    row.refresh_from_db()
    assert row.status == "CANDIDATE", "跨租户授角色必须整体回滚"


# --------------------------------------------------------------------------
# M-1：历史 bids_json 缺 totalAmount 不得 500
# --------------------------------------------------------------------------


def test_m1_inquiry_list_tolerates_legacy_bid_entries(seed_auth):
    from apps.procure.models import GSupplier

    u, sup, bid = _supplier_ctx(seed_auth, suffix="LEG")
    bid.bids_json = [{"supplierId": sup.id, "supplierName": sup.name}]  # 缺 totalAmount
    bid.save(update_fields=["bids_json"])
    c = Client()
    r = c.get("/api/v1/portal/supplier/inquiries", **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 200, r.content
    assert r.json()["data"]["list"][0]["quoted"] is True
    assert r.json()["data"]["list"][0]["my_amount"] is None
