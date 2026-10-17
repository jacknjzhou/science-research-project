"""幂等中间件语义测试（移植 Go idempotency 语义）。"""
import json

from django.test import Client

from tests.conftest import bearer


def _post_dict(client, fakeredis_client, key: str, payload: dict):
    return client.post(
        "/api/v1/admin/dicts",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Idempotency-Key": key},
        **bearer(1, ["R-ADMIN"]),
    )


def _seed_dict(db):
    from apps.sysadmin.models import SysDict

    SysDict.objects.create(id=100, code="seed", name="种子", tenant_id=1, creator_id=1)


def test_missing_key_passes_through(db, fakeredis_client):
    """无 Idempotency-Key 的写请求直接放行，绝不触碰 Redis。"""
    c = Client()
    r = c.post(
        "/api/v1/admin/dicts",
        data=json.dumps({"code": "x1", "name": "X1"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert fakeredis_client.dbsize() == 0


def test_get_never_touches_redis(db, fakeredis_client):
    c = Client()
    c.get("/api/v1/page-grants", **bearer(1, ["R-ADMIN"]))
    assert fakeredis_client.dbsize() == 0


def test_idem_replay_same_body(db, fakeredis_client):
    """同键重放返回首次响应快照（恒 200）。"""
    c = Client()
    r1 = _post_dict(c, fakeredis_client, "K1", {"code": "x1", "name": "X1"})
    assert r1.status_code == 200
    r2 = _post_dict(c, fakeredis_client, "K1", {"code": "x2", "name": "X2"})
    assert r2.status_code == 200
    assert r2.json()["data"]["code"] == "x1"  # 回放首次结果
    assert fakeredis_client.dbsize() == 1  # 仅快照，锁已清


def test_idem_different_key_executes(db, fakeredis_client):
    c = Client()
    r1 = _post_dict(c, fakeredis_client, "K1", {"code": "x1", "name": "X1"})
    r2 = _post_dict(c, fakeredis_client, "K2", {"code": "x2", "name": "X2"})
    assert r1.json()["data"]["code"] == "x1"
    assert r2.json()["data"]["code"] == "x2"


def test_idem_lock_conflict(db, fakeredis_client):
    """SETNX 未命中（锁已存在但快照未落）→ 409/40909。"""
    c = Client()
    fakeredis_client.set("idem:POST:/api/v1/admin/dicts:KL:lock", "1")
    r = _post_dict(c, fakeredis_client, "KL", {"code": "xl", "name": "XL"})
    assert r.status_code == 409
    assert r.json()["code"] == 40909
    assert r.json()["message"] == "相同幂等键正在处理中"


def test_redis_unavailable_passes_through(db, monkeypatch):
    """Redis 不可用静默放行（对齐 Go nil 守卫）。"""
    from core import redis_util

    class Broken:
        def get(self, *a, **k):
            raise ConnectionError("down")

        def set(self, *a, **k):
            raise ConnectionError("down")

        def delete(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(redis_util, "get_client", lambda: Broken())
    c = Client()
    r = c.post(
        "/api/v1/admin/dicts",
        data=json.dumps({"code": "x9", "name": "X9"}),
        content_type="application/json",
        headers={"Idempotency-Key": "KX"},
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
