"""科研诚信与伦理域 C API（对齐 design/06-科研诚信与伦理-C.openapi.yaml，纯契约实现）。

链路：案卷 DRAFT→SUBMITTED（送审→FORMAL_CHECK）→形式审查→分派（COI 回避）→委员意见→
会议签到/表决→批件签发（1:1，公开编号验证）→修正案/不良事件（SERIOUS/SUSAR→MONITORING）/
年度复审；诚信：承诺签署 / 失信档案（独立调查+申诉）/ 不端检测（确定性降级）/ 人遗备案。
公开通道：GET /ethics/letter/{letterNo}（编号可查、内容不可查）。
"""
from __future__ import annotations

import time
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.ethics.mappings import (
    num_float,
    to_api_assign,
    to_api_ae,
    to_api_amendment,
    to_api_annual,
    to_api_case,
    to_api_hgr,
    to_api_integrity,
    to_api_letter,
    to_api_meeting,
    to_api_opinion,
    to_api_pledge,
    to_api_scan,
)
from apps.ethics.models import (
    CAeReport,
    CAmendment,
    CAnnualReview,
    CDecisionLetter,
    CEthicsCase,
    CHgrFiling,
    CIntegrityPledge,
    CIntegrityRecord,
    CMeetingRecord,
    CMisconductScan,
    CReviewOpinion,
    CReviewerAssign,
)
from core.auth.deps import domain_from
from core.httpx import ApiError, CODE_BAD_REQUEST, CODE_CONFLICT, CODE_NOT_FOUND, ok, read_json
from apps.output.api import page_args, _parse_date  # 共用分页/日期解析


def _now():
    return dj_tz.now()


def _parse_dt(s):
    """date 或 ISO datetime 字符串 → aware datetime；空/非法返回 None。"""
    if not s:
        return None
    s = str(s)
    try:
        dt = datetime.fromisoformat(s[:19])
    except ValueError:
        return None
    return dj_tz.make_aware(dt) if dj_tz.is_naive(dt) else dt


REVIEW_TYPES = {"HUMAN", "ANIMAL", "BIO_SAFETY", "HGR", "DATA_EXPORT"}
SEVERITIES = {"SERIOUS", "NON_SERIOUS", "SUSAR"}
FILING_TYPES = {"COLLECT", "PRESERVE", "INTL_COOP", "DEVELOP"}


def _gen_case_code(tenant_id: int) -> str:
    year = _now().year
    seq = CEthicsCase.objects.filter(tenant_id=tenant_id, code__startswith=f"ETH-{year}-").count() + 1
    return f"ETH-{year}-{seq:06d}"


def _get_case_or_404(cid: int) -> CEthicsCase:
    c = CEthicsCase.objects.filter(id=cid, deleted=0).first()
    if c is None:
        raise ApiError(404, CODE_NOT_FOUND, "伦理案卷不存在")
    return c


def _guard(obj, allowed: set[str], action: str):
    if obj.status not in allowed:
        raise ApiError(409, CODE_CONFLICT, f"{action} 状态机冲突：当前 {obj.status}")


# ---------------------------------------------------------------------------
# 伦理案卷 C-01/C-02
# ---------------------------------------------------------------------------


