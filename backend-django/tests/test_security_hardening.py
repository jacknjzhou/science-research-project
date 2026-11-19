"""安全收口期次回归（E-1..E-5）——每条用例都必须在未修复源码上失败。

约定：
- 跨租户用例显式 `bearer(uid, roles, tenant_id=2)`，默认 bearer 的 tenant_id 是 1；
- 只断言「不该发生的事没发生」，不断言内部实现细节。
"""
from __future__ import annotations

import json

import pytest
from django.test import Client

from tests.conftest import bearer

pytestmark = pytest.mark.django_db


def _login(client: Client, username: str, password: str, tenant_id: int = 1):
    return client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {"username": username, "password": password, "tenant_id": tenant_id}
        ),
        content_type="application/json",
    )


# ---------------------------------------------------------------- E-3 登录后门


def test_dev_login_disabled_when_not_debug(settings, monkeypatch):
    """生产（DEBUG=False）即便设了 ARK_DEV_LOGIN=1 也不得开后门。"""
    from core.auth.api import _dev_login_enabled

    settings.DEBUG = False
    monkeypatch.setenv("ARK_DEV_LOGIN", "1")
    assert _dev_login_enabled() is False
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 401
    assert r.json()["code"] == 40102


def test_dev_login_disabled_without_env_flag(settings, monkeypatch):
    """DEBUG=True 但未显式开 ARK_DEV_LOGIN，同样不放行。"""
    from core.auth.api import _dev_login_enabled

    settings.DEBUG = True
    monkeypatch.delenv("ARK_DEV_LOGIN", raising=False)
    assert _dev_login_enabled() is False
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 401
    assert r.json()["code"] == 40102


def test_dev_login_enabled_issues_minimal_roles(settings, monkeypatch):
    """显式开关打开时，签发的角色域只含 R-STAFF（不再固定带 R-MANAGER）。"""
    from core.auth.api import _dev_login_enabled
    from core.auth.jwt_util import parse_token

    settings.DEBUG = True
    monkeypatch.setenv("ARK_DEV_LOGIN", "1")
    assert _dev_login_enabled() is True
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 200
    data = r.json()["data"]
    claims = parse_token(data["access_token"])
    roles = claims.get("roles") or []
    assert roles == ["R-STAFF"]
    assert "R-MANAGER" not in roles


# ---------------------------------------------------------------- E-1 N 域租户


def _expert(tenant_id: int, name: str, status: str = "ACTIVE"):
    from apps.expertreview.models import NExpert

    return NExpert.objects.create(
        tenant_id=tenant_id, creator_id=1, name=name, status=status,
        source="INTERNAL", field_tags=[],
    )


def _task(tenant_id: int, title: str, status: str = "DRAFT"):
    from apps.expertreview.models import NReviewTask

    return NReviewTask.objects.create(
        tenant_id=tenant_id, creator_id=1, biz_type="OTHER", title=title, status=status,
    )


def test_list_experts_is_tenant_scoped(seed_auth):
    mine = _expert(1, "本租户专家")
    other = _expert(2, "他租户专家")
    r = Client().get("/api/v1/experts", **bearer(seed_auth["admin"].id, ["R-ADMIN"]))
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["data"]["list"]]
    assert mine.id in ids
    assert other.id not in ids


def test_list_reviews_is_tenant_scoped(seed_auth):
    mine = _task(1, "本租户评审")
    other = _task(2, "他租户评审")
    r = Client().get("/api/v1/reviews", **bearer(seed_auth["admin"].id, ["R-ADMIN"]))
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["data"]["list"]]
    assert mine.id in ids
    assert other.id not in ids


def test_draw_experts_pool_is_tenant_scoped(seed_auth):
    """只有他租户有 ACTIVE 专家时，本租户任务抽签不得抽到人。"""
    from apps.expertreview.models import NReviewInvitation
    t = _task(1, "本租户抽签", status="DRAFT")
    _expert(2, "他租户唯一专家")
    r = Client().post(
        f"/api/v1/reviews/{t.id}/draw",
        data=json.dumps({"plan_count": 2}),
        content_type="application/json",
        **bearer(seed_auth["admin"].id, ["R-ADMIN"]),
    )
    if r.status_code == 200:
        assert NReviewInvitation.objects.filter(task_id=t.id).count() == 0
    else:
        assert r.status_code in (409, 422)


# ---------------------------------------------------------------- E-2 G 域租户


