"""M2-c：外部专家/供应商协同/消息通道（C3/C4/C5）回归。"""
from __future__ import annotations

import json

import pytest
from django.test import Client

from tests.conftest import bearer


# ---------------------------------------------------------------- Task 1

def test_supplier_has_org_binding_column(seed_auth):
    from apps.procure.models import GSupplier
    from apps.sysadmin.models import SysPartnerOrg

    org = SysPartnerOrg.objects.create(
        code="PTN-2026-000101", tenant_id=1, name="外部供应商甲",
        org_type="SUPPLIER", status="APPROVED", creator_id=1,
    )
    s = GSupplier.objects.create(
        code="SUP-M2C-01", tenant_id=1, name="外部供应商甲", type="供应商",
        status="IN_LIBRARY", org_id=org.id, creator_id=1,
    )
    assert GSupplier.objects.get(id=s.id).org_id == org.id
