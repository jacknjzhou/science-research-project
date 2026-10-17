"""Phase 4 C 科研诚信与伦理域测试：案卷状态机→形式审查→分派（COI）→意见→会议→
批件（公开验证）→修正案/不良事件/年度复审；承诺签署 / 失信档案 / 申诉 / 检测 / 人遗备案。

角色按 policy.csv：R-STAFF 申请人；R-ETHICS 伦理办（形式审查/分派/会议/批件）；
R-EXPERT 委员（意见/签到/表决）；R-AUDITOR 纪检（失信档案）。
"""
import json

from django.test import Client

from apps.ethics.models import (
    CAmendment,
    CAeReport,
    CDecisionLetter,
    CEthicsCase,
    CIntegrityRecord,
    CMeetingRecord,
)
from tests.conftest import bearer


def _c():
    return Client()


def _json(r):
    return r.json()


def _case(**kw):
    base = dict(tenant_id=1, creator_id=2, review_type="HUMAN",
                applicant_user_id=2, protocol_title="靶向药物临床试验",
                protocol_summary="摘要", methodology="双盲 RCT",
                risk_level="MED", legal_entity_id=1)
    base.update(kw)
    return CEthicsCase.objects.create(**base)


# ===========================================================================
# 案卷状态机 + 形式审查 + 分派 COI + 意见 + 会议 + 批件
# ===========================================================================