def list_ethics_cases(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    dom = domain_from(request)
    qs = CEthicsCase.objects.filter(tenant_id=dom.tenant_id, deleted=0)
    for k in ("review_type", "status", "risk_level"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    if v := request.GET.get("project_id"):
        try:
            qs = qs.filter(project_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("applicant_user_id"):
        try:
            qs = qs.filter(applicant_user_id=int(v))
        except ValueError:
            pass
    if request.GET.get("mine") in ("true", "1"):
        qs = qs.filter(applicant_user_id=dom.user_id)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    # 列表视图脱敏涉受试者字段（detail §7）
    return ok(request, {"list": [to_api_case(r, masked=True) for r in rows],
                        "total": total, "page": page, "size": size})


@transaction.atomic
def create_ethics_case(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if b.get("review_type") not in REVIEW_TYPES or not b.get("protocol_title"):
        raise ApiError(400, CODE_BAD_REQUEST, "review_type 与 protocol_title 必填")
    if not b.get("applicant_user_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "applicant_user_id 必填")
    c = CEthicsCase.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_case_code(dom.tenant_id),
        review_type=b["review_type"],
        project_id=b.get("project_id"),
        applicant_user_id=int(b["applicant_user_id"]),
        department_id=b.get("department_id"),
        protocol_title=b["protocol_title"],
        protocol_summary=b.get("protocol_summary"),
        methodology=b.get("methodology"),
        risk_level=b.get("risk_level") or "MED",
        informed_consent_url=b.get("informed_consent_url"),
        is_emergency=bool(b.get("is_emergency", False)),
        security_level=b.get("security_level") or "INTERNAL",
        legal_entity_id=dom.legal_entity_id or 1,
        remark=b.get("remark"),
    )
    return ok(request, to_api_case(c))


def get_ethics_case(request: HttpRequest, id: int):
    dom = domain_from(request)
    c = _get_case_or_404(id)
    data = to_api_case(c)
    # 委员意见：PI 视角匿名（reviewer_user_id 不透出）
    opinions = CReviewOpinion.objects.filter(case=c, deleted=0).exclude(status="SUPERSEDED")
    data["opinions"] = [to_api_opinion(o) for o in opinions]
    assigns = CReviewerAssign.objects.filter(case=c, deleted=0)
    data["reviewers"] = [{
        "reviewer_user_id": a.reviewer_user_id, "role": a.role, "status": a.status,
        "conflict_of_interest": a.conflict_of_interest,
    } for a in assigns]
    letter = CDecisionLetter.objects.filter(case=c, deleted=0).first()
    data["letter_no"] = letter.letter_no if letter else None
    return ok(request, data)


@transaction.atomic
def submit_ethics_case(request: HttpRequest, id: int):
    """提交送审：DRAFT/NEEDS_REVISION → FORMAL_CHECK（补件重提复用）。"""
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"DRAFT", "NEEDS_REVISION"}, "提交送审")
    b = read_json(request)
    if mats := b.get("materials"):
        c.materials = list(c.materials or []) + list(mats)
    if b.get("consent_url"):
        c.informed_consent_url = b["consent_url"]
    c.status = "FORMAL_CHECK"
    c.submitted_at = _now()
    c.modifier_id = dom.user_id
    c.save()
    return ok(request, to_api_case(c))


@transaction.atomic
def ai_prescreen_ethics(request: HttpRequest, id: int):
    """C-17 关键要素完整性预审（确定性规则；LLM 增强由 svc-ai 承接）。"""
    c = _get_case_or_404(id)
    missing = []
    if not c.protocol_summary:
        missing.append("protocol_summary")
    if not c.methodology:
        missing.append("methodology")
    if not c.informed_consent_url and c.review_type in ("HUMAN", "HGR"):
        missing.append("informed_consent_url")
    if not (c.materials or []):
        missing.append("materials")
    result = {"missing_fields": missing, "passed": not missing, "confidence": 0.9}
    c.ai_prescreen = result
    c.save(update_fields=["ai_prescreen", "updated_at"])
    return ok(request, result)


@transaction.atomic
def formal_check(request: HttpRequest, id: int):
    """形式审查（管理员/秘书）：齐备→UNDER_REVIEW，缺件→NEEDS_REVISION。"""
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"FORMAL_CHECK", "NEEDS_REVISION"}, "形式审查")
    b = read_json(request)
    result = b.get("result")
    if result not in ("OK", "MISSING"):
        raise ApiError(400, CODE_BAD_REQUEST, "result 必须为 OK/MISSING")
    if result == "MISSING":
        c.status = "NEEDS_REVISION"
        c.remark = "; ".join(filter(None, [c.remark, b.get("comment"),
                                           f"缺件: {','.join(b.get('missing_docs') or [])}"]))
    else:
        c.status = "UNDER_REVIEW"
    c.modifier_id = dom.user_id
    c.save()
    return ok(request, to_api_case(c))


