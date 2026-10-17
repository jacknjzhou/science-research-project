"""信封/TraceID/错误码语义测试（移植 Go envelope_test.go / trace 语义）。"""
import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_envelope():
    c = Client()
    r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["ok"] is True
    assert isinstance(body["timestamp"], int)
    assert body["traceId"]
    assert r["X-Trace-Id"] == body["traceId"]


@pytest.mark.django_db
def test_trace_id_passthrough():
    c = Client()
    r = c.get("/healthz", headers={"X-Trace-Id": "tr-fixed-123"})
    assert r["X-Trace-Id"] == "tr-fixed-123"
    assert r.json()["traceId"] == "tr-fixed-123"


@pytest.mark.django_db
def test_trace_id_generated():
    c = Client()
    r1 = c.get("/healthz")
    r2 = c.get("/healthz")
    t1, t2 = r1.json()["traceId"], r2.json()["traceId"]
    assert t1.startswith("py-") and t2.startswith("py-")
    assert t1 != t2


@pytest.mark.django_db
def test_error_envelope_shape():
    """未认证请求 → 401 信封（code=40101），信封结构不变。"""
    c = Client()
    r = c.get("/api/v1/auth/me")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == 40101
    assert body["message"] == "未认证"
    assert body["data"] is None
    assert body["traceId"]


@pytest.mark.django_db
def test_trace_error_prefix_format():
    c = Client()
    r = c.get("/healthz")
    tid = r.json()["traceId"]
    assert len(tid) == len("py-") + 16
    int(tid[3:], 16)  # 必须是合法 hex