def test_ethics_case_full_flow(seed_auth):
    c = _c()
    # 创建（R-STAFF）→ DRAFT，code=ETH-年-序
    r = c.post("/api/v1/ethics", data=json.dumps({
        "review_type": "HUMAN", "protocol_title": "新药试验", "applicant_user_id": 2,
        "protocol_summary": "摘要", "methodology": "双盲 RCT", "risk_level": "MED"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    case = _json(r)["data"]
    assert case["code"].startswith("ETH-2026-")
    assert case["status"] == "DRAFT"
    cid = case["id"]
    # 列表视图脱敏：protocol_summary=None
    lst = _json(c.get("/api/v1/ethics", **bearer(2, ["R-STAFF"])))["data"]["list"]
    assert lst[0]["protocol_summary"] is None
    # AI 预审：HUMAN 缺知情同意书与材料 → 未过
    r = c.post(f"/api/v1/ethics/{cid}/ai-prescreen", **bearer(2, ["R-STAFF"]))
    pre = _json(r)["data"]
    assert pre["passed"] is False
    assert set(pre["missing_fields"]) == {"informed_consent_url", "materials"}
    # 提交（带材料）→ FORMAL_CHECK；补齐后预审通过
    r = c.post(f"/api/v1/ethics/{cid}/submit", data=json.dumps({
        "materials": [{"name": "知情同意书", "url": "s3://a.pdf"}],
        "consent_url": "s3://consent.pdf"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["status"] == "FORMAL_CHECK"
    r = c.post(f"/api/v1/ethics/{cid}/ai-prescreen", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["passed"] is True
    # 非法直接分派（未形式审查通过）409
    r = c.post(f"/api/v1/ethics/{cid}/assign", data=json.dumps({
        "assignments": [{"reviewer_user_id": 1, "role": "CHIEF"}]}),
        content_type="application/json", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["code"] == 40901
    # 形式审查 OK → UNDER_REVIEW
    r = c.post(f"/api/v1/ethics/{cid}/formal-check", data=json.dumps({"result": "OK"}),
               content_type="application/json", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["data"]["status"] == "UNDER_REVIEW"
    # 分派 COI：委员=申请人 → 40901 强制回避
    r = c.post(f"/api/v1/ethics/{cid}/assign", data=json.dumps({
        "assignments": [{"reviewer_user_id": 2, "role": "CHIEF"}]}),
        content_type="application/json", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["code"] == 40901
    # 正常分派（admin 1 为 CHIEF，expert 用真实委员：seed 里只有 admin/staff，用 R-EXPERT bearer 模拟 uid=5）
    r = c.post(f"/api/v1/ethics/{cid}/assign", data=json.dumps({
        "assignments": [{"reviewer_user_id": 1, "role": "CHIEF"},
                        {"reviewer_user_id": 5, "role": "BOARD"},
                        {"reviewer_user_id": 6, "role": "BOARD"}]}),
        content_type="application/json", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["code"] == 0
    # 重复分派 409
    r = c.post(f"/api/v1/ethics/{cid}/assign", data=json.dumps({
        "assignments": [{"reviewer_user_id": 1, "role": "CHIEF"}]}),
        content_type="application/json", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["code"] == 40901
    # 非分派委员提交意见 → 403
    r = c.post(f"/api/v1/ethics/{cid}/opinion", data=json.dumps({
        "recommendation": "APPROVE", "score": 0.9}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40301
    # 委员 5 提交意见
    r = c.post(f"/api/v1/ethics/{cid}/opinion", data=json.dumps({
        "recommendation": "APPROVE", "score": 0.9, "comments": "方案可行",
        "risks_identified": [{"item": "样本量", "severity": "LOW"}]}),
        content_type="application/json", **bearer(5, ["R-EXPERT"]))
    assert _json(r)["code"] == 0
    # 重复意见 409
    r = c.post(f"/api/v1/ethics/{cid}/opinion", data=json.dumps({
        "recommendation": "APPROVE"}),
        content_type="application/json", **bearer(5, ["R-EXPERT"]))
    assert _json(r)["code"] == 40901
    # 会议签到 + 表决（达法定人数、approve>reject → APPROVED）
    r = c.post(f"/api/v1/ethics/{cid}/meeting/check-in", data=json.dumps({
        "attendees": [{"user_id": 1, "role": "CHIEF", "signed_in": True},
                      {"user_id": 5, "role": "BOARD", "signed_in": True},
                      {"user_id": 6, "role": "BOARD", "signed_in": True}]}),
        content_type="application/json", **bearer(1, ["R-EXPERT"]))
    assert _json(r)["data"]["status"] == "SCHEDULED"
    r = c.post(f"/api/v1/ethics/{cid}/meeting/vote", data=json.dumps({
        "decision": "APPROVE", "vote": {"approve": 3, "reject": 0, "abstain": 0},
        "quorum_met": True, "discussion_text": "一致通过"}),
        content_type="application/json", **bearer(1, ["R-EXPERT"]))
    body = _json(r)["data"]
    assert body["case"]["status"] == "APPROVED"
    assert body["meeting"]["vote_result"]["pass"] is True
    # 批件签发（R-EXPERT 主审角色按 policy 放行）→ PUBLISHED + 公开验证
    r = c.post(f"/api/v1/ethics/{cid}/letter", data=json.dumps({
        "decision_type": "APPROVE", "valid_until": "2027-10-17",
        "next_review_at": "2027-09-17", "publish": True}),
        content_type="application/json", **bearer(1, ["R-EXPERT"]))
    letter = _json(r)["data"]
    assert letter["letter_no"].startswith("PZ-ETH-")
    assert letter["status"] == "PUBLISHED"
    row = CEthicsCase.objects.get(id=cid)
    assert str(row.valid_until) == "2027-10-17"
    # 重复签发 409（1:1）
    r = c.post(f"/api/v1/ethics/{cid}/letter", data=json.dumps({"decision_type": "APPROVE"}),
               content_type="application/json", **bearer(1, ["R-EXPERT"]))
    assert _json(r)["code"] == 40901
    # 公开验证：无鉴权可查真伪，不含受试者内容
    r = c.get(f"/api/v1/ethics/letter/{letter['letter_no']}")
    v = _json(r)["data"]
    assert v["valid"] is True and v["letter_no"] == letter["letter_no"]
    assert "protocol" not in v
    # 不存在批件 → valid=false
    r = c.get("/api/v1/ethics/letter/PZ-NOTHING")
    assert _json(r)["data"]["valid"] is False
    return cid


def test_ethics_missing_docs_and_reject_path(seed_auth):
    c = _c()
    r = c.post("/api/v1/ethics", data=json.dumps({
        "review_type": "HUMAN", "protocol_title": "缺件试验", "applicant_user_id": 2}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    cid = _json(r)["data"]["id"]
    # AI 预审：缺摘要/方法学/知情同意/材料
    r = c.post(f"/api/v1/ethics/{cid}/ai-prescreen", **bearer(2, ["R-STAFF"]))
    pre = _json(r)["data"]
    assert pre["passed"] is False
    assert set(pre["missing_fields"]) == {"protocol_summary", "methodology", "informed_consent_url", "materials"}
    # 提交 → 形式审查 MISSING → NEEDS_REVISION
    c.post(f"/api/v1/ethics/{cid}/submit", data=json.dumps({}),
           content_type="application/json", **bearer(2, ["R-STAFF"]))
    r = c.post(f"/api/v1/ethics/{cid}/formal-check", data=json.dumps({
        "result": "MISSING", "missing_docs": ["知情同意书"], "comment": "补齐后重提"}),
        content_type="application/json", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["data"]["status"] == "NEEDS_REVISION"
    # 补件重提 → FORMAL_CHECK
    r = c.post(f"/api/v1/ethics/{cid}/submit", data=json.dumps({
        "materials": [{"name": "同意书", "url": "s3://b.pdf"}]}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["status"] == "FORMAL_CHECK"
    # 走到 UNDER_REVIEW → 会议否决 → REJECTED
    c.post(f"/api/v1/ethics/{cid}/formal-check", data=json.dumps({"result": "OK"}),
           content_type="application/json", **bearer(1, ["R-ETHICS"]))
    c.post(f"/api/v1/ethics/{cid}/assign", data=json.dumps({
        "assignments": [{"reviewer_user_id": 1, "role": "CHIEF"}]}),
        content_type="application/json", **bearer(1, ["R-ETHICS"]))
    c.post(f"/api/v1/ethics/{cid}/meeting/check-in", data=json.dumps({
        "attendees": [{"user_id": 1, "role": "CHIEF", "signed_in": True}]}),
        content_type="application/json", **bearer(1, ["R-EXPERT"]))
    r = c.post(f"/api/v1/ethics/{cid}/meeting/vote", data=json.dumps({
        "decision": "REJECT", "vote": {"approve": 0, "reject": 1, "abstain": 0},
        "quorum_met": True}),
        content_type="application/json", **bearer(1, ["R-EXPERT"]))
    assert _json(r)["data"]["case"]["status"] == "REJECTED"


def test_amendment_ae_and_annual_review(seed_auth):
    c = _c()
    r = c.post("/api/v1/ethics", data=json.dumps({
        "review_type": "ANIMAL", "protocol_title": "动物实验", "applicant_user_id": 2,
        "protocol_summary": "摘要", "methodology": "方法", "risk_level": "LOW"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    cid = _json(r)["data"]["id"]
    # 未批件先提修正案 → 409
    r = c.post(f"/api/v1/ethics/{cid}/amendment", data=json.dumps({"change_summary": "改"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40901
    # 直批（ORM 置 APPROVED）后提修正案
    CEthicsCase.objects.filter(id=cid).update(status="APPROVED")
    r = c.post(f"/api/v1/ethics/{cid}/amendment", data=json.dumps({
        "change_summary": "样本量 60→80"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    am = _json(r)["data"]
    # 决定 APPROVE
    r = c.post(f"/api/v1/ethics/amendment/{am['id']}/decision", data=json.dumps({
        "decision": "APPROVE", "decision_note": "无新增风险"}),
        content_type="application/json", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["data"]["status"] == "APPROVED"
    # 严重不良事件 → 案卷 MONITORING
    r = c.post(f"/api/v1/ethics/{cid}/ae-report", data=json.dumps({
        "event_date": "2026-10-17T08:00:00", "severity": "SERIOUS",
        "description": "实验动物异常死亡", "action_taken": "隔离观察"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    ae = _json(r)["data"]
    assert CEthicsCase.objects.get(id=cid).status == "MONITORING"
    assert CAeReport.objects.get(id=ae["id"]).severity == "SERIOUS"
    # 非法 severity 40001
    r = c.post(f"/api/v1/ethics/{cid}/ae-report", data=json.dumps({
        "event_date": "2026-10-17", "severity": "WEIRD", "description": "x"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40001
    # 年度复审 2026 + 重复 409
    r = c.post(f"/api/v1/ethics/{cid}/annual-review", data=json.dumps({
        "review_year": 2026, "progress_summary": "按计划推进",
        "incidents": [{"ref": ae["id"]}]}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    ar = _json(r)["data"]
    assert CEthicsCase.objects.get(id=cid).next_review_at.year == 2027
    r = c.post(f"/api/v1/ethics/{cid}/annual-review", data=json.dumps({
        "review_year": 2026, "progress_summary": "重复"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40901
    # 复审列表（按案卷）
    r = c.get(f"/api/v1/ethics/{cid}/annual-review", **bearer(1, ["R-ETHICS"]))
    assert _json(r)["data"]["total"] >= 1


# ===========================================================================
# 诚信承诺 / 失信档案 / 申诉 / 检测 / 人遗
# ===========================================================================

def test_pledge_and_integrity_appeal_flow(seed_auth):
    c = _c()
    # 承诺签署（C-15）：存证字段
    r = c.post("/api/v1/integrity/pledge", data=json.dumps({
        "user_id": 2, "pledge_type": "APPLY", "content_version": "v1.2",
        "read_seconds": 45, "biz_ref_type": "APPLICATION", "biz_ref_id": 77}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    p = _json(r)["data"]
    assert p["read_seconds"] == 45 and p["signed_at"] is not None
    # 我的承诺 + 类型过滤
    r = c.get("/api/v1/integrity/pledge?pledge_type=APPLY", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["total"] == 1
    # 纪检建立失信档案
    r = c.post("/api/v1/integrity/records", data=json.dumps({
        "user_id": 2, "event_type_code": "DATA_FABRICATION",
        "discovered_date": "2026-10-01", "evidence": [{"name": "截图", "url": "s3://e.png"}]}),
        content_type="application/json", **bearer(3, ["R-AUDITOR"]))
    rec = _json(r)["data"]
    assert rec["investigation_status"] == "INVESTIGATING"
    assert rec["appeal_status"] == "NONE"
    # 本人可查，他人（非纪检）不可查
    r = c.get(f"/api/v1/integrity/records/{rec['id']}", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 0
    r = c.get(f"/api/v1/integrity/records/{rec['id']}", **bearer(4, ["R-EXPERT"]))
    assert _json(r)["code"] == 40301
    # 本人申诉
    r = c.post(f"/api/v1/integrity/records/{rec['id']}/appeal", data=json.dumps({
        "reason": "数据为正常统计处理", "deadline": "2026-11-01"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    ap = _json(r)["data"]
    assert ap["appeal_status"] == "FILED" and ap["status"] == "APPEALING"
    # 重复申诉 409
    r = c.post(f"/api/v1/integrity/records/{rec['id']}/appeal", data=json.dumps({"reason": "再"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40901
    # 纪检裁定维持 → 结案
    r = c.put(f"/api/v1/integrity/records/{rec['id']}", data=json.dumps({
        "investigation_status": "SUSTAINED", "appeal_status": "UPHELD",
        "decision": "通报批评", "sanction": "暂停申报资格 1 年",
        "sanction_effective_until": "2027-10-17"}),
        content_type="application/json", **bearer(3, ["R-AUDITOR"]))
    up = _json(r)["data"]
    assert up["status"] == "CLOSED"
    assert up["investigation_status"] == "SUSTAINED"
    assert up["appeal_resolved_at"] is not None
    # 检测：确定性落档 DONE/CLEAN
    r = c.post("/api/v1/integrity/misconduct-scan", data=json.dumps({
        "target_type": "PAPER", "target_id": 9, "scan_type": "TEXT_DUP",
        "engine": "CNKI", "triggered_by": "ON_REGISTER"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    sc = _json(r)["data"]
    assert sc["status"] == "DONE" and sc["verdict"] == "CLEAN"
    assert sc["engine"] == "CNKI"
    # 非法 target 40001
    r = c.post("/api/v1/integrity/misconduct-scan", data=json.dumps({
        "target_type": "USER", "target_id": 1, "scan_type": "TEXT_DUP"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40001
    # 人遗备案 + 同步
    r = c.post("/api/v1/hgr/filing", data=json.dumps({
        "project_id": 5, "filing_type_code": "COLLECT", "submission_date": "2026-10-17"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    hg = _json(r)["data"]
    assert hg["filing_no"].startswith("HGR-")
    r = c.post(f"/api/v1/hgr/filing/{hg['id']}/sync", **bearer(1, ["R-MANAGER"]))
    synced = _json(r)["data"]
    assert synced["status"] == "NATIONAL_RECEIVED"
    assert synced["national_approval_no"].startswith("HGR-EXT-")
    assert synced["sync_batch_id"].startswith("SYNC-")
    # 再次同步仍幂等通过（NATIONAL_RECEIVED 允许重推）
    r = c.post(f"/api/v1/hgr/filing/{hg['id']}/sync", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0
