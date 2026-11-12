"""经费域 F 模型（对齐 Go f_schema.sql 全部表结构，db_table 保留）。

金额一律 NUMERIC(18,2)（PRD 2.6，Django DecimalField 承载）；
预算行余额 remaining = planned + adjusted - frozen - used - released（应用层计算）。
"""
from __future__ import annotations

from django.db import models


class FSubject(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # ACTIVE/INACTIVE/SUPERSEDED
    status = models.CharField(max_length=32, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    name = models.CharField(max_length=128)
    parent_id = models.BigIntegerField(null=True, blank=True)  # 树形上级
    level = models.SmallIntegerField(default=1)
    # DIRECT/INDIRECT/PERFORMANCE
    category = models.CharField(max_length=16)
    is_leaf = models.BooleanField(default=True)
    ratio_limit = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    applies_to = models.JSONField(null=True, blank=True)
    sort_no = models.IntegerField(default=0)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "f_subject"


class FBudget(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # BUD-年-序
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/UNDER_REVIEW/APPROVED/EXECUTING/ADJUSTING/RE_APPROVED/CLOSED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField()
    # 预算制/包干制
    mode = models.CharField(max_length=8, default="预算制")
    total_approved = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_adjusted = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    pending_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    version = models.IntegerField(default=1)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.BigIntegerField(null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "f_budget"


class FBudgetLine(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # ACTIVE/FROZEN/CLOSED
    status = models.CharField(max_length=32, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    budget_id = models.BigIntegerField()
    subject_id = models.BigIntegerField()
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    amount_planned = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_adjusted = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    pending_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_frozen = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_used = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_released = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    @property
    def remaining(self) -> "decimal.Decimal":
        return (self.amount_planned + self.amount_adjusted
                - self.amount_frozen - self.amount_used - self.amount_released)

    class Meta:
        db_table = "f_budget_line"


class FIncome(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # INC-年-序
    tenant_id = models.BigIntegerField()
    # ACTIVE/REVERSED/CLOSED
    status = models.CharField(max_length=32, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField(null=True, blank=True)  # 认领后回填
    legal_entity_id = models.BigIntegerField(default=1)
    receipt_no = models.CharField(max_length=64, null=True, blank=True)
    receipt_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payer_name = models.CharField(max_length=256, null=True, blank=True)
    payer_bank = models.CharField(max_length=128, null=True, blank=True)
    purpose_text = models.TextField(null=True, blank=True)
    bank_flow_no = models.CharField(max_length=64, null=True, blank=True)
    # UNCLAIMED/AUTO_MATCHED/CLAIMED/DOUBTFUL
    claim_status = models.CharField(max_length=16, default="UNCLAIMED")
    match_confidence = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    claimed_by = models.BigIntegerField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    voucher_url = models.CharField(max_length=512, null=True, blank=True)
    mgmt_fee = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # T21 认领入账管理费

    class Meta:
        db_table = "f_income"


class FExpense(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # EXP-年-序
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/AI_REVIEW/HUMAN_REVIEW/APPROVED/REJECTED/RETURNED/PAID/VOUCHER_SYNCED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField()
    budget_line_id = models.BigIntegerField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField()
    applicant_user_id = models.BigIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    expense_category = models.CharField(max_length=32, null=True, blank=True)
    # EQUIPMENT/MATERIAL/TRAVEL/MEETING/LABOR/EXPERT/OTHER
    expense_type = models.CharField(max_length=16, default="OTHER")
    description = models.TextField(null=True, blank=True)
    invoice_ids = models.JSONField(default=list)
    attachment_ids = models.JSONField(default=list)
    # 发票三重指纹（发票号+金额+开票日期）查重，命中拒绝（PRD 11）
    fingerprint_invoice_no = models.CharField(max_length=64, null=True, blank=True)
    fingerprint_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    fingerprint_invoice_date = models.DateField(null=True, blank=True)
    fingerprint_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    # 预算制/包干制
    submit_mode = models.CharField(max_length=8, default="预算制")
    # PASS/REVIEW/REJECT（AI 仅建议）
    ai_verdict = models.CharField(max_length=8, null=True, blank=True)
    ai_confidence = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    # PENDING/PASSED/FAILED/MANUAL（税总查验）
    invoice_check_status = models.CharField(max_length=16, default="PENDING")
    submitted_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    frozen_at = models.DateTimeField(null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # 差旅/借款关联（M1-a）
    related_loan_id = models.BigIntegerField(null=True, blank=True)
    travel_over_limit = models.BooleanField(default=False)
    travel_staff_category = models.CharField(max_length=32, null=True, blank=True)
    travel_city_tier = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        db_table = "f_expense"


class FExpenseApproval(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/DONE/SKIPPED/DELEGATED
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    expense_id = models.BigIntegerField()
    step_order = models.IntegerField()
    approver_user_id = models.BigIntegerField(null=True, blank=True)
    role = models.CharField(max_length=32, null=True, blank=True)  # R-MANAGER/R-FINANCE/R-LEADER/PI
    # APPROVE/REJECT/RETURN/DELEGATE
    action = models.CharField(max_length=16, null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    ai_suggestion = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "f_expense_approval"


class FIndirectFee(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/CALCULATED/POSTED/REVERSED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    period = models.CharField(max_length=8)  # YYYYMM
    total_budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    actual_income = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    actual_expense = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    indirect_rate = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    indirect_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    performance_rate = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    performance_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    calc_detail = models.JSONField(null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "f_indirect_fee"


class FOutward(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/APPROVED/REJECTED
    status = models.CharField(max_length=16, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField()
    budget_id = models.BigIntegerField(null=True, blank=True)
    budget_line_id = models.BigIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    to_unit = models.CharField(max_length=256)
    reason = models.TextField(null=True, blank=True)
    first_approved_by = models.BigIntegerField(null=True, blank=True)
    first_approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.BigIntegerField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "f_outward"


class FCarryover(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/APPROVED/REJECTED
    status = models.CharField(max_length=16, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField()
    fiscal_year = models.IntegerField()
    target_year = models.IntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    income_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "f_carryover"


class FWarnConfig(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=16, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_category_id = models.BigIntegerField(null=True, blank=True)
    warn_kind = models.CharField(max_length=32)
    threshold_pct = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    ahead_days = models.IntegerField(null=True, blank=True)
    level = models.CharField(max_length=8, default="P2")
    channel = models.CharField(max_length=16, default="INBOX")
    cron_expr = models.CharField(max_length=64, null=True, blank=True)
    template = models.TextField(null=True, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "f_warn_config"


class FInvoice(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # INV-年-序，code_of("INV", id) 回填
    tenant_id = models.BigIntegerField()
    # DRAFT/OCR_DONE/CHECKED/BOUND/VOID
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    number = models.CharField(max_length=64, null=True, blank=True)  # 发票号码
    invoice_code = models.CharField(max_length=32, null=True, blank=True)  # 发票代码
    # GENERAL/SPECIAL/ELECTRONIC/ITINERARY
    invoice_type = models.CharField(max_length=16, default="ELECTRONIC")
    seller_name = models.CharField(max_length=256, null=True, blank=True)
    seller_tax_id = models.CharField(max_length=32, null=True, blank=True)
    buyer_name = models.CharField(max_length=256, null=True, blank=True)
    buyer_tax_id = models.CharField(max_length=32, null=True, blank=True)
    amount_excl_tax = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    issue_date = models.DateField(null=True, blank=True)
    ocr_confidence = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    ocr_raw_json = models.JSONField(null=True, blank=True)
    # PASS/FAIL/PENDING
    check_result = models.CharField(max_length=16, default="PENDING")
    is_duplicated = models.BooleanField(default=False)
    expense_id = models.BigIntegerField(null=True, blank=True)
    remark = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "f_invoice"


class FLoan(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # LOAN-年-序
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/APPROVED/REJECTED/RETURNED/PAID/CLOSED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField()
    budget_line_id = models.BigIntegerField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField()
    applicant_user_id = models.BigIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    reason = models.TextField(null=True, blank=True)
    write_off_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    refunded_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    frozen_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    @property
    def remaining_for_writeoff(self) -> "decimal.Decimal":
        return (self.amount - self.write_off_amount - self.refunded_amount)

    class Meta:
        db_table = "f_loan"


class FTravelStandard(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    name = models.CharField(max_length=64)
    staff_category = models.CharField(max_length=32)  # 员工类别
    city_tier = models.CharField(max_length=32)  # 城市类别
    accommodation_cap = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    meals_cap = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    transport_cap = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    # ACTIVE/DISABLED
    status = models.CharField(max_length=16, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    @property
    def total_cap(self) -> "decimal.Decimal":
        return (self.accommodation_cap + self.meals_cap + self.transport_cap)

    class Meta:
        db_table = "f_travel_standard"