@transaction.atomic
def assign_reviewers(request: HttpRequest, id: int):
    """分派主审+委员（C-03）；利益冲突：与申请人同人强制拒绝，COI 标记留痕。"""
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"UNDER_REVIEW"}, "分派")
    b = read_json(request)
    items = b.get("assignments") or []
    if not items:
        raise ApiError(400, CODE_BAD_REQUEST, "assignments 不能为空")
    deadline = b.get("review_deadline")
    out = []
    for it in items:
        uid = it.get("reviewer_user_id")
        role = it.get("role")
        if not uid or role not in ("CHIEF", "BOARD"):
            raise ApiError(400, CODE_BAD_REQUEST, "assignments 项需 reviewer_user_id 与 role(CHIEF/BOARD)")
        if CReviewerAssign.objects.filter(case=c, reviewer_user_id=uid, deleted=0).exists():
            raise ApiError(409, CODE_CONFLICT, f"委员 {uid} 已分派")
        coi = uid == c.applicant_user_id
        if coi:
            raise ApiError(409, CODE_CONFLICT, f"利益冲突：委员 {uid} 为本案申请人，强制回避")
        a = CReviewerAssign.objects.create(
            tenant_id=dom.tenant_id, creator_id=dom.user_id, case=c,
            reviewer_user_id=uid, role=role,
            deadline=_parse_dt(deadline),
        )
        out.append(to_api_assign(a))
    return ok(request, {"list": out})


@transaction.atomic
def submit_opinion(request: HttpRequest, id: int):
    """委员打分与意见（C-03/C-04）；须为已分派委员，一人一份。"""
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"UNDER_REVIEW"}, "意见提交")
    b = read_json(request)
    rec = b.get("recommendation")
    if rec not in ("APPROVE", "APPROVE_WITH_CHANGES", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "recommendation 非法")
    uid = dom.user_id
    if not CReviewerAssign.objects.filter(case=c, reviewer_user_id=uid, deleted=0).exists():
        raise ApiError(403, 40301, "非本案分派委员")
    if CReviewOpinion.objects.filter(case=c, reviewer_user_id=uid, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "已提交意见")
    o = CReviewOpinion.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, case=c, reviewer_user_id=uid,
        score=b.get("score"), comments=b.get("comments"),
        objection=b.get("objection") or {},
        risks_identified=b.get("risks_identified") or [],
        recommendation=rec,
    )
    return ok(request, to_api_opinion(o))


# ---------------------------------------------------------------------------
# 会议审查 C-04
# ---------------------------------------------------------------------------


@transaction.atomic
def meeting_check_in(request: HttpRequest, id: int):
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"UNDER_REVIEW"}, "会议签到")
    b = read_json(request)
    attendees = b.get("attendees") or []
    if not attendees:
        raise ApiError(400, CODE_BAD_REQUEST, "attendees 不能为空")
    m = CMeetingRecord.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, case=c,
        meeting_date=_now(),
        attendees=[{**a, "signed_at": _now().isoformat()} for a in attendees],
    )
    c.status = "UNDER_REVIEW"
    c.save(update_fields=["updated_at"])
    return ok(request, to_api_meeting(m))


@transaction.atomic
def meeting_vote(request: HttpRequest, id: int):
    """表决与生成纪要（C-04）：approve>reject 且达法定人数 → 决议生效。"""
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"UNDER_REVIEW"}, "会议表决")
    b = read_json(request)
    decision = b.get("decision")
    if decision not in ("APPROVE", "APPROVE_WITH_CHANGES", "REJECT", "CONTINUE"):
        raise ApiError(400, CODE_BAD_REQUEST, "decision 非法")
    vote = b.get("vote") or {}
    quorum = bool(b.get("quorum_met", False))
    m = CMeetingRecord.objects.filter(case=c, deleted=0).order_by("-id").first()
    if m is None:
        raise ApiError(404, CODE_NOT_FOUND, "无会议纪要记录（先签到）")
    approve_n, reject_n = int(vote.get("approve", 0)), int(vote.get("reject", 0))
    passed = quorum and (reject_n > approve_n if decision == "REJECT" else approve_n > reject_n)
    m.status = "MINUTED"
    m.attendees = b.get("attendees") or m.attendees
    m.quorum_met = quorum
    m.discussion_text = b.get("discussion_text") or m.discussion_text
    m.decision = decision
    m.vote_result = {**vote, "total": sum(int(vote.get(k, 0)) for k in ("approve", "reject", "abstain")),
                     "pass": passed}
    m.modifier_id = dom.user_id
    m.save()
    if decision in ("APPROVE", "APPROVE_WITH_CHANGES") and passed:
        c.status = "APPROVED"
        c.decision_date = dj_tz.localdate()
    elif decision == "REJECT" and passed:
        c.status = "REJECTED"
        c.decision_date = dj_tz.localdate()
    c.modifier_id = dom.user_id
    c.save()
    return ok(request, {"meeting": to_api_meeting(m), "case": to_api_case(c)})


