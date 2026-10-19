"""经费域 F 测试（移植 Go funding handler_test 语义：状态机/冻结实扣/指纹查重/幂等导入/两级审批）。"""
import json
from datetime import timedelta
from decimal import Decimal

from django.test import Client, override_settings
from django.utils import timezone as dj_tz

from apps.funding.models import (
    FBudget,
    FBudgetLine,
    FCarryover,
    FExpense,
    FIncome,
    FIndirectFee,
    FOutward,
    FSubject,
    FWarnConfig,
)
from apps.notify.models import SysNotification
from apps.project.models import EProject, EProjectCategory
from tests.conftest import bearer


def _c():
    return Client()


def _project(**kw):
    base = dict(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="经费测试项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    base.update(kw)
    return EProject.objects.create(**base)


def _subject(**kw):
    base = dict(tenant_id=1, creator_id=1, name="设备费", category="DIRECT")
    base.update(kw)
    return FSubject.objects.create(**base)


def _budget_with_line(project_id: int, planned="50000.00", subject=None):
    sub = subject or _subject()
    bud = FBudget.objects.create(
        tenant_id=1, creator_id=1, project_id=project_id, legal_entity_id=1,
        mode="预算制", total_approved=Decimal(planned), status="EXECUTING",
    )
    line = FBudgetLine.objects.create(
        tenant_id=1, creator_id=1, budget_id=bud.id, subject_id=sub.id,
        amount_planned=Decimal(planned),
    )
    return bud, line


# ---------------------------------------------------------------------------
# 科目
# ---------------------------------------------------------------------------
def test_subject_tree_and_level(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/subjects",
        data=json.dumps({"name": "直接费用", "category": "DIRECT"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    root = r.json()["data"]
    assert root["level"] == 1
    r = c.post(
        "/api/v1/subjects",
        data=json.dumps({"name": "设备费", "category": "DIRECT", "parent_id": root["id"]}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["level"] == 2  # parent.level + 1
    r = c.get("/api/v1/subjects/tree", **bearer(1, ["R-ADMIN"]))
    tree = r.json()["data"]
    assert tree[0]["children"][0]["name"] == "设备费"


def test_subject_delete_guards(seed_auth):
    c = _c()
    root = _subject(name="材料费")
    kid = _subject(name="耗材", parent_id=root.id)
    r = c.delete(f"/api/v1/subjects/{root.id}", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409  # 有子级
    c.delete(f"/api/v1/subjects/{kid.id}", **bearer(1, ["R-ADMIN"]))
    bud, _ = _budget_with_line(1, subject=root)
    r = c.delete(f"/api/v1/subjects/{root.id}", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409  # 被预算行引用


# ---------------------------------------------------------------------------
# 预算生命周期
# ---------------------------------------------------------------------------
def test_budget_lifecycle(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/budgets",
        data=json.dumps({"project_id": 1, "legal_entity_id": 1, "mode": "预算制",
                         "lines": [{"subject_id": 1, "amount": "30000.00"},
                                   {"subject_id": 2, "amount": "20000.50"}]}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    bud = r.json()["data"]
    assert bud["total_approved"] == "50000.50"
    assert bud["code"].startswith("BUD-")
    assert bud["status"] == "DRAFT"

    # 非 DRAFT 提交 → 409；先 submit 再重复 submit 校验
    r = c.post(f"/api/v1/budgets/{bud['id']}/submit", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"]["status"] == "SUBMITTED"
    r = c.post(f"/api/v1/budgets/{bud['id']}/submit", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409

    # approve → EXECUTING
    r = c.post(f"/api/v1/budgets/{bud['id']}/approve", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"]["status"] == "EXECUTING"
    assert r.json()["data"]["approved_by"] == 1

    # adjust：行 amount_adjusted 累加、version+1
    r = c.get(f"/api/v1/budgets/{bud['id']}/lines", **bearer(1, ["R-ADMIN"]))
    line = r.json()["data"]["list"][0]
    r = c.post(
        f"/api/v1/budgets/{bud['id']}/adjust",
        data=json.dumps({"lines": [{"line_id": line["id"], "delta": "-1000.00"}]}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["total_adjusted"] == "-1000.00"
    assert r.json()["data"]["version"] == 2
    r = c.get(f"/api/v1/budget-lines/{line['id']}/balance", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"]["remaining"] == "29000.00"


def test_budget_append_flow(seed_auth):
    from apps.sysadmin.models import SysUserRole

    SysUserRole.objects.create(user=seed_auth["staff"], role=seed_auth["roles"]["R-LEADER"], tenant_id=1)
    bud, line = _budget_with_line(1)
    c = _c()
    # 负 delta → 400
    r = c.post(
        f"/api/v1/budgets/{bud.id}/append",
        data=json.dumps({"lines": [{"line_id": line.id, "delta": "-5"}]}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 400
    # 追加 → ADJUSTING
    r = c.post(
        f"/api/v1/budgets/{bud.id}/append",
        data=json.dumps({"lines": [{"line_id": line.id, "delta": "10000.00"}]}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["pending_delta"] == "10000.00"
    bud.refresh_from_db()
    assert bud.status == "ADJUSTING"
    # 批复 → total_approved 并入、行 adjusted 并入、version+1、回 EXECUTING
    r = c.post(f"/api/v1/budgets/{bud.id}/append/approve", **bearer(1, ["R-ADMIN"]))
    data = r.json()["data"]
    assert data["total_approved"] == "60000.00"
    assert data["version"] == 2
    assert data["status"] == "EXECUTING"
    line.refresh_from_db()
    assert str(line.amount_adjusted) == "10000.00"
    assert str(line.pending_delta) == "0.00"
    # 通知触达 R-LEADER（best-effort，含 admin）
    assert SysNotification.objects.filter(title="预算追加待批复").exists()


# ---------------------------------------------------------------------------
# 到款
# ---------------------------------------------------------------------------
def test_income_claim_with_mgmt_fee(seed_auth):
    cat = EProjectCategory.objects.create(tenant_id=1, code="MGMT", name="有管理费", mgmt_fee_pct=5)
    p = _project(category_id=cat.id)
    c = _c()
    r = c.post(
        "/api/v1/incomes",
        data=json.dumps({"legal_entity_id": 1, "amount": "20000.00", "payer_name": "甲方",
                         "bank_flow_no": "BK-C1"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    inc = r.json()["data"]
    assert inc["code"].startswith("INC-")
    assert inc["claim_status"] == "UNCLAIMED"
    # 认领 → CLAIMED + 管理费 = 20000 × 5% = 1000
    r = c.post(
        f"/api/v1/incomes/{inc['id']}/claim",
        data=json.dumps({"project_id": p.id}),
        content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.json()["data"]["claim_status"] == "CLAIMED"
    assert r.json()["data"]["mgmt_fee"] == "1000.00"
    # 重复认领 → 409
    r = c.post(
        f"/api/v1/incomes/{inc['id']}/claim",
        data=json.dumps({"project_id": p.id}),
        content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.status_code == 409


def test_import_bank_flow_idempotent(seed_auth):
    c = _c()
    rows = [{"bank_flow_no": "BK-X1", "amount": "100.00"},
            {"bank_flow_no": "BK-X2", "amount": "200.00"}]
    r = c.post(
        "/api/v1/incomes/import-bank-flow",
        data=json.dumps(rows), content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"] == {"imported": 2, "skipped": 0}
    # 重复导入 → 全部跳过
    r = c.post(
        "/api/v1/incomes/import-bank-flow",
        data=json.dumps(rows + [{"bank_flow_no": "BK-X3", "amount": "300.00"}]),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"] == {"imported": 1, "skipped": 2}


# ---------------------------------------------------------------------------
# 报销：指纹查重 / 冻结 / 审批链 / 实扣-释放
# ---------------------------------------------------------------------------
def _expense(c, line_id=None, amount="1000.00", invoice_no="INV-001", **kw):
    body = {
        "project_id": 1, "legal_entity_id": 1, "amount": amount,
        "expense_type": "TRAVEL", "budget_line_id": line_id,
        "invoice_no": invoice_no, "invoice_date": "2026-01-10",
    }
    body.update(kw)
    r = c.post("/api/v1/expenses", data=json.dumps(body), content_type="application/json",
               **bearer(2, ["R-STAFF"]))
    return r


def test_expense_fingerprint_dedupe(seed_auth):
    bud, line = _budget_with_line(1)
    c = _c()
    r = _expense(c, line.id)
    assert r.status_code == 200
    assert r.json()["data"]["code"].startswith("EXP-")
    # 同发票（号+金额+日期）→ 40903
    r = _expense(c, line.id)
    assert r.status_code == 409
    assert r.json()["code"] == "40903"


def test_expense_submit_freeze_and_approve(seed_auth):
    bud, line = _budget_with_line(1, planned="5000.00")
    c = _c()
    r = _expense(c, line.id, amount="3000.00")
    eid = r.json()["data"]["id"]
    r = c.post(f"/api/v1/expenses/{eid}/submit", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["status"] == "SUBMITTED"
    line.refresh_from_db()
    assert str(line.amount_frozen) == "3000.00"  # 提交即冻结（F-10）
    # 审批链：<10 万 1 步 R-MANAGER
    r = c.get(f"/api/v1/expenses/{eid}", **bearer(1, ["R-ADMIN"]))
    steps = r.json()["data"]["approvals"]
    assert len(steps) == 1 and steps[0]["role"] == "R-MANAGER"
    # STAFF 审批 → 403
    r = c.post(
        f"/api/v1/expenses/{eid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 403
    # MANAGER 批准（末步）→ APPROVED + 冻结转实扣
    r = c.post(
        f"/api/v1/expenses/{eid}/approval",
        data=json.dumps({"action": "APPROVE", "comment": "ok"}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.json()["data"]["status"] == "APPROVED"
    line.refresh_from_db()
    assert str(line.amount_frozen) == "0.00"
    assert str(line.amount_used) == "3000.00"
    assert str(line.remaining) == "2000.00"
    # 报销人收到结果通知
    assert SysNotification.objects.filter(user_id=2, typ="EXPENSE_RESULT").exists()


def test_expense_reject_releases_budget(seed_auth):
    bud, line = _budget_with_line(1, planned="5000.00")
    c = _c()
    eid = _expense(c, line.id, amount="2000.00", invoice_no="INV-R1").json()["data"]["id"]
    c.post(f"/api/v1/expenses/{eid}/submit", **bearer(2, ["R-STAFF"]))
    r = c.post(
        f"/api/v1/expenses/{eid}/approval",
        data=json.dumps({"action": "REJECT", "comment": "票据不合规"}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.json()["data"]["status"] == "REJECTED"
    line.refresh_from_db()
    assert str(line.amount_frozen) == "0.00"
    assert str(line.amount_released) == "2000.00"  # 驳回解冻
    # Go 口径：remaining = planned + adjusted - frozen - used - released（released 计入占用）
    assert str(line.remaining) == "3000.00"


def test_expense_submit_insufficient_balance_40902(seed_auth):
    bud, line = _budget_with_line(1, planned="1000.00")
    c = _c()
    eid = _expense(c, line.id, amount="2000.00", invoice_no="INV-B1").json()["data"]["id"]
    r = c.post(f"/api/v1/expenses/{eid}/submit", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 409
    assert r.json()["code"] == 40902
    # 状态回退 DRAFT
    e = FExpense.objects.get(id=eid)
    assert e.status == "DRAFT"
    assert str(e.fingerprint_amount) == "2000.00"


def test_expense_submit_dup_in_transit_40903(seed_auth):
    bud, line = _budget_with_line(1)
    c = _c()
    e1 = _expense(c, line.id, invoice_no="INV-D1").json()["data"]["id"]
    c.post(f"/api/v1/expenses/{e1}/submit", **bearer(2, ["R-STAFF"]))
    # 同指纹第二单 create 时即被唯一指纹拦截（uk_expense_fingerprint → 40903）
    r = _expense(c, line.id, invoice_no="INV-D1")
    assert r.status_code == 409 and r.json()["code"] == "40903"


def test_expense_two_step_chain_over_100k(seed_auth):
    bud, line = _budget_with_line(1, planned="200000.00")
    c = _c()
    eid = _expense(c, line.id, amount="150000.00", invoice_no="INV-BIG").json()["data"]["id"]
    c.post(f"/api/v1/expenses/{eid}/submit", **bearer(2, ["R-STAFF"]))
    r = c.get(f"/api/v1/expenses/{eid}", **bearer(1, ["R-ADMIN"]))
    steps = r.json()["data"]["approvals"]
    assert [s["role"] for s in steps] == ["R-MANAGER", "R-LEADER"]
    # 第一步 MANAGER → 进入下一审批步（仍 HUMAN_REVIEW）
    r = c.post(
        f"/api/v1/expenses/{eid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.json()["data"]["status"] == "HUMAN_REVIEW"
    line.refresh_from_db()
    assert str(line.amount_frozen) == "150000.00"  # 未终审仍冻结
    # 第二步 LEADER → APPROVED
    r = c.post(
        f"/api/v1/expenses/{eid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(4, ["R-LEADER"]),
    )
    assert r.json()["data"]["status"] == "APPROVED"
    line.refresh_from_db()
    assert str(line.amount_used) == "150000.00"


def test_expense_approval_batch(seed_auth):
    bud, line = _budget_with_line(1, planned="9000.00")
    c = _c()
    ids = []
    for i, no in enumerate(["INV-M1", "INV-M2"]):
        eid = _expense(c, line.id, amount="1000.00", invoice_no=no).json()["data"]["id"]
        c.post(f"/api/v1/expenses/{eid}/submit", **bearer(2, ["R-STAFF"]))
        ids.append(eid)
    r = c.post(
        "/api/v1/expenses/approval-batch",
        data=json.dumps({"ids": ids, "action": "APPROVE"}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    body = r.json()["data"]
    assert body["ok"] == 2
    assert all(x["ok"] for x in body["results"])


# ---------------------------------------------------------------------------
# 外拨（F-24）
# ---------------------------------------------------------------------------
def test_outward_two_level_and_deduct(seed_auth):
    bud, line = _budget_with_line(1, planned="8000.00")
    c = _c()
    r = c.post(
        "/api/v1/outwards",
        data=json.dumps({"project_id": 1, "budget_line_id": line.id, "amount": "5000.00",
                         "to_unit": "合作大学"}),
        content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    oid = r.json()["data"]["id"]
    # STAFF 直接终审？→ STAFF 非 leader，做一级批复
    r = c.post(
        f"/api/v1/outwards/{oid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.json()["data"]["first_approved_by"] == 3
    assert r.json()["data"]["status"] == "PENDING"  # 一级后仍待终审
    # MANAGER 终审 → 409（无终审权走 leader 分支? is_leader=False → 检查一级已批 → 409）
    r = c.post(
        f"/api/v1/outwards/{oid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.status_code == 409
    # LEADER 终审 → 实扣
    r = c.post(
        f"/api/v1/outwards/{oid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(4, ["R-LEADER"]),
    )
    assert r.json()["data"]["status"] == "APPROVED"
    line.refresh_from_db()
    assert str(line.amount_used) == "5000.00"
    # 通知提交人
    assert SysNotification.objects.filter(user_id=3, title="外拨已批复").exists()


def test_outward_leader_double_hop(seed_auth):
    bud, line = _budget_with_line(1, planned="8000.00")
    c = _c()
    oid = c.post(
        "/api/v1/outwards",
        data=json.dumps({"project_id": 1, "budget_line_id": line.id, "amount": "1000.00",
                         "to_unit": "乙方"}),
        content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    ).json()["data"]["id"]
    # LEADER 一次打通（补一级 + 终审）
    r = c.post(
        f"/api/v1/outwards/{oid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(4, ["R-LEADER"]),
    )
    assert r.json()["data"]["status"] == "APPROVED"
    assert r.json()["data"]["first_approved_by"] == 4


def test_outward_insufficient_40902(seed_auth):
    bud, line = _budget_with_line(1, planned="500.00")
    c = _c()
    oid = c.post(
        "/api/v1/outwards",
        data=json.dumps({"project_id": 1, "budget_line_id": line.id, "amount": "2000.00",
                         "to_unit": "丙方"}),
        content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    ).json()["data"]["id"]
    r = c.post(
        f"/api/v1/outwards/{oid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(4, ["R-LEADER"]),
    )
    assert r.status_code == 409 and r.json()["code"] == 40902


# ---------------------------------------------------------------------------
# 结转（F-25）
# ---------------------------------------------------------------------------
def test_carryover_closed_guard_and_income_generation(seed_auth):
    closed = _project(status="CLOSED")
    executing = _project()
    c = _c()
    # 未结题 → 409
    r = c.post(
        "/api/v1/carryovers",
        data=json.dumps({"project_id": executing.id, "fiscal_year": 2026, "target_year": 2027,
                         "amount": "800.00"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 409
    r = c.post(
        "/api/v1/carryovers",
        data=json.dumps({"project_id": closed.id, "fiscal_year": 2026, "target_year": 2027,
                         "amount": "800.00"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    coid = r.json()["data"]["id"]
    # 批复 → 生成 CRO-<id> 到账行（幂等键）
    r = c.post(
        f"/api/v1/carryovers/{coid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    data = r.json()["data"]
    assert data["status"] == "APPROVED" and data["income_id"]
    inc = FIncome.objects.get(id=data["income_id"])
    assert inc.bank_flow_no == f"CRO-{coid}"
    assert str(inc.amount) == "800.00"
    # 重复操作 → 409
    r = c.post(
        f"/api/v1/carryovers/{coid}/approval",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# 间接费（F-12）
# ---------------------------------------------------------------------------
def test_indirect_fee_calculate_and_range_guard(seed_auth):
    p = _project()
    FIncome.objects.create(tenant_id=1, creator_id=1, project_id=p.id,
                           amount=Decimal("100000.00"), claim_status="CLAIMED")
    c = _c()
    r = c.post(
        "/api/v1/indirect-fees/calculate",
        data=json.dumps({"project_id": p.id}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    data = r.json()["data"]
    assert data["indirectRate"] == "0.2000"  # 缺省 0.20
    assert data["indirectAmount"] == "20000.00"  # 100000 × 0.20
    # 幂等更新（同项目再次计提覆盖）
    r = c.post(
        "/api/v1/indirect-fees/calculate",
        data=json.dumps({"project_id": p.id, "rate": 0.10}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["indirectAmount"] == "10000.00"
    assert FIndirectFee.objects.filter(project_id=p.id).count() == 1
    # 费率超限 → 40904
    r = c.post(
        "/api/v1/indirect-fees/calculate",
        data=json.dumps({"project_id": p.id, "rate": 0.5}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 422 and r.json()["code"] == "40904"


# ---------------------------------------------------------------------------
# 执行率聚合 + 预警（T23）
# ---------------------------------------------------------------------------
def test_funding_execution_aggregation(seed_auth):
    bud, line = _budget_with_line(1, planned="10000.00")
    line.amount_used = Decimal("6000.00")  # 行级口径（dim=subject 用）
    line.save()
    FIncome.objects.create(tenant_id=1, creator_id=1, project_id=1,
                           amount=Decimal("9000.00"), claim_status="CLAIMED")
    # 文档级口径：executionOf.used 取已批准报销
    FExpense.objects.create(
        tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1,
        applicant_user_id=2, amount=Decimal("6000.00"), status="APPROVED",
        expense_type="OTHER",
    )
    FExpense.objects.create(
        tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1,
        applicant_user_id=2, amount=Decimal("1500.00"), status="SUBMITTED",
        expense_type="OTHER",
    )
    c = _c()
    r = c.get("/api/v1/funding/execution?project_id=1", **bearer(1, ["R-ADMIN"]))
    m = r.json()["data"]
    assert m["budgetApproved"] == "10000.00"
    assert m["incomeTotal"] == "9000.00"
    assert m["used"] == "6000.00"
    assert m["frozen"] == "1500.00"
    assert m["remaining"] == "2500.00"
    assert abs(m["execRateByBudget"] - 0.6) < 1e-9
    # dim=subject
    r = c.get("/api/v1/funding/execution?dim=subject", **bearer(1, ["R-ADMIN"]))
    row = r.json()["data"]["list"][0]
    assert row["dimId"] == line.subject_id
    assert row["used"] == "6000.00"


def test_funding_warnings_levels(seed_auth):
    # rate = 6000/10000 = 0.6 → 无预警；end_date 30 天内 → DEADLINE_RISK
    p = _project(end_date=dj_tz.localdate() + timedelta(days=10))
    bud, line = _budget_with_line(p.id, planned="10000.00")
    FExpense.objects.create(
        tenant_id=1, creator_id=1, project_id=p.id, legal_entity_id=1,
        applicant_user_id=2, amount=Decimal("6000.00"), status="APPROVED",
        expense_type="OTHER",
    )
    c = _c()
    r = c.get(f"/api/v1/funding/warnings?project_id={p.id}", **bearer(1, ["R-ADMIN"]))
    rows = r.json()["data"]["list"]
    assert rows[0]["level"] == "DEADLINE_RISK"
    # rate=1.0 → CRITICAL + 通知 PI
    FExpense.objects.create(
        tenant_id=1, creator_id=1, project_id=p.id, legal_entity_id=1,
        applicant_user_id=2, amount=Decimal("4000.00"), status="APPROVED",
        expense_type="OTHER",
    )
    r = c.get(f"/api/v1/funding/warnings?project_id={p.id}", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"]["list"][0]["level"] == "CRITICAL"
    assert SysNotification.objects.filter(typ="FUNDING_WARNING").exists()


# ---------------------------------------------------------------------------
# AI 审核（F-15 降级语义）
# ---------------------------------------------------------------------------
def test_ai_invoice_review_degraded(seed_auth):
    c = _c()
    FExpense.objects.create(
        tenant_id=1, creator_id=2, project_id=1, legal_entity_id=1,
        applicant_user_id=2, amount=Decimal("500.00"), expense_type="OTHER",
    )
    r = c.post(
        "/api/v1/expense/ai-invoice-review",
        data=json.dumps({"expenseId": 1}), content_type="application/json",
        **bearer(2, ["R-FINANCE"]),
    )
    data = r.json()["data"]
    assert data["verdict"] == "REVIEW"  # LLM 未配置降级
    assert data["available"] is False
    assert data["issues"][0]["rule"] == "SERVICE_DEGRADED"


# ---------------------------------------------------------------------------
# 预警配置（T15）
# ---------------------------------------------------------------------------
def test_warn_config_crud(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/funding/warn-configs",
        data=json.dumps({"warn_kind": "EXEC_RATE", "threshold_pct": "0.8000", "ahead_days": 30}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    w = r.json()["data"]
    assert w["level"] == "P2" and w["channel"] == "INBOX" and w["enabled"] is True
    # 非法 kind → 400
    r = c.post(
        "/api/v1/funding/warn-configs",
        data=json.dumps({"warn_kind": "BOGUS"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 400
    # 局部更新
    r = c.put(
        f"/api/v1/funding/warn-configs/{w['id']}",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["enabled"] is False
    assert r.json()["data"]["warn_kind"] == "EXEC_RATE"  # 未传不覆盖
    # 列表过滤
    r = c.get("/api/v1/funding/warn-configs?enabled=false", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"]["total"] == 1
    # 删除
    r = c.delete(f"/api/v1/funding/warn-configs/{w['id']}", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
