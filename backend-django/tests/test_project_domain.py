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


# ---------------------------------------------------------------------------
# M1-d：评估模板 / 变更版本快照 / 变更分级（B3/B4 表结构）
# ---------------------------------------------------------------------------
def test_m1d_eval_template_model(seed_auth):
    from apps.project.models import EEvalTemplate

    t = EEvalTemplate.objects.create(
        tenant_id=1, creator_id=1, name="中期检查模板A", scene="MID_CHECK",
        sections=[{"key": "progress", "title": "进度达成"}, {"key": "finance", "title": "经费执行"}],
        score_rubric={"total": 100},
    )
    got = EEvalTemplate.objects.get(pk=t.pk)
    assert got.scene == "MID_CHECK"
    assert got.status == "ACTIVE"
    assert got.deleted == 0
    assert [s["key"] for s in got.sections] == ["progress", "finance"]
    assert got.score_rubric == {"total": 100}
    assert EEvalTemplate._meta.db_table == "E_EVAL_TEMPLATE"


def test_m1d_change_version_model(seed_auth):
    from apps.project.models import EChangeRequest, EChangeVersion

    p = _project()
    ch = EChangeRequest.objects.create(
        tenant_id=1, creator_id=1, project=p, change_type="TITLE", new_value={"title": "新题"}
    )
    v = EChangeVersion.objects.create(
        tenant_id=1, creator_id=1, change=ch, version_no=1,
        snapshot={"title": "旧题", "totalBudget": "100.00"},
    )
    got = EChangeVersion.objects.get(pk=v.pk)
    assert got.version_no == 1
    assert got.change_id == ch.id
    assert got.snapshot["title"] == "旧题"
    assert EChangeVersion._meta.db_table == "E_CHANGE_VERSION"


def test_m1d_change_severity_default(seed_auth):
    from apps.project.models import EChangeRequest

    p = _project()
    ch = EChangeRequest.objects.create(tenant_id=1, creator_id=1, project=p, change_type="TITLE")
    assert ch.severity == "GENERAL"
    ch2 = EChangeRequest.objects.create(
        tenant_id=1, creator_id=1, project=p, change_type="BUDGET", severity="MAJOR"
    )
    assert ch2.severity == "MAJOR"


