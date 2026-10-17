"""申报域 P 测试：指南发布语义 + 申报书创建 + 撤回/终止状态机。"""
import json

from django.test import Client

from apps.p.models import PApplication, PGuideline
from tests.conftest import bearer


def _c():
    return Client()


# ---------------------------------------------------------------------------
# 申报指南
# ---------------------------------------------------------------------------
def test_guideline_publish_sets_publish_at_once(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/apply/guidelines",
        data=json.dumps({"code": "GUIDE-2026", "title": "2026 指南", "project_type": "HORIZONTAL",
                         "status": "PUBLISHED", "total_envelope": "100.50"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    g = r.json()["data"]
    assert g["status"] == "PUBLISHED"
    assert g["publish_at"]  # 首次 PUBLISHED 记 publish_at
    assert g["total_envelope"] == "100.50"  # 2 位小数字符串
    first_at = g["publish_at"]

    r = c.put_like = c.get(f"/api/v1/apply/guidelines/{g['id']}", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"]["publish_at"] == first_at

    # 再次 upsert 仍 PUBLISHED：publish_at 不变
    r = c.post(
        "/api/v1/apply/guidelines",
        data=json.dumps({"id": g["id"], "code": "GUIDE-2026", "title": "2026 指南V2",
                         "project_type": "HORIZONTAL", "status": "PUBLISHED"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["publish_at"] == first_at


def test_guideline_invalid_status_400(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/apply/guidelines",
        data=json.dumps({"code": "G1", "title": "x", "project_type": "T", "status": "BOGUS"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 400
    assert r.json()["code"] == 40002


# ---------------------------------------------------------------------------
# 申报书
# ---------------------------------------------------------------------------
def test_create_application_draft_and_budget_round(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/apply/applications",
        data=json.dumps({"title": "AI 药物筛选", "project_type": "NATURAL",
                         "pi_user_id": 2, "total_budget": 99.987}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    a = r.json()["data"]
    assert a["status"] == "DRAFT"
    assert a["total_budget"] == "99.99"  # 四舍五入 2 位

    r = c.get("/api/v1/apply/applications", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["total"] >= 1


def test_create_application_bad_budget_400(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/apply/applications",
        data=json.dumps({"title": "x", "project_type": "T", "pi_user_id": 2,
                         "total_budget": "abc"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 400
    assert r.json()["code"] == 40002


# ---------------------------------------------------------------------------
# 撤回/终止（契约超前 Go，Django 补齐）
# ---------------------------------------------------------------------------
def test_withdraw_before_review(seed_auth):
    c = _c()
    a = PApplication.objects.create(
        tenant_id=1, status="SUBMITTED", creator_id=2, title="待撤回",
        project_type="NATURAL", pi_user_id=2,
    )
    r = c.post(
        f"/api/v1/apply/applications/{a.id}:withdraw",
        data=json.dumps({"reason": "材料需重写"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["status"] == "WITHDRAWN"
    assert body["withdraw_reason"] == "材料需重写"
    assert body["withdraw_at"]


def test_withdraw_after_review_409(seed_auth):
    c = _c()
    a = PApplication.objects.create(
        tenant_id=1, status="UNDER_REVIEW", creator_id=2, title="在评",
        project_type="NATURAL", pi_user_id=2,
    )
    r = c.post(
        f"/api/v1/apply/applications/{a.id}:withdraw",
        data=json.dumps({"reason": "撤回"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901


def test_terminate_after_review_maps_rejected(seed_auth):
    c = _c()
    a = PApplication.objects.create(
        tenant_id=1, status="INTERVIEWING", creator_id=2, title="面评中",
        project_type="NATURAL", pi_user_id=2,
    )
    r = c.post(
        f"/api/v1/apply/applications/{a.id}:terminate",
        data=json.dumps({"reason": "PI 离职"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "REJECTED"
    a.refresh_from_db()
    assert a.withdraw_reason == "PI 离职"


def test_terminate_before_review_409(seed_auth):
    c = _c()
    a = PApplication.objects.create(
        tenant_id=1, status="DRAFT", creator_id=2, title="草稿",
        project_type="NATURAL", pi_user_id=2,
    )
    r = c.post(
        f"/api/v1/apply/applications/{a.id}:terminate",
        data=json.dumps({"reason": "x"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 409


def test_withdraw_reason_required_400(seed_auth):
    c = _c()
    a = PApplication.objects.create(
        tenant_id=1, status="SUBMITTED", creator_id=2, title="x",
        project_type="NATURAL", pi_user_id=2,
    )
    r = c.post(
        f"/api/v1/apply/applications/{a.id}:withdraw",
        data=json.dumps({}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 400