def _req_row(tenant_id: int, item: str = "他租户采购", status: str = "WAY_DECIDED"):
    from decimal import Decimal

    from apps.procure.models import GRequisition

    return GRequisition.objects.create(
        tenant_id=tenant_id, creator_id=1, project_id=5, applicant_id=1,
        category="设备", item_name=item, est_amount=Decimal("1000"),
        status=status,
    )


def _sup_row(tenant_id: int, name: str = "他租户供应商"):
    from apps.procure.models import GSupplier

    return GSupplier.objects.create(
        tenant_id=tenant_id, creator_id=1, name=name, status="IN_LIBRARY",
        qualification_expire_date="2030-12-31",
    )


def test_create_bid_rejects_foreign_requisition(seed_auth):
    r2 = _req_row(2)
    r = Client().post(
        "/api/v1/procurement/bids",
        data=json.dumps({"requisition_id": r2.id, "method": "询价"}),
        content_type="application/json",
        **bearer(seed_auth["admin"].id, ["R-MANAGER"]),
    )
    assert r.status_code == 404


def test_award_bid_rejects_foreign_bid(seed_auth):
    from apps.procure.models import GBid

    r2 = _req_row(2)
    s2 = _sup_row(2)
    b2 = GBid.objects.create(
        tenant_id=2, creator_id=1, requisition=r2, method="询价", status="PUBLICIZING",
    )
    r = Client().post(
        f"/api/v1/procurement/bids/{b2.id}/award",
        data=json.dumps({"winner_supplier_id": s2.id}),
        content_type="application/json",
        **bearer(seed_auth["admin"].id, ["R-MANAGER"]),
    )
    assert r.status_code == 404


def test_create_contract_rejects_foreign_supplier(seed_auth):
    s2 = _sup_row(2)
    r = Client().post(
        "/api/v1/contract",
        data=json.dumps({
            "contract_type": "采购", "party_b": "他租户供应商", "supplier_id": s2.id,
            "amount": "1000", "project_id": 5,
        }),
        content_type="application/json",
        **bearer(seed_auth["admin"].id, ["R-MANAGER"]),
    )
    assert r.status_code == 403
    assert r.json()["code"] == 40913


# ---------------------------------------------------------------- E-4 打分前置


def _bound_expert(tenant_id: int, user_id: int, name: str = "打分专家"):
    from apps.expertreview.models import NExpert

    return NExpert.objects.create(
        tenant_id=tenant_id, creator_id=1, name=name, status="ACTIVE",
        source="INTERNAL", user_id=user_id, field_tags=[],
    )


def _invite(task, expert, response: str = "PENDING"):
    from django.utils import timezone

    from apps.expertreview.models import NReviewInvitation

    return NReviewInvitation.objects.create(
        tenant_id=task.tenant_id, task_id=task.id, expert_id=expert.id,
        seat_no=1, response=response, invited_at=timezone.now(),
    )


def _score(client, task_id: int, uid: int, total: str = "88.00"):
    return client.post(
        f"/api/v1/reviews/{task_id}/scores",
        data=json.dumps({"total_score": total}),
        content_type="application/json",
        **bearer(uid, ["R-EXPERT"]),
    )


def test_score_requires_invitation(seed_auth):
    uid = seed_auth["staff"].id
    t = _task(1, "未受邀打分", status="IN_REVIEW")
    _bound_expert(1, uid)
    r = _score(Client(), t.id, uid)
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_score_rejects_pending_invitation(seed_auth):
    uid = seed_auth["staff"].id
    t = _task(1, "待响应邀请", status="IN_REVIEW")
    e = _bound_expert(1, uid)
    _invite(t, e, response="PENDING")
    r = _score(Client(), t.id, uid)
    assert r.status_code == 409
    assert r.json()["code"] == 40901


def test_score_rejects_concluded_task(seed_auth):
    uid = seed_auth["staff"].id
    t = _task(1, "已归档评审", status="CONCLUDED")
    e = _bound_expert(1, uid)
    _invite(t, e, response="ACCEPT")
    r = _score(Client(), t.id, uid)
    assert r.status_code == 409
    assert r.json()["code"] == 40901


def test_score_allowed_after_accept(seed_auth):
    uid = seed_auth["staff"].id
    t = _task(1, "正常打分", status="IN_REVIEW")
    e = _bound_expert(1, uid)
    _invite(t, e, response="ACCEPT")
    r = _score(Client(), t.id, uid)
    assert r.status_code == 200
    assert r.json()["data"]["total_score"] == "88.00"


