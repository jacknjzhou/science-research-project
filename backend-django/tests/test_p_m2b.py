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
