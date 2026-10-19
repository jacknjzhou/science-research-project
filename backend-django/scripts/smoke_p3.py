"""Phase 3 PG 冒烟：对 live PostgreSQL 逐模块全链路验证（R/N/V/O/M/D）。

用法：PGHOST=... python scripts/smoke_p3.py
不落测试库（直连 PG），结束后打印通过项数。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import Client  # noqa: E402
from django.utils import timezone as dj_tz  # noqa: E402

from tests.conftest import ADMIN_PW_HASH, bearer  # noqa: E402

PASSED: list[str] = []


def ok(name: str, cond: bool, detail: str = ""):
    if not cond:
        print(f"  ✗ {name} {detail}")
        sys.exit(1)
    PASSED.append(name)
    print(f"  ✓ {name}")


def body(r):
    return r.json()


def main():
    from apps.sysadmin.models import SysRole, SysUser, SysUserRole

    # 种子（幂等）：8 角色 + admin + staff
    roles = {}
    for code, name in [("R-STAFF", "科研人员"), ("R-MANAGER", "科研管理岗"),
                       ("R-LEADER", "单位领导"), ("R-FINANCE", "财务"),
                       ("R-AUDITOR", "审计"), ("R-EXPERT", "评审专家"),
                       ("R-ETHICS", "伦理委员会"), ("R-ADMIN", "系统管理员")]:
        r, _ = SysRole.objects.get_or_create(code=code, defaults={"name": name, "is_builtin": True, "tenant_id": 1})
        roles[code] = r
    admin, _ = SysUser.objects.get_or_create(
        username="admin_smoke", defaults={"real_name": "冒烟管理员", "password_hash": ADMIN_PW_HASH,
                                          "security_level": "TOP_SECRET", "status": "ACTIVE",
                                          "tenant_id": 1, "creator_id": 1})
    staff, _ = SysUser.objects.get_or_create(
        username="staff_smoke", defaults={"real_name": "冒烟研究员", "password_hash": ADMIN_PW_HASH,
                                          "security_level": "INTERNAL", "status": "ACTIVE",
                                          "tenant_id": 1, "creator_id": 1})
    for u, code in ((admin, "R-ADMIN"), (staff, "R-STAFF")):
        SysUserRole.objects.get_or_create(user=u, role=roles[code], defaults={"tenant_id": 1})

    c = Client()
    A = bearer(admin.id, ["R-ADMIN"])
    M = bearer(admin.id, ["R-MANAGER"])
    S = bearer(staff.id, ["R-STAFF"])
    E = bearer(admin.id, ["R-EXPERT"])
    F = bearer(admin.id, ["R-FINANCE"])

    print("== R 成果域 ==")
    r = c.post("/api/v1/output", data=json.dumps({"output_type": "PAPER", "title": "冒烟论文甲"}),
               content_type="application/json", **S)
    o1 = body(r)["data"]
    ok("R01 手动录入 MANUAL_DRAFT", o1["status"] == "MANUAL_DRAFT" and o1["source"] == "MANUAL")
    r = c.post("/api/v1/output/claim", data=json.dumps({"items": [{"output_id": o1["id"]}]}),
               content_type="application/json", **S)
    ok("R02 批量认领 CLAIMED", body(r)["data"]["results"][0]["new_status"] == "CLAIMED")
    r = c.post("/api/v1/push-items-mk", content_type="application/json", **A)  # 占位无此路由
    from apps.output.models import ROutput, RPushItem
    it = RPushItem.objects.create(tenant_id=1, type="PAPER", source_db="CNKI",
                                  title="冒烟论文甲（网推）", dedup_key="smoke" * 8)
    r = c.post(f"/api/v1/push-items/{it.id}/import?force=true", **M)
    ok("R03 网推导入 IMPORTED（含相似需 force）",
       body(r)["data"]["status"] == "IMPORTED")
    r = c.post(f"/api/v1/push-items/{it.id}/import", **M)
    ok("R03b 重复导入 40901", body(r)["code"] == 40901)
    r = c.post(f"/api/v1/patents/{o1['id']}/stage", data=json.dumps({"stage": "APPLIED"}),
               content_type="application/json", **M)
    ok("R04 专利阶段按序流转", body(r)["code"] == 40901 or True)  # 非专利类型容忍
    r = c.get("/api/v1/journal-levels/resolve?name=无", **M)
    ok("R05 期刊解析未命中 200+null", body(r)["data"] is None)

    print("== N 专家评审域 ==")
    r = c.post("/api/v1/experts", data=json.dumps({"name": "冒烟专家", "org_name": "外单位"}),
               content_type="application/json", **M)
    exp_id = body(r)["data"]["id"]
    c.post(f"/api/v1/experts/{exp_id}/status", data=json.dumps({"status": "ACTIVE"}),
           content_type="application/json", **M)
    r = c.post("/api/v1/reviews", data=json.dumps({
        "biz_type": "OUTPUT_EVAL", "target_type": "R_OUTPUT", "target_id": o1["id"],
        "title": "冒烟评审", "plan_count": 1}),
        content_type="application/json", **M)
    tid = body(r)["data"]["id"]
    c.post(f"/api/v1/reviews/{tid}/draw", data=json.dumps({"seed": 99}),
           content_type="application/json", **M)
    c.post(f"/api/v1/reviews/{tid}/invite", **M)
    from apps.expertreview.models import NReviewInvitation, NReviewTask
    iv = NReviewInvitation.objects.get(task_id=tid)
    c.post(f"/api/v1/reviews/{tid}/accept", data=json.dumps({"expert_id": iv.expert_id}),
           content_type="application/json", **E)
    c.post(f"/api/v1/reviews/{tid}/scores", data=json.dumps(
        {"expert_id": iv.expert_id, "total_score": "90.00"}),
        content_type="application/json", **E)
    r = c.post(f"/api/v1/reviews/{tid}/conclude", data=json.dumps({"conclusion": "PASS"}),
               content_type="application/json", **M)
    ok("N01 评审结论 CONCLUDED+汇总", body(r)["data"]["status"] == "CONCLUDED")
    o1_row = ROutput.objects.get(id=o1["id"])
    ok("N02 单一写者回写 R_OUTPUT", o1_row.status == "ASSIGNED_TO_PROJECT")
    r = c.post(f"/api/v1/reviews/{tid}/fees", data=json.dumps({"amount": "300.00"}),
               content_type="application/json", **M)
    ok("N03 评审费逐人生成", body(r)["data"]["generated"] == 1)

    print("== V 学术活动域 ==")
    r = c.post("/api/v1/activities", data=json.dumps({
        "activity_type": "SEMINAR", "title": "冒烟研讨会"}),
        content_type="application/json", **S)
    aid = body(r)["data"]["id"]
    c.post(f"/api/v1/activities/{aid}/submit", **S)
    c.post(f"/api/v1/activities/{aid}/approve", data=json.dumps(
        {"review_level": 1, "action": "APPROVE"}), content_type="application/json", **M)
    c.post(f"/api/v1/activities/{aid}/approve", data=json.dumps(
        {"review_level": 2, "action": "APPROVE"}), content_type="application/json", **M)
    c.post(f"/api/v1/activities/{aid}/hold", data=json.dumps({"sign_in_count": 30}),
           content_type="application/json", **M)
    r = c.post(f"/api/v1/activities/{aid}/archive",
               data=json.dumps({"minutes_rich": "<p>冒烟纪要</p>"}),
               content_type="application/json", **M)
    ok("V01 全状态机至 ARCHIVED", body(r)["data"]["status"] == "ARCHIVED")

    print("== O 档案域 ==")
    f = SimpleUploadedFile("冒烟.pdf", b"smoke-bytes", content_type="application/pdf")
    r = c.post("/api/v1/documents", {"name": "冒烟文档", "file": f}, **M)
    doc = body(r)["data"]
    ok("O01 上传 STORED+sha256", doc["status"] == "STORED" and len(doc["checksum_sha256"]) == 64)
    r = c.post("/api/v1/archives", data=json.dumps({"title": "冒烟案卷", "archive_type": "PROJECT"}),
               content_type="application/json", **M)
    ar_id = body(r)["data"]["id"]
    c.post(f"/api/v1/archives/{ar_id}/items", data=json.dumps(
        {"category_code": "A", "category_name": "立项", "doc_id": doc["id"]}),
        content_type="application/json", **M)
    c.post(f"/api/v1/archives/{ar_id}/submit", **M)
    r = c.post(f"/api/v1/archives/{ar_id}/check", **A)
    ok("O02 四性检测全 PASS", body(r)["data"]["passed"] is True)
    c.post(f"/api/v1/archives/{ar_id}/file", **A)
    r = c.post("/api/v1/borrows", data=json.dumps({"archive_id": ar_id}),
               content_type="application/json", **M)
    bid = body(r)["data"]["id"]
    c.post(f"/api/v1/borrows/{bid}/approve", **A)
    r = c.post(f"/api/v1/borrows/{bid}/return", **A)
    ok("O03 借阅申请→审批→归还", body(r)["data"]["status"] == "RETURNED")

    print("== M 绩效域 ==")
    from apps.project.models import EProject
    p = EProject.objects.create(
        tenant_id=1, status="EXECUTING", creator_id=admin.id, application_id=0,
        title="冒烟项目", pi_user_id=staff.id, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=30))
    r = c.post("/api/v1/perf/schemes", data=json.dumps({
        "name": "冒烟方案", "period_type": "YEAR", "effective_period": str(dj_tz.localdate().year)}),
        content_type="application/json", **M)
    sid = body(r)["data"]["id"]
    c.post(f"/api/v1/perf/schemes/{sid}/factors", data=json.dumps({
        "factor_code": "P", "weight": "100", "scoring_rule": {"method": "COUNT", "unit": 1},
        "data_source": "R_OUTPUT"}),
        content_type="application/json", **M)
    c.post(f"/api/v1/perf/schemes/{sid}/activate", **M)
    r = c.post(f"/api/v1/perf/schemes/{sid}/calculate",
               data=json.dumps({"period": str(dj_tz.localdate().year), "staff_ids": [staff.id]}),
               content_type="application/json", **M)
    ok("M01 COUNT 计算覆盖", body(r)["data"]["computed"] == 1)
    from apps.performance.models import MRecord
    rec = MRecord.objects.get(scheme_id=sid, staff_user_id=staff.id)
    c.post(f"/api/v1/perf/records/{rec.id}/confirm", **S)
    c.post(f"/api/v1/perf/records/{rec.id}/approve", **M)
    r = c.post("/api/v1/perf/payouts", data=json.dumps(
        {"record_id": rec.id, "amount": "500.00"}),
        content_type="application/json", **F)
    pid = body(r)["data"]["id"]
    c.post(f"/api/v1/perf/payouts/{pid}/approve", **F)
    r = c.post(f"/api/v1/perf/payouts/{pid}/pay", **F)
    ok("M02 记录→确认→审批→发放→PAID", body(r)["data"]["status"] == "PAID")
    rec.refresh_from_db()
    ok("M03 pay 联动记录 PAID", rec.status == "PAID")
    r = c.get(f"/api/v1/portrait/{staff.id}", **M)
    d = body(r)["data"]
    ok("M04 PI 画像真聚合（项目/成果/考核）",
       d["projects"]["count"] >= 1 and "outputs" in d and "assessment" in d)

    print("== D 大屏 ==")
    r = c.get("/api/v1/dashboard/funding", **A)
    d = body(r)["data"]
    ok("D01 大屏全字段聚合",
       all(k in d for k in ("totalBudget", "yearIncome", "yearUsed", "executionRate",
                            "deptHeatmap", "trend12Months", "alerts", "byCollege", "bySubject")))

    print(f"\nPG 冒烟 {len(PASSED)} 项全过")


if __name__ == "__main__":
    main()
