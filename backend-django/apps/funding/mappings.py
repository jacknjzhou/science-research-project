"""经费域 F 契约映射（对齐 Go funding/mapper.go）。

NUMERIC → 定标字符串（PRD 2.6）；时间 RFC3339；金额平衡应用层计算。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone as dj_tz

from apps.funding.models import (
    FBudget,
    FBudgetLine,
    FCarryover,
    FExpense,
    FExpenseApproval,
    FIncome,
    FOutward,
    FSubject,
    FWarnConfig,
)


def num2(v) -> str:
    if v is None:
        return "0"
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return f"{Decimal(str(v)):.2f}"


def num4(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return f"{v:.4f}"
    return f"{Decimal(str(v)):.4f}"


def fmt_ts(t):
    if t is None:
        return None
    return dj_tz.localtime(t).isoformat()


def fmt_date(d):
    if d is None:
        return None
    return f"{d:%Y-%m-%d}"


def code_of(prefix: str, id_: int) -> str:
    return f"{prefix}-{dj_tz.localdate():%Y}-{id_:06d}"


def to_api_subject(s: FSubject) -> dict[str, Any]:
    return {
        "id": s.id, "code": s.code, "name": s.name,
        "parent_id": s.parent_id, "level": s.level,
        "category": s.category, "is_leaf": s.is_leaf,
        "ratio_limit": num4(s.ratio_limit), "sort_no": s.sort_no,
    }


def to_api_budget(b: FBudget) -> dict[str, Any]:
    return {
        "id": b.id, "code": b.code, "project_id": b.project_id,
        "legal_entity_id": b.legal_entity_id, "mode": b.mode,
        "total_approved": num2(b.total_approved), "total_adjusted": num2(b.total_adjusted),
        "version": b.version, "status": b.status,
        "approved_at": fmt_ts(b.approved_at), "approved_by": b.approved_by,
        "created_at": fmt_ts(b.created_at), "updated_at": fmt_ts(b.updated_at),
    }


def to_api_line(l: FBudgetLine) -> dict[str, Any]:
    return {
        "id": l.id, "budget_id": l.budget_id, "subject_id": l.subject_id,
        "amount_planned": num2(l.amount_planned), "amount_adjusted": num2(l.amount_adjusted),
        "amount_frozen": num2(l.amount_frozen), "amount_used": num2(l.amount_used),
        "amount_released": num2(l.amount_released),
        "remaining": num2(l.remaining), "status": l.status,
    }


def to_api_income(i: FIncome) -> dict[str, Any]:
    return {
        "id": i.id, "code": i.code, "project_id": i.project_id,
        "legal_entity_id": i.legal_entity_id, "receipt_no": i.receipt_no,
        "receipt_date": fmt_date(i.receipt_date), "amount": num2(i.amount),
        "payer_name": i.payer_name, "payer_bank": i.payer_bank,
        "purpose_text": i.purpose_text, "bank_flow_no": i.bank_flow_no,
        "claim_status": i.claim_status, "claimed_by": i.claimed_by,
        "claimed_at": fmt_ts(i.claimed_at),
        "mgmt_fee": num2(i.mgmt_fee),
        "created_at": fmt_ts(i.created_at),
    }


def to_api_expense(e: FExpense) -> dict[str, Any]:
    return {
        "id": e.id, "code": e.code, "status": e.status,
        "project_id": e.project_id, "budget_line_id": e.budget_line_id,
        "applicant_user_id": e.applicant_user_id, "amount": num2(e.amount),
        "expense_category": e.expense_category, "expense_type": e.expense_type,
        "description": e.description,
        "submit_mode": e.submit_mode,
        "ai_verdict": e.ai_verdict,
        "invoice_check": e.invoice_check_status,
        "submitted_at": fmt_ts(e.submitted_at),
        "paid_at": fmt_ts(e.paid_at),
        "frozen_at": fmt_ts(e.frozen_at),
        "created_at": fmt_ts(e.created_at),
    }


def to_api_approval(a: FExpenseApproval) -> dict[str, Any]:
    return {
        "id": a.id, "expense_id": a.expense_id, "step_order": a.step_order,
        "approver_user_id": a.approver_user_id, "role": a.role,
        "action": a.action, "comment": a.comment,
        "status": a.status, "acted_at": fmt_ts(a.acted_at),
    }


def to_api_outward(o: FOutward) -> dict[str, Any]:
    return {
        "id": o.id, "code": o.code, "status": o.status,
        "project_id": o.project_id, "budget_line_id": o.budget_line_id,
        "amount": num2(o.amount), "to_unit": o.to_unit,
        "reason": o.reason,
        "first_approved_by": o.first_approved_by, "approved_by": o.approved_by,
        "created_at": fmt_ts(o.created_at),
    }


def to_api_carryover(co: FCarryover) -> dict[str, Any]:
    return {
        "id": co.id, "code": co.code, "status": co.status,
        "project_id": co.project_id, "fiscal_year": co.fiscal_year, "target_year": co.target_year,
        "amount": num2(co.amount), "income_id": co.income_id,
        "remark": co.remark, "created_at": fmt_ts(co.created_at),
    }


def to_api_warn_config(w: FWarnConfig) -> dict[str, Any]:
    return {
        "id": w.id, "warn_kind": w.warn_kind,
        "project_category_id": w.project_category_id,
        "threshold_pct": num4(w.threshold_pct), "ahead_days": w.ahead_days,
        "level": w.level, "channel": w.channel, "cron_expr": w.cron_expr,
        "template": w.template, "enabled": w.enabled,
        "remark": w.remark, "created_at": fmt_ts(w.created_at),
    }
