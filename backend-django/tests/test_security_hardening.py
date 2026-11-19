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
