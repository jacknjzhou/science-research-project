"""E-7 funding 域：预算/报销/拨款关联按租户收口（跨租户一律 404 / 不被采纳）。"""
import json
from decimal import Decimal

from django.test import Client

from apps.funding.models import FBudget, FBudgetLine, FExpense, FExpenseApproval
from apps.project.models import EProject
from tests.conftest import bearer

FIN = ["R-MANAGER", "R-FINANCE"]


def _json(r):
    return json.loads(r.content.decode())


def _mk_budget(tenant_id: int = 1, status: str = "DRAFT"):
    b = FBudget.objects.create(
        tenant_id=tenant_id, creator_id=1, project_id=11, legal_entity_id=1,
        status=status, mode="预算制", total_approved=Decimal("10000.00"),
    )
    line = FBudgetLine.objects.create(
        tenant_id=tenant_id, creator_id=1, budget_id=b.id, subject_id=1,
        status="ACTIVE", amount_planned=Decimal("10000.00"),
    )
    return b, line


def _mk_expense(tenant_id: int = 1, line_id=None, status: str = "DRAFT"):
    return FExpense.objects.create(
        tenant_id=tenant_id, creator_id=1, project_id=11, budget_line_id=line_id,
        legal_entity_id=1, applicant_user_id=2, amount=Decimal("500.00"),
        status=status, submit_mode="预算制",
    )


def test_cross_tenant_budget_read_and_lines_are_404(seed_auth):
    b, _ = _mk_budget()
    c = Client()
    r = c.get(f"/api/v1/budgets/{b.id}", **bearer(1, FIN, tenant_id=2))
    assert r.status_code == 404
    r = c.get(f"/api/v1/budgets/{b.id}/lines", **bearer(1, FIN, tenant_id=2))
    assert r.status_code == 404


def test_cross_tenant_budget_submit_is_rejected(seed_auth):
    b, _ = _mk_budget(status="DRAFT")
    r = Client().post(f"/api/v1/budgets/{b.id}/submit", **bearer(1, FIN, tenant_id=2))
    assert r.status_code in (404, 409)
    b.refresh_from_db()
    assert b.status == "DRAFT", "他租户不得推进本租户预算状态"


def test_cross_tenant_budget_line_balance_is_404(seed_auth):
    _, line = _mk_budget()
    r = Client().get(f"/api/v1/budget-lines/{line.id}/balance", **bearer(1, FIN, tenant_id=2))
    assert r.status_code == 404


def test_cross_tenant_expense_read_is_404(seed_auth):
    e = _mk_expense()
    r = Client().get(f"/api/v1/expenses/{e.id}", **bearer(1, FIN, tenant_id=2))
    assert r.status_code == 404


def test_cross_tenant_expense_submit_is_rejected(seed_auth):
    _, line = _mk_budget()
    e = _mk_expense(line_id=line.id, status="DRAFT")
    r = Client().post(f"/api/v1/expenses/{e.id}/submit", **bearer(2, ["R-STAFF"], tenant_id=2))
    assert r.status_code in (404, 409)
    e.refresh_from_db()
    line.refresh_from_db()
    assert e.status == "DRAFT"
    assert line.amount_frozen == Decimal("0.00"), "不得冻结他租户预算行"


def test_cross_tenant_expense_approve_is_rejected(seed_auth):
    _, line = _mk_budget(status="EXECUTING")
    e = _mk_expense(line_id=line.id, status="SUBMITTED")
    FExpenseApproval.objects.create(
        tenant_id=1, creator_id=1, expense_id=e.id, step_order=1,
        role="R-MANAGER", status="PENDING")
    r = Client().post(f"/api/v1/expenses/{e.id}/approval",
                      data=json.dumps({"action": "APPROVE", "comment": "x"}),
                      content_type="application/json", **bearer(1, FIN, tenant_id=2))
    assert r.status_code in (404, 409)
    e.refresh_from_db()
    assert e.status != "PAID", "他租户不得替他租户报销单放款"


def test_create_budget_rejects_foreign_project(seed_auth):
    p = EProject.objects.create(
        tenant_id=2, creator_id=1, code="PRJ-E7-2", title="他租户项目", application_id=1,
        pi_user_id=1,
        status="EXECUTING", legal_entity_id=1, total_budget=Decimal("1.00"),
    )
    r = Client().post("/api/v1/budgets", data=json.dumps({
        "project_id": p.id, "legal_entity_id": 1, "mode": "预算制",
        "lines": [{"subject_id": 1, "amount": "100.00"}],
    }), content_type="application/json", **bearer(1, FIN, tenant_id=1))
    assert r.status_code == 404, r.content.decode()


def test_related_loan_and_expense_id_reject_foreign(seed_auth):
    """他租户报销单不得被本租户借款冲销（expense 查询须带 tenant）。"""
    from apps.funding.models import FLoan

    loan = FLoan.objects.create(
        tenant_id=1, creator_id=1, project_id=11, legal_entity_id=1,
        amount=Decimal("1000.00"), status="PAID", applicant_user_id=2,
    )
    e = _mk_expense(tenant_id=2, status="APPROVED")
    e.related_loan_id = loan.id
    e.save(update_fields=["related_loan_id"])
    r = Client().post(f"/api/v1/loans/{loan.id}/write-off", data=json.dumps(
        {"expenseId": e.id}), content_type="application/json",
        **bearer(1, FIN, tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    loan.refresh_from_db()
    assert loan.write_off_amount == Decimal("0.00"), "不得拿他租户报销单冲销本租户借款"


def test_carryover_rejects_foreign_project(seed_auth):
    p2 = EProject.objects.create(
        tenant_id=2, creator_id=1, code="PRJ-E7-3", title="他租户项目2",
        application_id=2, pi_user_id=1, status="CLOSED", legal_entity_id=1,
    )
    r = Client().post("/api/v1/carryovers", data=json.dumps({
        "project_id": p2.id, "fiscal_year": 2025, "target_year": 2026,
        "amount": "100.00",
    }), content_type="application/json", **bearer(1, FIN, tenant_id=1))
    assert r.status_code in (404, 422), r.content.decode()


def test_indirect_fee_rejects_foreign_project(seed_auth):
    p2 = EProject.objects.create(
        tenant_id=2, creator_id=1, code="PRJ-E7-4", title="他租户项目3",
        application_id=3, pi_user_id=1, status="EXECUTING", legal_entity_id=1,
    )
    r = Client().post("/api/v1/indirect-fees/calculate", data=json.dumps({
        "project_id": p2.id, "basis": "DIRECT_COST", "rate": "0.10",
    }), content_type="application/json", **bearer(1, FIN, tenant_id=1))
    assert r.status_code in (400, 404), r.content.decode()
