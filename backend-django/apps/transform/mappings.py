"""成果转化域 T 契约映射（对齐 05-T.openapi.yaml 实体 schema）。

契约 number 字段（金额/比例）→ float 输出；其余 NUMERIC 按 Phase 2/3 惯例字符串。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone as dj_tz

from apps.transform.models import (
    TAnnualReport,
    TApprovalChain,
    TContract,
    TDeal,
    TDisclosure,
    TDistributionRecord,
    TDistributionRule,
    TEnterpartner,
    TIncome,
    TPublicity,
    TValuation,
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


def num4(v) -> str:
    if v is None:
        return "0"
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


def to_api_disclosure(r: TDisclosure) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "tenant_id": r.tenant_id,
        "status": r.status,
        "output_id": r.output_id,
        "project_id": r.project_id,
        "disclosed_by": r.disclosed_by,
        "department_id": r.department_id,
        "disclosure_date": fmt_date(r.disclosure_date),
        "tech_summary": r.tech_summary,
        "application_scenarios": r.application_scenarios or [],
        "maturity_level": r.maturity_level,
        "is_core_tech": r.is_core_tech,
        "target_partners": r.target_partners or [],
        "expected_value": num_float(r.expected_value),
        "legal_entity_id": r.legal_entity_id,
        "security_level": r.security_level,
        "created_at": fmt_ts(r.created_at),
        "updated_at": fmt_ts(r.updated_at),
        "remark": r.remark,
    }


def to_api_valuation(r: TValuation) -> dict[str, Any]:
    return {
        "id": r.id,
        "disclosure_id": r.disclosure_id,
        "code": r.code,
        "status": r.status,
        "valuator_type": r.valuator_type,
        "valuator_name": r.valuator_name,
        "valuator_org": r.valuator_org,
        "method": r.method,
        "valuation_amount": num_float(r.valuation_amount),
        "currency": r.currency,
        "report_url": r.report_url,
        "valuation_date": fmt_date(r.valuation_date),
        "valid_until": fmt_date(r.valid_until),
    }


def to_api_partner(r: TEnterpartner) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "status": r.status,
        "company_name": r.company_name,
        "credit_code": r.credit_code,
        "industry": r.industry,
        "register_status": r.register_status,
        "check_abnormal": r.check_abnormal,
        "tech_needs": r.tech_needs or [],
        "contact": r.contact,
        "past_deals": r.past_deals or [],
        "evaluation_score": num_float(r.evaluation_score),
        "last_checked_at": fmt_ts(r.last_checked_at),
    }


def to_api_deal(r: TDeal) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "status": r.status,
        "disclosure_id": r.disclosure_id,
        "output_id": r.output_id,
        "project_id": r.project_id,
        "enterpartner_id": r.enterpartner_id,
        "deal_type": r.deal_type,
        "partner_name": r.partner_name,
        "partner_credit_code": r.partner_credit_code,
        "contract_amount": num_float(r.contract_amount),
        "payment_method": r.payment_method,
        "initial_fee": num_float(r.initial_fee),
        "royalty_rate": num_float(r.royalty_rate),
        "term_start": fmt_date(r.term_start),
        "term_end": fmt_date(r.term_end),
        "partner_check_abnormal": r.partner_check_abnormal,
        "equity_ratio": num_float(r.equity_ratio),
        "equity_value": num_float(r.equity_value),
        "approval_required_level": r.approval_required_level,
        "policy_pack_id": r.policy_pack_id,
        "signed_at": fmt_ts(r.signed_at),
        "legal_entity_id": r.legal_entity_id,
        "security_level": r.security_level,
        "terminated_reason": r.terminated_reason,
    }


def to_api_contract(r: TContract) -> dict[str, Any]:
    return {
        "id": r.id,
        "deal_id": r.deal_id,
        "code": r.code,
        "status": r.status,
        "contract_no": r.contract_no,
        "template_code": r.template_code,
        "contract_file_url": r.contract_file_url,
        "redline_file_url": r.redline_file_url,
        "signed_at": fmt_ts(r.signed_at),
        "seal_records": r.seal_records or [],
        "legal_opinion": r.legal_opinion,
        "finance_opinion": r.finance_opinion,
        "leader_opinion": r.leader_opinion,
        "ai_risk_report": r.ai_risk_report,
        "version": r.version,
    }


def to_api_chain(r: TApprovalChain) -> dict[str, Any]:
    return {
        "id": r.id,
        "deal_id": r.deal_id,
        "step_order": r.step_order,
        "parallel_group": r.parallel_group,
        "approver_role": r.approver_role,
        "approver_id": r.approver_id,
        "status": r.status,
        "action": r.action,
        "comment": r.comment,
        "amount_threshold": num_float(r.amount_threshold),
        "acted_at": fmt_ts(r.acted_at),
    }


def to_api_income(r: TIncome) -> dict[str, Any]:
    return {
        "id": r.id,
        "deal_id": r.deal_id,
        "finance_receipt_id": r.finance_receipt_id,
        "status": r.status,
        "received_date": fmt_date(r.received_date),
        "amount": num_float(r.amount),
        "currency": r.currency,
        "receipt_no": r.receipt_no,
        "bank_flow_no": r.bank_flow_no,
        "payment_phase": r.payment_phase,
        "sales_amount": num_float(r.sales_amount),
        "royalty_calc_amount": num_float(r.royalty_calc_amount),
        "voucher_url": r.voucher_url,
        "allocated": r.allocated,
    }


def to_api_rule(r: TDistributionRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "status": r.status,
        "rule_name": r.rule_name,
        "applies_to": r.applies_to,
        "team_pct": num_float(r.team_pct),
        "institute_pct": num_float(r.institute_pct),
        "individual_pct": num_float(r.individual_pct),
        "min_team_pct": num_float(r.min_team_pct),
        "policy_ref": r.policy_ref,
        "policy_pack_id": r.policy_pack_id,
        "effective_from": fmt_date(r.effective_from),
        "effective_to": fmt_date(r.effective_to),
        "active": r.active,
    }


def to_api_dist_record(r: TDistributionRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "income_id": r.income_id,
        "deal_id": r.deal_id,
        "rule_id": r.rule_id,
        "status": r.status,
        "total_amount": num_float(r.total_amount),
        "team_amount": num_float(r.team_amount),
        "institute_amount": num_float(r.institute_amount),
        "individual_amount": num_float(r.individual_amount),
        "breakdown": r.breakdown or [],
        "held_reason": r.held_reason,
        "dispute_note": r.dispute_note,
        "issued_at": fmt_ts(r.issued_at),
    }


def to_api_publicity(r: TPublicity) -> dict[str, Any]:
    return {
        "id": r.id,
        "deal_id": r.deal_id,
        "status": r.status,
        "publish_start_at": fmt_ts(r.publish_start_at),
        "publish_end_at": fmt_ts(r.publish_end_at),
        "duration_days": r.duration_days,
        "url": r.url,
        "summary_json": r.summary_json or {},
        "objection_open": r.objection_open,
        "objections": r.objections or [],
    }


def to_api_annual(r: TAnnualReport) -> dict[str, Any]:
    return {
        "id": r.id,
        "report_year": r.report_year,
        "status": r.status,
        "total_deals": r.total_deals,
        "total_contract_amount": num_float(r.total_contract_amount),
        "total_income": num_float(r.total_income),
        "total_distributed": num_float(r.total_distributed),
        "top_deals": r.top_deals or [],
        "distribution_summary": r.distribution_summary,
        "report_file_url": r.report_file_url,
        "generated_at": fmt_ts(r.generated_at),
        "published_at": fmt_ts(r.published_at),
    }
