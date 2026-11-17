"""M1-b：成本池/平行记账/决算/凭证同步（A4/A5/A7）模型冒烟 + Task 3 凭证同步端点。"""
import json

import pytest
from django.test import Client

from apps.funding.models import FCostPool, FAccountingEntry, FSettlement, FVoucherSync, FExpense
from tests.conftest import bearer


@pytest.mark.django_db
def test_m1b_models_crud_smoke():
    cp = FCostPool.objects.create(tenant_id=1, creator_id=1, project_id=1,
        legal_entity_id=1, period="202611", direct_cost="100.00", full_cost="120.00")
    assert cp.status == "DRAFT" and str(cp.direct_cost) == "100.00"
    ae = FAccountingEntry.objects.create(tenant_id=1, creator_id=1, source_txn_id=cp.id,
        source_txn_type="EXPENSE", legal_entity_id=1, period="202611",
        fin_entry_json={"lines": []}, bud_entry_json={"lines": []})
    assert ae.reconcile_status == "UNRECONCILED" and ae.posted_finance is False
    vs = FVoucherSync.objects.create(tenant_id=1, creator_id=1, expense_id=1, finance_system="YONYOU")
    assert vs.sync_status == "PENDING" and vs.retry_count == 0
    st = FSettlement.objects.create(tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1)
    assert st.status == "DRAFT" and st.treatment == "结转"


# ---------------------------------------------------------------------------
# 凭证同步 push + callback（Task 3 / F-11）
# ---------------------------------------------------------------------------
def _c():
    return Client()


def _paid_expense(**kw) -> FExpense:
    """PAID 报销单 fixture（复用 M1-a _expense 风格，本文件内重建）。"""
    base = dict(
        tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1,
        applicant_user_id=1, amount=1000, expense_type="TRAVEL",
        status="PAID", paid_at=None,
    )
    base.update(kw)
    return FExpense.objects.create(**base)


def _push(c, body, roles=None):
    return c.post("/api/v1/vouchers/sync", data=json.dumps(body),
                  content_type="application/json",
                  **bearer(1, roles or ["R-FINANCE"]))


def _callback(c, body, roles=None):
    return c.post("/api/v1/vouchers/sync-callback", data=json.dumps(body),
                  content_type="application/json",
                  **bearer(1, roles or ["R-FINANCE"]))


def test_voucher_push_new_syncing(seed_auth):
    c = _c()
    e = _paid_expense()
    r = _push(c, {"expenseId": e.id})
    assert r.status_code == 200, r.content
    v = r.json()["data"]
    assert v["id"] > 0
    assert v["expenseId"] == e.id
    assert v["financeSystem"] == "YONYOU"
    assert v["syncStatus"] == "SYNCING"
    assert v["voucherNo"] is None and v["errorMsg"] is None and v["syncAt"] is None
    assert v["retryCount"] == 0
    assert "code" not in v  # 契约 VoucherSync 无 code 键
    row = FVoucherSync.objects.get(id=v["id"])
    assert row.status == "SYNCING"
    assert row.payload_json and row.payload_json.get("expenseId") == e.id


def test_voucher_push_idempotent(seed_auth):
    c = _c()
    e = _paid_expense()
    r1 = _push(c, {"expenseId": e.id})
    assert r1.status_code == 200
    id1 = r1.json()["data"]["id"]
    r2 = _push(c, {"expenseId": e.id})
    assert r2.status_code == 200
    assert r2.json()["data"]["id"] == id1
    # MANUAL 状态也返回既有行（不自动重试）
    row = FVoucherSync.objects.get(id=id1)
    row.status = "MANUAL"
    row.save()
    r3 = _push(c, {"expenseId": e.id})
    assert r3.status_code == 200
    assert r3.json()["data"]["id"] == id1


def test_voucher_push_expense_not_found(seed_auth):
    c = _c()
    r = _push(c, {"expenseId": 999999})
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    r2 = _push(c, {})
    assert r2.status_code == 400
    assert r2.json()["code"] == 40001


def test_voucher_callback_success_writes_back(seed_auth):
    c = _c()
    e = _paid_expense()
    vid = _push(c, {"expenseId": e.id}).json()["data"]["id"]
    r = _callback(c, {"expenseId": e.id, "result": "SUCCESS", "voucherNo": "PZ-2026-001"})
    assert r.status_code == 200, r.content
    row = FVoucherSync.objects.get(id=vid)
    assert row.sync_status == "SUCCESS"
    assert row.voucher_no == "PZ-2026-001"
    assert row.sync_at is not None
    assert row.callback_json is not None
    e.refresh_from_db()
    assert e.status == "VOUCHER_SYNCED"


def test_voucher_callback_success_idempotent(seed_auth):
    c = _c()
    e = _paid_expense()
    vid = _push(c, {"expenseId": e.id}).json()["data"]["id"]
    r1 = _callback(c, {"expenseId": e.id, "result": "SUCCESS", "voucherNo": "PZ-001"})
    assert r1.status_code == 200
    r2 = _callback(c, {"expenseId": e.id, "result": "SUCCESS", "voucherNo": "PZ-001"})
    assert r2.status_code == 200
    row = FVoucherSync.objects.get(id=vid)
    assert row.sync_status == "SUCCESS" and row.voucher_no == "PZ-001"
    assert row.retry_count == 0
    e.refresh_from_db()
    assert e.status == "VOUCHER_SYNCED"


def test_voucher_callback_failed_manual(seed_auth):
    c = _c()
    e = _paid_expense(status="APPROVED")
    vid = _push(c, {"expenseId": e.id}).json()["data"]["id"]
    for i in range(4):
        r = _callback(c, {"expenseId": e.id, "result": "FAILED", "detail": {"msg": f"网络超时{i+1}"}})
        assert r.status_code == 200, r.content
    row = FVoucherSync.objects.get(id=vid)
    assert row.retry_count == 4
    assert row.status == "MANUAL"
    assert row.sync_status == "FAILED"
    assert row.error_msg and "网络超时" in row.error_msg
    e.refresh_from_db()
    assert e.status == "APPROVED"  # 失败不动报销状态


def test_voucher_callback_no_record_40401(seed_auth):
    c = _c()
    e = _paid_expense()
    r = _callback(c, {"expenseId": e.id, "result": "SUCCESS", "voucherNo": "PZ-X"})
    assert r.status_code == 404
    assert r.json()["code"] == 40401