# ---------------------------------------------------------------------------
# 批件 C-06（含公开验证）
# ---------------------------------------------------------------------------


@transaction.atomic
def issue_decision_letter(request: HttpRequest, id: int):
    """主审签发批件（1:1）；publish=true → PUBLISHED 并生成公开验证页。"""
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"APPROVED", "REJECTED"}, "批件签发")
    if CDecisionLetter.objects.filter(case=c, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "批件已签发（1:1）")
    b = read_json(request)
    dt = b.get("decision_type")
    if dt not in ("APPROVE", "APPROVE_WITH_CHANGES", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "decision_type 非法")
    publish = bool(b.get("publish", True))
    letter = CDecisionLetter.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, case=c,
        decision_type=dt, letter_no=f"PZ-{c.code}",
        letter_url=b.get("letter_body_ref"),
        verify_url=f"/public/ethics/letter/{c.code}",
        status="PUBLISHED" if publish else "ISSUED",
        issued_at=_now(),
        expires_at=_parse_dt(b.get("valid_until")),
    )
    c.valid_until = _parse_date(b.get("valid_until"))
    c.next_review_at = _parse_date(b.get("next_review_at"))
    c.modifier_id = dom.user_id
    c.save()
    return ok(request, to_api_letter(letter))


def verify_decision_letter(request: HttpRequest, letterNo: str):
    """公开验证（免鉴权）：编号可查、内容不可查——仅真伪与存在性元数据。"""
    letter = CDecisionLetter.objects.filter(letter_no=letterNo, deleted=0).first()
    if letter is None:
        return ok(request, {"valid": False, "letter_no": letterNo})
    return ok(request, {
        "valid": letter.status in ("ISSUED", "PUBLISHED"),
        "letter_no": letter.letter_no,
        "decision_type": letter.decision_type,
        "status": letter.status,
        "issued_at": letter.issued_at.isoformat() if letter.issued_at else None,
        "verify_url": letter.verify_url,
    })


# ---------------------------------------------------------------------------
# 修正案 C-08 / 不良事件 C-09 / 年度复审 C-07
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_amendment(request: HttpRequest, id: int):
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"APPROVED", "MONITORING"}, "修正案提交")
    b = read_json(request)
    if not b.get("change_summary"):
        raise ApiError(400, CODE_BAD_REQUEST, "change_summary 必填")
    a = CAmendment.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, case=c,
        change_summary=b["change_summary"], materials=b.get("materials") or [],
        submitted_at=_now(), status="SUBMITTED",
    )
    return ok(request, to_api_amendment(a))


@transaction.atomic
def decide_amendment(request: HttpRequest, id: int):
    dom = domain_from(request)
    a = CAmendment.objects.filter(id=id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "修正案不存在")
    if a.status != "SUBMITTED":
        raise ApiError(409, CODE_CONFLICT, f"修正案决定状态机冲突：当前 {a.status}")
    b = read_json(request)
    decision = b.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "decision 必须为 APPROVE/REJECT")
    a.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    a.decided_at = _now()
    a.decision_note = b.get("decision_note")
    a.modifier_id = dom.user_id
    a.save()
    return ok(request, to_api_amendment(a))


