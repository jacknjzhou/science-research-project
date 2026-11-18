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
        data=json.dumps({"change_type": "DELAY", "severity": "MAJOR",
                         "old_value": "2026-01",
                         "new_value": {"endDate": "2026-06-30"}, "reason": "延期"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    cr = r.json()["data"]
    assert cr["status"] == "SUBMITTED"
    assert cr["code"].startswith("CHG-")  # 自动编号（M1-d 起统一 CHG-年-序）

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
        # 审批生效要求内容可应用（M1-d C-1）：无 payload 的预算变更一律拒绝，故此处给合法额度
        new_value={"totalBudget": "120000.00"},
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
    p.refresh_from_db()
    assert str(p.total_budget) == "120000.00"  # 终审生效真正回写项目总预算


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


# ---------------------------------------------------------------------------
# M1-d B3：评估结论批文生成 + 通知（conclude 单一写者尾部）
# ---------------------------------------------------------------------------
def test_m1d_mid_check_conclude_issues_report(seed_auth):
    from apps.project.api import conclude_mid_check
    from apps.project.models import EMidCheck, EReport

    p = _project()
    mc = EMidCheck.objects.create(tenant_id=1, creator_id=1, project=p, check_round=1)
    conclude_mid_check(mc.id, p.id, "PASS", {"total": 92})

    mc.refresh_from_db()
    assert mc.approval_doc_id is not None
    rp = EReport.objects.get(id=mc.approval_doc_id)
    assert rp.project_id == p.id
    assert rp.doc_type == "MID_CHECK"
    assert "批文" in rp.title
    assert rp.mid_check_id == mc.id
    assert rp.status == "ISSUED"
    assert rp.issued_at is not None
    assert rp.code and rp.code.startswith("RPT-")


def test_m1d_conclude_report_idempotent(seed_auth):
    from apps.project.api import conclude_final_accept
    from apps.project.models import EFinalAccept, EReport

    p = _project()
    fa = EFinalAccept.objects.create(tenant_id=1, creator_id=1, project=p)
    conclude_final_accept(fa.id, "APPROVED")
    conclude_final_accept(fa.id, "APPROVED")

    fa.refresh_from_db()
    assert fa.status == "APPROVED"
    assert fa.approval_doc_id is not None
    assert EReport.objects.filter(final_accept_id=fa.id, deleted=0).count() == 1


def test_m1d_final_accept_rejected_issues_no_report(seed_auth):
    """驳回/补正不出批文——批文只在通过时签发。"""
    from apps.project.api import conclude_final_accept
    from apps.project.models import EFinalAccept, EReport

    p = _project()
    fa = EFinalAccept.objects.create(tenant_id=1, creator_id=1, project=p)
    conclude_final_accept(fa.id, "REJECTED")
    fa.refresh_from_db()
    assert fa.approval_doc_id is None
    assert EReport.objects.filter(final_accept_id=fa.id, deleted=0).count() == 0


def test_m1d_conclude_notify_failure_does_not_block(seed_auth, monkeypatch):
    """通知 best-effort：_notify_role 抛错也要出批文（业务不可被通知拖挂）。"""
    from apps.project import api as project_api
    from apps.project.models import EMidCheck, EReport

    def boom(*a, **kw):
        raise RuntimeError("notify down")

    monkeypatch.setattr(project_api, "_notify_role", boom)
    p = _project()
    mc = EMidCheck.objects.create(tenant_id=1, creator_id=1, project=p, check_round=2)
    project_api.conclude_mid_check(mc.id, p.id, "PASS", {})
    mc.refresh_from_db()
    assert mc.approval_doc_id is not None
    assert EReport.objects.filter(mid_check_id=mc.id, deleted=0).count() == 1


# ---------------------------------------------------------------------------
# M1-d B4：变更分流（重大审批/一般备案）+ 冲突回退 + 生效回写 + 版本快照 + 预算联动
# ---------------------------------------------------------------------------
def _budget(project_id, total="100000.00", mode="预算制"):
    from apps.funding.models import FBudget
    return FBudget.objects.create(
        code=f"BUD-M1D-{project_id}", tenant_id=1, creator_id=1,
        project_id=project_id, legal_entity_id=1, mode=mode,
        total_approved=total, status="APPROVED",
    )


def test_m1d_change_general_takes_effect_without_approval(seed_auth):
    """一般变更：提交即备案生效（单步），并回写 EProject。"""
    p = _project(title="旧题目")
    c = _c()
    r = c.post(
        f"/api/v1/project/{p.id}/change-request",
        data=json.dumps({"change_type": "TITLE", "severity": "GENERAL",
                         "new_value": {"title": "新题目"}, "reason": "题目微调"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    cr = r.json()["data"]
    assert cr["status"] == "EFFECTIVE"
    assert cr["code"].startswith("CHG-")
    p.refresh_from_db()
    assert p.title == "新题目"
    from core.approval import SysApprovalLog
    assert SysApprovalLog.objects.filter(biz_type="CHANGE_REQUEST", biz_id=cr["id"]).count() == 1


def test_m1d_change_major_goes_through_approval(seed_auth):
    """重大变更：仍走审批链，批准后才生效。"""
    p = _project(title="旧题目")
    c = _c()
    r = c.post(
        f"/api/v1/project/{p.id}/change-request",
        data=json.dumps({"change_type": "TITLE", "severity": "MAJOR",
                         "new_value": {"title": "重大改名"}, "reason": "方向调整"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    cr = r.json()["data"]
    assert cr["status"] == "SUBMITTED"
    p.refresh_from_db()
    assert p.title == "旧题目"  # 未生效

    r = c.post(
        f"/api/v1/project/{p.id}/change-request/{cr['id']}/approve",
        data=json.dumps({"comment": "同意"}),
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "EFFECTIVE"
    p.refresh_from_db()
    assert p.title == "重大改名"


def test_m1d_change_budget_conflict_rolls_back(seed_auth):
    """预算变更降到已支出以下 → 冲突标记 + ROLLED_BACK（一般备案与重大审批两条路径都拦）。"""
    p = _project(spent_amount="8000.00")
    c = _c()
    body = {"change_type": "BUDGET", "severity": "GENERAL",
            "new_value": {"totalBudget": "5000.00"}, "reason": "压缩预算"}

    r = c.post(f"/api/v1/project/{p.id}/change-request", data=json.dumps(body),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 409
    cr = EChangeRequest.objects.filter(project_id=p.id).first()
    assert cr.conflict_flag == 1
    assert cr.status == "ROLLED_BACK"
    p.refresh_from_db()
    assert str(p.total_budget) in ("100000.00", "0.00")  # 未回写

    # 重大变更走审批，同样在生效前被拦
    r = c.post(f"/api/v1/project/{p.id}/change-request",
               data=json.dumps({**body, "severity": "MAJOR", "new_value": {"totalBudget": "4000.00"}}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    cid = r.json()["data"]["id"]
    r = c.post(f"/api/v1/project/{p.id}/change-request/{cid}/approve",
               data=json.dumps({"comment": "同意"}), content_type="application/json",
               **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409
    row = EChangeRequest.objects.get(id=cid)
    assert row.status == "ROLLED_BACK"
    assert row.conflict_flag == 1


def test_m1d_change_budget_effective_syncs_funding(seed_auth):
    """预算变更生效：EProject.total_budget 与 FBudget.total_approved 同步，快照留调剂记录。"""
    from apps.funding.models import FBudget
    p = _project(total_budget="100000.00")
    b = _budget(p.id, "100000.00")
    c = _c()
    r = c.post(
        f"/api/v1/project/{p.id}/change-request",
        data=json.dumps({"changeType": "BUDGET", "severity": "GENERAL",
                         "newValue": {"totalBudget": "120000.00"}, "reason": "追加经费"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "EFFECTIVE"
    p.refresh_from_db()
    b.refresh_from_db()
    assert str(p.total_budget) == "120000.00"
    assert str(b.total_approved) == "120000.00"

    from apps.project.models import EChangeVersion
    v = EChangeVersion.objects.filter(change_id=r.json()["data"]["id"]).first()
    assert v is not None
    assert v.snapshot["budgetAdjustment"]["delta"] == "20000.00"


def test_m1d_change_versions_endpoint(seed_auth):
    """版本快照：每次提交落一行，versions 端点按 versionNo 升序返回。"""
    p = _project(title="V0")
    c = _c()
    ids = []
    for i, t in enumerate(["V1", "V2"], start=1):
        r = c.post(f"/api/v1/project/{p.id}/change-request",
                   data=json.dumps({"change_type": "TITLE", "severity": "MAJOR",
                                    "new_value": {"title": t}, "reason": f"第{i}次"}),
                   content_type="application/json", **bearer(2, ["R-STAFF"]))
        assert r.status_code == 200
        ids.append(r.json()["data"]["id"])

    r = c.get(f"/api/v1/project/{p.id}/change-request/{ids[0]}/versions",
              **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    rows = r.json()["data"]["list"]
    assert len(rows) == 1
    assert rows[0]["versionNo"] == 1
    assert rows[0]["snapshot"]["title"] == "V0"
    assert "createdAt" in rows[0]

    # 详情在别的项目下取版本 → 404（跨项目不串）
    other = _project(title="别的项目")
    r = c.get(f"/api/v1/project/{other.id}/change-request/{ids[0]}/versions",
              **bearer(2, ["R-STAFF"]))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# M1-d 终审回归：输入强校验（C-1）与租户隔离（C-2/C-3）
# ---------------------------------------------------------------------------
def test_m1d_change_invalid_input_rejected(seed_auth):
    """非法变更内容一律 40001，且不落半条生效变更单（C-1）。"""
    p = _project()
    c = _c()
    cases = [
        # changeType 不在枚举内（PG 上会撞 DDL CHECK，必须在应用层先拒）
        {"change_type": "DATE", "new_value": {"endDate": "2026-06-30"}, "reason": "x"},
        # 非法 changeType 即使 severity=MAJOR 也不许建单
        {"change_type": "BOGUS", "severity": "MAJOR", "new_value": {}, "reason": "x"},
        # 延期但日期非法
        {"change_type": "DELAY", "new_value": {"endDate": "not-a-date"}, "reason": "x"},
        # 延期但缺 endDate
        {"change_type": "DELAY", "new_value": {}, "reason": "x"},
        # 预算但金额非法
        {"change_type": "BUDGET", "new_value": {"totalBudget": "abc"}, "reason": "x"},
        # 预算但金额非正
        {"change_type": "BUDGET", "new_value": {"totalBudget": "0"}, "reason": "x"},
        # 题目但空标题
        {"change_type": "TITLE", "new_value": {"title": "   "}, "reason": "x"},
    ]
    for body in cases:
        r = c.post(f"/api/v1/project/{p.id}/change-request", data=json.dumps(body),
                   content_type="application/json", **bearer(2, ["R-STAFF"]))
        assert r.status_code == 400, body
        assert r.json()["code"] == 40001, body
    assert EChangeRequest.objects.filter(project_id=p.id).count() == 0  # 无半成品

    # 更多非法输入：NaN/Infinity 能被 Decimal 解析但不可用于金额；成员名单必须给 ID 数组
    more = [
        {"change_type": "BUDGET", "new_value": {"totalBudget": "Infinity"}, "reason": "x"},
        {"change_type": "BUDGET", "new_value": {"totalBudget": "NaN"}, "reason": "x"},
        {"change_type": "BUDGET", "new_value": {"totalBudget": "-1"}, "reason": "x"},
        {"change_type": "MEMBER", "new_value": {}, "reason": "x"},
        {"change_type": "MEMBER", "new_value": {"memberIds": []}, "reason": "x"},
        {"change_type": "MEMBER", "new_value": {"memberIds": ["abc"]}, "reason": "x"},
    ]
    for body in more:
        r = c.post(f"/api/v1/project/{p.id}/change-request", data=json.dumps(body),
                   content_type="application/json", **bearer(2, ["R-STAFF"]))
        assert r.status_code == 400, body
        assert r.json()["code"] == 40001, body

    # 范围变更无对应列可回写 → 两种严重程度都拒绝（M2 任务书版本化再开）
    for sev in ("GENERAL", "MAJOR"):
        r = c.post(f"/api/v1/project/{p.id}/change-request",
                   data=json.dumps({"change_type": "SCOPE", "severity": sev,
                                    "new_value": {"scope": "扩展研究内容"}, "reason": "x"}),
                   content_type="application/json", **bearer(2, ["R-STAFF"]))
        assert r.status_code == 400, sev
        assert r.json()["code"] == 40001

    # 成员变更给合法 memberIds 才可建单（重大走审批）
    r = c.post(f"/api/v1/project/{p.id}/change-request",
               data=json.dumps({"change_type": "MEMBER", "severity": "MAJOR",
                                "new_value": {"memberIds": [2, 3]}, "reason": "加入成员"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200


def test_m1d_board_and_change_tenant_isolated(seed_auth):
    """看板/变更/审批必须按租户隔离：他租户项目一律 404，且不得被回写（C-2）。"""
    p = _project(tenant_id=2, title="他租户项目")
    c = _c()
    # 看板：本项目属租户 2，租户 1 的 R-STAFF 不可见
    r = c.get(f"/api/v1/project/{p.id}/board", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 404
    # 建变更：同样 404，不落单
    r = c.post(f"/api/v1/project/{p.id}/change-request",
               data=json.dumps({"change_type": "TITLE", "new_value": {"title": "劫持"}}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 404
    assert EChangeRequest.objects.filter(project_id=p.id).count() == 0

    # 审批：变更单属租户 2，租户 1 的 LEADER 不能审批回写
    cr = EChangeRequest.objects.create(
        code="CR-X1", tenant_id=2, creator_id=1, project_id=p.id,
        change_type="TITLE", severity="MAJOR", status="SUBMITTED",
        new_value={"title": "他租户改名"},
    )
    r = c.post(f"/api/v1/project/{p.id}/change-request/{cr.id}/approve",
               data=json.dumps({"comment": "越权"}), content_type="application/json",
               **bearer(4, ["R-LEADER"]))
    assert r.status_code == 404
    cr.refresh_from_db()
    assert cr.status == "SUBMITTED"
    p.refresh_from_db()
    assert p.title == "他租户项目"


def test_m1d_report_signing_uses_eval_row_tenant(seed_auth):
    """批文签发以评估单自身项目/租户为准，调用方传入的 project_id 不再影响幂等键（I-5）。"""
    from apps.project.models import EMidCheck, EReport

    p1 = _project(tenant_id=1, title="项目一")
    p2 = _project(tenant_id=1, title="项目二")
    mc = EMidCheck.objects.create(tenant_id=1, creator_id=1, project_id=p1.id, check_round=1)

    from apps.project.api import conclude_mid_check
    conclude_mid_check(mc.id, p1.id, "PASS", {"items": []})
    # 用别的 project_id 重复回写：不得再签发第二份批文
    conclude_mid_check(mc.id, p2.id, "PASS", {"items": []})
    reports = EReport.objects.filter(mid_check_id=mc.id)
    assert reports.count() == 1
    assert reports.first().project_id == p1.id
    mc.refresh_from_db()
    assert mc.approval_doc_id == reports.first().id


def test_m1d_eval_template_prefill_and_snapshot(seed_auth):
    """I-1：中检按模板 sections 预填打分骨架，验收固化模板快照；模板后改不影响已建评估。"""
    from apps.project.models import EEvalTemplate, EFinalAccept, EMidCheck

    p = _project()
    tpl = EEvalTemplate.objects.create(
        tenant_id=1, creator_id=1, name="中检模板", scene="MID_CHECK", status="ACTIVE",
        sections=[{"key": "progress", "label": "进度", "weight": 0.4},
                  {"key": "finance", "label": "经费", "weight": 0.6}],
    )
    c = _c()
    r = c.post(f"/api/v1/project/{p.id}/mid-check",
               data=json.dumps({"checkRound": 1, "templateId": tpl.id}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    mc = EMidCheck.objects.get(id=r.json()["data"]["id"])
    assert mc.template_id == tpl.id
    assert mc.template_snapshot["templateId"] == tpl.id
    assert len(mc.template_snapshot["sections"]) == 2
    assert [it["key"] for it in mc.score_detail["items"]] == ["progress", "finance"]
    assert all(it["score"] is None for it in mc.score_detail["items"])  # 骨架未打分
    # I-2：契约键是 camelCase（02-E EvalTemplateSchema/EMidCheck），snake_case 键为过渡保留
    assert r.json()["data"]["templateId"] == tpl.id
    assert r.json()["data"]["template_id"] == tpl.id
    assert r.json()["data"]["approvalDocId"] is None  # 签批文前为空，键必须存在

    # 模板随后被改，已建中检的快照不变
    tpl.sections = [{"key": "only", "weight": 1.0}]
    tpl.save(update_fields=["sections"])
    mc.refresh_from_db()
    assert len(mc.template_snapshot["sections"]) == 2

    tplf = EEvalTemplate.objects.create(
        tenant_id=1, creator_id=1, name="验收模板", scene="FINAL_ACCEPT",
        status="ACTIVE", sections=[{"key": "target", "weight": 0.5}],
    )
    r = c.post(f"/api/v1/project/{p.id}/final-accept",
               data=json.dumps({"templateId": tplf.id, "outputSummary": {"n": 1}}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    fa = EFinalAccept.objects.get(id=r.json()["data"]["id"])
    assert fa.template_snapshot["sections"] == [{"key": "target", "weight": 0.5}]
    # I-2：验收响应带 templateId（camelCase 为契约口径）
    assert r.json()["data"]["templateId"] == tplf.id
    assert r.json()["data"]["template_id"] == tplf.id
    assert r.json()["data"]["approvalDocId"] is None


def test_m1d_eval_template_status_validated(seed_auth):
    """I-4：创建模板的 status 也校验枚举（与 update 一致）。"""
    c = _c()
    r = c.post("/api/v1/project/eval-templates",
               data=json.dumps({"name": "坏状态", "scene": "MID_CHECK", "status": "BOGUS"}),
               content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 400
    assert r.json()["code"] == 40001


# transaction=True：不套 pytest-django 的测试级 atomic，否则 in_atomic_block 恒 True，
# 这个用例就退化成恒真（r4 实测）。非事务包裹下才能区分「有没有 atomic」。
@pytest.mark.django_db(transaction=True)
def test_m1d_conclude_works_without_caller_transaction(monkeypatch):
    """N-1 回归：批文签发必须在事务内（PG 下 select_for_update 在 autocommit 会抛）。

    sqlite 的 has_select_for_update=False 会静默降级，看「能不能跑通」抓不到缺陷，
    所以 spy 签发时的 connection.in_atomic_block——去掉 atomic 时这里变成 False。
    """
    from django.db import connection
    from apps.project.models import EFinalAccept, EReport
    from apps.project import api as project_api

    seen: list[bool] = []
    real = project_api._issue_report

    def spy(*args, **kwargs):
        seen.append(connection.in_atomic_block)
        return real(*args, **kwargs)

    monkeypatch.setattr(project_api, "_issue_report", spy)

    p = _project()
    fa = EFinalAccept.objects.create(tenant_id=1, creator_id=1, project_id=p.id,
                                     status="APPLIED")
    project_api.conclude_final_accept(fa.id, "APPROVED")
    assert seen == [True], "批文签发必须在事务内（否则 PG 上 select_for_update 抛错）"
    fa.refresh_from_db()
    assert fa.status == "APPROVED"
    assert fa.accept_at is not None
    assert fa.approval_doc_id is not None
    from apps.project.mappings import to_api_final_accept
    assert to_api_final_accept(fa)["approvalDocId"] == fa.approval_doc_id
    assert EReport.objects.filter(final_accept_id=fa.id).count() == 1

    project_api.conclude_final_accept(fa.id, "APPROVED")  # 幂等
    assert EReport.objects.filter(final_accept_id=fa.id).count() == 1
    fa.refresh_from_db()
    assert fa.approval_doc_id == EReport.objects.filter(final_accept_id=fa.id).first().id


def test_m1d_change_batch_isolates_bad_rows(seed_auth):
    """N-5：批量审批逐条独立成败，一条内容非法不带垮整批。"""
    p = _project()
    c = _c()
    good = EChangeRequest.objects.create(
        tenant_id=1, creator_id=2, project_id=p.id, change_type="TITLE",
        severity="MAJOR", status="SUBMITTED", new_value={"title": "批量改名"},
    )
    bad = EChangeRequest.objects.create(
        tenant_id=1, creator_id=2, project_id=p.id, change_type="SCOPE",
        severity="MAJOR", status="SUBMITTED", new_value={"scope": "无回写目标"},
    )
    r = c.post("/api/v1/projects/approve-batch",
               data=json.dumps({"ids": [good.id, bad.id], "action": "APPROVE",
                                "comment": "批量同意"}),
               content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ok"] == 1
    by_id = {x["id"]: x for x in data["results"]}
    assert by_id[good.id]["ok"] is True
    assert by_id[bad.id]["ok"] is False
    assert "范围变更" in by_id[bad.id]["err"]
    p.refresh_from_db()
    assert p.title == "批量改名"  # 好的那条照常生效


def test_m1d_budget_amount_bounds_rejected(seed_auth):
    """Important-3：预算变更拒绝不可落库的数值（有限大指数 / 亚分精度）。"""
    p = _project()
    c = _c()
    for bad in ("1e100", "0.001", "1e-30", "1e16"):
        r = c.post(f"/api/v1/project/{p.id}/change-request",
                   data=json.dumps({"changeType": "BUDGET", "severity": "MAJOR",
                                    "newValue": {"totalBudget": bad}, "reason": "x"}),
                   content_type="application/json", **bearer(2, ["R-STAFF"]))
        assert r.status_code == 400, bad
        assert r.json()["code"] == 40001, bad
    # 两位小数正常值放行
    r = c.post(f"/api/v1/project/{p.id}/change-request",
               data=json.dumps({"changeType": "BUDGET", "severity": "MAJOR",
                                "newValue": {"totalBudget": "123456.78"}, "reason": "追加预算"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200


def test_m1d_member_change_requires_major(seed_auth):
    """Important-1：成员变更影响「参与项目」判定，不允许一般备案即时生效。"""
    p = _project()
    c = _c()
    r = c.post(f"/api/v1/project/{p.id}/change-request",
               data=json.dumps({"changeType": "MEMBER", "severity": "GENERAL",
                                "newValue": {"memberIds": [2, 3]}, "reason": "加人"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 400
    assert r.json()["code"] == 40001
    r = c.post(f"/api/v1/project/{p.id}/change-request",
               data=json.dumps({"changeType": "MEMBER", "severity": "MAJOR",
                                "newValue": {"memberIds": [2, 3]}, "reason": "加人"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "SUBMITTED"
