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


class FCostPool(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # CPL-年-序，code_of("CPL", id) 回填
    tenant_id = models.BigIntegerField()
    # DRAFT/CALCULATED/LOCKED/REVERSED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    # 业务列：项目全成本核算与分摊（F-20），全成本=直接费用+Σ间接分摊，联动 A-12 折旧
    project_id = models.BigIntegerField()  # 逻辑引用 E_PROJECT(id)
    legal_entity_id = models.BigIntegerField()
    period = models.CharField(max_length=8)  # 核算期间 YYYYMM
    direct_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # 直接费用合计（报销/外拨/采购）
    indirect_alloc_json = models.JSONField(null=True, blank=True)  # 间接分摊明细 [{type,basis,amount}]
    full_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # 全成本 = direct_cost + Σ间接分摊
    basis_rule_id = models.BigIntegerField(null=True, blank=True)  # 命中的分摊制度规则（可解释/复算）
    policy_pack_id = models.BigIntegerField(null=True, blank=True)  # 分摊依据制度包快照

    class Meta:
        db_table = "f_cost_pool"
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="idx_costpool_tenant_status"),
            models.Index(fields=["project_id"], name="idx_costpool_project"),
        ]


class FAccountingEntry(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # ACC-年-序，code_of("ACC", id) 回填
    tenant_id = models.BigIntegerField()
    # DRAFT/POSTED/SUSPENSE/REVERSED（SUSPENSE=挂账）
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    # 业务列：政府会计制度平行记账（F-21），财务会计权责发生制 + 预算会计收付实现制
    source_txn_id = models.BigIntegerField()  # 源交易 id（报销/收付/折旧，多态）
    # EXPENSE/INCOME/DISBURSEMENT/DEPRECIATION/INDIRECT
    source_txn_type = models.CharField(max_length=16)
    project_id = models.BigIntegerField(null=True, blank=True)  # 逻辑引用 E_PROJECT(id)
    legal_entity_id = models.BigIntegerField()
    period = models.CharField(max_length=8)  # 会计期间 YYYYMM
    fin_entry_json = models.JSONField(null=True, blank=True)  # 财务会计分录（权责发生制 借/贷科目、金额）
    bud_entry_json = models.JSONField(null=True, blank=True)  # 预算会计分录（收付实现制 预算支出/资金结存）
    posted_finance = models.BooleanField(default=False)  # 财务会计过账状态
    posted_budget = models.BooleanField(default=False)  # 预算会计过账状态
    # BALANCED/UNRECONCILED/SUSPENSE（两账勾稽结果）
    reconcile_status = models.CharField(max_length=16, default="UNRECONCILED")
    voucher_sync_id = models.BigIntegerField(null=True, blank=True)  # 关联 F_VOUCHER_SYNC（凭证同步 F-11）
    policy_pack_id = models.BigIntegerField(null=True, blank=True)  # 制度包快照（供复算）

    class Meta:
        db_table = "f_accounting_entry"
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="idx_entry_tenant_status"),
            models.Index(fields=["tenant_id", "reconcile_status"], name="idx_entry_reconcile"),
            models.Index(fields=["project_id"], name="idx_entry_project"),
        ]


class FSettlement(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # SET-年-序，code_of("SET", id) 回填
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/AUDITING/APPROVED/REJECTED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    # 业务列：项目决算与结转结余（F-13），一键生成审计包，E_PROJECT 1:1
    project_id = models.BigIntegerField()  # 逻辑引用 E_PROJECT(id)
    legal_entity_id = models.BigIntegerField()
    closing_date = models.DateField(null=True, blank=True)  # 决算基准日
    income_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # 到账合计
    expense_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # 支出合计
    remaining = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # 结余
    # 结转/收回/留用（结余处理方式）
    treatment = models.CharField(max_length=8, default="结转")
    audit_report_url = models.CharField(max_length=512, null=True, blank=True)  # 决算审计包（PDF）
    approved_by = models.BigIntegerField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    score_detail = models.JSONField(null=True, blank=True)  # 决算各科目执行明细/审计评分

    class Meta:
        db_table = "f_settlement"
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="idx_settle_tenant_status"),
            models.Index(fields=["project_id"], name="idx_settle_project"),
        ]


