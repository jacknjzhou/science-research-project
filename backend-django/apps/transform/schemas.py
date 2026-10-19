"""T 成果转化域 · 接口请求 Schema 验证定义（pydantic v2，配合 core.reqschema.validate_body）。"""
from __future__ import annotations

from core.reqschema import BaseIn


class DisclosureIn(BaseIn):
    output_id: int
    disclosure_date: str
    tech_summary: str | None = None
    maturity_level: int | None = None
    is_core_tech: bool | None = None
    application_scenarios: list | None = None
    legal_entity_id: int | None = None
    security_level: str | None = None
    remark: str | None = None


class ValuationIn(BaseIn):
    valuator_type: str  # INTERNAL/EXTERNAL（枚举由 handler 判定）
    valuator_name: str | None = None
    valuator_org: str | None = None
    method: str | None = None
    valuation_amount: float | None = None
    report_url: str | None = None
    valuation_date: str | None = None


class DealIn(BaseIn):
    disclosure_id: int
    deal_type: str
    contract_amount: float
    payment_method: str | None = None
    partner_name: str | None = None
    partner_credit_code: str | None = None
    equity_ratio: float | None = None
    exit_arrangement: str | None = None
    royalty_rate: float | None = None
    legal_entity_id: int | None = None
    remark: str | None = None


class NegotiationIn(BaseIn):
    deal_type: str
    contract_amount: float
    payment_method: str | None = None
    partner_name: str | None = None
    partner_credit_code: str | None = None
    equity_ratio: float | None = None
    exit_arrangement: str | None = None
    royalty_rate: float | None = None


class PartnerIn(BaseIn):
    company_name: str
    credit_code: str | None = None
    industry: str | None = None
    register_status: str | None = None
    tech_needs: list | None = None
    contact: str | dict | None = None
    business_check_json: dict | None = None
    past_deals: list | None = None
    evaluation_score: float | None = None
    legal_entity_id: int | None = None


class ContractDraftIn(BaseIn):
    deal_id: int
    contract_text: str | None = None
    clauses: list | None = None
    version: int | None = None
    remark: str | None = None


class ObjectionHandleIn(BaseIn):
    objection_id: str | int  # 公开通道生成的 OBJ<pubId>-<n> 字符串
    handle_status: str
    handle_result: str | None = None
    note: str | None = None


class IncomeIn(BaseIn):
    deal_id: int
    received_date: str
    amount: float
    payer_name: str | None = None
    invoice_url: str | None = None
    remark: str | None = None


class DistributionRuleIn(BaseIn):
    rule_name: str
    applies_to: str | list
    team_pct: float
    institute_pct: float
    individual_pct: float
    min_team_pct: float
    effective_from: str
    hold_dispute_note: str | None = None


class DistributionIssueIn(BaseIn):
    record_id: int | None = None
    note: str | None = None


class AnnualReportIn(BaseIn):
    report_year: int
    content: dict | None = None
    remark: str | None = None