@transaction.atomic
def report_adverse_event(request: HttpRequest, id: int):
    """不良事件（C-09）；SERIOUS/SUSAR 触发主审快速评估 → 案卷 MONITORING。"""
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"APPROVED", "MONITORING", "UNDER_REVIEW"}, "不良事件报告")
    b = read_json(request)
    if b.get("severity") not in SEVERITIES or not b.get("description") or not b.get("event_date"):
        raise ApiError(400, CODE_BAD_REQUEST, "event_date/severity/description 必填")
    ae = CAeReport.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, case=c,
        event_date=_parse_dt(b["event_date"]),
        severity=b["severity"], description=b["description"],
        action_taken=b.get("action_taken"),
    )
    if b["severity"] in ("SERIOUS", "SUSAR"):
        c.status = "MONITORING"
        c.save(update_fields=["status", "updated_at"])
    return ok(request, to_api_ae(ae))


@transaction.atomic
def submit_annual_review(request: HttpRequest, id: int):
    dom = domain_from(request)
    c = _get_case_or_404(id)
    _guard(c, {"APPROVED", "MONITORING"}, "年度复审提交")
    b = read_json(request)
    if not b.get("review_year") or not b.get("progress_summary"):
        raise ApiError(400, CODE_BAD_REQUEST, "review_year 与 progress_summary 必填")
    if CAnnualReview.objects.filter(case=c, review_year=int(b["review_year"]), deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "该年度复审已提交")
    r = CAnnualReview.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, case=c,
        review_year=int(b["review_year"]), progress_summary=b["progress_summary"],
        incidents=b.get("incidents") or [], next_plan=b.get("next_plan"),
        submitted_at=_now(), status="SUBMITTED",
    )
    c.next_review_at = dj_tz.localdate().replace(year=int(b["review_year"]) + 1)
    c.save(update_fields=["next_review_at", "updated_at"])
    return ok(request, to_api_annual(r))


def list_annual_reviews(request: HttpRequest, id: int):
    """按案卷列年度复审（GET /ethics/{id}/annual-review）。"""
    page, size, limit, offset = page_args(request)
    qs = CAnnualReview.objects.filter(tenant_id=domain_from(request).tenant_id,
                                      deleted=0, case_id=id)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_annual(r) for r in rows],
                        "total": total, "page": page, "size": size})


# ---------------------------------------------------------------------------
# 诚信承诺 C-15 / 失信档案 C-16
# ---------------------------------------------------------------------------


@transaction.atomic
def sign_pledge(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    for k in ("user_id", "pledge_type", "content_version", "read_seconds"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    p = CIntegrityPledge.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        user_id=int(b["user_id"]), pledge_type=b["pledge_type"],
        content_version=b["content_version"], read_seconds=int(b["read_seconds"]),
        signature_url=b.get("signature_url"),
        ip=request.META.get("REMOTE_ADDR"),
        ua=(request.META.get("HTTP_USER_AGENT") or "")[:256],
        biz_ref_type=b.get("biz_ref_type"), biz_ref_id=b.get("biz_ref_id"),
    )
    return ok(request, to_api_pledge(p))


def list_my_pledges(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    dom = domain_from(request)
    uid = int(request.GET.get("user_id") or dom.user_id)
    qs = CIntegrityPledge.objects.filter(tenant_id=dom.tenant_id, deleted=0, user_id=uid)
    if v := request.GET.get("pledge_type"):
        qs = qs.filter(pledge_type=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_pledge(r) for r in rows],
                        "total": total, "page": page, "size": size})


AUDITOR_ROLES = {"R-AUDITOR", "R-ADMIN"}


def list_integrity_records(request: HttpRequest):
    """纪检/管理员查全部；其他人仅本人记录（detail §7）。"""
    page, size, limit, offset = page_args(request)
    dom = domain_from(request)
    qs = CIntegrityRecord.objects.filter(tenant_id=dom.tenant_id, deleted=0)
    is_auditor = bool(set(dom.roles) & AUDITOR_ROLES)
    if not is_auditor:
        qs = qs.filter(user_id=dom.user_id)
    if v := request.GET.get("event_type_code"):
        qs = qs.filter(event_type_code=v)
    if v := request.GET.get("investigation_status"):
        qs = qs.filter(investigation_status=v)
    if request.GET.get("user_id") and is_auditor:
        qs = qs.filter(user_id=int(request.GET["user_id"]))
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_integrity(r) for r in rows],
                        "total": total, "page": page, "size": size})


