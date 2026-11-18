"""M2-b 开放课题全流程（机构化申报 / 指南建议 / 任务书）模型层。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_m2b_models_exist_with_ddl_columns():
    from apps.p.models import PApplication, PGuideSuggestion, PTaskBook
    from apps.project.models import EProject

    s = PGuideSuggestion.objects.create(
        tenant_id=1, creator_id=1, title="建议一", status="PENDING"
    )
    assert s.deleted == 0 and s.status == "PENDING"

    t = PTaskBook.objects.create(
        tenant_id=1, creator_id=1, application_id=1, status="DRAFT"
    )
    assert t.content_snapshot == {} and t.sign_records == []

    a = PApplication.objects.create(
        tenant_id=1, creator_id=1, title="T", project_type="ZIGE", pi_user_id=1
    )
    assert a.applicant_type == "INTERNAL" and a.applicant_org_id is None

    assert "ext_org_id" in [f.name for f in EProject._meta.get_fields()]


# ===========================================================================
# Task 2：机构/租户隔离
# ===========================================================================
import json

from django.test import Client

from tests.conftest import bearer


def _data(resp):
    return json.loads(resp.content)["data"]


def _get(url, roles=("R-STAFF",), uid=2):
    return Client().get(url, **bearer(uid, list(roles)))


def _put(url, body, roles=("R-STAFF",), uid=2):
    return Client().put(
        url, data=json.dumps(body), content_type="application/json",
        **bearer(uid, list(roles))
    )


def _post(url, body, roles=("R-STAFF",), uid=2):
    return Client().post(
        url, data=json.dumps(body), content_type="application/json",
        **bearer(uid, list(roles))
    )


def _partner_users(seed):
    """机构 A / 机构 B 各建一个 R-PARTNER 外部账号。"""
    from apps.sysadmin.models import SysPartnerOrg, SysUser, SysUserRole

    org_a = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="机构A", credit_code="91310000MA1K3XY11A",
        org_type="COLLAB", status="APPROVED")
    org_b = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="机构B", credit_code="91310000MA1K3XY11B",
        org_type="COLLAB", status="APPROVED")
    role = seed["roles"]["R-PARTNER"]
    ua = SysUser.objects.create(
        username="pa", real_name="A", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1, org_id=org_a.id, user_source="EXTERNAL")
    ub = SysUser.objects.create(
        username="pb", real_name="B", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1, org_id=org_b.id, user_source="EXTERNAL")
    SysUserRole.objects.create(user=ua, role=role, tenant_id=1)
    SysUserRole.objects.create(user=ub, role=role, tenant_id=1)
    return org_a, org_b, ua, ub


def test_application_and_project_are_org_scoped(seed_auth):
    from apps.p.models import PApplication
    from apps.project.models import EProject

    # tenant-2 的申报单，用 tenant-1 身份读必须 404
    other = PApplication.objects.create(
        tenant_id=2, creator_id=1, title="别家", project_type="ZIGE", pi_user_id=1)
    assert _get(f"/api/v1/apply/applications/{other.id}").status_code == 404

    org_a, org_b, ua, ub = _partner_users(seed_auth)
    mine = PApplication.objects.create(
        tenant_id=1, creator_id=ua.id, title="本机构", project_type="ZIGE",
        pi_user_id=ua.id, applicant_org_id=org_a.id, applicant_type="EXTERNAL")
    # 机构 B 读机构 A 的申报 → 404；机构 A 自己读 → 200
    assert _get(f"/api/v1/apply/applications/{mine.id}",
                roles=("R-PARTNER",), uid=ub.id).status_code == 404
    assert _get(f"/api/v1/apply/applications/{mine.id}",
                roles=("R-PARTNER",), uid=ua.id).status_code == 200

    proj = EProject.objects.create(
        tenant_id=1, creator_id=1, application_id=1, title="A 课题",
        pi_user_id=ua.id, ext_org_id=org_a.id)
    assert _post(f"/api/v1/project/{proj.id}/progress-report", {},
                 roles=("R-PARTNER",), uid=ub.id).status_code == 404
    assert _post(f"/api/v1/project/{proj.id}/progress-report", {},
                 roles=("R-PARTNER",), uid=ua.id).status_code != 404


# ===========================================================================
# Task 3：指南建议（外部提交 → 管理端采纳成指南草稿）
# ===========================================================================


def test_guide_suggestion_flow(seed_auth):
    from apps.p.models import PGuideline

    org_a, org_b, ua, ub = _partner_users(seed_auth)
    # 外部机构 A 提交（body 里传别家 org_id 应被忽略）
    r = _post("/api/v1/apply/guide-suggestions",
              {"title": "智能育种方向建议", "background": "面向 2030",
               "org_id": 999},
              roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 200, r.content
    sid = _data(r)["id"]
    assert _data(r)["org_id"] == org_a.id

    # 机构 B 看不到、也读不到
    lb = _data(_get("/api/v1/apply/guide-suggestions", roles=("R-PARTNER",), uid=ub.id))
    assert lb["total"] == 0
    assert _get(f"/api/v1/apply/guide-suggestions/{sid}",
                roles=("R-PARTNER",), uid=ub.id).status_code == 404

    # 管理端采纳 → 生成 DRAFT 指南
    acc = _post(f"/api/v1/apply/guide-suggestions/{sid}:accept", {}, roles=("R-MANAGER",))
    assert acc.status_code == 200, acc.content
    assert _data(acc)["status"] == "ACCEPTED"
    gid = _data(acc)["guideline_id"]
    g = PGuideline.objects.get(id=gid)
    assert g.status == "DRAFT" and g.publish_at is None
    # 再采纳一次 40901
    again = _post(f"/api/v1/apply/guide-suggestions/{sid}:accept", {}, roles=("R-MANAGER",))
    assert again.status_code == 409 and json.loads(again.content)["code"] == 40901


def test_guide_suggestion_reject_requires_reason(seed_auth):
    _org_a, _org_b, ua, _ub = _partner_users(seed_auth)
    sid = _data(_post("/api/v1/apply/guide-suggestions", {"title": "建议X"},
                      roles=("R-PARTNER",), uid=ua.id))["id"]
    bad = _post(f"/api/v1/apply/guide-suggestions/{sid}:reject", {}, roles=("R-MANAGER",))
    assert bad.status_code == 400 and json.loads(bad.content)["code"] == 40001
    okr = _post(f"/api/v1/apply/guide-suggestions/{sid}:reject", {"reason": "方向不符"},
                roles=("R-MANAGER",))
    assert _data(okr)["status"] == "REJECTED"
    assert _data(okr)["reject_reason"] == "方向不符"


def test_guide_suggestion_requires_title(seed_auth):
    _org_a, _org_b, ua, _ub = _partner_users(seed_auth)
    r = _post("/api/v1/apply/guide-suggestions", {"title": "  "},
              roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 400 and json.loads(r.content)["code"] == 40001


# ===========================================================================
# Task 4：申报机构化
# ===========================================================================


def test_partner_application_is_org_bound(seed_auth):
    org_a, _org_b, ua, ub = _partner_users(seed_auth)
    r = _post("/api/v1/apply/applications",
              {"title": "开放课题甲", "project_type": "开放课题",
               "pi_user_id": 999, "applicant_org_id": 999},
              roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 200, r.content
    d = _data(r)
    assert d["pi_user_id"] == ua.id and d["applicant_org_id"] == org_a.id
    assert d["applicant_type"] == "EXTERNAL"
    aid = d["id"]
    lb = _data(_get("/api/v1/apply/applications", roles=("R-PARTNER",), uid=ub.id))
    assert lb["total"] == 0
    assert _get(f"/api/v1/apply/applications/{aid}",
                roles=("R-PARTNER",), uid=ub.id).status_code == 404


def test_internal_application_stays_internal(seed_auth):
    d = _data(_post("/api/v1/apply/applications",
                    {"title": "院内课题", "project_type": "ZIGE", "pi_user_id": 2},
                    roles=("R-STAFF",), uid=2))
    assert d["applicant_type"] == "INTERNAL" and d["applicant_org_id"] is None
    assert d["pi_user_id"] == 2


# ===========================================================================
# Task 5：任务书生成 / 签章 / 立项建项 + 签订后冻结
# ===========================================================================
def _party(seed):
    from apps.p.models import PApplication

    org_a, org_b, ua, ub = _partner_users(seed)

    def make(user, org, status="PUBLISHED", title="开放课题甲"):
        return PApplication.objects.create(
            tenant_id=1, creator_id=user.id, title=title, project_type="开放课题",
            pi_user_id=user.id, applicant_org_id=org.id, applicant_type="EXTERNAL",
            status=status, total_budget="100000.00",
        )

    return org_a, org_b, ua, ub, make


def test_task_book_sign_creates_project_once(seed_auth):
    from apps.project.models import EProject

    org_a, _org_b, ua, _ub, make = _party(seed_auth)
    aid = make(ua, org_a).id
    tb = _data(_post("/api/v1/apply/task-books", {"application_id": aid},
                     roles=("R-MANAGER",)))
    assert tb["status"] == "DRAFT"
    assert tb["content_snapshot"]["pi_user_id"] == ua.id
    assert tb["content_snapshot"]["total_budget"] == "100000.00"
    # 幂等：同申报再生成拿回同一份
    assert _data(_post("/api/v1/apply/task-books", {"application_id": aid},
                       roles=("R-MANAGER",)))["id"] == tb["id"]
    # PI 单签：仍 DRAFT
    s1 = _data(_post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "PI"},
                     roles=("R-PARTNER",), uid=ua.id))
    assert s1["status"] == "DRAFT" and len(s1["sign_records"]) == 1
    assert s1["sign_records"][0]["signerId"] == ua.id
    # 管理端签 → SIGNED + 立项
    s2 = _data(_post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "MANAGER"},
                     roles=("R-MANAGER",)))
    assert s2["status"] == "SIGNED" and s2["project_id"]
    proj = EProject.objects.get(id=s2["project_id"])
    assert proj.ext_org_id == org_a.id and proj.pi_user_id == ua.id
    assert proj.status == "EXECUTING" and proj.application_id == aid
    # 再签 409，且只有一个项目
    again = _post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "MANAGER"},
                  roles=("R-MANAGER",))
    assert again.status_code == 409 and json.loads(again.content)["code"] == 40901
    assert EProject.objects.filter(application_id=aid).count() == 1


def test_application_is_frozen_after_task_book_signed(seed_auth):
    org_a, _org_b, ua, _ub, make = _party(seed_auth)
    aid = make(ua, org_a).id
    tb = _data(_post("/api/v1/apply/task-books", {"application_id": aid},
                     roles=("R-MANAGER",)))
    _post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "PI"},
          roles=("R-PARTNER",), uid=ua.id)
    _post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "MANAGER"},
          roles=("R-MANAGER",))

    sec = _put(f"/api/v1/apply/applications/{aid}/sections/GOAL",
               {"content_rich": "签后偷偷改"}, roles=("R-PARTNER",), uid=ua.id)
    assert sec.status_code == 409 and json.loads(sec.content)["code"] == 40901
    bud = _post(f"/api/v1/apply/applications/{aid}/budget",
                {"subject_code": "7201", "amount": "1000.00"},
                roles=("R-PARTNER",), uid=ua.id)
    assert bud.status_code == 409
    sub = _post(f"/api/v1/apply/applications/{aid}/submit", {},
                roles=("R-PARTNER",), uid=ua.id)
    assert sub.status_code == 409


def test_task_book_requires_published_and_partner_cannot_see_others(seed_auth):
    org_a, _org_b, ua, ub, make = _party(seed_auth)
    draft = make(ua, org_a, status="DRAFT", title="草稿课题")
    r = _post("/api/v1/apply/task-books", {"application_id": draft.id},
              roles=("R-MANAGER",))
    assert r.status_code == 409 and json.loads(r.content)["code"] == 40901

    aid = make(ua, org_a).id
    tb = _data(_post("/api/v1/apply/task-books", {"application_id": aid},
                     roles=("R-MANAGER",)))
    # 机构 B 读不到
    assert _get(f"/api/v1/apply/task-books/{tb['id']}",
                roles=("R-PARTNER",), uid=ub.id).status_code == 404
    # 本机构 PI 可读
    assert _get(f"/api/v1/apply/task-books/{tb['id']}",
                roles=("R-PARTNER",), uid=ua.id).status_code == 200


def test_task_book_sign_role_validation(seed_auth):
    org_a, _org_b, ua, _ub, make = _party(seed_auth)
    aid = make(ua, org_a).id
    tb = _data(_post("/api/v1/apply/task-books", {"application_id": aid},
                     roles=("R-MANAGER",)))
    bad = _post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "BOSS"},
                roles=("R-MANAGER",))
    assert bad.status_code == 400 and json.loads(bad.content)["code"] == 40001
    # 同角色重复签 40901
    _post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "PI"},
          roles=("R-PARTNER",), uid=ua.id)
    dup = _post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "PI"},
                roles=("R-PARTNER",), uid=ua.id)
    assert dup.status_code == 409 and json.loads(dup.content)["code"] == 40901


# ===========================================================================
# Task 6：阶段汇报外部化
# ===========================================================================
def _manager_user(seed, username="mgr"):
    """建一个 R-MANAGER 账号（通知广播的接收方）。"""
    from apps.sysadmin.models import SysUser, SysUserRole

    u = SysUser.objects.create(
        username=username, real_name="管理岗", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1)
    SysUserRole.objects.create(user=u, role=seed["roles"]["R-MANAGER"], tenant_id=1)
    return u


def _ext_project(org, pi_uid, title="A 课题"):
    from apps.project.models import EProject

    return EProject.objects.create(
        tenant_id=1, creator_id=1, application_id=1, title=title,
        pi_user_id=pi_uid, ext_org_id=org.id, total_budget="100000.00")


def test_partner_submits_progress_report_within_own_org(seed_auth):
    from apps.notify.models import SysNotification

    org_a, _org_b, ua, ub, _make = _party(seed_auth)
    _manager_user(seed_auth)
    proj = _ext_project(org_a, ua.id)
    r = _post(f"/api/v1/project/{proj.id}/progress-report",
              {"period": "2026Q1", "report_type": "QUARTERLY", "progress_percent": 40},
              roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 200, r.content
    assert _data(r)["period"] == "2026Q1"
    assert SysNotification.objects.filter(tenant_id=1, typ="TODO").exists()
    lst = _data(_get(f"/api/v1/project/{proj.id}/progress-report",
                     roles=("R-PARTNER",), uid=ua.id))
    assert lst["total"] == 1
    # 机构 B 提交/查看均 404
    assert _post(f"/api/v1/project/{proj.id}/progress-report",
                 {"period": "2026Q1", "report_type": "QUARTERLY"},
                 roles=("R-PARTNER",), uid=ub.id).status_code == 404
    assert _get(f"/api/v1/project/{proj.id}/progress-report",
                roles=("R-PARTNER",), uid=ub.id).status_code == 404


# ===========================================================================
# Task 7：验收结题外部化（申请 / 查看 / 结题通知 + 机构邮件）
# ===========================================================================
def test_partner_applies_final_accept_and_gets_notified(seed_auth, mailoutbox):
    from apps.notify.models import SysNotification
    from apps.project.api import conclude_final_accept

    org_a, _org_b, ua, ub, _make = _party(seed_auth)
    _manager_user(seed_auth)
    org_a.contact_email = "org-a@example.com"
    org_a.save(update_fields=["contact_email"])
    proj = _ext_project(org_a, ua.id)

    r = _post(f"/api/v1/project/{proj.id}/final-accept",
              {"outputSummary": "完成 3 篇论文"}, roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 200, r.content
    fa = _data(r)
    got = _data(_get(f"/api/v1/project/{proj.id}/final-accept",
                     roles=("R-PARTNER",), uid=ua.id))
    assert got["id"] == fa["id"]
    # 机构 B 读不到
    assert _get(f"/api/v1/project/{proj.id}/final-accept",
                roles=("R-PARTNER",), uid=ub.id).status_code == 404
    # 机构 B 也不能代提验收
    assert _post(f"/api/v1/project/{proj.id}/final-accept", {},
                 roles=("R-PARTNER",), uid=ub.id).status_code == 404

    conclude_final_accept(fa["id"], "APPROVED")
    assert SysNotification.objects.filter(user_id=ua.id).exists()
    assert mailoutbox and "结题" in mailoutbox[-1].subject
    assert mailoutbox[-1].to == ["org-a@example.com"]


# ===========================================================================
# 终审 M2-b 修复回归：C1 子资源跨机构 / C2 签署身份 / C3 状态机 / C4 空机构 / I1 决议 / I4 角色
# ===========================================================================
def _org_app(org, uid, status="DRAFT"):
    from apps.p.models import PApplication

    return PApplication.objects.create(
        tenant_id=1, creator_id=uid, title=f"{org.name} 申报", project_type="开放课题",
        pi_user_id=uid, status=status, applicant_org_id=org.id, applicant_type="EXTERNAL",
        total_budget=1000)


def test_c1_application_subresources_are_org_scoped(seed_auth):
    """机构 B 对机构 A 的 documents/budget/sections/submit/withdraw/terminate 必须 404。"""
    org_a, org_b, ua, ub = _partner_users(seed_auth)
    a = _org_app(org_a, ua.id)
    as_b = ("R-PARTNER",)
    assert _get(f"/api/v1/apply/applications/{a.id}/documents", roles=as_b, uid=ub.id).status_code == 404
    assert _get(f"/api/v1/apply/applications/{a.id}/budget", roles=as_b, uid=ub.id).status_code == 404
    assert _put(f"/api/v1/apply/applications/{a.id}/sections/background",
                {"content_rich": "B 写入"}, roles=as_b, uid=ub.id).status_code == 404
    assert _post(f"/api/v1/apply/applications/{a.id}/budget",
                 {"subject_code": "01", "amount": "1.00"}, roles=as_b, uid=ub.id).status_code == 404
    assert _post(f"/api/v1/apply/applications/{a.id}/submit",
                 {}, roles=as_b, uid=ub.id).status_code == 404
    # withdraw/terminate 外部角色在策略层也没有授权 → 403 亦可接受（两者都代表拒绝）
    assert _post(f"/api/v1/apply/applications/{a.id}:withdraw",
                 {"reason": "x"}, roles=as_b, uid=ub.id).status_code in (403, 404)
    assert _post(f"/api/v1/apply/applications/{a.id}:terminate",
                 {"reason": "x"}, roles=as_b, uid=ub.id).status_code in (403, 404)
    # 本机构自己正常
    assert _get(f"/api/v1/apply/applications/{a.id}/documents",
                roles=as_b, uid=ua.id).status_code == 200


def test_c2_sign_requires_identity_and_role(seed_auth):
    """外部可签 PI（本人）；不得签 MANAGER；signer_id 被忽略；R-STAFF 不得签 MANAGER。"""
    from apps.p.models import PApplication, PTaskBook

    org_a, org_b, ua, ub = _partner_users(seed_auth)
    m = _manager_user(seed_auth)
    a = PApplication.objects.create(
        tenant_id=1, creator_id=ua.id, title="双签", project_type="开放课题",
        pi_user_id=ua.id, status="PUBLISHED", applicant_org_id=org_a.id,
        applicant_type="EXTERNAL", total_budget=1000)
    tb = PTaskBook.objects.create(tenant_id=1, creator_id=ua.id, application_id=a.id)

    # 跨机构他人：连任务书都不可见 → 404（不泄露存在性）
    r = _post(f"/api/v1/apply/task-books/{tb.id}:sign", {"role": "PI"},
              roles=("R-PARTNER",), uid=ub.id)
    assert r.status_code == 404, r.content
    # 同机构他人签 PI → 403（可见但非 PI 本人）
    from apps.sysadmin.models import SysUser, SysUserRole

    ua2 = SysUser.objects.create(
        username="pa2", real_name="A2", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1, org_id=org_a.id, user_source="EXTERNAL")
    SysUserRole.objects.create(user=ua2, role=seed_auth["roles"]["R-PARTNER"], tenant_id=1)
    r = _post(f"/api/v1/apply/task-books/{tb.id}:sign", {"role": "PI"},
              roles=("R-PARTNER",), uid=ua2.id)
    assert r.status_code == 403, r.content
    # 外部签 MANAGER → 403（即便伪造 signer_id）
    r = _post(f"/api/v1/apply/task-books/{tb.id}:sign",
              {"role": "MANAGER", "signer_id": 999999}, roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 403, r.content
    # R-STAFF 不在策略内 → 403（策略层或 handler 层均可）
    r = _post(f"/api/v1/apply/task-books/{tb.id}:sign", {"role": "MANAGER"},
              roles=("R-STAFF",), uid=m.id)
    assert r.status_code in (403,), r.content
    # PI 本人签署 → 200，签署人恒为本人（忽略 body.signer_id）
    r = _post(f"/api/v1/apply/task-books/{tb.id}:sign",
              {"role": "PI", "signer_id": 424242}, roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 200, r.content
    recs = _data(r)["sign_records"]
    assert [x["signerId"] for x in recs] == [ua.id]
    # 管理端签署 → 200，签署人为调用者本人
    r = _post(f"/api/v1/apply/task-books/{tb.id}:sign",
              {"role": "MANAGER", "signer_id": 777}, roles=("R-MANAGER",), uid=m.id)
    assert r.status_code == 200, r.content
    assert _data(r)["status"] == "SIGNED"
    assert [x["signerId"] for x in _data(r)["sign_records"]] == [ua.id, m.id]


def test_c3_sign_and_terminate_respect_state_machine(seed_auth):
    """REJECTED 不可签署；已签/执行中不可终止（都要 409）。"""
    from apps.p.models import PApplication, PTaskBook
    from apps.project.models import EProject

    org_a, org_b, ua, ub = _partner_users(seed_auth)
    m = _manager_user(seed_auth)
    a = PApplication.objects.create(
        tenant_id=1, creator_id=ua.id, title="已终止", project_type="开放课题",
        pi_user_id=ua.id, status="REJECTED", applicant_org_id=org_a.id,
        applicant_type="EXTERNAL", total_budget=1000)
    tb = PTaskBook.objects.create(tenant_id=1, creator_id=ua.id, application_id=a.id)
    assert _post(f"/api/v1/apply/task-books/{tb.id}:sign", {"role": "PI"},
                 roles=("R-PARTNER",), uid=ua.id).status_code == 409

    # 签后终止 → 409 且项目状态不变
    b = PApplication.objects.create(
        tenant_id=1, creator_id=ua.id, title="将立项", project_type="开放课题",
        pi_user_id=ua.id, status="PUBLISHED", applicant_org_id=org_a.id,
        applicant_type="EXTERNAL", total_budget=1000)
    tb2 = PTaskBook.objects.create(tenant_id=1, creator_id=ua.id, application_id=b.id)
    assert _post(f"/api/v1/apply/task-books/{tb2.id}:sign", {"role": "PI"},
                 roles=("R-PARTNER",), uid=ua.id).status_code == 200
    assert _post(f"/api/v1/apply/task-books/{tb2.id}:sign", {"role": "MANAGER"},
                 roles=("R-MANAGER",), uid=m.id).status_code == 200
    b.refresh_from_db()
    assert b.status == "EXECUTING"
    r = _post(f"/api/v1/apply/applications/{b.id}:terminate",
              {"reason": "终止"}, roles=("R-MANAGER",), uid=m.id)
    assert r.status_code == 409, r.content
    b.refresh_from_db()
    assert b.status == "EXECUTING"
    assert EProject.objects.filter(application_id=b.id, status="EXECUTING").exists()


def test_c4_orgless_partner_sees_nothing(seed_auth):
    """org_id 为空的外部账号：列表空、子资源 404（不能命中院内 applicant_org_id IS NULL）。"""
    from apps.p.models import PApplication
    from apps.sysadmin.models import SysUser, SysUserRole

    internal = PApplication.objects.create(
        tenant_id=1, creator_id=1, title="院内申报", project_type="ZIGE", pi_user_id=1)
    role = seed_auth["roles"]["R-PARTNER"]
    u = SysUser.objects.create(
        username="nullorg", real_name="无机构", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1, org_id=None, user_source="EXTERNAL")
    SysUserRole.objects.create(user=u, role=role, tenant_id=1)

    page = _data(_get("/api/v1/apply/applications", roles=("R-PARTNER",), uid=u.id))
    assert page["total"] == 0 and page["list"] == []
    assert _get(f"/api/v1/apply/applications/{internal.id}/documents",
                roles=("R-PARTNER",), uid=u.id).status_code == 404
    # 指南建议列表同款守卫
    assert _data(_get("/api/v1/apply/guide-suggestions",
                      roles=("R-PARTNER",), uid=u.id))["total"] == 0


def test_c4_create_user_rejects_bad_partner_grant(seed_auth):
    """管理端建号：R-PARTNER 必须带有效机构，且不得与内部角色共存。"""
    from apps.sysadmin.models import SysPartnerOrg

    org = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="机构C", credit_code="91310000MA1K3XY11C",
        org_type="COLLAB", status="APPROVED")
    base = {"username": "newp", "real_name": "新人", "password": "Abcdef@123"}
    # 无机构 → 400
    r = _post("/api/v1/admin/users", {**base, "roles": ["R-PARTNER"]}, roles=("R-ADMIN",), uid=1)
    assert r.status_code == 400, r.content
    # 混合内部角色 → 400
    r = _post("/api/v1/admin/users", {**base, "roles": ["R-PARTNER", "R-STAFF"], "org_id": org.id},
              roles=("R-ADMIN",), uid=1)
    assert r.status_code == 400, r.content
    # 合规：带机构且只有 R-PARTNER → 200 且 user_source=EXTERNAL
    r = _post("/api/v1/admin/users", {**base, "roles": ["R-PARTNER"], "org_id": org.id},
              roles=("R-ADMIN",), uid=1)
    assert r.status_code == 200, r.content
    assert _data(r)["user_source"] == "EXTERNAL" and _data(r)["org_id"] == org.id


def test_i1_decide_application_publishes_and_unblocks_task_book(seed_auth):
    """I1：SUBMITTED →（:decide）PUBLISHED → 可生成任务书；外部用户无权决议。"""
    from apps.p.models import PApplication

    org_a, org_b, ua, ub = _partner_users(seed_auth)
    m = _manager_user(seed_auth)
    a = PApplication.objects.create(
        tenant_id=1, creator_id=ua.id, title="待决议", project_type="开放课题",
        pi_user_id=ua.id, status="SUBMITTED", applicant_org_id=org_a.id,
        applicant_type="EXTERNAL", total_budget=1000)
    # 外部 / R-STAFF 均 403
    assert _post(f"/api/v1/apply/applications/{a.id}:decide", {"decision": "PUBLISHED"},
                 roles=("R-PARTNER",), uid=ua.id).status_code == 403
    # 非法 decision → 400
    assert _post(f"/api/v1/apply/applications/{a.id}:decide", {"decision": "FOO"},
                 roles=("R-MANAGER",), uid=m.id).status_code == 400
    r = _post(f"/api/v1/apply/applications/{a.id}:decide", {"decision": "PUBLISHED"},
              roles=("R-MANAGER",), uid=m.id)
    assert r.status_code == 200, r.content
    assert _data(r)["status"] == "PUBLISHED"
    # 决议后才可生成任务书
    r = _post("/api/v1/apply/task-books", {"application_id": a.id}, roles=("R-MANAGER",), uid=m.id)
    assert r.status_code == 200, r.content
    # 再决议 → 409
    assert _post(f"/api/v1/apply/applications/{a.id}:decide", {"decision": "DECIDED"},
                 roles=("R-MANAGER",), uid=m.id).status_code == 409


def test_i4_leader_can_sign_manager_cannot_be_partner(seed_auth):
    """I4：R-LEADER 具备签署策略；R-PARTNER 永远不能签 MANAGER/LEADER。"""
    from apps.p.models import PApplication, PTaskBook

    org_a, org_b, ua, ub = _partner_users(seed_auth)
    a = PApplication.objects.create(
        tenant_id=1, creator_id=ua.id, title="领导签", project_type="开放课题",
        pi_user_id=ua.id, status="PUBLISHED", applicant_org_id=org_a.id,
        applicant_type="EXTERNAL", total_budget=1000)
    tb = PTaskBook.objects.create(tenant_id=1, creator_id=ua.id, application_id=a.id)
    assert _post(f"/api/v1/apply/task-books/{tb.id}:sign", {"role": "PI"},
                 roles=("R-PARTNER",), uid=ua.id).status_code == 200
    r = _post(f"/api/v1/apply/task-books/{tb.id}:sign", {"role": "LEADER"},
              roles=("R-LEADER",), uid=3)
    assert r.status_code == 200, r.content
    assert _data(r)["status"] == "SIGNED"
    assert _post(f"/api/v1/apply/task-books/{tb.id}:sign", {"role": "LEADER"},
                 roles=("R-PARTNER",), uid=ua.id).status_code in (403, 409)


# ===========================================================================
# 终审 r2：覆盖不全 / 边界写入口 / 契约入参
# ===========================================================================
def _mixed_user(seed, org):
    """造一个 R-PARTNER + R-STAFF 混合角色账号（绕过 create_user 的校验，模拟历史脏数据）。"""
    from apps.sysadmin.models import SysUser, SysUserRole

    u = SysUser.objects.create(
        username="mixed", real_name="混合", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1, org_id=org.id, user_source="EXTERNAL")
    for code in ("R-PARTNER", "R-STAFF"):
        SysUserRole.objects.create(user=u, role=seed["roles"][code], tenant_id=1)
    return u


def test_r2c1_task_book_generation_is_org_scoped(seed_auth):
    """r2 C-1：生成任务书曾内联加锁查询绕过机构收口 → 混合外部账号可读他机构快照。"""
    from apps.p.models import PApplication

    org_a, org_b, ua, ub, _make = _party(seed_auth)
    mixed = _mixed_user(seed_auth, org_b)
    other = PApplication.objects.create(
        tenant_id=1, creator_id=ua.id, title="机构A申报", project_type="开放课题",
        pi_user_id=ua.id, status="PUBLISHED", applicant_org_id=org_a.id,
        applicant_type="EXTERNAL", total_budget=1000)
    # 混合账号属机构 B：机构 A 的申报生成任务书必须 404（且不落库）
    r = _post("/api/v1/apply/task-books", {"application_id": other.id},
              roles=("R-PARTNER", "R-STAFF"), uid=mixed.id)
    assert r.status_code == 404, r.content
    from apps.p.models import PTaskBook
    assert not PTaskBook.objects.filter(application_id=other.id).exists()
    # 院内账号（无机构）正常可生成
    m = _manager_user(seed_auth)
    assert _post("/api/v1/apply/task-books", {"application_id": other.id},
                 roles=("R-MANAGER",), uid=m.id).status_code == 200


def test_r2i1_assign_role_and_create_user_reject_mixed(seed_auth):
    """r2 I-1：给已有外部账号追加内部角色、或建 EXTERNAL 账号持内部角色，都必须 400。"""
    from apps.sysadmin.models import SysPartnerOrg, SysUser

    org = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="机构D", credit_code="91310000MA1K3XY11D",
        org_type="COLLAB", status="APPROVED")
    u = SysUser.objects.create(
        username="ponly", real_name="外", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1, org_id=org.id, user_source="EXTERNAL")
    from apps.sysadmin.models import SysUserRole

    SysUserRole.objects.create(user=u, role=seed_auth["roles"]["R-PARTNER"], tenant_id=1)
    staff_role_id = seed_auth["roles"]["R-STAFF"].id
    r = _post(f"/api/v1/admin/users/{u.id}/roles", {"role_id": staff_role_id},
              roles=("R-ADMIN",), uid=1)
    assert r.status_code == 400, r.content
    # EXTERNAL + R-STAFF 建号 → 400
    r = _post("/api/v1/admin/users",
              {"username": "ext2", "real_name": "外2", "password": "Abcdef@123",
               "roles": ["R-STAFF"], "user_source": "EXTERNAL"},
              roles=("R-ADMIN",), uid=1)
    assert r.status_code == 400, r.content
    # PENDING 机构不得挂账号
    pend = SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name="机构E", credit_code="91310000MA1K3XY11E",
        org_type="COLLAB", status="PENDING")
    r = _post("/api/v1/admin/users",
              {"username": "pend", "real_name": "待审", "password": "Abcdef@123",
               "roles": ["R-PARTNER"], "org_id": pend.id},
              roles=("R-ADMIN",), uid=1)
    assert r.status_code == 400, r.content
    # org_id 非整数 → 400（原先 500）
    r = _post("/api/v1/admin/users",
              {"username": "badorg", "real_name": "坏", "password": "Abcdef@123",
               "roles": ["R-PARTNER"], "org_id": "abc"},
              roles=("R-ADMIN",), uid=1)
    assert r.status_code == 400, r.content


def test_r2i2_progress_report_accepts_contract_camel_case(seed_auth):
    """r2 I-2：契约 EProgressReportSubmit 是 camelCase，按契约提交必须 200。"""
    org_a, _org_b, ua, _ub, _make = _party(seed_auth)
    _manager_user(seed_auth)
    proj = _ext_project(org_a, ua.id)
    r = _post(f"/api/v1/project/{proj.id}/progress-report",
              {"period": "2026Q1", "reportType": "QUARTERLY", "progressPercent": 55,
               "contentRich": "进展", "nextPlan": "下一步"},
              roles=("R-PARTNER",), uid=ua.id)
    assert r.status_code == 200, r.content
    d = _data(r)
    assert d["progressPercent"] == 55 and d["reportType"] == "QUARTERLY"


def test_r2i3_orgless_external_cannot_write(seed_auth):
    """r2 I-3：空机构外部账号不得建申报/建议（否则写出 NULL-org 的院内形状数据）。"""
    from apps.sysadmin.models import SysUser, SysUserRole

    u = SysUser.objects.create(
        username="nullorg2", real_name="无机构", password_hash="x", status="ACTIVE",
        tenant_id=1, creator_id=1, org_id=None, user_source="EXTERNAL")
    SysUserRole.objects.create(user=u, role=seed_auth["roles"]["R-PARTNER"], tenant_id=1)
    r = _post("/api/v1/apply/applications",
              {"title": "空机构申报", "project_type": "开放课题"},
              roles=("R-PARTNER",), uid=u.id)
    assert r.status_code == 403, r.content
    r = _post("/api/v1/apply/guide-suggestions", {"title": "空机构建议"},
              roles=("R-PARTNER",), uid=u.id)
    assert r.status_code == 403, r.content


def test_r2i4_pi_must_exist(seed_auth):
    """r2 I-4：院内申报的 pi_user_id 必须存在，否则 PI 签署永久 403、申报卡死。"""
    r = _post("/api/v1/apply/applications",
              {"title": "幽灵 PI", "project_type": "ZIGE", "pi_user_id": 999999},
              roles=("R-STAFF",), uid=2)
    assert r.status_code == 400, r.content