# ---------------------------------------------------------------- E-5 已付额口径


def test_contract_list_paid_sum_uses_paid_amount(seed_auth):
    from datetime import date, timedelta
    from decimal import Decimal

    from apps.procure.models import GContract, GContractPayment

    sup = _sup_row(1, "本租户供应商")
    c = GContract.objects.create(
        tenant_id=1, creator_id=1, supplier=sup, contract_type="采购",
        party_a="本单位", party_b=sup.name, amount=Decimal("98000"),
        sign_date=date.today(), start_date=date.today(),
        end_date=date.today() + timedelta(days=90), status="ACTIVE",
    )
    GContractPayment.objects.create(
        tenant_id=1, creator_id=1, contract=c, phase="预付",
        plan_amount=Decimal("40000"), paid_amount=Decimal("40000"), status="PAID",
    )
    GContractPayment.objects.create(
        tenant_id=1, creator_id=1, contract=c, phase="验收",
        plan_amount=Decimal("58000"), paid_amount=Decimal("0"), status="PLANNED",
    )
    r = Client().get("/api/v1/contract", **bearer(seed_auth["admin"].id, ["R-MANAGER"]))
    assert r.status_code == 200
    row = next(x for x in r.json()["data"]["list"] if x["id"] == c.id)
    # 管理端列表 paid_sum 既有形态是 float（_api_contract: float(paid_sum)），
    # 本任务只修口径（paid_amount 而非 plan_amount），不改响应类型（契约债另记）。
    assert Decimal(str(row["paid_sum"])) == Decimal("40000")


# ---------------------------------------------------------------- 终审 r1：C-1/C-2 余量


def test_payment_callback_rejects_foreign_payment(seed_auth):
    """C-1：他租户付款单不得被本租户回调实扣（含预算冻结→实扣）。"""
    from datetime import date, timedelta
    from decimal import Decimal

    from apps.procure.models import GContract, GContractPayment

    sup2 = _sup_row(2, "他租户供应商")
    c2 = GContract.objects.create(
        tenant_id=2, creator_id=1, supplier=sup2, contract_type="采购",
        party_a="他单位", party_b=sup2.name, amount=Decimal("98000"),
        sign_date=date.today(), start_date=date.today(),
        end_date=date.today() + timedelta(days=90), status="ACTIVE",
    )
    p2 = GContractPayment.objects.create(
        tenant_id=2, creator_id=1, contract=c2, phase="预付",
        plan_amount=Decimal("40000"), paid_amount=Decimal("0"), status="PLANNED",
    )
    r = Client().post(
        "/api/v1/finance/expense",
        data=json.dumps({"payment_id": p2.id, "expense_id": 9001,
                         "paid_amount": "40000"}),
        content_type="application/json",
        **bearer(seed_auth["admin"].id, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    p2.refresh_from_db()
    assert p2.status == "PLANNED" and p2.paid_amount == Decimal("0")


def test_create_contract_rejects_foreign_requisition(seed_auth):
    """C-2：合同不得挂到他租户的采购申请上（否则 trace 会带出他人采购链）。"""
    req2 = _req_row(2, "他租户采购申请")
    r = Client().post(
        "/api/v1/contract",
        data=json.dumps({
            "contract_type": "采购", "party_b": "某相对方", "amount": "1000",
            "project_id": 5, "requisition_id": req2.id,
        }),
        content_type="application/json",
        **bearer(seed_auth["admin"].id, ["R-MANAGER"]),
    )
    assert r.status_code == 404


def test_asset_convert_rejects_foreign_order(seed_auth):
    """E-2 同族：资产转固不得引用他租户订单。"""
    from decimal import Decimal

    from apps.procure.models import GOrder

    sup2 = _sup_row(2, "他租户供应商")
    req2 = _req_row(2, "他租户订单来源")
    o2 = GOrder.objects.create(
        tenant_id=2, creator_id=1, requisition=req2, supplier=sup2,
        order_amount=Decimal("1000"), delivery_status="ACCEPTED",
    )
    r = Client().post(
        "/api/v1/asset/from-order",
        data=json.dumps({"orderId": o2.id, "category": "设备", "name": "服务器"}),
        content_type="application/json",
        **bearer(seed_auth["admin"].id, ["R-STAFF"]),
    )
    assert r.status_code == 404
