"""项目过程域 E 测试：视角过滤、变更状态机、申报计划两级审批、转立项幂等、预警去重。"""
import json
from datetime import timedelta

import pytest
from django.test import Client, override_settings
from django.utils import timezone as dj_tz

from apps.notify.models import SysNotification
from apps.project.models import (
    EApplication,
    EApplyPlan,
    EChangeRequest,
    EProject,
    EProjectCategory,
)
from tests.conftest import bearer


def _c():
    return Client()


def _project(**kw):
    base = dict(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="测试项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
    )
    base.update(kw)
    return EProject.objects.create(**base)


# ---------------------------------------------------------------------------
# 项目视角
# ---------------------------------------------------------------------------
def test_list_my_projects_staff_sees_own_only(seed_auth):
    _project(title="我的A")
    _project(title="我的B", pi_user_id=3)
    c = _c()
    r = c.get("/api/v1/project/mine", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total"] == 1
    assert body["list"][0]["title"] == "我的A"


def test_list_my_projects_admin_sees_all(seed_auth):
    _project(title="A")
    _project(title="B", pi_user_id=3)
    c = _c()
    r = c.get("/api/v1/project/mine", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"]["total"] == 2


# ---------------------------------------------------------------------------
# 变更单状态机（两级开关 off：一步 EFFECTIVE）
# ---------------------------------------------------------------------------
def test_change_request_approve_one_step(seed_auth):
    p = _project()
    c = _c()
    r = c.post(
        f"/api/v1/project/{p.id}/change-request",
        data=json.dumps({"change_type": "DATE", "old_value": "2026-01",
                         "new_value": "2026-06", "reason": "延期"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    cr = r.json()["data"]
    assert cr["status"] == "SUBMITTED"
    assert cr["code"].startswith("CR-")  # 自动编号

    r = c.post(
        f"/api/v1/project/{p.id}/change-request/{cr['id']}/approve",
        data=json.dumps({"comment": "同意"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "EFFECTIVE"

    # 再审批 → 409
    r = c.post(
        f"/api/v1/project/{p.id}/change-request/{cr['id']}/approve",
        data=json.dumps({}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 409


@override_settings(APPROVAL_TWOSTEP=True)
def test_change_request_two_step_roles(seed_auth):
    p = _project()
    cr = EChangeRequest.objects.create(
        code="CR-T1", tenant_id=1, creator_id=2, project_id=p.id,
        change_type="BUDGET", status="SUBMITTED",
    )
    c = _c()
    # STAFF 首审 → 403
    r = c.post(
        f"/api/v1/project/{p.id}/change-request/{cr.id}/approve",
        data=json.dumps({}), content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 403

    # MANAGER 首审 → APPROVING
    r = c.post(
        f"/api/v1/project/{p.id}/change-request/{cr.id}/approve",
        data=json.dumps({"comment": "初审同意"}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "APPROVING"

    # MANAGER 终审 → 403（需 R-LEADER）
    r = c.post(
        f"/api/v1/project/{p.id}/change-request/{cr.id}/approve",
        data=json.dumps({}), content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.status_code == 403

    # LEADER 终审 → EFFECTIVE
    r = c.post(
        f"/api/v1/project/{p.id}/change-request/{cr.id}/approve",
        data=json.dumps({"comment": "终审同意"}), content_type="application/json",
        **bearer(4, ["R-LEADER"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "EFFECTIVE"


def test_change_reject_and_batch(seed_auth):
    p = _project()
    cr1 = EChangeRequest.objects.create(
        code="CR-R1", tenant_id=1, creator_id=2, project_id=p.id,
        change_type="TEAM", status="SUBMITTED")
    cr2 = EChangeRequest.objects.create(
        code="CR-R2", tenant_id=1, creator_id=2, project_id=p.id,
        change_type="TEAM", status="SUBMITTED")
    c = _c()
    r = c.post(
        "/api/v1/projects/approve-batch",
        data=json.dumps({"ids": [cr1.id, cr2.id], "action": "REJECT", "comment": "批量驳回"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["ok"] == 2
    cr1.refresh_from_db()
    assert cr1.status == "REJECTED"


# ---------------------------------------------------------------------------
# 申报计划 + 申报单
# ---------------------------------------------------------------------------
def _plan(**kw):
    today = dj_tz.localdate()
    base = dict(
        tenant_id=1, name="2026 申报计划", source="纵向", start_at=today,
        end_at=today + timedelta(days=30), need_review=True, status="DRAFT",
    )
    base.update(kw)
    return EApplyPlan.objects.create(**base)


def test_apply_plan_lifecycle(seed_auth):
    plan = _plan()
    c = _c()
    # 未开启时 stop → 409
    r = c.post(f"/api/v1/apply-plans/{plan.id}/stop", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409
    # start → OPEN
    r = c.post(f"/api/v1/apply-plans/{plan.id}/start", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "OPEN"
    # 重复 start → 409（仅 DRAFT 可开启）
    r = c.post(f"/api/v1/apply-plans/{plan.id}/start", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409
    # stop → STOPPED
    r = c.post(f"/api/v1/apply-plans/{plan.id}/stop", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200


def test_auto_stop_expired_plans(seed_auth):
    today = dj_tz.localdate()
    _plan(name="过期计划", end_at=today - timedelta(days=1), status="OPEN")
    _plan(name="未过期", status="OPEN")
    c = _c()
    r = c.post("/api/v1/apply-plans/auto-stop", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"]["stopped"] == 1


def test_plan_application_window_guard(seed_auth):
    plan = _plan(status="DRAFT")  # 未开启
    c = _c()
    r = c.post(
        f"/api/v1/apply-plans/{plan.id}/applications",
        data=json.dumps({"project_name": "新申报"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 409

    plan.status = "OPEN"
    plan.save()
    r = c.post(
        f"/api/v1/apply-plans/{plan.id}/applications",
        data=json.dumps({"project_name": "新申报", "apply_amount": 50}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "SUBMITTED"


@override_settings(APPROVAL_TWOSTEP=True)
def test_application_two_step_approve_and_to_project(seed_auth):
    plan = _plan(status="OPEN")
    app = EApplication.objects.create(
        tenant_id=1, plan=plan, project_name="转立项申报",
        apply_amount=80, applicant_id=2,
    )
    c = _c()
    # STAFF 审批 → 403
    r = c.post(
        f"/api/v1/applications/{app.id}/approve",
        data=json.dumps({"action": "APPROVE"}), content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 403
    # MANAGER 首审
    r = c.post(
        f"/api/v1/applications/{app.id}/approve",
        data=json.dumps({"action": "APPROVE", "comment": "形式审查通过"}),
        content_type="application/json",
        **bearer(3, ["R-MANAGER"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "COLLEGE_PASSED"
    # 未通过前 to-project → 409
    r = c.post(f"/api/v1/applications/{app.id}/to-project", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409
    # LEADER 终审
    r = c.post(
        f"/api/v1/applications/{app.id}/approve",
        data=json.dumps({"action": "APPROVE"}),
        content_type="application/json",
        **bearer(4, ["R-LEADER"]),
    )
    assert r.json()["data"]["status"] == "SCHOOL_PASSED"

    # 转立项（幂等）
    r = c.post(f"/api/v1/applications/{app.id}/to-project", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["duplicated"] is False
    pid = body["project_id"]
    # EXECUTING 项目，预算 = 申报金额
    proj = EProject.objects.get(id=pid)
    assert proj.status == "EXECUTING"
    assert str(proj.total_budget) == "80.00"
    assert proj.pi_user_id == 2

    r = c.post(f"/api/v1/applications/{app.id}/to-project", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"] == {"project_id": pid, "duplicated": True}


def test_list_plan_applications_formal_check_view(seed_auth):
    _project(title="PI主持", total_budget=100)
    plan = _plan(status="OPEN")
    EApplication.objects.create(
        tenant_id=1, plan=plan, project_name="形式审查对象",
        apply_amount=20, applicant_id=2,
    )
    c = _c()
    r = c.get(f"/api/v1/apply-plans/{plan.id}/applications", **bearer(3, ["R-MANAGER"]))
    assert r.status_code == 200
    row = r.json()["data"]["list"][0]
    assert row["pi_project_count"] == 1
    assert row["pi_budget_total"] == "100.00"
    assert row["apply_amount"] == "20.00"


# ---------------------------------------------------------------------------
# 分类 + 预警去重
# ---------------------------------------------------------------------------
def test_category_dup_code_409_and_crud(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/project-categories",
        data=json.dumps({"code": "KEY", "name": "重点专项"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    cat = r.json()["data"]
    # 重复 code → 409
    r = c.post(
        "/api/v1/project-categories",
        data=json.dumps({"code": "KEY", "name": "重复"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 409
    # 更新
    r = c.put(
        f"/api/v1/project-categories/{cat['id']}",
        data=json.dumps({"name": "重点专项V2"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.json()["data"]["name"] == "重点专项V2"
    # 删除（软删）
    r = c.delete(f"/api/v1/project-categories/{cat['id']}", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    # 删除后再取 → 404
    r = c.put(
        f"/api/v1/project-categories/{cat['id']}",
        data=json.dumps({"name": "x"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 404


def test_attach_category_and_scan_warnings_dedupe(seed_auth):
    today = dj_tz.localdate()
    cat = EProjectCategory.objects.create(
        tenant_id=1, code="WIN", name="窗口分类",
        midcheck_from=today + timedelta(days=5),
        midcheck_to=today + timedelta(days=10),
    )
    p = _project(title="预警项目")
    c = _c()
    r = c.post(
        f"/api/v1/projects/{p.id}/category",
        data=json.dumps({"category_id": cat.id}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200

    # 第一次扫描：命中中检窗口 → 1 条
    r = c.post("/api/v1/project-categories/scan-warnings", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"]["sent"] == 1
    n = SysNotification.objects.filter(user_id=2, typ="WARNING").count()
    assert n == 1

    # 第二次扫描：同用户同标题未读 → 去重 0 条
    r = c.post("/api/v1/project-categories/scan-warnings", **bearer(1, ["R-ADMIN"]))
    assert r.json()["data"]["sent"] == 0
    assert SysNotification.objects.filter(user_id=2, typ="WARNING").count() == 1
