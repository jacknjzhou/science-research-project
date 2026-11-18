"""M2-c：N 域租户与身份收口（专家/评审邀请/打分）。"""
from __future__ import annotations

import json

from django.test import Client

from tests.conftest import bearer


def _c() -> Client:
    return Client()


def _post(path, payload, uid, roles, tenant_id=1):
    return _c().post(path, data=json.dumps(payload), content_type="application/json",
                     **bearer(uid, roles, tenant_id))


def _post_tenant(path, payload, uid, roles, tenant_id):
    return _c().post(path, data=json.dumps(payload), content_type="application/json",
                     **bearer(uid, roles, tenant_id))


def _expert(tenant_id=1, uid=101, status="ACTIVE", name="专家A"):
    from apps.expertreview.models import NExpert

    return NExpert.objects.create(
        tenant_id=tenant_id, creator_id=1, status=status, name=name,
        user_id=uid, source="EXTERNAL", field_tags=["AI"],
    )


def _task(tenant_id=1, plan_count=1):
    from apps.expertreview.models import NReviewTask

    return NReviewTask.objects.create(
        tenant_id=tenant_id, creator_id=1, biz_type="OUTPUT_EVAL",
        target_type="R_OUTPUT", target_id=1, title="评审任务", plan_count=plan_count,
        status="INVITING",
    )


def _invite(task, expert, response="PENDING"):
    from apps.expertreview.models import NReviewInvitation

    return NReviewInvitation.objects.create(
        tenant_id=task.tenant_id, task_id=task.id, expert_id=expert.id,
        seat_no=1, response=response,
    )


