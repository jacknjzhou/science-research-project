"""M2-c / C5：统一站内信+邮件投递，以及四处业务接线。"""
import json

import pytest
from django.test import Client

from tests.conftest import bearer


def _user(seed, uid=201, email="ext-user@example.com"):
    from apps.sysadmin.models import SysUser

    return SysUser.objects.create(
        id=uid, username=f"u{uid}", real_name=f"用户{uid}", email=email,
        status="ACTIVE", tenant_id=1, creator_id=1, password_hash=seed["admin"].password_hash)


def test_notify_user_writes_inapp_and_sends_mail(seed_auth):
    from django.core import mail

    from apps.notify.email import notify_user
    from apps.notify.models import SysNotification

    u = _user(seed_auth)
    notify_user(1, u.id, "ANNOUNCE", "立项通知", "您的项目已立项", "task-book:1")

    row = SysNotification.objects.filter(user_id=u.id).latest("id")
    assert row.channel == "BOTH" and row.biz_ref == "task-book:1"
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["ext-user@example.com"]


def test_notify_user_without_email_still_inapp(seed_auth):
    from django.core import mail

    from apps.notify.email import notify_user
    from apps.notify.models import SysNotification

    u = _user(seed_auth, uid=202, email=None)
    notify_user(1, u.id, "MESSAGE", "无邮箱", "内容", "x:1")
    assert SysNotification.objects.filter(user_id=u.id).exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_guide_suggestion_reject_mails_proposer(seed_auth):
    """C5 接线①：指南建议驳回 → 建议人收到含理由邮件。"""
    from django.core import mail

    from apps.p.models import PGuideSuggestion

    u = _user(seed_auth, uid=203, email="proposer@example.com")
    s = PGuideSuggestion.objects.create(
        tenant_id=1, creator_id=u.id, org_id=None, proposer_user_id=u.id,
        title="关于开放课题的建议", background="b", status="PENDING")

    r = Client().post(f"/api/v1/apply/guide-suggestions/{s.id}:reject",
                      data=json.dumps({"reason": "重复建议"}),
                      content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    assert any("proposer@example.com" in m.to for m in mail.outbox)
    assert any("重复建议" in m.body for m in mail.outbox)


@pytest.mark.django_db
def test_award_bid_mails_winner_users(seed_auth):
    """C5 接线②：定标 → 中标供应商绑定用户收到邮件。"""
    from django.core import mail

    from apps.procure.models import GBid, GRequisition, GSupplier, GSupplier
    from apps.sysadmin.models import SysPartnerOrg

    org = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="中标供应商机构",
        credit_code="91310000MA1K3XY099", org_type="SUPPLIER", status="APPROVED")
    sup = GSupplier.objects.create(
        code="SUP-M2C-99", tenant_id=1, name="中标供应商", type="供应商",
        status="IN_LIBRARY", org_id=org.id, creator_id=1)
    u = _user(seed_auth, uid=204, email="winner@example.com")
    from apps.sysadmin.models import SysUser

    SysUser.objects.filter(id=u.id).update(org_id=org.id, user_source="EXTERNAL")
    req = GRequisition.objects.create(
        tenant_id=1, creator_id=1, project_id=1, applicant_id=1, category="设备",
        item_name="服务器", est_amount="100000.00")
    bid = GBid.objects.create(
        tenant_id=1, creator_id=1, requisition=req, method="询价",
        invited_supplier_ids=[sup.id])

    r = Client().post(f"/api/v1/procurement/bids/{bid.id}/award",
                      data=json.dumps({"winner_supplier_id": sup.id,
                                       "winner_reason": "价格最优"}),
                      content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    assert any("winner@example.com" in m.to for m in mail.outbox)


@pytest.mark.django_db
def test_sign_task_book_mails_pi(seed_auth):
    """C5 接线③：任务书双签立项 → PI 收到「任务书已签订」邮件。"""
    from django.core import mail

    from tests.test_p_m2b import _manager_user, _party

    org_a, _org_b, ua, _ub, make = _party(seed_auth)
    from apps.sysadmin.models import SysUser

    SysUser.objects.filter(id=ua.id).update(email="pi-ext@example.com")
    mgr = _manager_user(seed_auth)
    aid = make(ua, org_a).id
    c = Client()
    r = c.post("/api/v1/apply/task-books", data=json.dumps({"application_id": aid}),
               content_type="application/json", **bearer(mgr.id, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    tb_id = r.json()["data"]["id"]

    c.post(f"/api/v1/apply/task-books/{tb_id}:sign",
           data=json.dumps({"role": "PI"}), content_type="application/json",
           **bearer(ua.id, ["R-PARTNER"]))
    c.post(f"/api/v1/apply/task-books/{tb_id}:sign",
           data=json.dumps({"role": "MANAGER"}), content_type="application/json",
           **bearer(mgr.id, ["R-MANAGER"]))
    assert any("pi-ext@example.com" in m.to for m in mail.outbox)
    assert any("任务书已签订" in m.subject for m in mail.outbox)
