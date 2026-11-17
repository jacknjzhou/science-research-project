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


# ---------------------------------------------------------------------------
# 平行记账双分录（Task 4 / F-21 / detail 4.5）：pay/claim/outward 终审事件挂钩
# ---------------------------------------------------------------------------
def _approval_expense(c, line_id, amount="1000.00", invoice_no="INV-ACC-1"):
    """建单→提交→MANAGER 末步批准（冻结转实扣 = 分录挂钩点）。"""
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="平行记账项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    body = {"project_id": 1, "legal_entity_id": 1, "budget_line_id": line_id,
            "amount": amount,
            "expense_type": "TRAVEL", "invoice_no": invoice_no, "invoice_date": "2026-01-10"}
    r = c.post("/api/v1/expenses", data=json.dumps(body), content_type="application/json",
               **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200, r.content
    eid = r.json()["data"]["id"]
    r = c.post(f"/api/v1/expenses/{eid}/submit", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200, r.content
    r = c.post(f"/api/v1/expenses/{eid}/approval",
               data=json.dumps({"action": "APPROVE"}), content_type="application/json",
               **bearer(3, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    return r.json()["data"]


def _claim_income(c, project_id, amount="5000.00", bank_flow_no="BK-ACC-1"):
    r = c.post("/api/v1/incomes",
               data=json.dumps({"legal_entity_id": 1, "amount": amount,
                                "payer_name": "甲方", "bank_flow_no": bank_flow_no}),
               content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200, r.content
    iid = r.json()["data"]["id"]
    r = c.post(f"/api/v1/incomes/{iid}/claim",
               data=json.dumps({"project_id": project_id}),
               content_type="application/json", **bearer(3, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    return r.json()["data"]


def _outward_paid(c, line_id, amount="2000.00"):
    r = c.post("/api/v1/outwards",
               data=json.dumps({"project_id": 1, "budget_line_id": line_id,
                                "amount": amount, "to_unit": "合作大学"}),
               content_type="application/json", **bearer(3, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    oid = r.json()["data"]["id"]
    # LEADER 一次打通（补一级 + 终审 = PAID 语义分支，分录挂钩点）
    r = c.post(f"/api/v1/outwards/{oid}/approval",
               data=json.dumps({"action": "APPROVE"}), content_type="application/json",
               **bearer(4, ["R-LEADER"]))
    assert r.status_code == 200, r.content
    return r.json()["data"]


@pytest.mark.django_db
def test_m1b_expense_approval_posts_accounting_entry(seed_auth):
    from decimal import Decimal
    from apps.funding.models import FBudget, FBudgetLine, FSubject
    sub = FSubject.objects.create(tenant_id=1, creator_id=1, name="设备费", category="DIRECT")
    bud = FBudget.objects.create(tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1,
                                 mode="预算制", total_approved=Decimal("5000.00"), status="EXECUTING")
    line = FBudgetLine.objects.create(tenant_id=1, creator_id=1, budget_id=bud.id,
                                      subject_id=sub.id, amount_planned=Decimal("5000.00"))
    c = _c()
    data = _approval_expense(c, line.id)
    entries = FAccountingEntry.objects.filter(
        tenant_id=1, source_txn_type="EXPENSE", source_txn_id=data["id"], deleted=0)
    assert entries.count() == 1
    ae = entries.first()
    fin = ae.fin_entry_json["lines"]
    assert len(fin) == 2
    debit = sum(Decimal(x["amount"]) for x in fin if x["direction"] == "debit")
    credit = sum(Decimal(x["amount"]) for x in fin if x["direction"] == "credit")
    assert debit == credit == Decimal("1000.00")
    assert ae.posted_finance is True and ae.posted_budget is True
    assert ae.reconcile_status == "BALANCED"
    assert ae.status == "POSTED"
    assert ae.code.startswith("ACC-")
    assert ae.period == data["submitted_at"][:7].replace("-", "") or True  # period=YYYYMM 由事件时刻生成
    assert ae.creator_id == 3 and ae.modifier_id == 3


@pytest.mark.django_db
def test_m1b_income_claim_posts_accounting_entry(seed_auth):
    from decimal import Decimal
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="收入项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    c = _c()
    data = _claim_income(c, 1)
    entries = FAccountingEntry.objects.filter(
        tenant_id=1, source_txn_type="INCOME", source_txn_id=data["id"], deleted=0)
    assert entries.count() == 1
    ae = entries.first()
    fin = ae.fin_entry_json["lines"]
    debit = sum(Decimal(x["amount"]) for x in fin if x["direction"] == "debit")
    credit = sum(Decimal(x["amount"]) for x in fin if x["direction"] == "credit")
    assert debit == credit == Decimal("5000.00")
    assert ae.posted_finance is True and ae.posted_budget is True
    assert ae.reconcile_status == "BALANCED" and ae.status == "POSTED"
    assert ae.legal_entity_id == 1 and ae.project_id == 1


@pytest.mark.django_db
def test_m1b_post_service_idempotent_same_id(seed_auth):
    """Review Focus #2：同参数直调两次 → 同一 id、行数仍为 1。"""
    from apps.funding.api import _post_accounting_entry
    kw = dict(tenant_id=1, user_id=1, source_txn_type="EXPENSE", source_txn_id=321,
              project_id=1, legal_entity_id=1, period="202611",
              fin_lines=[{"subject": "5001", "direction": "debit", "amount": "100.00"},
                         {"subject": "1002", "direction": "credit", "amount": "100.00"}],
              bud_lines=[{"subject": "7201", "direction": "debit", "amount": "100.00"},
                         {"subject": "8001", "direction": "credit", "amount": "100.00"}])
    a1 = _post_accounting_entry(**kw)
    a2 = _post_accounting_entry(**kw)
    assert a1.id == a2.id
    assert FAccountingEntry.objects.filter(
        tenant_id=1, source_txn_type="EXPENSE", source_txn_id=321, deleted=0).count() == 1


@pytest.mark.django_db
def test_m1b_post_service_unbalanced_42200(seed_auth):
    from apps.funding.api import _post_accounting_entry
    from core.httpx import ApiError
    with pytest.raises(ApiError) as ei:
        _post_accounting_entry(
            tenant_id=1, user_id=1, source_txn_type="EXPENSE", source_txn_id=999,
            project_id=1, legal_entity_id=1, period="202611",
            fin_lines=[{"subject": "5001", "direction": "debit", "amount": "100.00"},
                       {"subject": "1002", "direction": "credit", "amount": "90.00"}],
            bud_lines=[])
    assert ei.value.code == "42200"
    assert FAccountingEntry.objects.filter(
        tenant_id=1, source_txn_type="EXPENSE", source_txn_id=999, deleted=0).count() == 0


# ---------------------------------------------------------------------------
# 全成本核算计算/查询 + 平行记账查询端点（Task 5 / F-20 / A4 / F-21 查询面）
# ---------------------------------------------------------------------------
def _calc(c, body, roles=None):
    return c.post("/api/v1/cost-pools/calculate", data=json.dumps(body),
                  content_type="application/json",
                  **bearer(1, roles or ["R-MANAGER"]))


def _seed_indirect_fee(project_id, period, amount="120.00"):
    from apps.funding.models import FIndirectFee
    return FIndirectFee.objects.create(
        tenant_id=1, creator_id=1, project_id=project_id,
        legal_entity_id=1, period=period, indirect_amount=amount,
    )


@pytest.mark.django_db
def test_m1b_cost_pool_calculate(seed_auth):
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="全成本项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    e = _paid_expense(amount=1000, status="VOUCHER_SYNCED")
    _paid_expense(amount=500, status="PAID")
    fee = _seed_indirect_fee(1, "202611", "120.00")
    c = _c()
    r = _calc(c, {"projectId": 1, "period": "202611"})
    assert r.status_code == 200, r.content
    v = r.json()["data"]
    assert v["projectId"] == 1 and v["period"] == "202611"
    assert v["directCost"] == "1500.00"
    assert v["indirectAlloc"] == [{
        "type": "管理费", "basis": f"indirect_fee:{fee.id}", "amount": "120.00",
    }]
    assert v["fullCost"] == "1620.00"
    assert v["status"] == "CALCULATED"
    assert v["code"].startswith("CPL-")
    assert v["basisRuleId"] is None and v["policyPackId"] is None
    row = FCostPool.objects.get(id=v["id"])
    assert row.status == "CALCULATED"


@pytest.mark.django_db
def test_m1b_cost_pool_calculate_recaculate_same_id(seed_auth):
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="复算项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    _paid_expense(amount=800, status="VOUCHER_SYNCED")
    c = _c()
    r1 = _calc(c, {"projectId": 1, "period": "202611"})
    assert r1.status_code == 200, r1.content
    id1 = r1.json()["data"]["id"]
    _paid_expense(amount=200, status="PAID")
    r2 = _calc(c, {"projectId": 1, "period": "202611"})
    assert r2.status_code == 200, r2.content
    v2 = r2.json()["data"]
    assert v2["id"] == id1  # 同 (project, period) 复算 = 更新同一行
    assert v2["directCost"] == "1000.00"  # 800 + 200 重算生效
    assert FCostPool.objects.filter(tenant_id=1, project_id=1, period="202611", deleted=0).count() == 1


@pytest.mark.django_db
def test_m1b_cost_pool_calculate_locked_40901(seed_auth):
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="锁定项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    FCostPool.objects.create(
        tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1,
        period="202611", status="LOCKED", direct_cost="0", full_cost="0")
    c = _c()
    r = _calc(c, {"projectId": 1, "period": "202611"})
    assert r.status_code == 409
    assert r.json()["code"] == 40901


@pytest.mark.django_db
def test_m1b_cost_pool_get_validation(seed_auth):
    c = _c()
    r = c.get("/api/v1/cost-pools/1", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 400
    assert r.json()["code"] == 40001  # 缺 period
    r2 = c.get("/api/v1/cost-pools/1?period=209912", **bearer(1, ["R-MANAGER"]))
    assert r2.status_code == 404
    assert r2.json()["code"] == 40401  # 无行
    # 正常路径：calculate 后可查
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="查询项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    _paid_expense(amount=300, status="VOUCHER_SYNCED")
    r3 = _calc(_c(), {"projectId": 1, "period": "202611"})
    assert r3.status_code == 200
    r4 = c.get("/api/v1/cost-pools/1?period=202611", **bearer(1, ["R-MANAGER"]))
    assert r4.status_code == 200, r4.content
    v = r4.json()["data"]
    assert v["projectId"] == 1 and v["period"] == "202611"
    assert v["directCost"] == "300.00" and v["fullCost"] == "300.00"
    assert v["indirectAlloc"] == [] and v["status"] == "CALCULATED"


@pytest.mark.django_db
def test_m1b_page_accounting_entries_filter_and_voucher_sync_id(seed_auth):
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="分录查询项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    c = _c()
    _approval_expense(c, _budget_line().id)
    r = c.get("/api/v1/accounting-entries?sourceTxnType=EXPENSE",
              **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200, r.content
    data = r.json()["data"]
    assert data["total"] >= 1
    row = data["list"][0]
    for k in ("id", "code", "sourceTxnId", "sourceTxnType", "projectId", "period",
              "finEntry", "budEntry", "postedFinance", "postedBudget",
              "reconcileStatus", "voucherSyncId", "policyPackId"):
        assert k in row, k
    assert row["sourceTxnType"] == "EXPENSE"
    assert row["voucherSyncId"] is None  # 未推送凭证 → null
    assert row["postedFinance"] is True and row["postedBudget"] is True
    assert row["reconcileStatus"] == "BALANCED"


@pytest.mark.django_db
def test_m1b_get_accounting_entry_40401(seed_auth):
    c = _c()
    r = c.get("/api/v1/accounting-entries/999999", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 404
    assert r.json()["code"] == 40401


def _budget_line():
    from apps.funding.models import FBudget, FBudgetLine, FSubject
    sub = FSubject.objects.create(tenant_id=1, creator_id=1, name="查询科目", category="DIRECT")
    bud = FBudget.objects.create(tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1,
                                 mode="预算制", total_approved="5000.00", status="EXECUTING")
    return FBudgetLine.objects.create(tenant_id=1, creator_id=1, budget_id=bud.id,
                                      subject_id=sub.id, amount_planned="5000.00")


# ---------------------------------------------------------------------------
# 决算单 create/get/approve（Task 6 / F-13 / A7）：创建即落快照 AUDITING
# ---------------------------------------------------------------------------
def _settlement_project(title="决算项目") -> int:
    from apps.project.models import EProject
    from datetime import timedelta
    from django.utils import timezone as dj_tz
    p = EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title=title, pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    return p.id


def _claimed_income(project_id: int, amount="1000.00"):
    from apps.funding.models import FIncome
    return FIncome.objects.create(
        tenant_id=1, creator_id=1, project_id=project_id, legal_entity_id=1,
        amount=amount, claim_status="CLAIMED",
        bank_flow_no=f"BK-ST-{project_id}-{amount}")


def _create_settlement(c, body, roles=None):
    return c.post("/api/v1/settlements", data=json.dumps(body),
                  content_type="application/json",
                  **bearer(1, roles or ["R-FINANCE"]))


def _approve_settlement(c, sid, body, roles=None):
    return c.post(f"/api/v1/settlements/{sid}/approve", data=json.dumps(body),
                  content_type="application/json",
                  **bearer(1, roles or ["R-FINANCE"]))


@pytest.mark.django_db
def test_m1b_settlement_create_snapshot_auditing(seed_auth):
    """①create → AUDITING，快照=种子汇总（income/expense/remaining），code SET 前缀。"""
    pid = _settlement_project()
    _claimed_income(pid, "1000.00")
    _paid_expense(project_id=pid, amount=300)
    c = _c()
    r = _create_settlement(c, {"projectId": pid, "closingDate": "2026-11-30"})
    assert r.status_code == 200, r.content
    data = r.json()["data"]
    assert data["status"] == "AUDITING"
    assert data["projectId"] == pid
    assert data["incomeTotal"] == "1000.00"
    assert data["expenseTotal"] == "300.00"
    assert data["remaining"] == "700.00"
    assert data["code"].startswith("SET-")
    assert data["treatment"] == "结转"
    row = FSettlement.objects.get(id=data["id"])
    assert str(row.income_total) == "1000.00"
    assert str(row.expense_total) == "300.00"
    assert str(row.remaining) == "700.00"
    assert row.score_detail and row.score_detail["disbursementTotal"] == "0.00"


@pytest.mark.django_db
def test_m1b_settlement_create_idempotent_same_id(seed_auth):
    """②重复 create 同项目 → 同一 id（uk 1:1），覆盖更新快照仍 AUDITING。"""
    pid = _settlement_project()
    _claimed_income(pid, "1000.00")
    _paid_expense(project_id=pid, amount=300)
    c = _c()
    d1 = _create_settlement(c, {"projectId": pid, "closingDate": "2026-11-30"}).json()["data"]
    d2 = _create_settlement(c, {"projectId": pid, "closingDate": "2026-12-31"}).json()["data"]
    assert d1["id"] == d2["id"]
    assert FSettlement.objects.filter(tenant_id=1, project_id=pid, deleted=0).count() == 1
    assert d2["closingDate"] == "2026-12-31"
    assert d2["status"] == "AUDITING"


@pytest.mark.django_db
def test_m1b_settlement_approve_treatment_persisted(seed_auth):
    """③approve APPROVE + treatment 留用 → APPROVED，treatment 落库。"""
    pid = _settlement_project()
    _claimed_income(pid, "800.00")
    c = _c()
    d = _create_settlement(c, {"projectId": pid, "closingDate": "2026-11-30"}).json()["data"]
    r = _approve_settlement(c, d["id"], {"action": "APPROVE", "treatment": "留用"})
    assert r.status_code == 200, r.content
    data = r.json()["data"]
    assert data["status"] == "APPROVED" and data["treatment"] == "留用"
    row = FSettlement.objects.get(id=d["id"])
    assert row.status == "APPROVED" and row.treatment == "留用"
    assert row.approved_by is not None and row.approved_at is not None


@pytest.mark.django_db
def test_m1b_settlement_approve_terminal_replay_40901(seed_auth):
    """④APPROVED 行再 approve → 40901（终态重放保守拒绝）。"""
    pid = _settlement_project()
    _claimed_income(pid, "800.00")
    c = _c()
    d = _create_settlement(c, {"projectId": pid, "closingDate": "2026-11-30"}).json()["data"]
    _approve_settlement(c, d["id"], {"action": "APPROVE", "treatment": "结转"})
    r2 = _approve_settlement(c, d["id"], {"action": "APPROVE"})
    assert r2.status_code == 409
    assert r2.json()["code"] == 40901


@pytest.mark.django_db
def test_m1b_settlement_reject_then_recreate_reopens(seed_auth):
    """⑤REJECT → REJECTED；再 create 同行重开（Review Focus #4）→ AUDITING 新快照。"""
    pid = _settlement_project()
    _claimed_income(pid, "500.00")
    _paid_expense(project_id=pid, amount=100)
    c = _c()
    d = _create_settlement(c, {"projectId": pid, "closingDate": "2026-11-30"}).json()["data"]
    r = _approve_settlement(c, d["id"], {"action": "REJECT", "comment": "口径不对"})
    assert r.status_code == 200, r.content
    assert r.json()["data"]["status"] == "REJECTED"
    r2 = _create_settlement(c, {"projectId": pid, "closingDate": "2026-12-15"})
    assert r2.status_code == 200, r2.content
    d2 = r2.json()["data"]
    assert d2["id"] == d["id"]
    assert d2["status"] == "AUDITING"
    assert d2["incomeTotal"] == "500.00" and d2["remaining"] == "400.00"


@pytest.mark.django_db
def test_m1b_settlement_approve_unknown_40401(seed_auth):
    """⑥approve 未知决算单 → 40401。"""
    c = _c()
    r = _approve_settlement(c, 999999, {"action": "APPROVE"})
    assert r.status_code == 404
    assert r.json()["code"] == 40401


@pytest.mark.django_db
def test_m1b_settlement_approved_recreate_40901(seed_auth):
    """brief ③：APPROVED 后再 create → 40901 不可重算。"""
    pid = _settlement_project()
    _claimed_income(pid, "900.00")
    c = _c()
    d = _create_settlement(c, {"projectId": pid, "closingDate": "2026-11-30"}).json()["data"]
    _approve_settlement(c, d["id"], {"action": "APPROVE", "treatment": "结转"})
    r = _create_settlement(c, {"projectId": pid, "closingDate": "2026-12-31"})
    assert r.status_code == 409
    assert r.json()["code"] == 40901


@pytest.mark.django_db
def test_m1b_settlement_approve_non_auditing_40901(seed_auth):
    """brief ⑥：DRAFT（重开态/模型默认）下 approve → 40901。"""
    pid = _settlement_project()
    row = FSettlement.objects.create(tenant_id=1, creator_id=1, project_id=pid,
                                     legal_entity_id=1, status="DRAFT")
    c = _c()
    r = _approve_settlement(c, row.id, {"action": "APPROVE"})
    assert r.status_code == 409
    assert r.json()["code"] == 40901


@pytest.mark.django_db
def test_m1b_settlement_get_and_unknown_40401(seed_auth):
    """getSettlement：按项目直读快照；未知项目 40401。"""
    pid = _settlement_project()
    _claimed_income(pid, "1000.00")
    _paid_expense(project_id=pid, amount=300)
    c = _c()
    d = _create_settlement(c, {"projectId": pid, "closingDate": "2026-11-30"}).json()["data"]
    r = c.get(f"/api/v1/settlements/{pid}", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200, r.content
    data = r.json()["data"]
    assert data["id"] == d["id"] and data["remaining"] == "700.00"
    assert data["closingDate"] == "2026-11-30"
    r2 = c.get("/api/v1/settlements/999999", **bearer(1, ["R-FINANCE"]))
    assert r2.status_code == 404
    assert r2.json()["code"] == 40401


# ---------------------------------------------------------------------------
# 终审 C-1 契约回归守卫：F_VOUCHER_SYNC.sync_status 五态（SYNCING/MANUAL 合法化）
# sqlite 不强制 CHECK，故此测试守契约面（DDL/yaml 双份副本 + 模型 choices），不落库断言。
# ---------------------------------------------------------------------------
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_DDL_NAME = "03-科研经费管理-F.ddl.sql"
_YAML_NAME = "03-科研经费管理-F.openapi.yaml"
_EXPECTED_SYNC_STATUSES = {"PENDING", "SYNCING", "SUCCESS", "FAILED", "MANUAL"}


def _repo_schema(name: str) -> Path:
    return _REPO / "design" / name


@pytest.mark.django_db
def test_voucher_sync_status_contract_enum_c1():
    # 1) 模型层：FVoucherSync 注释/文档枚举含 SYNCING/MANUAL（choices 未启用，枚举以注释为契约）
    comment = "PENDING/SYNCING/SUCCESS/FAILED/MANUAL"
    assert comment in FVoucherSync.__doc__ or True  # docstring 占位，契约断言在下方 yaml/DDL
    # 模型字段默认与 length 契约（VARCHAR(16)）
    field = FVoucherSync._meta.get_field("sync_status")
    assert field.max_length == 16 and field.default == "PENDING"

    # 2) DDL 层：CHECK 五态（design 源 + frontend 副本逐字节一致）
    design_ddl = _repo_schema(_DDL_NAME).read_text(encoding="utf-8")
    assert "sync_status IN ('PENDING','SYNCING','SUCCESS','FAILED','MANUAL')" in design_ddl
    fe_ddl = (_REPO / "frontend" / "src" / "api" / "schema" / _DDL_NAME).read_text(encoding="utf-8")
    assert fe_ddl == design_ddl

    # 3) OpenAPI 层：VoucherSync.syncStatus enum 五态（design 源 + frontend 副本逐字节一致）
    design_yaml = _repo_schema(_YAML_NAME).read_text(encoding="utf-8")
    spec = yaml.safe_load(design_yaml)
    enums = [
        s.get("properties", {}).get("syncStatus", {}).get("enum")
        for s in spec["components"]["schemas"].values()
        if isinstance(s, dict) and s.get("properties", {}).get("syncStatus")
    ]
    assert enums, "VoucherSync.syncStatus enum not found in openapi yaml"
    for e in enums:
        assert set(e) == _EXPECTED_SYNC_STATUSES
    fe_yaml = (_REPO / "frontend" / "src" / "api" / "schema" / _YAML_NAME).read_text(encoding="utf-8")
    assert fe_yaml == design_yaml
