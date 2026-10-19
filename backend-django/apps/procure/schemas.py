"""G 采购合同域 · 接口请求 Schema 验证定义（pydantic v2，配合 core.reqschema.validate_body）。"""
from __future__ import annotations

from core.reqschema import BaseIn


class RequisitionIn(BaseIn):
    project_id: int
    category: str
    item_name: str
    est_amount: float
    budget_subject_code: str
    applicant_id: int | None = None
    spec: str | None = None
    legal_entity_id: int | None = None
    security_level: str | None = None
    remark: str | None = None


class BidIn(BaseIn):
    requisition_id: int
    method: str
    publish_at: str | None = None
    bid_open_at: str | None = None
    invited_supplier_ids: list | None = None
    bids_json: list | None = None


class AwardIn(BaseIn):
    winner_supplier_id: int | None = None
    winner_reason: str | None = None
    saving_amount: str | None = None
    voided: bool | None = None
    void_reason: str | None = None


class ContractIn(BaseIn):
    contract_type: str
    party_b: str
    amount: float
    requisition_id: int | None = None
    project_id: int | None = None
    supplier_id: int | None = None
    party_a: str | None = None
    currency: str | None = None
    pay_terms_json: list | None = None
    deliverables_json: list | None = None
    start_date: str | None = None
    end_date: str | None = None
    legal_entity_id: int | None = None
    security_level: str | None = None
    payout_subject_code: str | None = None
    remark: str | None = None


class ContractReviewIn(BaseIn):
    role: str
    result: str
    comment: str | None = None


class ContractPlanItemIn(BaseIn):
    phase: str | None = None
    plan_amount: float | None = None
    plan_date: str | None = None


class PaymentPlanIn(BaseIn):
    plans: list[ContractPlanItemIn] | None = None
    phase: str | None = None
    plan_amount: float | None = None
    plan_date: str | None = None


class PaymentCallbackIn(BaseIn):
    payment_id: int
    expense_id: int
    paid_amount: float | None = None
    pay_date: str | None = None
    voucher_status: str | None = None
    invoice_url: str | None = None
