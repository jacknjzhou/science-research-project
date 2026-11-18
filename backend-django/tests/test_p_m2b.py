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