def test_expert_and_task_lookups_are_tenant_scoped(seed_auth):
    """跨租户读专家与评审任务必须 404（原先只按 id，可跨租户读）。"""
    e = _expert(tenant_id=2, uid=901, name="异租户专家")
    t = _task(tenant_id=2)
    c = _c()
    r = c.get(f"/api/v1/experts/{e.id}", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 404, r.content
    r = c.get(f"/api/v1/reviews/{t.id}", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 404, r.content


def test_respond_uses_token_identity_not_body(seed_auth):
    """B 的令牌 + body.expert_id=A：拒绝且 A 的邀请保持 PENDING（Review Focus 3）。"""
    from apps.expertreview.models import NReviewInvitation

    a, b = _expert(uid=101, name="A"), _expert(uid=102, name="B")
    t = _task()
    inv_a = _invite(t, a)

    r = _post(f"/api/v1/reviews/{t.id}/accept", {"expert_id": a.id}, 102, ["R-EXPERT"])
    assert r.status_code == 400, r.content
    assert NReviewInvitation.objects.get(id=inv_a.id).response == "PENDING"


def test_respond_rejects_other_experts_invitation(seed_auth):
    """B 未被邀请却尝试拒绝：404（不泄露他人邀请）。"""
    a, b = _expert(uid=101, name="A"), _expert(uid=102, name="B")
    t = _task()
    _invite(t, a)
    r = _post(f"/api/v1/reviews/{t.id}/decline", {}, 102, ["R-EXPERT"])
    assert r.status_code == 404, r.content


def test_submit_score_ignores_foreign_expert_id(seed_auth):
    """打分同样以令牌身份为准，body 指向他人即拒绝。"""
    from apps.expertreview.models import NReviewScore

    a, b = _expert(uid=101, name="A"), _expert(uid=102, name="B")
    t = _task()
    _invite(t, a, response="ACCEPT")
    _invite(t, b, response="ACCEPT")

    r = _post(f"/api/v1/reviews/{t.id}/scores",
              {"expert_id": a.id, "total_score": "90.00"}, 102, ["R-EXPERT"])
    assert r.status_code == 400, r.content
    assert not NReviewScore.objects.filter(task_id=t.id, expert_id=a.id).exists()

    # 本人打分正常落库
    r = _post(f"/api/v1/reviews/{t.id}/scores",
              {"total_score": "88.00"}, 102, ["R-EXPERT"])
    assert r.status_code == 200, r.content
    assert NReviewScore.objects.filter(task_id=t.id, expert_id=b.id).exists()


# ---------------------------------------------------------------- Task 4

def _user(seed_auth, username="ext_expert", email="ext@example.com", org=None):
    from apps.sysadmin.models import SysUser

    return SysUser.objects.create(
        username=username, real_name=username, password_hash=seed_auth["admin"].password_hash,
        status="ACTIVE", tenant_id=1, creator_id=1, email=email,
        org_id=org.id if org else None,
        user_source="EXTERNAL" if org else "INTERNAL",
    )


def _org(name="协作机构", code="91310000MA1K3XY00A"):
    from apps.sysadmin.models import SysPartnerOrg

    return SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name=name, credit_code=code,
        org_type="UNIVERSITY", status="APPROVED")


def test_partner_user_can_apply_as_expert(seed_auth):
    """外部机构用户提交专家申请 → CANDIDATE 档案（C3 自助注册）。"""
    from apps.expertreview.models import NExpert

    org = _org()
    u = _user(seed_auth, org=org)
    r = _post("/api/v1/portal/expert-apply",
              {"name": "张三", "title": "教授", "field_tags": ["AI", "材料"]},
              u.id, ["R-PARTNER"])
    assert r.status_code == 200, r.content
    e = NExpert.objects.get(user_id=u.id, tenant_id=1)
    assert e.status == "CANDIDATE" and e.source == "EXTERNAL"
    assert e.field_tags == ["AI", "材料"] and e.code.startswith("NEX-")


def test_apply_twice_conflicts(seed_auth):
    org = _org()
    u = _user(seed_auth, org=org)
    _post("/api/v1/portal/expert-apply", {"name": "张三"}, u.id, ["R-PARTNER"])
    r = _post("/api/v1/portal/expert-apply", {"name": "张三"}, u.id, ["R-PARTNER"])
    assert r.status_code == 409, r.content
    assert r.json()["code"] == 40901


def test_manager_approves_expert_and_grants_role(seed_auth):
    """审核通过 → ACTIVE + 授 R-EXPERT + 站内信 + 邮件。"""
    from apps.expertreview.models import NExpert
    from apps.sysadmin.models import SysUserRole

    org = _org()
    u = _user(seed_auth, org=org)
    _post("/api/v1/portal/expert-apply", {"name": "李四"}, u.id, ["R-PARTNER"])
    e = NExpert.objects.get(user_id=u.id)

    manager = _user(seed_auth, username="mgr1", email="mgr1@example.com")
    SysUserRole.objects.create(user=manager, role=seed_auth["roles"]["R-MANAGER"], tenant_id=1)

    r = _post(f"/api/v1/expert-applications/{e.id}/audit", {"action": "APPROVE"},
              manager.id, ["R-MANAGER"])
    assert r.status_code == 200, r.content
    e.refresh_from_db()
    assert e.status == "ACTIVE"
    assert SysUserRole.objects.filter(user=u, role__code="R-EXPERT").exists()

    from apps.notify.models import SysNotification
    assert SysNotification.objects.filter(user_id=u.id).exists()
    from django.core import mail
    # 提交时给申请人发过一封「已提交」，审核通过再发一封「已通过」
    assert any("ext@example.com" in m.to for m in mail.outbox)
    assert any("通过" in m.subject for m in mail.outbox)


def test_reject_requires_reason(seed_auth):
    """驳回必须给理由；理由落库并在档案上留痕（置 SUSPENDED）。"""
    from apps.expertreview.models import NExpert
    from apps.sysadmin.models import SysUserRole

    org = _org()
    u = _user(seed_auth, org=org)
    _post("/api/v1/portal/expert-apply", {"name": "王五"}, u.id, ["R-PARTNER"])
    e = NExpert.objects.get(user_id=u.id)
    manager = _user(seed_auth, username="mgr2")
    SysUserRole.objects.create(user=manager, role=seed_auth["roles"]["R-MANAGER"], tenant_id=1)

    r = _post(f"/api/v1/expert-applications/{e.id}/audit", {"action": "REJECT"},
              manager.id, ["R-MANAGER"])
    assert r.status_code == 400, r.content

    r = _post(f"/api/v1/expert-applications/{e.id}/audit",
              {"action": "REJECT", "reason": "材料不全"}, manager.id, ["R-MANAGER"])
    assert r.status_code == 200, r.content
    e.refresh_from_db()
    assert e.status == "SUSPENDED" and "材料不全" in (e.remark or "")


def test_other_tenant_cannot_audit(seed_auth):
    from apps.expertreview.models import NExpert
    from apps.sysadmin.models import SysUserRole

    org = _org()
    u = _user(seed_auth, org=org)
    _post("/api/v1/portal/expert-apply", {"name": "赵六"}, u.id, ["R-PARTNER"])
    e = NExpert.objects.get(user_id=u.id)

    from apps.sysadmin.models import SysUser

    mgr2 = SysUser.objects.create(
        username="mgr_t2", real_name="异租户管理员", password_hash=seed_auth["admin"].password_hash,
        status="ACTIVE", tenant_id=2, creator_id=1, email="m2@example.com")
    from apps.sysadmin.models import SysRole

    role, _ = SysRole.objects.get_or_create(code="R-MANAGER", tenant_id=2,
                                            defaults={"name": "科研管理岗", "is_builtin": True})
    SysUserRole.objects.create(user=mgr2, role=role, tenant_id=2)

    r = _post_tenant(f"/api/v1/expert-applications/{e.id}/audit", {"action": "APPROVE"},
                     mgr2.id, ["R-MANAGER"], 2)
    assert r.status_code == 404, r.content


# ---------------------------------------------------------------- Task 5

def _credit_fixture(uid=101):
    """2 邀：1 接（2h 内响应）+ 1 拒；1 份打分 88.00。"""
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    from apps.expertreview.models import NReviewInvitation, NReviewScore

    e = _expert(uid=uid, name="信用专家")
    t1, t2 = _task(), _task()
    iv1 = _invite(t1, e, response="ACCEPT")
    NReviewInvitation.objects.filter(id=iv1.id).update(
        responded_at=dj_tz.now() - timedelta(hours=2))
    _invite(t2, e, response="DECLINE")
    NReviewScore.objects.create(tenant_id=1, task_id=t1.id, expert_id=e.id,
                                total_score="88.00", target_type="R_OUTPUT", target_id=1)
    return e, t1


def test_credit_computes_rates_from_invitations(seed_auth):
    e, _ = _credit_fixture()
    c = _c()
    r = c.get(f"/api/v1/experts/{e.id}/credit", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    d = r.json()["data"]
    assert d["invited_count"] == 2 and d["accepted_count"] == 1 and d["declined_count"] == 1
    assert d["accept_rate"] == "0.50"
    assert d["on_time_rate"] == "1.00"
    assert d["avg_score"] == "88.00" and d["abstain_count"] == 0


def test_portal_credit_only_self(seed_auth):
    """门户信用卡只给本人；他人 id 走门户即 404。"""
    e, _ = _credit_fixture(uid=101)
    other = _expert(uid=102, name="他人")
    c = _c()
    r = c.get("/api/v1/portal/expert/credit", **bearer(101, ["R-EXPERT"]))
    assert r.status_code == 200 and r.json()["data"]["expert_id"] == e.id
    r = c.get(f"/api/v1/portal/expert/credit?expert_id={other.id}", **bearer(101, ["R-EXPERT"]))
    assert r.status_code == 200 and r.json()["data"]["expert_id"] == e.id


def test_portal_reviews_lists_only_my_invitations(seed_auth):
    from apps.expertreview.models import NReviewInvitation

    e, t1 = _credit_fixture(uid=101)
    other = _expert(uid=102, name="他人")
    _invite(_task(), other)
    r = _c().get("/api/v1/portal/expert/reviews", **bearer(101, ["R-EXPERT"]))
    assert r.status_code == 200, r.content
    rows = r.json()["data"]["list"]
    assert len(rows) == 2
    mine = set(
        NReviewInvitation.objects.filter(tenant_id=1, expert_id=e.id)
        .values_list("task_id", flat=True)
    )
    assert {x["task_id"] for x in rows} == mine
    assert all(x["response"] in ("ACCEPT", "DECLINE", "PENDING") for x in rows)


def test_portal_activities_lists_invited_activities(seed_auth):
    from apps.activity.models import VActivity, VActivityParticipant

    e = _expert(uid=101)
    a = VActivity.objects.create(
        tenant_id=1, creator_id=1, title="学术沙龙", status="APPROVED",
        activity_type="SEMINAR", start_at="2026-12-01T09:00:00+08:00", venue="报告厅")
    VActivityParticipant.objects.create(
        tenant_id=1, activity_id=a.id, user_id=101, role="SPEAKER")
    r = _c().get("/api/v1/portal/expert/activities", **bearer(101, ["R-EXPERT"]))
    assert r.status_code == 200, r.content
    rows = r.json()["data"]["list"]
    assert len(rows) == 1 and rows[0]["title"] == "学术沙龙" and rows[0]["role"] == "SPEAKER"