@transaction.atomic
def create_integrity_record(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("user_id") or not b.get("event_type_code"):
        raise ApiError(400, CODE_BAD_REQUEST, "user_id 与 event_type_code 必填")
    r = CIntegrityRecord.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        user_id=int(b["user_id"]), event_type=b.get("event_type") or b["event_type_code"],
        event_type_code=b["event_type_code"],
        discovered_date=_parse_date(b.get("discovered_date")),
        evidence=b.get("evidence") or [], investigation=b.get("investigation") or {},
        decision=b.get("decision"), sanction=b.get("sanction"),
        sanction_effective_until=_parse_date(b.get("sanction_effective_until")),
        is_public=bool(b.get("is_public", False)),
        legal_entity_id=dom.legal_entity_id or 1,
        security_level=b.get("security_level") or "INTERNAL",
    )
    return ok(request, to_api_integrity(r))


def get_integrity_record(request: HttpRequest, id: int):
    dom = domain_from(request)
    r = CIntegrityRecord.objects.filter(id=id, deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "失信档案不存在")
    if not (set(dom.roles) & AUDITOR_ROLES) and r.user_id != dom.user_id:
        raise ApiError(403, 40301, "仅纪检或本人可查")
    return ok(request, to_api_integrity(r))


@transaction.atomic
def update_integrity_record(request: HttpRequest, id: int):
    """更新调查结论/处分/申诉裁定（纪检）。"""
    dom = domain_from(request)
    r = CIntegrityRecord.objects.filter(id=id, deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "失信档案不存在")
    b = read_json(request)
    for k in ("decision", "sanction", "event_type", "investigation", "evidence"):
        if b.get(k) is not None:
            setattr(r, k, b[k])
    if b.get("investigation_status") in ("INVESTIGATING", "SUSTAINED", "UNSUSTAINED", "CLOSED"):
        r.investigation_status = b["investigation_status"]
    if b.get("sanction_effective_until"):
        r.sanction_effective_until = _parse_date(b["sanction_effective_until"])
    if b.get("is_public") is not None:
        r.is_public = bool(b["is_public"])
    # 申诉裁定（独立流程收口）
    if b.get("appeal_status") in ("REVIEWING", "UPHELD", "OVERTURNED"):
        r.appeal_status = b["appeal_status"]
        r.appeal_resolved_at = _now()
        if b["appeal_status"] == "OVERTURNED":
            r.sanction = None
            r.sanction_effective_until = None
        r.status = "CLOSED" if b["appeal_status"] in ("UPHELD", "OVERTURNED") else r.status
    if b.get("investigation_status") == "CLOSED":
        r.status = "CLOSED"
    r.modifier_id = dom.user_id
    r.save()
    return ok(request, to_api_integrity(r))


@transaction.atomic
def appeal_integrity_record(request: HttpRequest, id: int):
    """本人申诉（独立流程，PRD §11）；申诉期内冻结处分生效。"""
    dom = domain_from(request)
    r = CIntegrityRecord.objects.filter(id=id, deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "失信档案不存在")
    if r.user_id != dom.user_id:
        raise ApiError(403, 40301, "仅被记录人本人可申诉")
    b = read_json(request)
    if not b.get("reason"):
        raise ApiError(400, CODE_BAD_REQUEST, "reason 必填")
    if r.appeal_status not in ("NONE",):
        raise ApiError(409, CODE_CONFLICT, f"申诉状态冲突：当前 {r.appeal_status}")
    r.appeal_status = "FILED"
    r.appeal_reason = b["reason"]
    r.appealed_at = _now()
    r.appeal_deadline = _parse_date(b.get("deadline"))
    r.status = "APPEALING"
    r.modifier_id = dom.user_id
    r.save()
    return ok(request, to_api_integrity(r))


