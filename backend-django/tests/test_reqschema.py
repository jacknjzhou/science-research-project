"""core.reqschema.validate_body 装饰器专项测试：统一信封 40001 / extra ignore / 必填缺失 / 嵌套 Schema。"""
import json

import pydantic

from django.test import Client

from tests.conftest import bearer


def _c():
    return Client()


def _json(r):
    return r.json()


def test_schema_missing_required_returns_40001(seed_auth):
    """缺必填字段 → 统一信封 40001（而非 500）。"""
    c = _c()
    r = c.post("/api/v1/integrity/pledge", data=json.dumps({
        "user_id": 2, "pledge_type": "APPLY", "content_version": "v1.2"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    body = _json(r)
    assert r.status_code == 400
    assert body["code"] == 40001
    assert "read_seconds" in body["message"]


def test_schema_wrong_type_returns_40001(seed_auth):
    """类型非法 → 40001。"""
    c = _c()
    r = c.post("/api/v1/integrity/pledge", data=json.dumps({
        "user_id": 2, "pledge_type": "APPLY", "content_version": "v1.2",
        "read_seconds": "not-a-number"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40001


def test_schema_extra_fields_ignored(seed_auth):
    """未声明字段被忽略（extra=ignore），合法请求照常通过。"""
    c = _c()
    r = c.post("/api/v1/integrity/pledge", data=json.dumps({
        "user_id": 2, "pledge_type": "APPLY", "content_version": "v1.2",
        "read_seconds": 30, "unknown_future_field": {"x": 1}}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    body = _json(r)
    assert body["code"] == 0
    assert body["data"]["read_seconds"] == 30


def test_schema_nested_items():
    """嵌套 Schema（list[VoucherItemIn]）元素缺必填 → ValidationError 指到具体字段。"""
    from apps.asset.schemas import VoucherCallbackIn

    try:
        VoucherCallbackIn(period="2026-10", items=[{"depreciationId": 1}])
        raised = False
    except pydantic.ValidationError as e:
        raised = True
        loc = e.errors()[0]["loc"]
        assert loc == ("items", 0, "voucherId")
    assert raised


def test_schema_nested_items_ok():
    """嵌套 Schema 合法元素通过。"""
    from apps.asset.schemas import VoucherCallbackIn

    s = VoucherCallbackIn(period="2026-10", items=[
        {"depreciationId": 1, "voucherId": 9, "posted": True}])
    assert s.items[0].voucherId == 9
