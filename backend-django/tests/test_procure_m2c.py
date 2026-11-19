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


# ---------------------------------------------------------------- Task 6

def _req(**kw):
    from apps.procure.models import GRequisition

    base = dict(tenant_id=1, creator_id=1, project_id=1, applicant_id=1,
                category="设备", item_name="服务器", est_amount="100000.00")
    base.update(kw)
    return GRequisition.objects.create(**base)


def _bid(suppliers=(), status="PUBLICIZING", code="BID-2026-000001"):
    from apps.procure.models import GBid

    return GBid.objects.create(
        tenant_id=1, creator_id=1, requisition=_req(), method="询价", status=status,
        code=code, invited_supplier_ids=[s.id for s in suppliers], bids_json=[])


def _supplier(org, code="SUP-M2C-02", name="外部供应商甲"):
    from apps.procure.models import GSupplier

    return GSupplier.objects.create(
        code=code, tenant_id=1, name=name, type="供应商", status="IN_LIBRARY",
        org_id=org.id, creator_id=1)


def _partner(seed_auth, org, username="sup_user"):
    from apps.sysadmin.models import SysUser

    return SysUser.objects.create(
        username=username, real_name=username, password_hash=seed_auth["admin"].password_hash,
        status="ACTIVE", tenant_id=1, creator_id=1, org_id=org.id, user_source="EXTERNAL")


def _org_supplier(seed_auth, suffix="1"):
    from apps.sysadmin.models import SysPartnerOrg

    return SysPartnerOrg.objects.create(
        tenant_id=1, creator_id=1, name=f"供应商机构{suffix}",
        credit_code=f"91310000MA1K3XY0{suffix}1", org_type="SUPPLIER", status="APPROVED")


def test_supplier_sees_only_invited_inquiries(seed_auth):
    org_a, org_b = _org_supplier(seed_auth, "1"), _org_supplier(seed_auth, "2")
    sa, sb = _supplier(org_a), _supplier(org_b, code="SUP-M2C-03", name="供应商乙")
    mine = _bid([sa], code="BID-2026-000011")
    _bid([sb], code="BID-2026-000012")
    ua = _partner(seed_auth, org_a)

    r = Client().get("/api/v1/portal/supplier/inquiries", **bearer(ua.id, ["R-PARTNER"]))
    assert r.status_code == 200, r.content
    rows = r.json()["data"]["list"]
    assert [x["id"] for x in rows] == [mine.id]
    assert rows[0]["quoted"] is False
    assert "est_amount" not in json.dumps(rows[0])


def test_supplier_quote_appends_to_bids_json(seed_auth):
    from apps.procure.models import GBid

    org = _org_supplier(seed_auth)
    s = _supplier(org)
    b = _bid([s])
    u = _partner(seed_auth, org)

    r = Client().post(f"/api/v1/portal/supplier/inquiries/{b.id}:quote",
                      data=json.dumps({"totalAmount": "98000.00", "remark": "含税包邮"}),
                      content_type="application/json", **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 200, r.content
    row = GBid.objects.get(id=b.id)
    assert len(row.bids_json) == 1
    entry = row.bids_json[0]
    assert entry["supplierId"] == s.id and entry["totalAmount"] == "98000.00"
    # 幂等：同供应商再报即覆盖，不重复追加
    Client().post(f"/api/v1/portal/supplier/inquiries/{b.id}:quote",
                  data=json.dumps({"totalAmount": "97000.00"}),
                  content_type="application/json", **bearer(u.id, ["R-PARTNER"]))
    row.refresh_from_db()
    assert len(row.bids_json) == 1 and row.bids_json[0]["totalAmount"] == "97000.00"


def test_supplier_quote_rejected_after_award(seed_auth):
    org = _org_supplier(seed_auth)
    s = _supplier(org)
    b = _bid([s], status="AWARDED")
    u = _partner(seed_auth, org)
    r = Client().post(f"/api/v1/portal/supplier/inquiries/{b.id}:quote",
                      data=json.dumps({"totalAmount": "1.00"}),
                      content_type="application/json", **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 409, r.content
    assert r.json()["code"] == 40901


def test_supplier_cannot_quote_others_inquiry(seed_auth):
    org_a, org_b = _org_supplier(seed_auth, "1"), _org_supplier(seed_auth, "2")
    sa, sb = _supplier(org_a), _supplier(org_b, code="SUP-M2C-04", name="供应商乙")
    b = _bid([sb], code="BID-2026-000013")
    ua = _partner(seed_auth, org_a)
    r = Client().post(f"/api/v1/portal/supplier/inquiries/{b.id}:quote",
                      data=json.dumps({"totalAmount": "1.00"}),
                      content_type="application/json", **bearer(ua.id, ["R-PARTNER"]))
    assert r.status_code == 404, r.content


def test_unbound_partner_gets_empty_list(seed_auth):
    org = _org_supplier(seed_auth, "9")
    s = _supplier(org)
    b = _bid([s], code="BID-2026-000014")
    u = _partner(seed_auth, org, username="nobind")
    # 机构未绑定任何供应商
    from apps.procure.models import GSupplier

    GSupplier.objects.filter(org_id=org.id).delete()

    r = Client().get("/api/v1/portal/supplier/inquiries", **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 200 and r.json()["data"]["list"] == []
    r = Client().post(f"/api/v1/portal/supplier/inquiries/{b.id}:quote",
                      data=json.dumps({"totalAmount": "1.00"}),
                      content_type="application/json", **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 403, r.content
