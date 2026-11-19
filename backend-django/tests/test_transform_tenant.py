"""E-7 transform 域：披露/交易/合同/到账按租户收口（跨租户一律 404）。"""
import json
from datetime import date
from decimal import Decimal

from django.test import Client

from apps.transform.models import TContract, TDeal, TDisclosure, TIncome
from tests.conftest import bearer

T_ROLES = ["R-MANAGER", "R-LEADER"]


def _mk_chain(tenant_id: int = 1):
    d = TDisclosure.objects.create(
        tenant_id=tenant_id, creator_id=1, output_id=1, disclosed_by=1,
        disclosure_date=date(2026, 1, 1), status="DRAFT",
    )
    deal = TDeal.objects.create(
        tenant_id=tenant_id, creator_id=1, disclosure=d, output_id=1,
        deal_type="转让", partner_name="某公司", status="DRAFT",
    )
    ct = TContract.objects.create(
        tenant_id=tenant_id, creator_id=1, deal=deal, status="DRAFT",
    )
    inc = TIncome.objects.create(
        tenant_id=tenant_id, creator_id=1, deal=deal, status="PENDING",
        amount=Decimal("5000.00"), received_date=date(2026, 2, 1),
    )
    return d, deal, ct, inc


def test_cross_tenant_disclosure_detail_and_submit_are_404(seed_auth):
    d, _, _, _ = _mk_chain()
    # 注意：/disclosure/{id} 无详情路由（契约与 config/api.py 都只有列表/submit/valuation），
    # 因此这里只断言 submit —— 用 GET 详情断言 404 会是 stub 造成的假绿。
    r = Client().post(f"/api/v1/disclosure/{d.id}/submit", **bearer(1, T_ROLES, tenant_id=2))
    assert r.status_code == 404, r.content.decode()
    d.refresh_from_db()
    assert d.status == "DRAFT", "他租户不得提交本租户披露"


def test_cross_tenant_deal_detail_is_404(seed_auth):
    _, deal, _, _ = _mk_chain()
    r = Client().get(f"/api/v1/deal/{deal.id}", **bearer(1, T_ROLES, tenant_id=2))
    assert r.status_code == 404


def test_cross_tenant_deal_action_is_404(seed_auth):
    _, deal, _, _ = _mk_chain()
    r = Client().post(f"/api/v1/deal/{deal.id}/publish", **bearer(1, T_ROLES, tenant_id=2))
    assert r.status_code == 404, r.content.decode()
    deal.refresh_from_db()
    assert deal.status == "DRAFT", "他租户不得变更本租户交易状态"


def test_cross_tenant_contract_detail_is_404(seed_auth):
    _, _, ct, _ = _mk_chain()
    r = Client().get(f"/api/v1/contract/{ct.id}", **bearer(1, T_ROLES, tenant_id=2))
    assert r.status_code == 404


def test_cross_tenant_income_match_is_404(seed_auth):
    _, _, _, inc = _mk_chain()
    r = Client().post(f"/api/v1/income/{inc.id}/match",
                      data=json.dumps({"deal_id": 1}), content_type="application/json",
                      **bearer(1, T_ROLES, tenant_id=2))
    assert r.status_code == 404, r.content.decode()
    inc.refresh_from_db()
    assert inc.status == "PENDING", "他租户不得确认本租户到账"
