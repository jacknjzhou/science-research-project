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


# ---------------------------------------------------------------------------
# M1-d B5：指南征集发布/关闭动作 + 专家论证评审入库推送
# ---------------------------------------------------------------------------
def _guideline(**kw):
    base = dict(code="GUIDE-M1D-1", tenant_id=1, creator_id=1, title="M1-d 指南",
                project_type="VERTICAL", status="DRAFT")
    base.update(kw)
    return PGuideline.objects.create(**base)


def test_m1d_guideline_publish_action_notifies_staff(seed_auth):
    """发布动作：DRAFT→PUBLISHED + publish_at + 推送 R-STAFF；重复发布幂等。"""
    from apps.notify.models import SysNotification

    g = _guideline()
    c = _c()
    r = c.post(f"/api/v1/apply/guidelines/{g.id}:publish", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "PUBLISHED"
    g.refresh_from_db()
    assert g.publish_at is not None
    assert SysNotification.objects.filter(tenant_id=1, user_id=2).exists()  # staff 用户 2

    # 重复发布：幂等 200，publish_at 不变
    at = g.publish_at
    r = c.post(f"/api/v1/apply/guidelines/{g.id}:publish", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    g.refresh_from_db()
    assert g.publish_at == at


def test_m1d_guideline_close_action(seed_auth):
    """关闭：仅 PUBLISHED 可关；DRAFT 直接关 40901。"""
    g = _guideline(status="PUBLISHED")
    draft = _guideline(code="GUIDE-M1D-2", status="DRAFT")
    c = _c()
    r = c.post(f"/api/v1/apply/guidelines/{g.id}:close", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "CLOSED"

    r = c.post(f"/api/v1/apply/guidelines/{draft.id}:close", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 409
    assert r.json()["code"] == 40901


def test_m1d_guide_review_conclude_publishes_guideline(seed_auth):
    """论证评审通过 → 指南入库发布（DRAFT→PUBLISHED）；不通过保持 DRAFT。"""
    from apps.expertreview.models import NReviewTask

    g = _guideline(code="GUIDE-M1D-3")
    g2 = _guideline(code="GUIDE-M1D-4")
    c = _c()
    rid = c.post(
        "/api/v1/reviews",
        data=json.dumps({"biz_type": "GUIDE", "target_id": g.id, "title": "指南论证"}),
        content_type="application/json", **bearer(1, ["R-ADMIN"]),
    ).json()["data"]["id"]
    rid2 = c.post(
        "/api/v1/reviews",
        data=json.dumps({"biz_type": "GUIDE", "target_id": g2.id, "title": "指南论证2"}),
        content_type="application/json", **bearer(1, ["R-ADMIN"]),
    ).json()["data"]["id"]

    r = c.post(f"/api/v1/reviews/{rid}/conclude",
               data=json.dumps({"conclusion": "PASS"}), content_type="application/json",
               **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    g.refresh_from_db()
    assert g.status == "PUBLISHED"
    assert g.publish_at is not None

    r = c.post(f"/api/v1/reviews/{rid2}/conclude",
               data=json.dumps({"conclusion": "REJECT"}), content_type="application/json",
               **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    g2.refresh_from_db()
    assert g2.status == "DRAFT"


def test_m1d_expertreview_does_not_import_p_at_top_level():
    """N 域不得顶层 import P 域（跨模块写纪律：延迟 import）。"""
    import ast
    import io as _io
    import pathlib

    src = pathlib.Path("apps/expertreview/api.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            top_imports.append(node.module)
        elif isinstance(node, ast.Import):
            top_imports.extend(a.name for a in node.names)
    assert not [m for m in top_imports if m.startswith("apps.p")], top_imports
