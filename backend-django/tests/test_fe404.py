"""前端 404 补端点测试：P 申报 8 条 + D 大屏 5 条 + E 项目 2 条。

对应前端 EditorView/ReviewView/DashView/BigscreenView/ProjectView 的真后端契约。
"""
import json

from django.test import Client

from apps.expertreview.models import NReviewInvitation, NReviewScore, NReviewTask
from apps.p.models import PApplication, PApplicationDoc
from apps.project.models import EArchiveChecklist, EProject
from tests.conftest import bearer


def _c():
    return Client()


def _mk_app(**kw) -> PApplication:
    defaults = dict(tenant_id=1, status="DRAFT", creator_id=2, title="AI 药物筛选",
                    project_type="NATURAL", pi_user_id=2, total_budget=100000)
    defaults.update(kw)
    return PApplication.objects.create(**defaults)


# ---------------------------------------------------------------------------
# P 域：documents / budget / sections / submit
# ---------------------------------------------------------------------------
def test_documents_returns_9_sections(seed_auth):
    c = _c()
    a = _mk_app(abstract="立项依据正文", research_target="目标正文")
    r = c.get(f"/api/v1/apply/applications/{a.id}/documents", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    docs = r.json()["data"]
    assert [d["section_code"] for d in docs] == [
        "background", "objective", "content", "route", "innovation",
        "foundation", "schedule", "budget_note", "attachments",
    ]
    by = {d["section_code"]: d for d in docs}
    assert by["background"]["content_rich"] == "立项依据正文"  # 旧字段合并
    assert by["objective"]["content_rich"] == "目标正文"
    assert by["content"]["content_rich"] == ""


def test_section_put_roundtrip_and_unknown_code(seed_auth):
    c = _c()
    a = _mk_app()
    r = c.put(
        f"/api/v1/apply/applications/{a.id}/sections/route",
        data=json.dumps({"content_rich": "技术路线：数据驱动 + 实验验证"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    doc = r.json()["data"]
    assert doc["doc_version"] == 1 and doc["word_count"] > 0

    # 二次保存版本自增
    r = c.put(
        f"/api/v1/apply/applications/{a.id}/sections/route",
        data=json.dumps({"content_rich": "技术路线 V2"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.json()["data"]["doc_version"] == 2
    assert PApplicationDoc.objects.filter(application=a, section_code="route").count() == 1

    r = c.put(
        f"/api/v1/apply/applications/{a.id}/sections/bogus",
        data=json.dumps({"content_rich": "x"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 400 and r.json()["code"] == 40002


def test_budget_deterministic_split(seed_auth):
    c = _c()
    a = _mk_app(total_budget=100000)
    r = c.get(f"/api/v1/apply/applications/{a.id}/budget", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 7
    assert sum(float(x["amount"]) for x in rows) == 100000.00
    assert rows[0]["subject_code"] == "EQUIPMENT"
    assert rows[0]["ai_compliance_flag"] == "OK"

    # 无预算 → 空列表
    a2 = _mk_app(title="无预算", total_budget=None)
    r = c.get(f"/api/v1/apply/applications/{a2.id}/budget", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"] == []


def test_submit_state_machine_and_watermark_confirm(seed_auth):
    c = _c()
    # AI 辅助过但未确认水印 → 40001
    a = _mk_app(ai_draft_marked=True)
    r = c.post(f"/api/v1/apply/applications/{a.id}/submit",
               data=json.dumps({}), content_type="application/json",
               **bearer(2, ["R-STAFF"]))
    assert r.status_code == 400 and r.json()["code"] == 40001

    # 确认水印 → SUBMITTED + submit_at
    r = c.post(f"/api/v1/apply/applications/{a.id}/submit",
               data=json.dumps({"confirm_ai_watermark": True}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["status"] == "SUBMITTED" and body["submit_at"]

    # 非 DRAFT 重复提交 → 40901
    r = c.post(f"/api/v1/apply/applications/{a.id}/submit",
               data=json.dumps({"confirm_ai_watermark": True}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 409 and r.json()["code"] == 40901


# ---------------------------------------------------------------------------
# P 域：AI 起草 / AI 评审意见 / mytasks / :score
# ---------------------------------------------------------------------------
def test_ai_draft_marks_and_returns_watermark(seed_auth):
    c = _c()
    a = _mk_app()
    r = c.post("/api/v1/apply/ai/draft",
               data=json.dumps({"application_id": a.id, "section_code": "background",
                                "keywords": "药物筛选"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    draft = r.json()["data"]
    assert draft["mode"] == "RULE" and draft["watermark"] and draft["confidence"]
    assert "药物筛选" in draft["content"]
    a.refresh_from_db()
    assert a.ai_draft_marked is True

    r = c.post("/api/v1/apply/ai/draft",
               data=json.dumps({"application_id": a.id, "section_code": "nope"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 400 and r.json()["code"] == 40002


def test_ai_review_draft_deterministic_by_score(seed_auth):
    c = _c()
    t = NReviewTask.objects.create(tenant_id=1, creator_id=1, biz_type="PROJECT_APPLY",
                                   title="评审任务", status="IN_REVIEW")
    detail = [{"dim": d, "score": "5", "max_score": "5"} for d in ("创新性", "科学问题", "研究方案", "研究基础")]
    r = c.post("/api/v1/apply/ai/review-draft",
               data=json.dumps({"task_id": t.id, "score_detail": detail}),
               content_type="application/json", **bearer(3, ["R-EXPERT"]))
    assert r.status_code == 200
    body = r.json()["data"]
    assert "优秀" in body["overall"] and body["adopted"] is False

    detail_low = [{"dim": d, "score": "1", "max_score": "5"} for d in ("创新性", "科学问题")]
    r = c.post("/api/v1/apply/ai/review-draft",
               data=json.dumps({"task_id": t.id, "score_detail": detail_low}),
               content_type="application/json", **bearer(3, ["R-EXPERT"]))
    assert "不予资助" in r.json()["data"]["overall"]


def _mk_assigned_task(expert_id: int) -> NReviewTask:
    t = NReviewTask.objects.create(tenant_id=1, creator_id=1, biz_type="PROJECT_APPLY",
                                   title="面上项目评审", status="IN_REVIEW", plan_count=3,
                                   target_type="APPLICATION")
    app = _mk_app(status="SUBMITTED", code="PRJ-2026-001")
    t.target_id = app.id
    t.save(update_fields=["target_id"])
    NReviewInvitation.objects.create(tenant_id=1, task_id=t.id, expert_id=expert_id,
                                     response="ACCEPT")
    return t, app


def test_mytasks_scoping_and_score_upsert(seed_auth):
    c = _c()
    t, app = _mk_assigned_task(expert_id=3)

    # 无关专家看不到
    r = c.get("/api/v1/apply/review/mytasks", {"status": "SCORING"},
              **bearer(4, ["R-EXPERT"]))
    assert r.json()["data"]["total"] == 0

    # 指派专家可见，包装 ReviewTask 含 dims/doc
    r = c.get("/api/v1/apply/review/mytasks", {"status": "SCORING"},
              **bearer(3, ["R-EXPERT"]))
    assert r.status_code == 200
    rows = r.json()["data"]["rows"]
    assert len(rows) == 1
    task = rows[0]
    assert task["application_id"] == app.id and task["status"] == "SCORING"
    assert task["doc"]["title"] == app.title and len(task["dims"]) == 4

    # 打分（首次创建）
    detail = [{"dim": "创新性", "score": "4", "max_score": "5"},
              {"dim": "科学问题", "score": "5", "max_score": "5"},
              {"dim": "研究方案", "score": "4", "max_score": "5"},
              {"dim": "研究基础", "score": "3", "max_score": "5"}]
    r = c.post(f"/api/v1/apply/review/tasks/{t.id}:score",
               data=json.dumps({"score_detail": detail, "comment_text": "整体可行"}),
               content_type="application/json", **bearer(3, ["R-EXPERT"]))
    assert r.status_code == 200
    assert r.json()["data"]["total_score"] == "16.00"

    # 幂等 upsert（同专家二次提交覆盖，不新增行）
    r = c.post(f"/api/v1/apply/review/tasks/{t.id}:score",
               data=json.dumps({"score_detail": detail, "comment_text": "修改意见"}),
               content_type="application/json", **bearer(3, ["R-EXPERT"]))
    assert r.status_code == 200
    assert NReviewScore.objects.filter(task_id=t.id, expert_id=3).count() == 1
    assert NReviewScore.objects.get(task_id=t.id, expert_id=3).comment == "修改意见"

    # 非指派专家 → 403
    r = c.post(f"/api/v1/apply/review/tasks/{t.id}:score",
               data=json.dumps({"score_detail": detail}),
               content_type="application/json", **bearer(4, ["R-EXPERT"]))
    assert r.status_code == 403 and r.json()["code"] == 40301


# ---------------------------------------------------------------------------
# D 大屏：tasks/summary / metrics / forecast / drill / screens
# ---------------------------------------------------------------------------
def test_tasks_summary_counts(seed_auth):
    from apps.notify.models import SysNotification, SysTask

    c = _c()
    SysTask.objects.create(tenant_id=1, assignee_id=2, typ="APPROVAL", title="待办1")
    SysNotification.objects.create(tenant_id=1, user_id=2, typ="MESSAGE", title="未读消息")
    SysNotification.objects.create(tenant_id=1, user_id=2, typ="WARNING", title="预警")
    SysNotification.objects.create(tenant_id=1, user_id=2, typ="MESSAGE", title="已读",
                                   read_at="2026-10-17T01:00:00Z")
    r = c.get("/api/v1/tasks/summary", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d == {"todo": 1, "message": 1, "warning": 1}


def test_metrics_known_and_unknown_zero_row(seed_auth):
    c = _c()
    EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=1,
                            title="在研项目", status="EXECUTING", pi_user_id=2)
    r = c.get("/api/v1/dash/metrics/in_research_projects", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    m = r.json()["data"]
    assert m["value"] == 1 and m["unit"] == "项" and m["dq_flag"] == "OK"

    # 未知 code 仍 200（DashView Promise.all 无兜底）
    r = c.get("/api/v1/dash/metrics/unknown_kpi", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    assert r.json()["data"]["dq_flag"] == "NO_DATA"


def test_forecast_shape_and_drill_bands(seed_auth):
    c = _c()
    r = c.get("/api/v1/dash/forecast", {"target_metric": "monthly_expense"},
              **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    lst = r.json()["data"]["list"]
    # 空库历史不足 2 期 → 空列表（结构仍合法）
    assert isinstance(lst, list)

    EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=1,
                            title="健康项目", status="EXECUTING", health_score=90, pi_user_id=2)
    EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=2,
                            title="风险项目", status="DELAYED", health_score=50, pi_user_id=2)
    r = c.get("/api/v1/dash/report/instance/1/drill", **bearer(2, ["R-STAFF"]))
    rows = r.json()["data"]["rows"]
    assert {r0["health"] for r0 in rows} == {"≥80 良好", "60-79 关注", "<60 风险"}
    assert rows[0]["count"] == 1 and rows[2]["count"] == 1


def test_screens_list(seed_auth):
    c = _c()
    r = c.get("/api/v1/dash/screens", {"size": 1}, **bearer(2, ["R-LEADER"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["total"] == 1 and d["rows"][0]["code"] == "SCR-FUNDING"


# ---------------------------------------------------------------------------
# E 项目：risk-warnings / archive-checklist
# ---------------------------------------------------------------------------
def test_risk_warnings_rules(seed_auth):
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    from apps.project.models import EMilestone

    c = _c()
    p = EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=1,
                                title="超支项目", status="EXECUTING", pi_user_id=2,
                                total_budget=100000, spent_amount=110000, health_score=50)
    EMilestone.objects.create(tenant_id=1, deleted=0, creator_id=1, project=p,
                              name="中期检查", due_date=dj_tz.localdate() - timedelta(days=5))
    r = c.get(f"/api/v1/project/{p.id}/risk-warnings", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    rows = r.json()["data"]
    sources = {x["source"] for x in rows}
    assert "FUNDING" in sources and "MILESTONE" in sources and "HEALTH" in sources
    assert all(x["level"] in ("HIGH", "MID") for x in rows)
    assert [x["warningId"] for x in rows] == list(range(1, len(rows) + 1))

    # 健康项目 → 无预警
    p2 = EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=2,
                                 title="健康项目", status="EXECUTING", health_score=95, pi_user_id=2)
    r = c.get(f"/api/v1/project/{p2.id}/risk-warnings", **bearer(2, ["R-STAFF"]))
    assert r.json()["data"] == []


def test_archive_checklist_idempotent_init(seed_auth):
    c = _c()
    p = EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=1,
                                title="结题项目", status="COMPLETING", pi_user_id=2)
    r = c.get(f"/api/v1/project/{p.id}/archive-checklist", {"stage": "FINAL"},
              **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["requiredCount"] == 3 and d["completedCount"] == 0
    assert d["completeness"] == "0%" and set(d["blockedItems"]) == {"结题报告", "成果清单", "经费决算表"}

    # 幂等：二次读取不重复建行
    r = c.get(f"/api/v1/project/{p.id}/archive-checklist", {"stage": "FINAL"},
              **bearer(2, ["R-STAFF"]))
    assert r.json()["data"]["requiredCount"] == 3
    assert EArchiveChecklist.objects.filter(project=p, code="FINAL").count() == 1

    r = c.get(f"/api/v1/project/{p.id}/risk-warnings", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200


def test_archive_checklist_item_upload_marks(seed_auth):
    from apps.archive.models import ODocument

    c = _c()
    p = EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=1,
                                title="结题项目二", status="COMPLETING", pi_user_id=2)
    doc = ODocument.objects.create(tenant_id=1, creator_id=2, name="结题报告.pdf",
                                   status="STORED", source_module="project", source_id=p.id)
    r = c.post(
        f"/api/v1/project/{p.id}/archive-checklist",
        data=json.dumps({"item": "结题报告", "doc_id": doc.id, "uploaded": True}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 200
    d = r.json()["data"]
    by = {i["item"]: i for i in d["checklistJson"]}
    assert by["结题报告"]["uploaded"] is True and by["结题报告"]["docId"] == doc.id
    assert d["completedCount"] == 1 and d["completeness"] == "33%"
    assert "结题报告" not in d["blockedItems"]
    row = EArchiveChecklist.objects.get(project=p, code="FINAL")
    assert row.passed is False  # 尚有必交项缺

    # 三项必交全补 → passed=True
    for name in ("成果清单", "经费决算表"):
        d2 = ODocument.objects.create(tenant_id=1, creator_id=2, name=f"{name}.pdf")
        r = c.post(
            f"/api/v1/project/{p.id}/archive-checklist",
            data=json.dumps({"item": name, "doc_id": d2.id}),
            content_type="application/json",
            **bearer(2, ["R-STAFF"]),
        )
        assert r.status_code == 200
    assert r.json()["data"]["completeness"] == "100%"
    assert EArchiveChecklist.objects.get(project=p, code="FINAL").passed is True


def test_archive_checklist_item_validation(seed_auth):
    c = _c()
    p = EProject.objects.create(tenant_id=1, deleted=0, creator_id=1, application_id=1,
                                title="校验项目", status="COMPLETING", pi_user_id=2)
    # 补传必须带 doc_id
    r = c.post(
        f"/api/v1/project/{p.id}/archive-checklist",
        data=json.dumps({"item": "结题报告"}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 400 and r.json()["code"] == 40001

    # doc_id 不存在 → 40902
    r = c.post(
        f"/api/v1/project/{p.id}/archive-checklist",
        data=json.dumps({"item": "结题报告", "doc_id": 99999}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 409 and r.json()["code"] == 40902

    # 未知清单项 → 40002
    from apps.archive.models import ODocument
    doc = ODocument.objects.create(tenant_id=1, creator_id=2, name="x.pdf")
    r = c.post(
        f"/api/v1/project/{p.id}/archive-checklist",
        data=json.dumps({"item": "不存在项", "doc_id": doc.id}),
        content_type="application/json",
        **bearer(2, ["R-STAFF"]),
    )
    assert r.status_code == 400 and r.json()["code"] == 40002


def test_finance_role_procurement_asset_access(seed_auth):
    """R-FINANCE：采购/资产台账 4 个 GET 不再 403；POST requisitions 过 casbin 到达 handler。"""
    c = _c()
    hdr = bearer(4, ["R-FINANCE"])
    for url in ("/api/v1/procurement/requisitions", "/api/v1/procurement/orders",
                "/api/v1/asset/ledger", "/api/v1/consumable"):
        r = c.get(url, **hdr)
        assert r.status_code == 200, f"{url} → HTTP {r.status_code}"
        assert r.json()["code"] == 0
    # 空 body → 40001（证明已过 casbin 进入 handler，而非 40301）
    r = c.post("/api/v1/procurement/requisitions",
               data=json.dumps({}), content_type="application/json", **hdr)
    assert r.status_code == 400 and r.json()["code"] == 40001


def test_finance_role_asset_issue_permission(seed_auth):
    """R-FINANCE：POST /asset/{id}/issue 过 casbin 到 handler（空 body → 40001 而非 40301）。"""
    from apps.asset.models import AAsset

    c = _c()
    a = AAsset.objects.create(tenant_id=1, creator_id=1, name="示波器", status="IDLE")
    r = c.post(f"/api/v1/asset/{a.id}/issue",
               data=json.dumps({}), content_type="application/json",
               **bearer(4, ["R-FINANCE"]))
    assert r.status_code == 400 and r.json()["code"] == 40001


def test_issue_idle_asset_status_changes_and_txn_recorded(seed_auth):
    """领用 IDLE 资产 → 状态变 IN_USE + 生成 REQUISITION 流水（前端「状态没变」回归）。"""
    from apps.asset.models import AAsset, AStockTxn

    c = _c()
    a = AAsset.objects.create(tenant_id=1, creator_id=2, name="激光粒度分析仪", status="IDLE")
    r = c.post(f"/api/v1/asset/{a.id}/issue",
               data=json.dumps({"projectId": 1, "usageRate": 0.5}), content_type="application/json",
               **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200 and r.json()["code"] == 0
    a.refresh_from_db()
    assert a.status == "IN_USE"
    assert a.project_id == 1
    assert AStockTxn.objects.filter(ref_asset_id=a.id, type="REQUISITION").exists()


def test_lifecycle_events_include_register_and_requisition(seed_auth):
    """GET /asset/{id}/lifecycle：事件时间线含 REGISTER 与领用流水（前端历史弹窗数据源）。"""
    from apps.asset.models import AAsset, AStockTxn

    c = _c()
    a = AAsset.objects.create(tenant_id=1, creator_id=2, name="离心机", status="IDLE")
    AStockTxn.objects.create(tenant_id=1, creator_id=2, code="TXN-T-1",
                             type="REQUISITION", ref_asset_id=a.id, qty=1,
                             balance_after=1, status="ISSUED", operator_id=2,
                             project_id=1)
    r = c.get(f"/api/v1/asset/{a.id}/lifecycle", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 200 and r.json()["code"] == 0
    events = r.json()["data"]["events"]
    stages = [e["stage"] for e in events]
    assert "REGISTER" in stages
    assert "ISSUE" in stages
    txn_ev = next(e for e in events if e["refType"] == "A_STOCK_TXN")
    assert txn_ev["detail"]["type"] == "REQUISITION"
