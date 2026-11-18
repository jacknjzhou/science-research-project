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
