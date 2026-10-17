"""科研诚信与伦理域 C 契约映射（对齐 06-C.openapi.yaml）。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone as dj_tz

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


def num2(v) -> str:
    if v is None:
        return "0"
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return f"{Decimal(str(v)):.2f}"


def num_float(v):
    if v is None:
        return None
    return float(v)


def fmt_ts(t):
    if t is None:
        return None
    return dj_tz.localtime(t).isoformat()


def fmt_date(d):
    if d is None:
        return None
    return f"{d:%Y-%m-%d}"


def to_api_case(r: CEthicsCase, masked: bool = False) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "status": r.status,
        "review_type": r.review_type,
        "project_id": r.project_id,
        "applicant_user_id": r.applicant_user_id,
        "department_id": r.department_id,
        # 涉受试者字段：masked=True 时脱敏（列表视图，detail §7）
        "protocol_title": r.protocol_title,
        "protocol_summary": None if masked else r.protocol_summary,
        "methodology": None if masked else r.methodology,
        "risk_level": r.risk_level,
        "materials": r.materials or [],
        "informed_consent_url": None if masked else r.informed_consent_url,
        "ai_prescreen": r.ai_prescreen or {},
        "risk_assessment": r.risk_assessment or {},
        "submitted_at": fmt_ts(r.submitted_at),
        "decision_date": fmt_date(r.decision_date),
        "valid_until": fmt_date(r.valid_until),
        "next_review_at": fmt_date(r.next_review_at),
        "is_emergency": r.is_emergency,
        "legal_entity_id": r.legal_entity_id,
        "security_level": r.security_level,
        "created_at": fmt_ts(r.created_at),
        "remark": r.remark,
    }


def to_api_assign(r: CReviewerAssign) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "reviewer_user_id": r.reviewer_user_id,
        "role": r.role,
        "status": r.status,
        "assigned_at": fmt_ts(r.assigned_at),
        "deadline": fmt_ts(r.deadline),
        "conflict_of_interest": r.conflict_of_interest,
        "coi_reason": r.coi_reason,
    }


def to_api_opinion(r: CReviewOpinion) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "status": r.status,
        "score": num_float(r.score),
        "comments": r.comments,
        "objection": r.objection or {},
        "risks_identified": r.risks_identified or [],
        "recommendation": r.recommendation,
        "submitted_at": fmt_ts(r.created_at),
        # reviewer_user_id 对 PI 匿名：仅委员/管理员视角可查（detail §7），默认不输出
    }


def to_api_meeting(r: CMeetingRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "status": r.status,
        "meeting_date": fmt_ts(r.meeting_date),
        "attendees": r.attendees or [],
        "quorum_met": r.quorum_met,
        "discussion_text": r.discussion_text,
        "decision": r.decision,
        "vote_result": r.vote_result or {},
    }


def to_api_letter(r: CDecisionLetter) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "status": r.status,
        "decision_type": r.decision_type,
        "letter_no": r.letter_no,
        "letter_url": r.letter_url,
        "verify_url": r.verify_url,
        "qr_code_url": r.qr_code_url,
        "issued_at": fmt_ts(r.issued_at),
        "expires_at": fmt_ts(r.expires_at),
    }


def to_api_amendment(r: CAmendment) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "status": r.status,
        "change_summary": r.change_summary,
        "materials": r.materials or [],
        "submitted_at": fmt_ts(r.submitted_at),
        "decided_at": fmt_ts(r.decided_at),
        "decision_note": r.decision_note,
    }


def to_api_ae(r: CAeReport) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "status": r.status,
        "event_date": fmt_ts(r.event_date),
        "severity": r.severity,
        "description": r.description,
        "action_taken": r.action_taken,
        "reported_at": fmt_ts(r.reported_at),
    }


def to_api_annual(r: CAnnualReview) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "status": r.status,
        "review_year": r.review_year,
        "progress_summary": r.progress_summary,
        "incidents": r.incidents or [],
        "next_plan": r.next_plan,
        "submitted_at": fmt_ts(r.submitted_at),
        "approved_at": fmt_ts(r.approved_at),
    }


def to_api_pledge(r: CIntegrityPledge) -> dict[str, Any]:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "status": r.status,
        "pledge_type": r.pledge_type,
        "content_version": r.content_version,
        "read_seconds": r.read_seconds,
        "signed_at": fmt_ts(r.signed_at),
        "signature_url": r.signature_url,
        "biz_ref_type": r.biz_ref_type,
        "biz_ref_id": r.biz_ref_id,
    }


def to_api_integrity(r: CIntegrityRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "status": r.status,
        "user_id": r.user_id,
        "event_type": r.event_type,
        "event_type_code": r.event_type_code,
        "discovered_date": fmt_date(r.discovered_date),
        "evidence": r.evidence or [],
        "investigation": r.investigation or {},
        "case_no": r.case_no,
        "investigation_status": r.investigation_status,
        "decision": r.decision,
        "sanction": r.sanction,
        "sanction_effective_until": fmt_date(r.sanction_effective_until),
        "is_public": r.is_public,
        "appeal_status": r.appeal_status,
        "appeal_deadline": fmt_date(r.appeal_deadline),
        "appeal_reason": r.appeal_reason,
        "appealed_at": fmt_ts(r.appealed_at),
        "appeal_resolved_at": fmt_ts(r.appeal_resolved_at),
        "legal_entity_id": r.legal_entity_id,
        "security_level": r.security_level,
    }


def to_api_scan(r: CMisconductScan) -> dict[str, Any]:
    return {
        "id": r.id,
        "status": r.status,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "scan_type": r.scan_type,
        "score": num_float(r.score),
        "confidence": num_float(r.confidence),
        "report_url": r.report_url,
        "verdict": r.verdict,
        "engine": r.engine,
        "triggered_by": r.triggered_by,
        "scanned_at": fmt_ts(r.scanned_at),
        "investigation_id": r.investigation_id,
    }


def to_api_hgr(r: CHgrFiling) -> dict[str, Any]:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "project_id": r.project_id,
        "status": r.status,
        "filing_type": r.filing_type,
        "filing_type_code": r.filing_type_code,
        "filing_no": r.filing_no,
        "national_approval_no": r.national_approval_no,
        "submission_date": fmt_date(r.submission_date),
        "approval_status": r.approval_status,
        "approval_date": fmt_date(r.approval_date),
        "expiry_date": fmt_date(r.expiry_date),
        "sync_batch_id": r.sync_batch_id,
        "security_level": r.security_level,
    }
