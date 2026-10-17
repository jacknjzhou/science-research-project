"""Phase 4 PG 冒烟：对 live PostgreSQL 逐域全链路验证（T/C/S/G/A/X + svc-ai）。

用法：python scripts/smoke_p4.py（直连 PG，默认 localhost/ark；幂等种子，可重复执行）
不落测试库，结束后打印通过项数；任一断言失败立即退出。
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

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


def post(c, url, data, **auth):
    return c.post(url, data=json.dumps(data), content_type="application/json", **auth)


def main():
    from apps.funding.models import FBudgetLine, FSubject
    from apps.sysadmin.models import SysRole, SysUser, SysUserRole

    # 种子（幂等）：8 角色 + admin/staff 冒烟用户
    roles = {}
    for code, name in [("R-STAFF", "科研人员"), ("R-MANAGER", "科研管理岗"),
                       ("R-LEADER", "单位领导"), ("R-FINANCE", "财务"),
                       ("R-AUDITOR", "审计"), ("R-EXPERT", "评审专家"),
                       ("R-ETHICS", "伦理委员会"), ("R-ADMIN", "系统管理员")]:
        r, _ = SysRole.objects.get_or_create(
            code=code, defaults={"name": name, "is_builtin": True, "tenant_id": 1})
        roles[code] = r
    admin, _ = SysUser.objects.get_or_create(
        username="admin_smoke", defaults={
            "real_name": "冒烟管理员", "password_hash": ADMIN_PW_HASH,
            "security_level": "TOP_SECRET", "status": "ACTIVE", "tenant_id": 1,
            "creator_id": 1})
    staff, _ = SysUser.objects.get_or_create(
        username="staff_smoke", defaults={
            "real_name": "冒烟研究员", "password_hash": ADMIN_PW_HASH,
            "security_level": "INTERNAL", "status": "ACTIVE", "tenant_id": 1,
            "creator_id": 1})
    for u, code in ((admin, "R-ADMIN"), (staff, "R-STAFF")):
        SysUserRole.objects.get_or_create(user=u, role=roles[code], defaults={"tenant_id": 1})

    c = Client()
    A = bearer(admin.id, ["R-ADMIN"])
    M = bearer(admin.id, ["R-MANAGER"])
    S = bearer(staff.id, ["R-STAFF"])
    F = bearer(admin.id, ["R-FINANCE"])
    MFA = {"HTTP_X_MFA_ASSERT": "smoke-mfa"}

    # 预算种子（G 域依赖）
    sub, _ = FSubject.objects.get_or_create(
        tenant_id=1, code="S-SMOKE", defaults={"name": "冒烟设备费", "category": "DIRECT",
                                               "creator_id": admin.id})
    line, _ = FBudgetLine.objects.get_or_create(
        tenant_id=1, budget_id=0, subject_id=sub.id,
        defaults={"amount_planned": Decimal("100000"), "creator_id": admin.id})

    # ------------------------------------------------------------------
    print("== T 成果转化域 ==")
    from apps.output.models import ROutput
    out, _ = ROutput.objects.get_or_create(
        tenant_id=1, title="冒烟转化专利", defaults={
            "status": "MANUAL_DRAFT", "creator_id": staff.id, "output_type": "PATENT",
            "authors": [], "project_ids": [], "source": "MANUAL", "legal_entity_id": 1})
    r = post(c, "/api/v1/disclosure", {
        "output_id": out.id, "disclosure_date": dj_tz.localdate().isoformat(),
        "tech_summary": "冒烟技术摘要", "maturity_level": 5, "is_core_tech": False,
        "application_scenarios": [{"scene": "化工", "desc": "催化"}]}, **S)
    if body(r)["code"] == 40901:  # 幂等重跑：已有披露
        from apps.transform.models import TDisclosure
        d_id = TDisclosure.objects.filter(output_id=out.id).first().id
    else:
        d_id = body(r)["data"]["id"]
        post(c, f"/api/v1/disclosure/{d_id}/submit", {}, **S)
    r = post(c, f"/api/v1/disclosure/{d_id}/valuation",
             {"valuator_type": "INTERNAL", "valuation_amount": "50000"}, **M)
    ok("T01 披露+评估链路", body(r)["code"] in (0, 40901))

    # ------------------------------------------------------------------
    print("== C 诚信伦理域 ==")
    r = post(c, "/api/v1/ethics", {
        "review_type": "HUMAN", "protocol_title": "冒烟伦理项目",
        "applicant_user_id": staff.id, "protocol_summary": "摘要",
        "methodology": "方法", "informed_consent_url": "http://x/consent",
        "materials": ["协议书"]}, **S)
    assert body(r)["code"] == 0, body(r)
    case_id = body(r)["data"]["id"]
    r = post(c, f"/api/v1/ethics/{case_id}/ai-prescreen", {}, **S)
    ok("C01 建卷+AI预审", body(r)["code"] == 0
       and "missing_fields" in body(r)["data"])

    # ------------------------------------------------------------------
    print("== S 人员团队域 ==")
    from apps.staff.models import SStaff
    SStaff.objects.get_or_create(
        tenant_id=1, user_id=staff.id,
        defaults={"hr_code": "SMOKE-HR-001", "name": "冒烟研究员",
                  "creator_id": admin.id, "employment_status": "ACTIVE",
                  "department_id": 0})
    r = c.get("/api/v1/staff/me", **S)
    ok("S01 /staff/me", body(r)["code"] == 0)

    # ------------------------------------------------------------------
    print("== G 采购与合同域 ==")
    r = post(c, "/api/v1/procurement/requisitions", {
        "project_id": 1, "category": "设备", "item_name": "冒烟离心机",
        "est_amount": "5000", "budget_subject_code": "S-SMOKE"}, **S)
    if body(r)["code"] == 40910:  # 冒烟额度被历史冻结占满 → 补额度重试
        line.amount_planned = line.amount_planned + Decimal("100000")
        line.save()
        r = post(c, "/api/v1/procurement/requisitions", {
            "project_id": 1, "category": "设备", "item_name": "冒烟离心机",
            "est_amount": "5000", "budget_subject_code": "S-SMOKE"}, **S)
    ok("G01 申请即冻结+方式判定", body(r)["code"] == 0
       and body(r)["data"]["status"] == "WAY_DECIDED")
    r = c.get(f"/api/v1/procurement/requisitions/{body(r)['data']['id']}/way", **S)
    ok("G02 方式判定可复算", body(r)["data"]["purchase_way"] == "自行采购")

    # ------------------------------------------------------------------
    print("== A 资产与耗材域 ==")
    r = post(c, "/api/v1/asset", {
        "assetType": "FIXED", "categoryCode": "CAT-SMOKE", "name": "冒烟资产",
        "serialNo": f"SN-SMOKE-{dj_tz.now().strftime('%H%M%S%f')}",
        "value": "120000", "custodianId": staff.id, "deptId": 1,
        "deprMethod": "STRAIGHT_LINE", "deprYears": 10, "projectId": 1}, **M)
    assert body(r)["code"] == 0, body(r)
    aid = body(r)["data"]["id"]
    r = post(c, "/api/v1/asset/depreciation/run", {"period": dj_tz.now().strftime("%Y-%m")},
             **M)
    ok("A01 建卡+当月折旧幂等", body(r)["code"] == 0
       and body(r)["data"]["processedCount"] >= 0)
    r = post(c, "/api/v1/consumable/SKU-SMOKE/stock-in",
             {"batchNo": "B-SMOKE", "expireDate": "2030-01-01", "qty": "10",
              "name": "冒烟试剂", "category": "REAGENT"}, **S)
    ok("A02 耗材入库", body(r)["code"] == 0 and body(r)["data"]["balanceAfter"] >= 10)

    # ------------------------------------------------------------------
    print("== X 涉密治理域 ==")
    r = post(c, "/api/v1/security/policy",
             {"matrixJson": {"SECRET": {"visible_zones": ["SECRET_NET"]}},
              "appliedModules": ["SMOKE"]}, **A, **MFA)
    if body(r)["code"] == 0:
        ok("X01 策略发布（MFA）", True)
    else:
        ok("X01 策略发布（MFA）", body(r)["code"] == 0, str(body(r)))
    r = post(c, "/api/v1/security/export", {
        "direction": "DOWN", "objectType": "DOC", "objectId": 1,
        "toDomain": "OFFICE", "payloadDigest": "SMOKE-DIGEST",
        "securityLevel": "SECRET"}, **S)
    ex_id = body(r)["data"]["id"]
    r = post(c, "/api/v1/security/export/approve",
             {"exportId": ex_id, "stage": "PRE_REVIEW", "verdict": "PASS",
              "approverId": admin.id}, **A)
    r = post(c, "/api/v1/security/export/approve",
             {"exportId": ex_id, "stage": "SEC_REVIEW", "verdict": "PASS"}, **A)
    r = post(c, "/api/v1/security/export/release",
             {"exportId": ex_id, "actualPayloadDigest": "SMOKE-DIGEST"}, **A, **MFA)
    ok("X02 输出双审+放行", body(r)["data"]["status"] == "RELEASED")
    r = c.get("/api/v1/security/log?risk=true", **bearer(admin.id, ["R-AUDITOR"]))
    ok("X03 安全日志哈希链完好", body(r)["data"]["chainIntact"] is True)

    # ------------------------------------------------------------------
    print("== svc-ai（进程内 TestClient）==")
    from fastapi.testclient import TestClient
    from svc_ai.main import app as ai_app
    ac = TestClient(ai_app)
    hz = ac.get("/healthz").json()
    ok("AI01 healthz", hz["status"] == "ok")
    r = ac.post("/ai/expense/review", json={"expense": {"amount": 100, "invoice_id": 1}})
    b = r.json()
    ok("AI02 降级契约 REVIEW/0/llm-unavailable",
       b["verdict"] == "REVIEW" and b["confidence"] == 0
       and b["reasons"] == ["llm-unavailable"])

    print(f"\nPhase 4 PG 冒烟通过 {len(PASSED)} 项")


if __name__ == "__main__":
    main()
