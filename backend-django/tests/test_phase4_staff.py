"""Phase 4 S 人员与团队域测试：档案/me/异动、画像聚合、合作网络、AI 标签/简历、
团队成员（在册唯一/快照同步/移除留痕）、客座申请审批（建档）、学生登记、人才计划/梯队。

角色按 policy.csv：R-STAFF 读+me 编辑；R-MANAGER 写（异动/团队/客座审批/学生）。
"""
import json

from django.test import Client

from apps.staff.models import (
    SCollabGraph,
    SMembership,
    SPortrait,
    SStaff,
    SStudent,
    STalentPlan,
    STeam,
    SVisitor,
)
from tests.conftest import bearer


def _c():
    return Client()


def _json(r):
    return r.json()


def _staff(user_id=2, **kw):
    base = dict(tenant_id=1, creator_id=1, user_id=user_id, hr_code=f"EMP{user_id:04d}",
                name=f"学者{user_id}", department_id=10, staff_type="FORMAL",
                employment_status="ONBOARD", legal_entity_id=1)
    base.update(kw)
    return SStaff.objects.create(**base)


# ===========================================================================
# 人员档案 / me / 异动
# ===========================================================================

def test_staff_me_and_transfer(seed_auth):
    c = _c()
    s = _staff(user_id=2, title="研究员", bio="从事催化研究、材料表征",
               research_expertise=[{"tag": "催化", "weight": 0.6, "source": "MANUAL"}],
               id_card_hash="hash123")
    # me：含 teams/students 标签页数据源
    r = c.get("/api/v1/staff/me", **bearer(2, ["R-STAFF"]))
    me = _json(r)["data"]
    assert me["name"] == "学者2"
    assert me["id_card_masked"] == "******"  # 敏感脱敏
    assert "id_card_hash" not in me
    # 无档案用户 404
    r = c.get("/api/v1/staff/me", **bearer(3, ["R-STAFF"]))
    assert _json(r)["code"] == 40401
    # me/research 编辑：MANUAL 保留 + bio 更新
    r = c.put("/api/v1/staff/me/research", data=json.dumps({
        "bio": "新能源材料方向", "external_appointments": [{"org": "X学会", "role": "理事"}]}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    up = _json(r)["data"]
    assert up["bio"] == "新能源材料方向"
    assert up["external_appointments"][0]["org"] == "X学会"
    assert up["research_expertise"][0]["source"] == "MANUAL"  # 自建标签保留
    # 列表筛选
    r = c.get("/api/v1/staff?keyword=学者&staff_type=FORMAL", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["total"] >= 1
    # 异动：调岗
    r = c.post(f"/api/v1/staff/{s.id}/transfer", data=json.dumps({
        "action": "TRANSFER_DEPT", "target_department_id": 20,
        "effective_date": "2026-11-01", "reason": "双聘"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    tr = _json(r)["data"]
    assert tr["department_id"] == 20
    assert SStaff.objects.get(id=s.id).leave_date is not None
    # 离职：INACTIVE + is_pi 置否 + 留痕
    r = c.post(f"/api/v1/staff/{s.id}/transfer", data=json.dumps({
        "action": "RESIGN", "handover_pi_staff_id": 9, "reason": "个人原因"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    tr = _json(r)["data"]
    assert tr["employment_status"] == "RESIGNED"
    row = SStaff.objects.get(id=s.id)
    assert row.status == "INACTIVE" and row.is_pi is False
    assert "交接 PI: 9" in (row.remark or "")
    # 非法 action 40001
    r = c.post(f"/api/v1/staff/{s.id}/transfer", data=json.dumps({"action": "FIRE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40001


# ===========================================================================
# 画像 / 合作网络 / AI
# ===========================================================================

def test_portrait_refresh_and_collab_graph(seed_auth):
    c = _c()
    s = _staff(user_id=2, is_pi=True,
               research_expertise=[{"tag": "催化", "weight": 0.5, "source": "MANUAL"}])
    from apps.project.models import EProject
    from apps.output.models import ROutput
    from datetime import timedelta
    from django.utils import timezone as tz
    EProject.objects.create(tenant_id=1, creator_id=1, status="EXECUTING", application_id=0,
                            title="催化项目", pi_user_id=2, member_ids=[],
                            start_date=tz.localdate(), end_date=tz.localdate() + timedelta(days=30),
                            legal_entity_id=1)
    ROutput.objects.create(tenant_id=1, creator_id=1, output_type="PAPER", title="论文A",
                           authors=[2], source="MANUAL", legal_entity_id=1)
    SStudent.objects.create(tenant_id=1, creator_id=1, staff=_staff(user_id=7, hr_code="S1"),
                            student_type="PHD", supervisor_staff=s)
    # 画像刷新 → 确定性聚合
    r = c.post(f"/api/v1/staff/{s.id}/portrait", **bearer(1, ["R-MANAGER"]))
    p = _json(r)["data"]
    assert p["project_count_total"] == 1 and p["project_count_active"] == 1
    assert p["output_count_papers"] == 1
    assert p["mentoring_count"] == 1
    assert p["snapshot_date"] is not None
    # 画像查询（R-AUDITOR 可见 integrity_flag）
    r = c.get(f"/api/v1/staff/{s.id}/portrait", **bearer(3, ["R-AUDITOR"]))
    assert "integrity_flag" in _json(r)["data"]
    r = c.get(f"/api/v1/staff/{s.id}/portrait", **bearer(2, ["R-STAFF"]))
    assert "integrity_flag" not in _json(r)["data"]
    # 合作网络：边 + 节点度
    SCollabGraph.objects.create(tenant_id=1, creator_id=1, staff_a_id=s.id,
                                staff_b_id=9, snapshot_date=tz.localdate(), weight=3)
    r = c.get(f"/api/v1/staff/{s.id}/collab-graph", **bearer(2, ["R-STAFF"]))
    g = _json(r)["data"]
    assert g["center_staff_id"] == s.id
    assert len(g["edges"]) == 1 and g["edges"][0]["weight"] == 3
    assert g["nodes"][0]["degree"] == 1
    # 无边学者 → 空图不报错
    s2 = _staff(user_id=3, hr_code="E3")
    r = c.get(f"/api/v1/staff/{s2.id}/collab-graph", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["edges"] == []
    # AI 方向标签（增量）
    r = c.post(f"/api/v1/staff/{s.id}/ai-expertise", data=json.dumps({"incremental": True}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    tags = _json(r)["data"]["tags"]
    assert tags[0]["tag"] == "催化"
    # AI 简历
    r = c.post(f"/api/v1/staff/{s.id}/ai-resume", data=json.dumps({"format": "PDF"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    cv = _json(r)["data"]
    assert cv["name"] == "学者2" and cv["download_url"].endswith(".pdf")
    assert cv["portrait"]["output_count_papers"] == 1


# ===========================================================================
# 团队 / 成员
# ===========================================================================

def test_team_member_lifecycle(seed_auth):
    c = _c()
    pi = _staff(user_id=2, name="PI学者")
    m1 = _staff(user_id=5, name="成员一")
    m2 = _staff(user_id=6, name="成员二")
    # 建团队（PI 自动 LEADER 在册 + is_pi 置位 + member_ids 快照同步）
    r = c.post("/api/v1/teams", data=json.dumps({
        "name": "催化课题组", "pi_staff_id": pi.id, "team_type": "PI_GROUP"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    t = _json(r)["data"]
    assert t["member_count"] == 1
    assert SStaff.objects.get(id=pi.id).is_pi is True
    tid = t["id"]
    # 新增成员
    r = c.post(f"/api/v1/teams/{tid}/members", data=json.dumps({
        "staff_id": m1.id, "role": "CORE", "contribution_summary": "表征担当"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["team_member_count"] == 2
    # 重复在册 409
    r = c.post(f"/api/v1/teams/{tid}/members", data=json.dumps({
        "staff_id": m1.id, "role": "MEMBER"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 非法 role 40001
    r = c.post(f"/api/v1/teams/{tid}/members", data=json.dumps({
        "staff_id": m2.id, "role": "BOSS"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40001
    # 团队详情：成员时间轴
    r = c.get(f"/api/v1/teams/{tid}", **bearer(2, ["R-STAFF"]))
    detail = _json(r)["data"]
    assert detail["member_count"] == 2
    assert [m["role"] for m in detail["members"]] == ["LEADER", "CORE"]
    # 移除成员：left_at + 快照同步
    r = c.post(f"/api/v1/teams/{tid}/members/remove", data=json.dumps({
        "staff_id": m1.id, "reason": "项目结束"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    rm = _json(r)["data"]
    assert rm["team_member_count"] == 1
    row = SMembership.objects.get(id=rm["id"])
    assert row.left_at is not None and row.status == "LEFT"
    # include_left=true 可见已退出
    r = c.get(f"/api/v1/teams/{tid}/members?include_left=true", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["total"] == 2
    # 移除不在册成员 404
    r = c.post(f"/api/v1/teams/{tid}/members/remove", data=json.dumps({"staff_id": m1.id}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40401


# ===========================================================================
# 客座 / 学生 / 人才计划 / 梯队
# ===========================================================================

def test_visitor_student_talent(seed_auth):
    c = _c()
    host = _staff(user_id=2, is_pi=True)
    # 客座申请：建 S_STAFF 档 + S_VISITOR
    r = c.post("/api/v1/visitors", data=json.dumps({
        "name": "张客座", "home_institution": "海外大学",
        "hr_code_placeholder": "VIS001", "host_pi_staff_id": host.id,
        "visit_type": "LONG_TERM", "start_date": "2026-11-01", "end_date": "2027-10-31",
        "permissions_scope": {"modules": ["project", "output"], "project_ids": [1]}}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    v = _json(r)["data"]
    assert v["status"] == "APPLIED"
    srow = SStaff.objects.get(id=v["staff_id"])
    assert srow.staff_type == "VISITING_SCHOLAR"
    assert srow.employment_status == "VISITING"
    # 工号重复 409
    r = c.post("/api/v1/visitors", data=json.dumps({
        "name": "重复", "hr_code_placeholder": "VIS001", "host_pi_staff_id": host.id,
        "visit_type": "SHORT_TERM", "start_date": "2026-11-01", "end_date": "2026-12-01",
        "permissions_scope": {}}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 审批 APPROVE → role_codes 写入授权范围
    r = c.post(f"/api/v1/visitors/{v['id']}/approve", data=json.dumps({
        "decision": "APPROVE", "role_codes": ["R-VISITOR"], "expires_at": "2027-10-31",
        "comment": "同意"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    ap = _json(r)["data"]
    assert ap["status"] == "APPROVED"
    assert ap["permissions_scope"]["role_codes"] == ["R-VISITOR"]
    # 重复审批 409
    r = c.post(f"/api/v1/visitors/{v['id']}/approve", data=json.dumps({"decision": "REJECT"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # REJECT 路径
    r = c.post("/api/v1/visitors", data=json.dumps({
        "name": "李客座", "hr_code_placeholder": "VIS002", "host_pi_staff_id": host.id,
        "visit_type": "SHORT_TERM", "start_date": "2026-11-01", "end_date": "2026-12-01",
        "permissions_scope": {}}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    v2 = _json(r)["data"]
    r = c.post(f"/api/v1/visitors/{v2['id']}/approve", data=json.dumps({"decision": "REJECT"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "REJECTED"
    # 学生登记
    r = c.post("/api/v1/students", data=json.dumps({
        "name": "王同学", "student_type": "PHD", "supervisor_staff_id": host.id,
        "enroll_year": 2026, "thesis_topic": "催化机理"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    st = _json(r)["data"]
    assert SStaff.objects.get(id=st["staff_id"]).staff_type == "STUDENT"
    # 人才计划（ORM 建档 + 查询）
    STalentPlan.objects.create(tenant_id=1, creator_id=1, staff=host,
                               plan_name="优秀青年科学基金", level="NATIONAL",
                               awarded_year=2025, duration_years=3, end_year=2028)
    r = c.get(f"/api/v1/staff/{host.id}/talent-plans", **bearer(2, ["R-STAFF"]))
    tp = _json(r)["data"]["list"]
    assert tp[0]["plan_name"].startswith("优秀青年")
    # 梯队分析：国家级在期 1 人，无缺口提示
    r = c.get("/api/v1/talent/analysis", **bearer(1, ["R-MANAGER"]))
    ta = _json(r)["data"]
    assert ta["active_by_level"]["NATIONAL"] == 1
    assert ta["total_pi"] >= 1
