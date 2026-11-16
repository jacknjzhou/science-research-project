"""M1-a：差旅标准/开票/借款（A1-A3）"""
import json
from datetime import timedelta

from django.test import Client
from django.utils import timezone as dj_tz

from apps.funding.models import FTravelStandard
from tests.conftest import bearer


def _c():
    return Client()


def _standard(**kw):
    base = dict(
        tenant_id=1,
        name="住宿标准",
        staff_category="普通员工",
        city_tier="一线城市",
        accommodation_cap=300,
        meals_cap=100,
        transport_cap=80,
        effective_from=dj_tz.localdate() - timedelta(days=30),
        effective_to=None,
        status="ACTIVE",
        creator_id=1,
    )
    base.update(kw)
    return FTravelStandard.objects.create(**base)


_CREATE_BODY = {
    "name": "住宿标准",
    "staffCategory": "普通员工",
    "cityTier": "一线城市",
    "accommodationCap": "300",
    "mealsCap": "100.5",
    "transportCap": "80",
    "effectiveFrom": "2026-01-01",
}


# ---------------------------------------------------------------------------
# 差旅费用标准（A3）
# ---------------------------------------------------------------------------
def test_travel_standard_create(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    w = r.json()["data"]
    assert w["id"] > 0
    assert w["name"] == "住宿标准"
    assert w["staffCategory"] == "普通员工" and w["cityTier"] == "一线城市"
    # 金额一律 num2 字符串
    assert w["accommodationCap"] == "300.00"
    assert w["mealsCap"] == "100.50"
    assert w["transportCap"] == "80.00"
    assert w["effectiveFrom"] == "2026-01-01"
    assert w["effectiveTo"] is None
    assert w["status"] == "ACTIVE"


def test_travel_standard_create_conflict_40901(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    wid = r.json()["data"]["id"]
    # 同 (staffCategory, cityTier) 再建 ACTIVE → 40901
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # 原记录置 DISABLED 后，同组合允许再建 ACTIVE
    r = c.put(
        f"/api/v1/travel-standards/{wid}",
        data=json.dumps({"status": "DISABLED"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.json()["data"]["status"] == "DISABLED"
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200


def test_travel_standard_update_conflict_40901(seed_auth):
    c = _c()
    a = _standard(staff_category="高管", city_tier="二线城市")
    b = _standard(staff_category="普通员工", city_tier="二线城市")
    # 把 b 改成与 a 相同的 ACTIVE 组合 → 40901
    r = c.put(
        f"/api/v1/travel-standards/{b.id}",
        data=json.dumps({"staffCategory": "高管"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # 自身不变更组合（排除自身）不冲突
    r = c.put(
        f"/api/v1/travel-standards/{a.id}",
        data=json.dumps({"name": "高管标准V2"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "高管标准V2"


def test_travel_standard_update_and_soft_delete(seed_auth):
    c = _c()
    row = _standard()
    r = c.put(
        f"/api/v1/travel-standards/{row.id}",
        data=json.dumps({"accommodationCap": "400", "name": "住宿标准V2"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["accommodationCap"] == "400.00" and d["name"] == "住宿标准V2"
    assert d["mealsCap"] == "100.00"  # 未传不覆盖
    # 软删：deleted=1，行仍在
    r = c.delete(f"/api/v1/travel-standards/{row.id}", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    assert FTravelStandard.objects.get(pk=row.id).deleted == 1
    # 列表不可见
    r = c.get("/api/v1/travel-standards", **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 0
    # 删后再 PUT/DELETE → 404
    r = c.put(
        f"/api/v1/travel-standards/{row.id}",
        data=json.dumps({"name": "x"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    r = c.delete(f"/api/v1/travel-standards/{row.id}", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 404


def test_travel_standard_list_filters(seed_auth):
    _standard(staff_category="普通员工", city_tier="一线城市")
    _standard(staff_category="高管", city_tier="二线城市")
    _standard(staff_category="普通员工", city_tier="二线城市", status="DISABLED")
    c = _c()
    r = c.get("/api/v1/travel-standards", **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 3
    r = c.get("/api/v1/travel-standards", data={"staffCategory": "普通员工"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 2
    r = c.get("/api/v1/travel-standards", data={"cityTier": "二线城市"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 2
    r = c.get("/api/v1/travel-standards", data={"status": "ACTIVE"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 2


def test_travel_standard_match(seed_auth):
    c = _c()
    today = dj_tz.localdate()
    row = _standard(
        staff_category="普通员工",
        city_tier="一线城市",
        effective_from=today - timedelta(days=30),
        effective_to=None,  # 长期有效
    )
    # 命中：date 缺省 → 今天
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "普通员工", "cityTier": "一线城市"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["id"] == row.id
    # 区间内指定日期 → 命中
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "普通员工", "cityTier": "一线城市", "date": str(today - timedelta(days=1))},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.json()["data"]["id"] == row.id
    # effective_to 边界：有效至今天 → 今天命中
    row2 = _standard(
        staff_category="高管",
        city_tier="一线城市",
        effective_from=today - timedelta(days=30),
        effective_to=today,
    )
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "高管", "cityTier": "一线城市"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.json()["data"]["id"] == row2.id
    # 过期（区间外）→ 40401
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "高管", "cityTier": "一线城市", "date": str(today + timedelta(days=1))},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # 无任何匹配记录 → 40401
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "外包", "cityTier": "三线城市"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # 缺必填参数 → 400
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "普通员工"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 400
