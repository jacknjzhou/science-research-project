"""C 诚信伦理域 · 接口请求 Schema 验证定义（pydantic v2，配合 core.reqschema.validate_body）。

字段名与各 handler 实际读取的请求体键一致（枚举/token 类字段一律 str 放行，
非法取值仍由 handler 按业务码 40001 判定——schema 只负责结构/必填/类型）。
"""
from __future__ import annotations

from core.reqschema import BaseIn


class CaseIn(BaseIn):
    review_type: str
    protocol_title: str
    applicant_user_id: int
    project_id: int | None = None
    department_id: int | None = None
    protocol_summary: str | None = None
    methodology: str | None = None
    risk_level: str | None = None
    informed_consent_url: str | None = None
    materials: list | None = None
    is_emergency: bool | None = None
    legal_entity_id: int | None = None
    security_level: str | None = None
    remark: str | None = None


class FormalCheckIn(BaseIn):
    result: str
    comment: str | None = None
    missing_docs: list | None = None


class AssignReviewersIn(BaseIn):
    assignments: list  # 每项 {reviewer_user_id, role(CHIEF/BOARD)}
    review_deadline: str | None = None


class OpinionIn(BaseIn):
    recommendation: str
    score: float | None = None
    comments: str | None = None
    objection: dict | None = None
    risks_identified: list | None = None


class MeetingVoteIn(BaseIn):
    decision: str
    vote: dict | None = None
    quorum_met: bool | None = None
    attendees: list | None = None
    discussion_text: str | None = None


class AmendmentIn(BaseIn):
    change_summary: str
    materials: list | None = None
    attachment_url: str | None = None
    remark: str | None = None


class AmendmentDecisionIn(BaseIn):
    decision: str
    decision_note: str | None = None


class AdverseEventIn(BaseIn):
    event_date: str
    severity: str
    description: str
    action_taken: str | None = None
    remark: str | None = None


class AnnualReviewIn(BaseIn):
    review_year: int
    progress_summary: str
    incidents: list | None = None
    next_plan: str | None = None
    attachment_url: str | None = None


class PledgeIn(BaseIn):
    user_id: int
    pledge_type: str
    content_version: str
    read_seconds: int
    signature_url: str | None = None
    biz_ref_type: str | None = None
    biz_ref_id: int | None = None


class MisconductScanIn(BaseIn):
    target_type: str
    target_id: int
    scan_type: str
    engine: str | None = None
    triggered_by: str | None = None
    remark: str | None = None


class AppealIn(BaseIn):
    reason: str
    deadline: str | None = None
    evidence: list | None = None


class IntegrityRecordIn(BaseIn):
    user_id: int
    event_type_code: str
    discovered_date: str | None = None
    evidence: list | None = None
    investigation: dict | None = None
    decision: str | None = None
    sanction: str | None = None
    sanction_effective_until: str | None = None
    is_public: bool | None = None
    security_level: str | None = None
    remark: str | None = None


class UpdateIntegrityRecordIn(BaseIn):
    """纪检更新：调查结论/处分/申诉裁定（全可选，PUT /integrity/records/{id}）。"""
    decision: str | None = None
    sanction: str | None = None
    event_type: str | None = None
    investigation: dict | None = None
    evidence: list | None = None
    investigation_status: str | None = None
    sanction_effective_until: str | None = None
    is_public: bool | None = None
    appeal_status: str | None = None
    remark: str | None = None


class HgrFilingIn(BaseIn):
    project_id: int
    filing_type_code: str
    case_id: int | None = None
    submission_date: str | None = None
    security_level: str | None = None
    remark: str | None = None