# ---------------------------------------------------------------------------
# M1-d B2：八要素看板聚合
# ---------------------------------------------------------------------------
def test_m1d_board_eight_sections_and_money_strings(seed_auth):
    from apps.funding.models import FBudget
    from apps.project.models import EHealthHistory, EMilestone
    from apps.procure.models import GContract

    p = _project(title="看板项目")
    FBudget.objects.create(
        tenant_id=1, creator_id=1, project_id=p.id, legal_entity_id=1,
        status="EXECUTING", total_approved=100000,
    )
    EMilestone.objects.create(tenant_id=1, creator_id=1, project=p, name="M1", status="ACHIEVED")
    EHealthHistory.objects.create(tenant_id=1, project=p, health_score=88, risk_level="MEDIUM")
    GContract.objects.create(
        tenant_id=1, creator_id=1, contract_type="技术服务", project_id=p.id, amount=50000,
    )
    EChangeRequest.objects.create(tenant_id=1, creator_id=1, project=p, change_type="TITLE")

    c = _c()
    r = c.get(f"/api/v1/project/{p.id}/board", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert set(d) == {"fund", "progress", "members", "quality", "outsource", "changes", "outputs"}

    # 经费：复用 F 域 _execution_of，金额一律 num2 字符串（Money=string 契约）
    fund = d["fund"]
    assert fund["projectId"] == p.id
    for k in ("budgetApproved", "incomeTotal", "used", "frozen", "remaining"):
        assert isinstance(fund[k], str), f"fund.{k} 必须为字符串"
    assert fund["budgetApproved"] == "100000.00"

    # 进度：里程碑/任务计数
    assert d["progress"]["milestonesTotal"] == 1
    assert d["progress"]["milestonesDone"] == 1
    assert d["progress"]["tasksTotal"] == 0
    assert d["progress"]["tasksDone"] == 0

    # 质量：项目当前分 + 历史最新一条
    assert d["quality"]["healthScore"] == 100
    assert d["quality"]["riskLevel"] == "LOW"
    assert d["quality"]["lastCheckAt"] is not None

    # 外包：合同计数 + 金额字符串
    assert d["outsource"]["contracts"] == 1
    assert d["outsource"]["amountTotal"] == "50000.00"
    assert isinstance(d["outsource"]["amountTotal"], str)

    # 变更 / 成果
    assert d["changes"]["total"] == 1
    assert d["changes"]["byStatus"] == {"DRAFT": 1}
    assert d["outputs"]["total"] == 0


def test_m1d_board_outputs_counts_str_ids(seed_auth):
    """Review Focus 3：R_OUTPUT.project_ids 元素 int/str 混存都要计数。"""
    from apps.output.models import ROutput

    p = _project()
    ROutput.objects.create(tenant_id=1, creator_id=1, output_type="PAPER", title="论文A",
                           project_ids=[p.id])
    ROutput.objects.create(tenant_id=1, creator_id=1, output_type="PATENT", title="专利B",
                           project_ids=[str(p.id)])
    ROutput.objects.create(tenant_id=1, creator_id=1, output_type="PAPER", title="论文C",
                           project_ids=[999])
    c = _c()
    r = c.get(f"/api/v1/project/{p.id}/board", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    assert r.json()["data"]["outputs"]["total"] == 2


def test_m1d_board_members_and_404(seed_auth):
    from apps.sysadmin.models import SysUser

    u = SysUser.objects.create(username="u2", real_name="张三", tenant_id=1, status="ACTIVE",
                               creator_id=1)
    p = _project(member_ids=[u.id, 999])
    c = _c()
    r = c.get(f"/api/v1/project/{p.id}/board", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    members = r.json()["data"]["members"]
    assert members == [{"userId": u.id, "name": "张三"}, {"userId": 999, "name": None}]

    r2 = c.get("/api/v1/project/999999/board", **bearer(1, ["R-MANAGER"]))
    assert r2.status_code == 404
    assert r2.json()["code"] == 40401


# ---------------------------------------------------------------------------
# M1-d B3：统一评估模板（一套模板支撑中检与验收）
# ---------------------------------------------------------------------------
def _mk_tpl(c, **body):
    return c.post(
        "/api/v1/project/eval-templates",
        data=json.dumps(body), content_type="application/json",
        **bearer(1, ["R-MANAGER"]),
    )


def test_m1d_eval_template_crud(seed_auth):
    from apps.project.models import EEvalTemplate

    c = _c()
    r = _mk_tpl(c, name="中检模板A", scene="MID_CHECK",
                sections=[{"key": "progress", "label": "进度完成情况", "weight": 40}],
                scoreRubric={"max": 100})
    assert r.status_code == 200
    d = r.json()["data"]
    # 新端点一律 camelCase（契约 02-E 为准）
    assert set(d) >= {"id", "name", "scene", "status", "sections", "scoreRubric", "createdAt"}
    assert d["name"] == "中检模板A"
    assert d["scene"] == "MID_CHECK"
    assert d["status"] == "ACTIVE"
    assert d["sections"][0]["weight"] == 40
    assert d["scoreRubric"] == {"max": 100}

    # 列表 + scene 过滤
    _mk_tpl(c, name="验收模板B", scene="FINAL_ACCEPT")
    r = c.get("/api/v1/project/eval-templates?scene=FINAL_ACCEPT", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    rows = r.json()["data"]["list"]
    assert [x["name"] for x in rows] == ["验收模板B"]
    assert rows[0]["scene"] == "FINAL_ACCEPT"

    # 部分更新：只改 name，scene/sections 不动
    r = c.put(
        f"/api/v1/project/eval-templates/{d['id']}",
        data=json.dumps({"name": "中检模板A2"}), content_type="application/json",
        **bearer(1, ["R-MANAGER"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "中检模板A2"
    assert r.json()["data"]["sections"][0]["weight"] == 40

    # 软删：列表不再出现，但行仍在（deleted=1）
    r = c.delete(f"/api/v1/project/eval-templates/{d['id']}", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    r = c.get("/api/v1/project/eval-templates", **bearer(1, ["R-MANAGER"]))
    assert [x["name"] for x in r.json()["data"]["list"]] == ["验收模板B"]
    assert EEvalTemplate.objects.filter(id=d["id"], deleted=1).exists()


def test_m1d_eval_template_validation_and_404(seed_auth):
    c = _c()
    # 缺 name → 40001
    r = _mk_tpl(c, scene="MID_CHECK")
    assert r.status_code == 400 and r.json()["code"] == 40001
    # 非法 scene → 40001
    r = _mk_tpl(c, name="X", scene="ANNUAL")
    assert r.status_code == 400 and r.json()["code"] == 40001
    # 更新/删除不存在的模板 → 40401
    r = c.put("/api/v1/project/eval-templates/999999", data=json.dumps({"name": "Y"}),
              content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 404 and r.json()["code"] == 40401
    r = c.delete("/api/v1/project/eval-templates/999999", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 404 and r.json()["code"] == 40401


def test_m1d_eval_template_not_swallowed_by_project_detail(seed_auth):
    """路由顺序：/project/eval-templates 必须先于 /project/{id}（否则被详情吞掉）。"""
    c = _c()
    r = c.get("/api/v1/project/eval-templates", **bearer(1, ["R-MANAGER"]))
    assert r.status_code == 200
    assert "list" in r.json()["data"]


def test_m1d_mid_check_binds_template(seed_auth):
    from apps.project.models import EMidCheck

    c = _c()
    t = _mk_tpl(c, name="中检模板", scene="MID_CHECK").json()["data"]
    p = _project()
    # 契约拼写 templateId
    r = c.post(f"/api/v1/project/{p.id}/mid-check",
               data=json.dumps({"checkRound": 1, "templateId": t["id"]}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    mc = EMidCheck.objects.get(id=r.json()["data"]["id"])
    assert mc.template_id == t["id"]
    assert mc.check_round == 1

    # 旧 snake_case 拼写仍兼容
    r = c.post(f"/api/v1/project/{p.id}/mid-check",
               data=json.dumps({"check_round": 2, "template_id": t["id"]}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    assert EMidCheck.objects.get(id=r.json()["data"]["id"]).template_id == t["id"]

    # 不传模板仍可创建（template 可选，旧调用方不破）
    r = c.post(f"/api/v1/project/{p.id}/mid-check",
               data=json.dumps({"checkRound": 3}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    assert EMidCheck.objects.get(id=r.json()["data"]["id"]).template_id is None


def test_m1d_final_accept_binds_template(seed_auth):
    from apps.project.models import EFinalAccept

    c = _c()
    t = _mk_tpl(c, name="验收模板", scene="FINAL_ACCEPT").json()["data"]
    p = _project()
    r = c.post(f"/api/v1/project/{p.id}/final-accept",
               data=json.dumps({"templateId": t["id"], "outputSummary": {"papers": 2}}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    fa = EFinalAccept.objects.get(id=r.json()["data"]["id"])
    assert fa.template_id == t["id"]
