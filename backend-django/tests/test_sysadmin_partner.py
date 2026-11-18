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
