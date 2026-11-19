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
