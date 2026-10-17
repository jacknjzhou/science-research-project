"""通知中心端点测试（移植 Go notify_test 语义）。"""
from django.test import Client

from tests.conftest import bearer


def test_list_and_filters(seed_notify):
    c = Client()
    r = c.get("/api/v1/notifications", **bearer(2, ["R-STAFF"]))
    body = r.json()["data"]
    assert body["total"] == 3
    # 最新在前
    assert body["list"][0]["title"] in ("待办A", "预警B", "已读C")

    r = c.get("/api/v1/notifications?unread=1", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["total"] == 2

    r = c.get("/api/v1/notifications?typ=WARNING", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["list"][0]["title"] == "预警B"


def test_unread_count_and_read_all(seed_notify):
    c = Client()
    r = c.get("/api/v1/notifications/unread-count", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["count"] == 2

    r = c.post("/api/v1/notifications/read-all", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["updated"] == 2
    r = c.get("/api/v1/notifications/unread-count", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["count"] == 0


def test_mark_read_single_and_404(seed_notify):
    c = Client()
    # 用户数据隔离：user_id=3 看不到 staff 的通知
    r = c.post("/api/v1/notifications/1/read", **bearer(3, ["R-STAFF"]))
    assert r.status_code == 404

    r = c.post("/api/v1/notifications/1/read", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    assert r.json()["data"]["read"] is True
    # 幂等：重复已读不报错
    r = c.post("/api/v1/notifications/1/read", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
