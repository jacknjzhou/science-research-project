"""项目过程域 E API 形状（对齐 Go project/mapper.go）。"""
from __future__ import annotations

from typing import Any

from apps.project.models import (
    EChangeRequest,
    EFinalAccept,
    EMidCheck,
    EMilestone,
    EProgressReport,
    EProject,
    EProjectCategory,
    ETask,
)
from apps.sysadmin.mappings import fmt_ts


def _date(d) -> str | None:
    return d.isoformat() if d else None


def _num2(v) -> str:
    return "0" if v is None else f"{float(v):.2f}"


def to_api_project(r: EProject) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "deleted": r.deleted, "creator_id": r.creator_id, "modifier_id": r.modifier_id,
        "remark": r.remark, "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "application_id": r.application_id, "title": r.title, "project_type": r.project_type,
        "pi_user_id": r.pi_user_id, "member_ids": r.member_ids or [],
        "department_id": r.department_id, "legal_entity_id": r.legal_entity_id,
        "start_date": _date(r.start_date), "end_date": _date(r.end_date),
        "actual_end_date": _date(r.actual_end_date),
        "total_budget": _num2(r.total_budget), "received_amount": _num2(r.received_amount),
        "spent_amount": _num2(r.spent_amount), "health_score": r.health_score,
        "risk_level": r.risk_level, "ethics_case_id": r.ethics_case_id,
        "policy_pack_id": r.policy_pack_id, "security_level": r.security_level,
    }


def to_api_task(r: ETask) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "deleted": r.deleted, "creator_id": r.creator_id, "modifier_id": r.modifier_id,
        "remark": r.remark, "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "project_id": r.project_id, "parent_task_id": r.parent_task_id, "name": r.name,
        "description": r.description, "owner_user_id": r.owner_user_id,
        "member_ids": r.member_ids or [], "dep_task_ids": r.dep_task_ids or [],
        "planned_start": _date(r.planned_start), "planned_end": _date(r.planned_end),
        "actual_start": _date(r.actual_start), "actual_end": _date(r.actual_end),
        "progress_percent": r.progress_percent, "weight": _num2(r.weight),
    }


def to_api_milestone(r: EMilestone) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "deleted": r.deleted, "creator_id": r.creator_id, "modifier_id": r.modifier_id,
        "remark": r.remark, "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "project_id": r.project_id, "name": r.name, "due_date": _date(r.due_date),
        "actual_date": _date(r.actual_date), "evidence_docs": r.evidence_docs or [],
        "owner_user_id": r.owner_user_id, "deliverable_type": r.deliverable_type,
        "weight": _num2(r.weight),
    }


def to_api_progress_report(r: EProgressReport) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "deleted": r.deleted, "creator_id": r.creator_id, "modifier_id": r.modifier_id,
        "remark": r.remark, "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "project_id": r.project_id, "period": r.period, "report_type": r.report_type,
        "content_rich": r.content_rich, "progress_percent": r.progress_percent,
        "issues_text": r.issues_text, "next_plan": r.next_plan,
        "attachment_ids": r.attachment_ids or [], "submitted_at": fmt_ts(r.submitted_at),
    }


def to_api_mid_check(r: EMidCheck) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "deleted": r.deleted, "creator_id": r.creator_id, "modifier_id": r.modifier_id,
        "remark": r.remark, "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "project_id": r.project_id, "check_round": r.check_round, "check_date": _date(r.check_date),
        "plan_id": r.plan_id, "template_id": r.template_id, "expert_ids": r.expert_ids or [],
        "conclusion": r.conclusion, "score_detail": r.score_detail, "report_id": r.report_id,
        "correct_deadline": _date(r.correct_deadline), "status_overdue": r.status_overdue,
    }


def to_api_change_request(r: EChangeRequest) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "deleted": r.deleted, "creator_id": r.creator_id, "modifier_id": r.modifier_id,
        "remark": r.remark, "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "project_id": r.project_id, "change_type": r.change_type, "old_value": r.old_value,
        "new_value": r.new_value, "reason": r.reason, "effective_from": _date(r.effective_from),
        "approval_status": r.approval_status, "approved_at": fmt_ts(r.approved_at),
        "impact_analysis": r.impact_analysis, "conflict_flag": r.conflict_flag,
        "snapshot_ref": r.snapshot_ref,
    }


def to_api_final_accept(r: EFinalAccept) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "deleted": r.deleted, "creator_id": r.creator_id, "modifier_id": r.modifier_id,
        "remark": r.remark, "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "project_id": r.project_id, "apply_at": fmt_ts(r.apply_at), "accept_at": fmt_ts(r.accept_at),
        "output_summary": r.output_summary, "finance_report_id": r.finance_report_id,
        "expert_ids": r.expert_ids or [], "conclusion": r.conclusion,
        "attachment_ids": r.attachment_ids or [], "archive_checklist_id": r.archive_checklist_id,
    }


def to_api_category(r: EProjectCategory) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "name": r.name, "level": r.level,
        "mgmt_fee_pct": _num2(r.mgmt_fee_pct),
        "midcheck_from": _date(r.midcheck_from), "midcheck_to": _date(r.midcheck_to),
        "closing_from": _date(r.closing_from), "closing_to": _date(r.closing_to),
        "created_at": fmt_ts(r.created_at),
    }