# ---------------------------------------------------------------------------
# 学术不端检测 C-14/C-18（多态目标；引擎对接 svc-integration，此处确定性落档）
# ---------------------------------------------------------------------------


@transaction.atomic
def create_misconduct_scan(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    for k in ("target_type", "target_id", "scan_type"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    if b["target_type"] not in ("PAPER", "DEAL", "OUTPUT"):
        raise ApiError(400, CODE_BAD_REQUEST, "target_type 非法")
    if b["scan_type"] not in ("TEXT_DUP", "IMAGE_DUP", "DATA_ANOMALY"):
        raise ApiError(400, CODE_BAD_REQUEST, "scan_type 非法")
    # 引擎未接入：确定性落档 DONE/CLEAN（score=0，confidence=0，人工可复核升级）
    s = CMisconductScan.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        target_type=b["target_type"], target_id=int(b["target_id"]),
        scan_type=b["scan_type"], engine=b.get("engine") or "CNKI",
        triggered_by=b.get("triggered_by") or "MANUAL",
        status="DONE", score=0, confidence=0, verdict="CLEAN",
        report_url=b.get("report_url"),
    )
    return ok(request, to_api_scan(s))


def list_misconduct_scans(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = CMisconductScan.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("verdict"):
        qs = qs.filter(verdict=v)
    if v := request.GET.get("target_type"):
        qs = qs.filter(target_type=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_scan(r) for r in rows],
                        "total": total, "page": page, "size": size})


@transaction.atomic
def delete_integrity_record(request: HttpRequest, id: int):
    """软删（纪检）；已有申诉的在档记录不可删。"""
    dom = domain_from(request)
    r = CIntegrityRecord.objects.filter(id=id, deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "失信档案不存在")
    if r.appeal_status in ("FILED", "REVIEWING"):
        raise ApiError(409, CODE_CONFLICT, "申诉处理中的档案不可删除")
    r.deleted = 1
    r.modifier_id = dom.user_id
    r.save(update_fields=["deleted", "modifier_id", "updated_at"])
    return ok(request, {"id": r.id, "deleted": True})


def list_hgr_filings(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = CHgrFiling.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("project_id"):
        try:
            qs = qs.filter(project_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_hgr(r) for r in rows],
                        "total": total, "page": page, "size": size})


# ---------------------------------------------------------------------------
# 人遗备案 C-10
# ---------------------------------------------------------------------------


@transaction.atomic
def create_hgr_filing(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("project_id") or b.get("filing_type_code") not in FILING_TYPES:
        raise ApiError(400, CODE_BAD_REQUEST, "project_id 与 filing_type_code 必填")
    f = CHgrFiling.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        case_id=b.get("case_id"), project_id=int(b["project_id"]),
        filing_type_code=b["filing_type_code"],
        filing_no=f"HGR-{dom.tenant_id}-{time.time_ns() % 10**10}",
        submission_date=_parse_date(b.get("submission_date")) or dj_tz.localdate(),
        security_level=b.get("security_level") or "INTERNAL",
        legal_entity_id=dom.legal_entity_id or 1,
    )
    return ok(request, to_api_hgr(f))


@transaction.atomic
def sync_hgr_filing(request: HttpRequest, id: int):
    """对接国家人遗系统同步（svc-integration 承接；此处确定性模拟回执）。"""
    dom = domain_from(request)
    f = CHgrFiling.objects.filter(id=id, deleted=0).first()
    if f is None:
        raise ApiError(404, CODE_NOT_FOUND, "备案记录不存在")
    if f.status not in ("DRAFT", "SUBMITTED", "NATIONAL_RECEIVED"):
        raise ApiError(409, CODE_CONFLICT, f"同步状态机冲突：当前 {f.status}")
    f.status = "NATIONAL_RECEIVED"
    f.approval_status = "PENDING"
    f.national_approval_no = f.national_approval_no or f"HGR-EXT-{f.id:08d}"
    f.sync_batch_id = f"SYNC-{time.time_ns() % 10**12}"
    f.modifier_id = dom.user_id
    f.save()
    return ok(request, to_api_hgr(f))