class FVoucherSync(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # VCH-年-序，code_of("VCH", id) 回填
    tenant_id = models.BigIntegerField()
    # PENDING/SYNCING/SUCCESS/FAILED/MANUAL
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    # 业务列：凭证同步（F-11），expense.approved 事件驱动下发，回调对账，重试 3 次转人工
    expense_id = models.BigIntegerField()  # 同模块逻辑引用 F_EXPENSE(id)（1:1；唯一性应用层 get-or-create 保证）
    # YONYOU=用友/KINGDEE=金蝶/INSPIRE=浪潮
    finance_system = models.CharField(max_length=16)
    voucher_no = models.CharField(max_length=64, null=True, blank=True)  # 财务系统凭证号（回调回填）
    # PENDING/SUCCESS/FAILED
    sync_status = models.CharField(max_length=16, default="PENDING")
    retry_count = models.SmallIntegerField(default=0)  # 重试计数（>3 转人工，PRD 11）
    payload_json = models.JSONField(null=True, blank=True)  # 下发凭证报文
    callback_json = models.JSONField(null=True, blank=True)  # 财务回调回执
    sync_at = models.DateTimeField(null=True, blank=True)
    error_msg = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "f_voucher_sync"
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="idx_voucher_tenant_status"),
            models.Index(fields=["voucher_no"], name="idx_voucher_voucher_no"),
        ]


class FDisbursement(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # DISB-年-序，code_of("DISB", id) 回填
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/APPROVED/PAID/VOUCHER_SYNCED/REJECTED/RETURNED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    # 业务列：外拨经费（F-22），联动 G-09 外协合同，超合同金额上限拦截，审计重点
    contract_id = models.BigIntegerField()  # 逻辑引用 G_CONTRACT(id)→G，跨模块只存 id，一致性走事件（外拨↔合同）
    outsource_unit_id = models.BigIntegerField()  # 逻辑引用 G_SUPPLIER(id)→G
    project_id = models.BigIntegerField()  # 逻辑引用 E_PROJECT(id)
    legal_entity_id = models.BigIntegerField()
    # PUBLIC/INTERNAL/SECRET/TOP_SECRET（横向/涉密外拨密级，参与读写双重过滤，PRD 2.13）
    security_level = models.CharField(max_length=16, default="INTERNAL")
    amount = models.DecimalField(max_digits=18, decimal_places=2)  # 外拨金额
    # 预付/进度/尾款（拨付阶段）
    phase = models.CharField(max_length=8, default="进度")
    approval_chain = models.JSONField(null=True, blank=True)  # 审批链快照
    invoice_url = models.CharField(max_length=512, null=True, blank=True)  # 对方发票/收据附件
    # PENDING/SUCCESS/FAILED/MANUAL（→F-11 凭证同步）
    voucher_status = models.CharField(max_length=16, default="PENDING")
    contract_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)  # 合同总额快照（来自 G，判定上限）
    disbursed_before = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # 本次前已拨累计
    remain_contract_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)  # 合同剩余可拨额（超合同额拦截，F-22）
    compliance_flags = models.JSONField(null=True, blank=True)  # 命中合规规则：整体转包/单一来源未说明/关联外协单位
    policy_pack_id = models.BigIntegerField(null=True, blank=True)  # 外拨限额/合规判定制度包快照

    class Meta:
        db_table = "f_disbursement"
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="idx_disb_tenant_status"),
            models.Index(fields=["contract_id"], name="idx_disb_contract"),
            models.Index(fields=["project_id"], name="idx_disb_project"),
            models.Index(fields=["outsource_unit_id"], name="idx_disb_unit"),
        ]
        # 条件唯一索引 uk_disb_code(tenant_id, code) WHERE deleted=0 不在 Meta 建
        # （sqlite 测试库不支持部分索引，M1-b Task 1 先例：应用层保证）
