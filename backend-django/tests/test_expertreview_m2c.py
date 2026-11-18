"""M2-c：N 域租户与身份收口（专家/评审邀请/打分）。"""
from __future__ import annotations

import json

from django.test import Client

from tests.conftest import bearer


def _c() -> Client:
    return Client()


def _post(path, payload, uid, roles):
    return _c().post(path, data=json.dumps(payload), content_type="application/json",
                     **bearer(uid, roles))


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
