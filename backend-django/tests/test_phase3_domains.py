"""Phase 3 域测试：R 成果/认领/治理、N 专家/评审/回写、V 活动、O 档案/四性/借阅、M 绩效/计算/发放、D 大屏。

角色按 policy.csv：R 写治理用 R-MANAGER；V approve 用 R-MANAGER/R-LEADER；
O 入库/销毁/借阅审批用 R-ADMIN；M calculate 用 R-MANAGER、payout 用 R-FINANCE。
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.test import Client
from django.utils import timezone as dj_tz

from apps.archive.models import OArchive, ODocument, OArchiveItem
from apps.expertreview.models import NExpert, NReviewInvitation, NReviewTask
from apps.funding.models import FBudget, FBudgetLine, FExpense, FIncome
from apps.output.models import ROutput, RPushItem
from apps.performance.models import MPayout, MRecord, MScheme, MSchemeFactor
from apps.project.models import EProject
from apps.activity.models import VActivity
from tests.conftest import bearer


def _c():
    return Client()


def _json(r):
    return r.json()


def _project(**kw):
    base = dict(
        tenant_id=1, status="EXECUTING", creator_id=1, application_id=0,
        title="绩效测试项目", pi_user_id=2, member_ids=[], legal_entity_id=1,
        start_date=dj_tz.localdate(), end_date=dj_tz.localdate() + timedelta(days=180),
    )
    base.update(kw)
    return EProject.objects.create(**base)


# ===========================================================================
# R 成果域
# ===========================================================================

def test_output_create_and_claim_chain(seed_auth):
    c = _c()
    # R-STAFF 手动录入（MANUAL_DRAFT + title_hash）
    r = c.post("/api/v1/output", data=json.dumps({
        "output_type": "PAPER", "title": "  Deep Learning for Science  "}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    out = _json(r)["data"]
    assert out["status"] == "MANUAL_DRAFT"
    assert out["source"] == "MANUAL"
    assert out["claim_status"] == "UNCLAIMED"
    # title_hash = sha256(lower(trim(title)))：mapper 不输出（契约字段外），查库验证
    import hashlib
    row = ROutput.objects.get(id=out["id"])
    assert row.title_hash == hashlib.sha256(
        b"deep learning for science").hexdigest()
    # 多条件列表
    r = c.get("/api/v1/output?output_type=PAPER&kw=deep", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["total"] == 1
    # 详情
    r = c.get(f"/api/v1/output/{out['id']}", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["title"] == "  Deep Learning for Science  "


def test_output_batch_claim_three_actions(seed_auth):
    c = _c()
    ids = [ROutput.objects.create(
        tenant_id=1, creator_id=2, output_type="PAPER", title=f"论文{i}",
        source="FETCH", status="PENDING_CLAIM").id for i in range(3)]
    # CLAIM
    r = c.post("/api/v1/output/claim", data=json.dumps({
        "action": "CLAIM", "items": [{"output_id": ids[0]}]}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    d = _json(r)["data"]
    assert d["results"][0]["success"] is True
    assert d["results"][0]["new_status"] == "CLAIMED"
    assert d["batch_id"].startswith("B")
    o = ROutput.objects.get(id=ids[0])
    assert o.claim_status == "CLAIMED" and o.is_claimed is True
    # REJECT
    c.post("/api/v1/output/reject", data=json.dumps({
        "reason": "非本人", "items": [{"output_id": ids[1]}]}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    o = ROutput.objects.get(id=ids[1])
    assert (o.claim_status, o.status, o.is_claimed) == ("REJECTED", "REJECTED", False)
    # MARK_NOT_MINE
    c.post("/api/v1/output/mark-not-mine", data=json.dumps({
        "items": [{"output_id": ids[2]}]}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    o = ROutput.objects.get(id=ids[2])
    assert (o.claim_status, o.status, o.is_claimed) == ("NOT_MINE", "PENDING_CLAIM", False)
    # 批量上限 101 → 40001
    r = c.post("/api/v1/output/claim", data=json.dumps({
        "items": [{"output_id": 1}] * 101}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40001


def test_output_link_projects_and_single_writer(seed_auth):
    c = _c()
    p = _project()
    o = ROutput.objects.create(
        tenant_id=1, creator_id=2, output_type="PAPER", title="关联项目论文",
        source="MANUAL", status="CLAIMED", claim_status="CLAIMED", is_claimed=True)
    # R-MANAGER PUT 关联（契约动词 PUT）
    r = c.put(f"/api/v1/output/{o.id}/projects", data=json.dumps({
        "project_ids": [p.id], "relation_type": "PRIMARY"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["linked"] == 1
    o.refresh_from_db()
    assert o.status == "ASSIGNED_TO_PROJECT"
    # 单一写者：conclude_output_eval(False) → REJECTED
    from apps.output.api import conclude_output_eval
    conclude_output_eval(o.id, False)
    o.refresh_from_db()
    assert o.status == "REJECTED"
    conclude_output_eval(o.id, True)
    o.refresh_from_db()
    assert o.status == "ASSIGNED_TO_PROJECT" and o.is_claimed is True


def test_push_item_import_dedup_and_force(seed_auth):
    c = _c()
    it = RPushItem.objects.create(
        tenant_id=1, type="PAPER", source_db="CNKI", title="网推论文甲",
        dedup_key="deadbeef" * 8)
    # R-MANAGER 导入（治理域角色）
    r = c.post(f"/api/v1/push-items/{it.id}/import", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "IMPORTED"
    oid = _json(r)["data"]["output_id"]
    o = ROutput.objects.get(id=oid)
    assert o.status == "PENDING_CLAIM" and o.source == "CNKI"
    # 已导入再导 → 40901
    r = c.post(f"/api/v1/push-items/{it.id}/import", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 精确重复：dedup_key 命中 title_hash → 40905 + existing_id
    it2 = RPushItem.objects.create(
        tenant_id=1, type="PAPER", source_db="WOS", title="网推论文乙",
        dedup_key=o.title_hash)
    r = c.post(f"/api/v1/push-items/{it2.id}/import", **bearer(1, ["R-MANAGER"]))
    body = _json(r)
    assert body["code"] == 40905
    assert body["data"]["existing_id"] == oid
    # 相似标题 → need_force
    it3 = RPushItem.objects.create(
        tenant_id=1, type="PAPER", source_db="WANFANG", title="网推论文甲（续）",
        dedup_key="cafe" * 16)
    r = c.post(f"/api/v1/push-items/{it3.id}/import", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"].get("need_force") is True
    # force=true 强制导入
    r = c.post(f"/api/v1/push-items/{it3.id}/import?force=true", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "IMPORTED"
    # ignore 幂等
    r = c.post(f"/api/v1/push-items/{it3.id}/ignore", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["ignored"] is True


def test_patent_stage_and_fees(seed_auth):
    c = _c()
    o = ROutput.objects.create(
        tenant_id=1, creator_id=1, output_type="PATENT", title="测试专利",
        source="CNIPA", status="CLAIMED", stage="APPLIED")
    # 按序 +1
    r = c.post(f"/api/v1/patents/{o.id}/stage", data=json.dumps({"stage": "PUBLISHED"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["stage"] == "PUBLISHED"
    # 跳级 → 40901
    r = c.post(f"/api/v1/patents/{o.id}/stage", data=json.dumps({"stage": "TRANSFERRED"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 原地幂等
    r = c.post(f"/api/v1/patents/{o.id}/stage", data=json.dumps({"stage": "PUBLISHED"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0
    # 年费
    r = c.post(f"/api/v1/patents/{o.id}/fees", data=json.dumps(
        {"year": 2026, "amount": "900.00"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    fee = _json(r)["data"]
    assert fee["amount"] == "900.00" and fee["status"] == "UNPAID"
    r = c.get(f"/api/v1/patents/{o.id}/fees", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["total"] == 1


def test_journal_governance(seed_auth):
    c = _c()
    r = c.post("/api/v1/journal-sources", data=json.dumps({"name": "SCI源库", "issn": "1234-5678"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    src = _json(r)["data"]
    r = c.post("/api/v1/journal-levels", data=json.dumps(
        {"code": "Q1", "name": "一区期刊"}), content_type="application/json",
        **bearer(1, ["R-MANAGER"]))
    lv = _json(r)["data"]
    r = c.post(f"/api/v1/journal-levels/{lv['id']}/sources",
               data=json.dumps({"source_id": src["id"], "year_from": 2024}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0
    # resolve 命中 / 未命中 200+null
    r = c.get("/api/v1/journal-levels/resolve?name=一区期刊&year=2025",
              **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["level_code"] == "Q1"
    r = c.get("/api/v1/journal-levels/resolve?name=不存在&year=2025",
              **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"] is None
    # 转载登记
    o = ROutput.objects.create(tenant_id=1, creator_id=1, output_type="PAPER",
                               title="被转载论文", source="MANUAL", status="CLAIMED")
    r = c.post(f"/api/v1/papers/{o.id}/reprints", data=json.dumps(
        {"name": "人大复印资料", "type": "FULL_TEXT"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0
    r = c.get(f"/api/v1/papers/{o.id}/reprints", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["total"] == 1


# ===========================================================================
# N 专家评审域
# ===========================================================================

def _seed_experts(n=5):
    out = []
    for i in range(n):
        out.append(NExpert.objects.create(
            tenant_id=1, creator_id=1, status="ACTIVE",
            name=f"专家{i}", org_name=f"单位{i % 2}", user_id=100 + i,
            source="EXTERNAL", field_tags=["AI", "材料"][: (i % 2) + 1],
            expertise_level="EXPERT"))
    return out


def test_expert_crud_and_status(seed_auth):
    c = _c()
    r = c.post("/api/v1/experts", data=json.dumps({"name": "张专家", "org_name": "外单位"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    e = _json(r)["data"]
    assert e["status"] == "CANDIDATE"
    r = c.post(f"/api/v1/experts/{e['id']}/status", data=json.dumps({"status": "ACTIVE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "ACTIVE"
    # 非法状态 → 40002
    r = c.post(f"/api/v1/experts/{e['id']}/status", data=json.dumps({"status": "GHOST"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40002
    r = c.put(f"/api/v1/experts/{e['id']}", data=json.dumps({"title": "教授"}),
              content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["title"] == "教授"
    r = c.delete(f"/api/v1/experts/{e['id']}", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0


def test_review_full_lifecycle_and_writeback(seed_auth):
    c = _c()
    experts = _seed_experts(4)
    # 建单（DRAFT）
    r = c.post("/api/v1/reviews", data=json.dumps({
        "biz_type": "OUTPUT_EVAL", "target_type": "R_OUTPUT", "target_id": 1,
        "title": "成果评审", "plan_count": 2, "draw_rule": {"field_tags": ["AI"]}}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    task = _json(r)["data"]
    assert task["status"] == "DRAFT" and task["plan_count"] == 2
    tid = task["id"]
    # 抽取（seed 固定，确定性）
    r = c.post(f"/api/v1/reviews/{tid}/draw", data=json.dumps({"seed": 42}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    d = _json(r)["data"]
    assert d["count"] == 2 and len(set(d["drawn"])) == 2
    task_row = NReviewTask.objects.get(id=tid)
    assert task_row.status == "DRAWN"
    # 邀请 → INVITING
    r = c.post(f"/api/v1/reviews/{tid}/invite", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0
    task_row.refresh_from_db()
    assert task_row.status == "INVITING"
    # 逐个应允 → 达法定人数 → QUORUM
    invites = list(NReviewInvitation.objects.filter(task_id=tid))
    for iv in invites:
        r = c.post(f"/api/v1/reviews/{tid}/accept", data=json.dumps({"expert_id": iv.expert_id}),
                   content_type="application/json", **bearer(1, ["R-EXPERT"]))
    task_row.refresh_from_db()
    assert task_row.status == "QUORUM"
    # 开始评审 → IN_REVIEW
    r = c.post(f"/api/v1/reviews/{tid}/start", **bearer(1, ["R-MANAGER"]))
    task_row.refresh_from_db()
    assert task_row.status == "IN_REVIEW"
    # 两人打分 → 全提交 → COLLECTING
    for iv in invites:
        r = c.post(f"/api/v1/reviews/{tid}/scores", data=json.dumps({
            "expert_id": iv.expert_id, "total_score": "88.50",
            "dimension_scores": [{"dim": "创新性", "score": 90}]}),
            content_type="application/json", **bearer(1, ["R-EXPERT"]))
        assert _json(r)["code"] == 0
    task_row.refresh_from_db()
    assert task_row.status == "COLLECTING"
    # 结论 → CONCLUDED；OUTPUT_EVAL+PASS → 单一写者回写目标成果
    target = ROutput.objects.create(
        tenant_id=1, creator_id=1, output_type="PAPER", title="被评成果",
        source="MANUAL", status="CLAIMED", is_claimed=True)
    NReviewTask.objects.filter(id=tid).update(target_id=target.id)
    r = c.post(f"/api/v1/reviews/{tid}/conclude", data=json.dumps({"conclusion": "PASS"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    body = _json(r)
    assert body["data"]["status"] == "CONCLUDED"
    assert body["data"]["score_summary"]["count"] == 2
    assert body["data"]["score_summary"]["avg"] == "88.50"
    target.refresh_from_db()
    assert target.status == "ASSIGNED_TO_PROJECT"  # 单一写者生效
    # 评审费生成：按已接受专家逐人
    r = c.post(f"/api/v1/reviews/{tid}/fees", data=json.dumps({"amount": "500.00"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["generated"] == 2
    # detail
    r = c.get(f"/api/v1/reviews/{tid}/detail", **bearer(1, ["R-MANAGER"]))
    d = _json(r)["data"]
    assert len(d["invitations"]) == 2 and len(d["scores"]) == 2


def test_review_final_accept_writeback_map(seed_auth):
    """FINAL_ACCEPT+PASS → E_FINAL_ACCEPT.APPROVED（经 E 单一写者）。"""
    c = _c()
    from apps.project.models import EFinalAccept
    p = _project()
    fa = EFinalAccept.objects.create(
        tenant_id=1, creator_id=1, status="APPLIED", project=p)
    r = c.post("/api/v1/reviews", data=json.dumps({
        "biz_type": "FINAL_ACCEPT", "target_type": "E_FINAL_ACCEPT",
        "target_id": fa.id, "title": "结题验收评审", "plan_count": 1}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    tid = _json(r)["data"]["id"]
    _seed_experts(2)
    c.post(f"/api/v1/reviews/{tid}/draw", data=json.dumps({"seed": 7}),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post(f"/api/v1/reviews/{tid}/invite", **bearer(1, ["R-MANAGER"]))
    iv = NReviewInvitation.objects.get(task_id=tid)
    c.post(f"/api/v1/reviews/{tid}/accept", data=json.dumps({"expert_id": iv.expert_id}),
           content_type="application/json", **bearer(1, ["R-EXPERT"]))
    c.post(f"/api/v1/reviews/{tid}/scores", data=json.dumps(
        {"expert_id": iv.expert_id, "total_score": "92.00"}),
        content_type="application/json", **bearer(1, ["R-EXPERT"]))
    r = c.post(f"/api/v1/reviews/{tid}/conclude", data=json.dumps({"conclusion": "PASS"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0
    fa.refresh_from_db()
    assert fa.status == "APPROVED" and fa.accept_at is not None


# ===========================================================================
# V 学术活动域
# ===========================================================================

def test_activity_full_state_machine(seed_auth):
    c = _c()
    # R-STAFF 创建（DRAFT）
    r = c.post("/api/v1/activities", data=json.dumps({
        "activity_type": "CONFERENCE", "title": "学术年会",
        "start_at": "2026-11-01T09:00:00", "est_attendees": 100}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    a = _json(r)["data"]
    assert a["status"] == "DRAFT"
    aid = a["id"]
    # 提交
    r = c.post(f"/api/v1/activities/{aid}/submit", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["status"] == "SUBMITTED"
    # 非法迁移 DRAFT→HELD 不可（已 SUBMITTED），测 APPROVED 前直接 hold → 40901
    r = c.post(f"/api/v1/activities/{aid}/hold", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 一级审批（level=1）→ DEPT_REVIEW
    r = c.post(f"/api/v1/activities/{aid}/approve", data=json.dumps(
        {"review_level": 1, "action": "APPROVE", "opinion": "部门通过"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "DEPT_REVIEW"
    # 二级审批 → APPROVED
    r = c.post(f"/api/v1/activities/{aid}/approve", data=json.dumps(
        {"review_level": 2, "action": "APPROVE"}),
        content_type="application/json", **bearer(1, ["R-LEADER"]))
    assert _json(r)["data"]["status"] == "APPROVED"
    # 举办
    r = c.post(f"/api/v1/activities/{aid}/hold", data=json.dumps(
        {"sign_in_count": 88, "hold_proof_ids": ["proof-1"]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "HELD"
    # 归档缺纪要 → 40002
    r = c.post(f"/api/v1/activities/{aid}/archive", data=json.dumps({}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40002
    r = c.post(f"/api/v1/activities/{aid}/archive", data=json.dumps(
        {"minutes_rich": "<p>纪要</p>"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "ARCHIVED"
    # 详情带参与人/审批留痕
    r = c.get(f"/api/v1/activities/{aid}", **bearer(2, ["R-STAFF"]))
    d = _json(r)["data"]
    assert len(d["reviews"]) == 2
    # 参与人维护
    r = c.post(f"/api/v1/activities/{aid}/participants", data=json.dumps(
        {"guest_name": "外聘专家", "role": "SPEAKER"}),
        content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 0
    # 双空校验 → 40004
    r = c.post(f"/api/v1/activities/{aid}/participants", data=json.dumps({"role": "CHAIR"}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40004
    # 日历与统计
    r = c.get("/api/v1/activities/calendar?month=2026-11", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["month"] == "2026-11"
    r = c.get("/api/v1/activities/stats?group_by=activity_type", **bearer(2, ["R-STAFF"]))
    buckets = _json(r)["data"]["buckets"]
    assert any(b["key"] == "CONFERENCE" for b in buckets)


# ===========================================================================
# O 档案域
# ===========================================================================

def test_document_upload_search_download_delete(seed_auth):
    c = _c()
    payload = b"hello archive world"
    from django.core.files.uploadedfile import SimpleUploadedFile
    f = SimpleUploadedFile("报告.txt", payload, content_type="text/plain")
    r = c.post("/api/v1/documents", {"name": "检测报告", "source_module": "E", "file": f},
               **bearer(1, ["R-MANAGER"]))
    doc = _json(r)["data"]
    assert doc["status"] == "STORED"
    assert doc["size_bytes"] == len(payload)
    import hashlib
    assert doc["checksum_sha256"] == hashlib.sha256(payload).hexdigest()
    did = doc["id"]
    # 详情不吐 text_content
    r = c.get(f"/api/v1/documents/{did}", **bearer(1, ["R-MANAGER"]))
    assert "text_content" not in _json(r)["data"]
    # 检索（静态先于 {id}）
    r = c.get("/api/v1/documents/search?q=检测", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["total"] == 1
    # 下载链接
    r = c.get(f"/api/v1/documents/{did}/download", **bearer(1, ["R-MANAGER"]))
    d = _json(r)["data"]
    assert d["url"] and d["expires_at"]
    # 软删（R-ADMIN）
    r = c.delete(f"/api/v1/documents/{did}", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["data"]["deleted"] is True
    r = c.get(f"/api/v1/documents/{did}", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40401


def test_archive_lifecycle_four_properties(seed_auth):
    c = _c()
    # 上传两份文档
    from django.core.files.uploadedfile import SimpleUploadedFile
    docs = []
    for name in ("立项书", "结题报告"):
        f = SimpleUploadedFile(f"{name}.pdf", f"{name}内容".encode(), content_type="application/pdf")
        r = c.post("/api/v1/documents", {"name": name, "file": f},
                   **bearer(1, ["R-MANAGER"]))
        docs.append(_json(r)["data"])
    # 建案卷 + 门类清单（2 必填：1 已填 1 缺）
    r = c.post("/api/v1/archives", data=json.dumps(
        {"title": "XX项目案卷", "archive_type": "PROJECT", "source_code": "PRJ-2026-000001"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    a = _json(r)["data"]
    aid = a["id"]
    assert a["status"] == "PENDING_SUBMIT"
    r = c.post(f"/api/v1/archives/{aid}/items", data=json.dumps(
        {"category_code": "LIX", "category_name": "立项书", "doc_id": docs[0]["id"]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "FILLED"
    r = c.post(f"/api/v1/archives/{aid}/items", data=json.dumps(
        {"category_code": "JIE", "category_name": "结题报告"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    missing_item = _json(r)["data"]
    assert missing_item["status"] == "MISSING"
    # 提交 → SUBMITTED
    r = c.post(f"/api/v1/archives/{aid}/submit", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "SUBMITTED"
    # 四性检测：完整性 FAIL → REJECTED
    r = c.post(f"/api/v1/archives/{aid}/check", **bearer(1, ["R-ADMIN"]))
    d = _json(r)["data"]
    assert d["passed"] is False
    by_type = {x["check_type"]: x["result"] for x in d["list"]}
    assert by_type["INTEGRITY"] == "FAIL"
    assert by_type["AUTHENTICITY"] == "PASS" and by_type["SECURITY"] == "PASS"
    a_row = OArchive.objects.get(id=aid)
    assert a_row.status == "REJECTED"
    # 补齐后重新走 SUBMITTED → PASSED → ARCHIVED → DESTROYED
    r = c.put(f"/api/v1/archives/{aid}/items/{missing_item['id']}",
              data=json.dumps({"doc_id": docs[1]["id"]}),
              content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "FILLED"
    r = c.post(f"/api/v1/archives/{aid}/submit", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "SUBMITTED"
    r = c.post(f"/api/v1/archives/{aid}/check", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["data"]["passed"] is True
    a_row.refresh_from_db()
    assert a_row.status == "PASSED"
    r = c.post(f"/api/v1/archives/{aid}/file", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["data"]["status"] == "ARCHIVED"
    # PASSED 不可再入库（幂等守卫）
    r = c.post(f"/api/v1/archives/{aid}/file", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["code"] == 40901
    r = c.post(f"/api/v1/archives/{aid}/destroy", data=json.dumps({"reason": "期满鉴定"}),
               content_type="application/json", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["data"]["status"] == "DESTROYED"


def test_borrow_flow(seed_auth):
    c = _c()
    a = OArchive.objects.create(tenant_id=1, creator_id=1, title="可借案卷", status="ARCHIVED")
    # 非 ARCHIVED 拒借
    a2 = OArchive.objects.create(tenant_id=1, creator_id=1, title="草稿案卷", status="PENDING_SUBMIT")
    r = c.post("/api/v1/borrows", data=json.dumps({"archive_id": a2.id}),
               content_type="application/json", **bearer(2, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 申请 → 审批 → 归还
    r = c.post("/api/v1/borrows", data=json.dumps(
        {"archive_id": a.id, "purpose": "审计取证", "borrow_type": "READ"}),
        content_type="application/json", **bearer(2, ["R-MANAGER"]))
    b = _json(r)["data"]
    assert b["status"] == "SUBMITTED" and b["borrower_user_id"] == 2
    r = c.post(f"/api/v1/borrows/{b['id']}/approve", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["data"]["status"] == "APPROVED"
    r = c.post(f"/api/v1/borrows/{b['id']}/return", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["data"]["status"] == "RETURNED"
    # 状态机守卫：REJECTED 只能从 SUBMITTED
    r = c.post("/api/v1/borrows", data=json.dumps({"archive_id": a.id}),
               content_type="application/json", **bearer(2, ["R-MANAGER"]))
    bid = _json(r)["data"]["id"]
    c.post(f"/api/v1/borrows/{bid}/approve", **bearer(1, ["R-ADMIN"]))
    r = c.post(f"/api/v1/borrows/{bid}/reject", **bearer(1, ["R-ADMIN"]))
    assert _json(r)["code"] == 40901


# ===========================================================================
# M 绩效域
# ===========================================================================

def test_scheme_lifecycle_and_activate(seed_auth):
    c = _c()
    r = c.post("/api/v1/perf/schemes", data=json.dumps({
        "name": "2026年度绩效", "period_type": "YEAR", "effective_period": "2026"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    s = _json(r)["data"]
    assert s["code"].startswith("PERF-") and s["status"] == "DRAFT"
    sid = s["id"]
    # 因子 upsert
    r = c.post(f"/api/v1/perf/schemes/{sid}/factors", data=json.dumps({
        "factor_code": "PAPER_CNT", "factor_name": "论文数",
        "weight": "60", "scoring_rule": {"method": "COUNT", "unit": 2},
        "data_source": "R_OUTPUT", "max_score": "20"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    f1 = _json(r)["data"]
    assert f1["weight"] == "60.00"
    # DRAFT 才可编辑
    r = c.put(f"/api/v1/perf/schemes/{sid}", data=json.dumps({"name": "2026年度绩效考核"}),
              content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["name"] == "2026年度绩效考核"
    # 激活 → ACTIVE
    r = c.post(f"/api/v1/perf/schemes/{sid}/activate", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "ACTIVE"
    # 同维度旧方案被 SUPERSEDED
    r = c.post("/api/v1/perf/schemes", data=json.dumps({
        "name": "2026绩效V2", "period_type": "YEAR", "effective_period": "2026"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    sid2 = _json(r)["data"]["id"]
    c.post(f"/api/v1/perf/schemes/{sid2}/activate", **bearer(1, ["R-MANAGER"]))
    s_row = MScheme.objects.get(id=sid)
    assert s_row.status == "SUPERSEDED" and s_row.active is False
    # ACTIVE 不可编辑 → 40901
    r = c.put(f"/api/v1/perf/schemes/{sid2}", data=json.dumps({"name": "改不动"}),
              content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901


def test_calculate_count_rule_and_record_flow(seed_auth):
    c = _c()
    staff_id = 2
    p = _project(pi_user_id=staff_id)
    # 数据源：2 篇已认领论文（staff 作者）
    for t in ("论文甲", "论文乙"):
        ROutput.objects.create(
            tenant_id=1, creator_id=staff_id, output_type="PAPER", title=t,
            source="MANUAL", status="CLAIMED", claim_status="CLAIMED",
            publish_date=dj_tz.localdate(),
            authors=[{"user_id": staff_id, "name": "张三", "order": 1}])
    # 方案 + COUNT 因子（unit=2, max=20 → raw=4）
    r = c.post("/api/v1/perf/schemes", data=json.dumps({
        "name": "计算方案", "period_type": "YEAR", "effective_period": "2026"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    sid = _json(r)["data"]["id"]
    c.post(f"/api/v1/perf/schemes/{sid}/factors", data=json.dumps({
        "factor_code": "PAPER", "weight": "100",
        "scoring_rule": {"method": "COUNT", "unit": 2}, "data_source": "R_OUTPUT",
        "max_score": "20"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    # 计算（staff_ids 优先）
    r = c.post(f"/api/v1/perf/schemes/{sid}/calculate", data=json.dumps({
        "period": "2026", "staff_ids": [staff_id]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    d = _json(r)["data"]
    assert d["computed"] == 1 and d["inserted"] == 1
    # 记录流：CALCULATED → confirm → approve → payout → pay
    rec = MRecord.objects.get(scheme_id=sid, staff_user_id=staff_id, period="2026")
    assert f"{rec.total_score:.2f}" == "4.00"  # 2 篇 × unit2 = 4，max20 未触顶
    r = c.get(f"/api/v1/perf/records/{rec.id}", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["total_score"] == "4.00"
    # 他人记录 R-STAFF 越权读 → 40301
    r = c.get(f"/api/v1/perf/records/{rec.id}", **bearer(3, ["R-STAFF"]))
    assert _json(r)["code"] == 40301
    # 状态机
    r = c.post(f"/api/v1/perf/records/{rec.id}/confirm", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["status"] == "CONFIRMED"
    r = c.post(f"/api/v1/perf/records/{rec.id}/approve", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "APPROVED"
    # 发放（R-FINANCE）
    r = c.post("/api/v1/perf/payouts", data=json.dumps(
        {"record_id": rec.id, "amount": "1000.00", "pay_channel": "BANK"}),
        content_type="application/json", **bearer(1, ["R-FINANCE"]))
    pay = _json(r)["data"]
    assert pay["status"] == "DRAFT" and pay["payee_user_id"] == staff_id
    r = c.post(f"/api/v1/perf/payouts/{pay['id']}/approve", **bearer(1, ["R-FINANCE"]))
    assert _json(r)["data"]["status"] == "APPROVED"
    r = c.post(f"/api/v1/perf/payouts/{pay['id']}/pay", data=json.dumps({"voucher_code": "V-001"}),
               content_type="application/json", **bearer(1, ["R-FINANCE"]))
    assert _json(r)["data"]["status"] == "PAID"
    rec.refresh_from_db()
    assert rec.status == "PAID"  # 联动记录 → PAID
    # 排行（管理角色）
    r = c.get(f"/api/v1/perf/ranking?scheme_id={sid}&period=2026", **bearer(1, ["R-MANAGER"]))
    rank = _json(r)["data"]["list"]
    assert rank[0]["rank"] == 1 and rank[0]["staff_user_id"] == staff_id
    # 我的绩效
    r = c.get("/api/v1/perf/me", **bearer(2, ["R-STAFF"]))
    assert len(_json(r)["data"]["list"]) == 1
    # 再次计算覆盖（updated）
    r = c.post(f"/api/v1/perf/schemes/{sid}/calculate", data=json.dumps({
        "period": "2026", "staff_ids": [staff_id]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["updated"] == 1


def test_ladder_and_by_amount_rules(seed_auth):
    c = _c()
    staff_id = 3
    p = _project(pi_user_id=staff_id, total_budget=Decimal("120000.00"))
    # F_INCOME 数据源：到款 60000
    FIncome.objects.create(
        tenant_id=1, creator_id=1, project_id=p.id, receipt_no="R-1",
        receipt_date=dj_tz.localdate(), amount=Decimal("60000.00"),
        claim_status="CLAIMED", claimed_by=staff_id)
    r = c.post("/api/v1/perf/schemes", data=json.dumps({
        "name": "阶梯方案", "period_type": "YEAR", "effective_period": "2026"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    sid = _json(r)["data"]["id"]
    # LADDER：amount 60000 命中 [50000,100000] → 15 分
    c.post(f"/api/v1/perf/schemes/{sid}/factors", data=json.dumps({
        "factor_code": "INCOME", "weight": "100",
        "scoring_rule": {"method": "LADDER", "ladder": [
            {"min": 0, "max": 50000, "score": 10},
            {"min": 50000, "max": 100000, "score": 15},
            {"min": 100000, "max": 99999999, "score": 20}]},
        "data_source": "F_INCOME"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    r = c.post(f"/api/v1/perf/schemes/{sid}/calculate", data=json.dumps({
        "period": "2026", "staff_ids": [staff_id]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    rec = MRecord.objects.get(scheme_id=sid, staff_user_id=staff_id, period="2026")
    assert f"{rec.total_score:.2f}" == "15.00"
    from apps.performance.models import MRecordItem
    item = MRecordItem.objects.get(record_id=rec.id)
    assert f"{item.metric_value:.4f}" == "60000.0000"
    assert f"{item.raw_score:.2f}" == "15.00"
    # BY_LEVEL：论文 1 篇 SCI(+5) + 1 篇 GENERAL(+1) = 6 分
    ROutput.objects.create(
        tenant_id=1, creator_id=staff_id, output_type="PAPER", title="SCI论文",
        source="MANUAL", status="CLAIMED", claim_status="CLAIMED",
        publish_date=dj_tz.localdate(),
        authors=[{"user_id": staff_id, "name": "李四", "order": 1}])
    ROutput.objects.create(
        tenant_id=1, creator_id=staff_id, output_type="PAPER", title="普刊论文",
        source="MANUAL", status="CLAIMED", claim_status="CLAIMED",
        publish_date=dj_tz.localdate(),
        authors=[{"user_id": staff_id, "name": "李四", "order": 1}])
    r = c.post("/api/v1/perf/schemes", data=json.dumps({
        "name": "分区方案", "period_type": "YEAR", "effective_period": "2026"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    sid2 = _json(r)["data"]["id"]
    c.post(f"/api/v1/perf/schemes/{sid2}/factors", data=json.dumps({
        "factor_code": "LEVEL", "weight": "100",
        "scoring_rule": {"method": "BY_LEVEL",
                         "levelMap": {"PAPER": 1, "PATENT": 3}},
        "data_source": "R_OUTPUT"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post(f"/api/v1/perf/schemes/{sid2}/calculate", data=json.dumps({
        "period": "2026", "staff_ids": [staff_id]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    rec2 = MRecord.objects.get(scheme_id=sid2, staff_user_id=staff_id, period="2026")
    assert f"{rec2.total_score:.2f}" == "2.00"  # 2 篇 PAPER × 1


# ===========================================================================
# D 数据决策大屏
# ===========================================================================

def test_funding_dashboard_aggregation(seed_auth):
    c = _c()
    from apps.funding.models import FSubject
    p = _project(pi_user_id=2)
    sub = FSubject.objects.create(tenant_id=1, creator_id=1, name="设备费", category="DIRECT")
    bud = FBudget.objects.create(
        tenant_id=1, creator_id=1, project_id=p.id, legal_entity_id=1,
        mode="预算制", total_approved=Decimal("100000.00"), status="EXECUTING")
    FBudgetLine.objects.create(
        tenant_id=1, creator_id=1, budget_id=bud.id, subject_id=sub.id,
        amount_planned=Decimal("100000.00"), amount_used=Decimal("30000.00"))
    FExpense.objects.create(
        tenant_id=1, creator_id=2, project_id=p.id, applicant_user_id=2,
        legal_entity_id=1, amount=Decimal("30000.00"), status="PAID",
        expense_category="DIRECT")
    FIncome.objects.create(
        tenant_id=1, creator_id=1, project_id=p.id, receipt_no="R-2026-1",
        receipt_date=dj_tz.localdate(), amount=Decimal("80000.00"))
    r = c.get("/api/v1/dashboard/funding", **bearer(1, ["R-ADMIN"]))
    d = _json(r)["data"]
    assert d["totalBudget"] == "100000.00"
    assert d["yearIncome"] == "80000.00"
    assert d["yearUsed"] == "30000.00"
    assert d["executionRate"] == 0.3
    assert len(d["deptHeatmap"]) == 1
    assert d["deptHeatmap"][0]["executionRate"] == 0.3
    assert "trend12Months" in d and "alerts" in d
    assert set(d["alerts"].keys()) == {"pre", "during", "post"}
    assert d["byCollege"] and d["bySubject"]
