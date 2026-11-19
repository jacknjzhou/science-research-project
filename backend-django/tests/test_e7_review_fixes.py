"""E-7 终审（final-review-e7）回归：预算行/公示/企业库/审计链/科目预言机。

覆盖终审的 4 条 Critical 与 3 条 Important——这些路径在 1b1b55f 上均可跨租户成功。
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client
from django.utils import timezone as dj_tz

from apps.confsec.models import XSecLog
from apps.funding.models import FBudget, FBudgetLine, FSubject
from apps.project.models import EProject
from apps.transform.models import TDeal, TDisclosure, TEnterpartner, TPublicity
from tests.conftest import bearer

FIN = ["R-MANAGER", "R-FINANCE"]
T_ROLES = ["R-MANAGER", "R-LEADER"]


def _json(r):
    return json.loads(r.content.decode())


def _line(tenant_id: int = 2):
    b = FBudget.objects.create(
        tenant_id=tenant_id, creator_id=1, project_id=11, legal_entity_id=1,
        status="EXECUTING", mode="预算制", total_approved=Decimal("10000.00"),
    )
    line = FBudgetLine.objects.create(
        tenant_id=tenant_id, creator_id=1, budget_id=b.id, subject_id=1,
        status="ACTIVE", amount_planned=Decimal("10000.00"),
    )
    return b, line


def _project(tenant_id: int = 1, code: str = "PRJ-E7C"):
    return EProject.objects.create(
        tenant_id=tenant_id, creator_id=1, code=code, title="E-7 项目",
        application_id=hash(code) % 100000 + 1, pi_user_id=1,
        status="EXECUTING", legal_entity_id=1,
    )


# --- C1 报销链：create/submit/approve 均不得触及他租户预算行 -----------------
def test_expense_cannot_bind_foreign_budget_line(seed_auth):
    _, foreign = _line(tenant_id=2)
    prj = _project()
    r = Client().post("/api/v1/expenses", data=json.dumps({
        "project_id": prj.id, "legal_entity_id": 1, "amount": "100.00",
        "expense_type": "MATERIAL", "budget_line_id": foreign.id,
    }), content_type="application/json", **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    assert _json(r)["code"] == 40401
    foreign.refresh_from_db()
    assert foreign.amount_frozen == Decimal("0.00"), "他租户预算行不得被引用"


# --- C2 外拨链 ---------------------------------------------------------------
def test_outward_cannot_bind_foreign_budget_line(seed_auth):
    _, foreign = _line(tenant_id=2)
    r = Client().post("/api/v1/outwards", data=json.dumps({
        "project_id": 11, "to_unit": "某协作单位", "amount": "50.00",
        "budget_line_id": foreign.id,
    }), content_type="application/json", **bearer(1, FIN, tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    foreign.refresh_from_db()
    assert foreign.amount_used == Decimal("0.00")


# --- C3 借款链 ---------------------------------------------------------------
def test_loan_cannot_bind_foreign_budget_line(seed_auth):
    _, foreign = _line(tenant_id=2)
    prj = _project(code="PRJ-E7L")
    r = Client().post("/api/v1/loans", data=json.dumps({
        "project_id": prj.id, "amount": "400.00", "reason": "差旅借款",
        "budget_line_id": foreign.id,
    }), content_type="application/json", **bearer(1, ["R-MANAGER"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    foreign.refresh_from_db()
    assert foreign.amount_frozen == Decimal("0.00")


# --- C4 公示异议：不得终止他租户交易 ---------------------------------------
def _publicity(tenant_id: int = 2):
    d = TDisclosure.objects.create(
        tenant_id=tenant_id, creator_id=1, output_id=1, disclosed_by=1,
        disclosure_date=date(2026, 1, 1), status="SUBMITTED",
    )
    deal = TDeal.objects.create(
        tenant_id=tenant_id, creator_id=1, disclosure=d, output_id=1,
        deal_type="转让", partner_name="他租户公司", status="PUBLICIZED",
    )
    now = dj_tz.now()
    p = TPublicity.objects.create(
        tenant_id=tenant_id, creator_id=1, deal=deal,
        publish_start_at=now - timedelta(days=1), publish_end_at=now + timedelta(days=10),
        duration_days=11, url=f"/public/transform/deal/{deal.id}", summary_json={},
        public_snapshot_hash="x", status="PUBLISHED",
    )
    p.objections = [{
        "objection_id": "OBJ1-1", "submitter": "匿名", "content": "侵权",
        "submitted_at": now.isoformat(), "handle_status": "OPEN",
        "handle_result": None, "handled_at": None,
    }]
    p.save()
    return deal, p


def test_objection_handle_rejects_foreign_publicity(seed_auth):
    deal, p = _publicity(tenant_id=2)
    r = Client().post(f"/api/v1/publicity/{deal.id}/objection/handle", data=json.dumps({
        "objection_id": "OBJ1-1", "handle_status": "SUSTAINED",
    }), content_type="application/json", **bearer(1, T_ROLES, tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    deal.refresh_from_db()
    assert deal.status == "PUBLICIZED", "他租户交易不得被终止"
    p.refresh_from_db()
    assert p.status == "PUBLISHED"


# --- I1 企业库引用 -----------------------------------------------------------
def test_deal_rejects_foreign_enterpartner(seed_auth):
    ep = TEnterpartner.objects.create(
        tenant_id=2, creator_id=1, company_name="他租户企业", credit_code="91330000XXXXXX001",
        check_abnormal=1, last_checked_at=dj_tz.now(),
    )
    d = TDisclosure.objects.create(
        tenant_id=1, creator_id=1, output_id=1, disclosed_by=1,
        disclosure_date=date(2026, 1, 1), status="SUBMITTED",
    )
    r = Client().post("/api/v1/deal", data=json.dumps({
        "disclosure_id": d.id, "deal_type": "转让", "payment_method": "一次性",
        "contract_amount": "1000.00", "partner_name": "本租户公司",
        "enterpartner_id": ep.id,
    }), content_type="application/json", **bearer(1, T_ROLES, tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    assert not TDeal.objects.filter(disclosure=d).exists()


# --- I2 审计链归属恒取令牌租户 ----------------------------------------------
def test_sec_log_ignores_body_tenant(seed_auth):
    before_other = XSecLog.objects.filter(tenant_id=2).count()
    r = Client().post("/api/v1/security/log", data=json.dumps({
        "tenantId": 2, "actorId": 1, "networkZone": "OFFICE", "action": "READ",
        "objectType": "ASSET", "objectId": 1, "result": "SUCCESS",
    }), content_type="application/json", **bearer(1, ["R-ADMIN"], tenant_id=1))
    assert r.status_code == 200, r.content.decode()
    assert XSecLog.objects.filter(tenant_id=2).count() == before_other, "不得写入他租户审计链"
    assert XSecLog.objects.filter(tenant_id=1).count() >= 1


# --- I3 科目删除不再泄露他租户数据形态 -------------------------------------
def test_delete_subject_foreign_id_is_opaque_404(seed_auth):
    parent = FSubject.objects.create(
        tenant_id=2, creator_id=1, code="S-2-1", name="他租户父科目", status="ACTIVE",
    )
    FSubject.objects.create(
        tenant_id=2, creator_id=1, code="S-2-2", name="他租户子科目", status="ACTIVE",
        parent_id=parent.id,
    )
    r = Client().delete(f"/api/v1/subjects/{parent.id}", **bearer(1, ["R-MANAGER"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    parent.refresh_from_db()
    assert parent.deleted == 0


# --- R2-I1 存量脏单：引用他租户预算行的单据不得静默推进 ----------------------
def test_legacy_expense_with_foreign_line_is_blocked_on_approve(seed_auth):
    """E-7 收口前建的报销单可能已绑他租户预算行；审批放款必须被阻断并回滚。"""
    from apps.funding.models import FExpense, FExpenseApproval

    _, foreign = _line(tenant_id=2)
    e = FExpense.objects.create(
        tenant_id=1, creator_id=1, project_id=11, legal_entity_id=1,
        applicant_user_id=1, amount=Decimal("500.00"), expense_type="MATERIAL",
        submit_mode="预算制", budget_line_id=foreign.id, status="SUBMITTED",
    )
    FExpenseApproval.objects.create(
        tenant_id=1, creator_id=1, expense_id=e.id, step_order=1,
        role="R-MANAGER", status="PENDING",
    )
    before_frozen = foreign.amount_frozen
    r = Client().post(f"/api/v1/expenses/{e.id}/approval", data=json.dumps({
        "action": "APPROVE", "comment": "终审通过",
    }), content_type="application/json", **bearer(1, ["R-MANAGER"], tenant_id=1))
    assert r.status_code == 409, r.content.decode()
    assert _json(r)["code"] == 40901
    e.refresh_from_db()
    foreign.refresh_from_db()
    assert e.status == "SUBMITTED", "阻断后单据不得推进"
    assert foreign.amount_frozen == before_frozen, "他租户预算行不得被扣减"
    assert foreign.amount_used == Decimal("0.00")


def test_legacy_loan_with_foreign_line_is_blocked_on_pay(seed_auth):
    """漏洞窗口期建的借款单放款时同样必须阻断（不得静默 no-op）。"""
    from apps.funding.models import FLoan

    _, foreign = _line(tenant_id=2)
    loan = FLoan.objects.create(
        tenant_id=1, creator_id=1, project_id=11, legal_entity_id=1,
        applicant_user_id=1, amount=Decimal("400.00"), budget_line_id=foreign.id,
        status="APPROVED",
    )
    r = Client().post(f"/api/v1/loans/{loan.id}/pay", data=json.dumps({}),
                      content_type="application/json",
                      **bearer(1, ["R-FINANCE"], tenant_id=1))
    assert r.status_code == 409, r.content.decode()
    loan.refresh_from_db()
    foreign.refresh_from_db()
    assert loan.status == "APPROVED", "阻断后借款单不得置 PAID"
    assert loan.paid_at is None
    assert foreign.amount_used == Decimal("0.00")


# --- R2-I2 公开公示：PII 脱敏 + 异议状态守卫 --------------------------------
def _public_case(status: str = "PUBLISHED", contact: str = "13800000000"):
    d = TDisclosure.objects.create(
        tenant_id=1, creator_id=1, output_id=1, disclosed_by=1,
        disclosure_date=date(2026, 1, 1), status="SUBMITTED",
    )
    deal = TDeal.objects.create(
        tenant_id=1, creator_id=1, disclosure=d, output_id=1,
        deal_type="转让", partner_name="某公司", contract_amount=Decimal("1000.00"),
        payment_method="一次性", status="PUBLICIZED",
    )
    p = TPublicity.objects.create(
        tenant_id=1, creator_id=1, deal_id=deal.id, status=status,
        publish_start_at=dj_tz.now() - timedelta(days=1),
        publish_end_at=dj_tz.now() + timedelta(days=15), duration_days=15,
        objection_open=True,
        objections=[{
            "objection_id": "OBJ1", "submitter": "张三丰", "contact": contact,
            "content": "权属存在争议", "submitted_at": dj_tz.now().isoformat(),
            "handle_status": "PROCESSING", "handled_at": None,
            # 管理员自由文本里可能含 PII，公开通道必须不返回（R3-I2）
            "handle_result": "已联系张三丰 13800000000 补交权属材料",
        }],
    )
    return deal, p


def test_public_publicity_masks_objector_pii(db):
    """匿名公示页不得回传异议人手机号/全名（R2-I2）。"""
    _, p = _public_case()
    r = Client().get(f"/api/v1/publicity/{p.deal_id}")
    assert r.status_code == 200, r.content.decode()
    raw = r.content.decode()
    assert "13800000000" not in raw, "手机号必须脱敏"
    assert "张三丰" not in raw, "全名必须脱敏"
    obj = _json(r)["data"]["objections"][0]
    assert obj["contact"] == "138****0000"
    assert obj["submitter"] == "张**"


def test_public_objection_rejected_on_closed_publicity(db):
    """公示已结束（COMPLETED）时不得再被匿名异议翻开（R2-I2）。"""
    _, p = _public_case(status="COMPLETED")
    r = Client().post(f"/api/v1/publicity/{p.deal_id}/objection", data=json.dumps({
        "content": "再提一次", "submitter": "李四", "contact": "13900000000",
    }), content_type="application/json")
    assert r.status_code == 409, r.content.decode()
    p.refresh_from_db()
    assert p.status == "COMPLETED"
    assert len(p.objections or []) == 1, "不得追加异议"


# --- M3 间接费试算 GET 也要能被业务角色调用 ---------------------------------
def test_indirect_fee_calculate_get_allowed_for_finance(seed_auth):
    prj = _project(tenant_id=1, code="PRJ-E7-IF")
    r = Client().get(
        f"/api/v1/indirect-fees/calculate?project_id={prj.id}",
        **bearer(1, ["R-FINANCE"], tenant_id=1),
    )
    assert r.status_code != 403, r.content.decode()
    r2 = Client().get(
        f"/api/v1/indirect-fees/calculate?project_id={prj.id}",
        **bearer(1, ["R-MANAGER"], tenant_id=1),
    )
    assert r2.status_code != 403, r2.content.decode()


# --- M5 脏单在提交时点同样按租户阻断 ---------------------------------------
def test_legacy_expense_with_foreign_line_cannot_be_submitted(seed_auth):
    """M5：脏单（submit 前直接落库）提交时也按租户阻断，不留悬空冻结。"""
    from apps.funding.models import FExpense

    _, foreign = _line(tenant_id=2)
    prj = _project(code="PRJ-E7-DIRTY")
    e = FExpense.objects.create(
        tenant_id=1, creator_id=1, project_id=prj.id, legal_entity_id=1,
        applicant_user_id=1, amount=Decimal("120.00"), submit_mode="预算制",
        expense_type="MATERIAL", status="DRAFT", budget_line_id=foreign.id,
    )
    r = Client().post(f"/api/v1/expenses/{e.id}/submit",
                      **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    foreign.refresh_from_db()
    assert foreign.amount_frozen == Decimal("0.00")


# --- R2-B body 引用未校验：创建接口一律按租户校验引用 ------------------------
def test_create_expense_rejects_foreign_project(seed_auth):
    prj = _project(tenant_id=2, code="PRJ-E7-FP")
    r = Client().post("/api/v1/expenses", data=json.dumps({
        "project_id": prj.id, "legal_entity_id": 1, "amount": "100.00",
        "expense_type": "MATERIAL",
    }), content_type="application/json", **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    assert _json(r)["code"] == 40401


def test_create_outward_rejects_foreign_project(seed_auth):
    prj = _project(tenant_id=2, code="PRJ-E7-FO")
    r = Client().post("/api/v1/outwards", data=json.dumps({
        "project_id": prj.id, "to_unit": "外协单位", "amount": "500.00",
    }), content_type="application/json", **bearer(1, ["R-MANAGER"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    assert _json(r)["code"] == 40401


def test_create_loan_rejects_foreign_project(seed_auth):
    prj = _project(tenant_id=2, code="PRJ-E7-FL")
    r = Client().post("/api/v1/loans", data=json.dumps({
        "project_id": prj.id, "amount": "800.00", "reason": "差旅借款",
    }), content_type="application/json", **bearer(1, ["R-MANAGER"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    assert _json(r)["code"] == 40401


def test_create_disclosure_rejects_foreign_output(seed_auth):
    from apps.output.models import ROutput

    out = ROutput.objects.create(tenant_id=2, creator_id=1, status="CLAIMED",
                                 title="他租户成果")
    r = Client().post("/api/v1/disclosure", data=json.dumps({
        "output_id": out.id, "disclosure_date": "2026-03-01",
    }), content_type="application/json", **bearer(1, T_ROLES, tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    assert _json(r)["code"] == 40401
    assert not TDisclosure.objects.filter(output_id=out.id).exists()


# --- R3-D 存量跨租户裸查（ethics / project / output）------------------------
def test_ethics_case_is_tenant_scoped(seed_auth):
    from apps.ethics.models import CEthicsCase

    case = CEthicsCase.objects.create(
        tenant_id=2, creator_id=1, code="ETH-2026-000099",
        protocol_title="他租户伦理案卷", applicant_user_id=1,
        review_type="HUMAN", status="DRAFT",
    )
    r = Client().get(f"/api/v1/ethics/{case.id}",
                     **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()

    r2 = Client().post(f"/api/v1/ethics/{case.id}/submit",
                       **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r2.status_code == 404, "他租户案卷不得被提交"
    case.refresh_from_db()
    assert case.status == "DRAFT"


def test_project_task_update_is_tenant_scoped(seed_auth):
    from apps.project.models import ETask

    prj = _project(tenant_id=2, code="PRJ-E7-T2")
    task = ETask.objects.create(
        tenant_id=2, creator_id=1, project_id=prj.id, name="他租户任务",
        status="TODO", progress_percent=0,
    )
    r = Client().put(f"/api/v1/project/{prj.id}/tasks/{task.id}", data=json.dumps({
        "status": "DONE", "progress_percent": 100,
    }), content_type="application/json", **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()
    task.refresh_from_db()
    assert task.status != "DONE", "他租户任务不得被改写"


def test_output_claim_rejects_foreign_output(seed_auth):
    from apps.output.models import ROutput

    o = ROutput.objects.create(tenant_id=2, creator_id=1, title="他租户成果",
                               status="PENDING_CLAIM", claim_status="UNCLAIMED")
    r = Client().post("/api/v1/output/claim", data=json.dumps({
        "items": [{"output_id": o.id}],
    }), content_type="application/json", **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r.status_code == 200, r.content.decode()
    assert _json(r)["data"]["results"][0]["success"] is False, "他租户成果不得被认领"
    o.refresh_from_db()
    assert o.claim_status == "UNCLAIMED"


# --- R3-I1 软删的他租户对象同样拒绝 -----------------------------------------
def test_create_expense_rejects_soft_deleted_foreign_project(seed_auth):
    prj = _project(tenant_id=2, code="PRJ-E7-SD")
    prj.deleted = 1
    prj.save(update_fields=["deleted"])
    r = Client().post("/api/v1/expenses", data=json.dumps({
        "project_id": prj.id, "legal_entity_id": 1, "amount": "88.00",
        "expense_type": "MATERIAL",
    }), content_type="application/json", **bearer(1, ["R-STAFF"], tenant_id=1))
    assert r.status_code == 404, r.content.decode()


# --- R3-I2 公开通道不返回管理员自由文本 handle_result ------------------------
def test_public_publicity_hides_handle_result(db):
    _, p = _public_case()
    r = Client().get(f"/api/v1/publicity/{p.deal_id}")
    assert r.status_code == 200
    body = r.content.decode()
    assert "张三丰" not in body and "13800000000" not in body
    assert _json(r)["data"]["objections"][0]["handle_result"] is None
