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
