"""成果转化域 T 模型（对齐 design/05-科技成果转化-T.ddl.sql，db_table 保留）。

披露 6 态 / 交易 13 态（PRD §6.2）/ 合同 7 态 / 到账 4 态 / 分配规则 3 态 /
分配明细 7 态 / 公示 7 态（独立异议状态机）/ 年报 4 态。
"""
from __future__ import annotations

from django.db import models


class TDisclosure(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/UNDER_EVAL/DEALING/COMPLETED/REJECTED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    output_id = models.BigIntegerField()  # 逻辑引用 R_OUTPUT.id
    project_id = models.BigIntegerField(null=True, blank=True)
    disclosed_by = models.BigIntegerField()
    department_id = models.BigIntegerField(null=True, blank=True)
    disclosure_date = models.DateField()
    tech_summary = models.TextField(null=True, blank=True)
    application_scenarios = models.JSONField(default=list)
    maturity_level = models.SmallIntegerField(null=True, blank=True)  # TRL 1-9
    is_core_tech = models.BooleanField(default=False)
    target_partners = models.JSONField(default=list)
    expected_value = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")

    class Meta:
        db_table = "t_disclosure"


class TValuation(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/ASSIGNED/REPORT_UPLOADED/CONFIRMED/INVALID
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    disclosure = models.ForeignKey(TDisclosure, on_delete=models.CASCADE, db_column="disclosure_id")
    valuator_type = models.CharField(max_length=16)  # INTERNAL/EXTERNAL
    valuator_name = models.CharField(max_length=128, null=True, blank=True)
    valuator_org = models.CharField(max_length=256, null=True, blank=True)
    method = models.CharField(max_length=16, null=True, blank=True)  # 收益法/成本法/市场法
    valuation_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default="CNY")
    report_url = models.CharField(max_length=512, null=True, blank=True)
    valuation_date = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    ai_pricing_ref = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "t_valuation"


class TEnterpartner(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/ACTIVE/BLACKLIST/EXPIRED
    status = models.CharField(max_length=32, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    company_name = models.CharField(max_length=256)
    credit_code = models.CharField(max_length=64, null=True, blank=True)
    industry = models.CharField(max_length=64, null=True, blank=True)
    register_status = models.CharField(max_length=32, null=True, blank=True)
    business_check_json = models.JSONField(null=True, blank=True)
    check_abnormal = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    tech_needs = models.JSONField(default=list)
    contact = models.JSONField(null=True, blank=True)
    past_deals = models.JSONField(default=list)
    evaluation_score = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "t_enterpartner"


class TDeal(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # DEAL-年-序
    tenant_id = models.BigIntegerField()
    # DRAFT/VALUATED/NEGOTIATING/DRAFT_CONTRACT/UNDER_APPROVAL/APPROVED/PUBLICIZED/
    # SIGNED/EXECUTING/INCOME_RECEIVED/DISTRIBUTED/CLOSED/TERMINATED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    disclosure = models.ForeignKey(TDisclosure, on_delete=models.CASCADE, db_column="disclosure_id")
    output_id = models.BigIntegerField()
    project_id = models.BigIntegerField(null=True, blank=True)
    enterpartner = models.ForeignKey(
        TEnterpartner, on_delete=models.SET_NULL, db_column="enterpartner_id", null=True, blank=True
    )
    deal_type = models.CharField(max_length=16)  # 转让/独占许可/排他许可/普通许可/作价投资/合作实施
    partner_name = models.CharField(max_length=256, null=True, blank=True)
    partner_credit_code = models.CharField(max_length=64, null=True, blank=True)
    contract_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=24, default="一次性")
    initial_fee = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    royalty_rate = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    term_start = models.DateField(null=True, blank=True)
    term_end = models.DateField(null=True, blank=True)
    partner_check_abnormal = models.BooleanField(default=False)
    partner_checked_at = models.DateTimeField(null=True, blank=True)
    equity_ratio = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    equity_value = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    exit_arrangement = models.JSONField(null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # LEGAL/FINANCE/INSTITUTE/COMPETENT_DEPT/BOARD
    approval_required_level = models.CharField(max_length=32, null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    signed_at = models.DateTimeField(null=True, blank=True)
    # NEGOTIATION_BREAK/OBJECTION_SUSTAINED/PARTNER_RISK/BREACH/OTHER
    terminated_reason = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        db_table = "t_deal"


class TContract(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/UNDER_APPROVAL/TO_SIGN/SIGNED/AMENDING/ARCHIVED/TERMINATED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    deal = models.ForeignKey(TDeal, on_delete=models.CASCADE, db_column="deal_id")  # 1:1 有效合同
    contract_no = models.CharField(max_length=64, null=True, blank=True)
    template_code = models.CharField(max_length=64, null=True, blank=True)
    contract_file_url = models.CharField(max_length=512, null=True, blank=True)
    redline_file_url = models.CharField(max_length=512, null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    seal_records = models.JSONField(default=list)
    legal_opinion = models.TextField(null=True, blank=True)
    finance_opinion = models.TextField(null=True, blank=True)
    leader_opinion = models.TextField(null=True, blank=True)
    ai_risk_report = models.JSONField(null=True, blank=True)
    version = models.IntegerField(default=1)
    immutable_hash = models.CharField(max_length=128, null=True, blank=True)
    prev_hash = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        db_table = "t_contract"


class TApprovalChain(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/APPROVED/REJECTED/RETURNED/SKIPPED
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    deal = models.ForeignKey(TDeal, on_delete=models.CASCADE, db_column="deal_id")
    step_order = models.IntegerField()
    parallel_group = models.CharField(max_length=32, null=True, blank=True)
    approver_role = models.CharField(max_length=32)  # LEGAL/FINANCE/INSTITUTE/COMPETENT_DEPT/BOARD
    approver_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=16, null=True, blank=True)  # APPROVE/REJECT/RETURN/SKIP
    comment = models.TextField(null=True, blank=True)
    amount_threshold = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "t_approval_chain"
        unique_together = [("deal", "step_order")]


class TIncome(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/MATCHED/ALLOCATED/REVERSED
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    deal = models.ForeignKey(TDeal, on_delete=models.CASCADE, db_column="deal_id")
    finance_receipt_id = models.BigIntegerField(null=True, blank=True)  # 逻辑引用 03 经费到账
    received_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=8, default="CNY")
    receipt_no = models.CharField(max_length=64, null=True, blank=True)
    bank_flow_no = models.CharField(max_length=64, null=True, blank=True)
    payment_phase = models.CharField(max_length=32, null=True, blank=True)
    sales_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    royalty_calc_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    voucher_url = models.CharField(max_length=512, null=True, blank=True)
    allocated = models.BooleanField(default=False)

    class Meta:
        db_table = "t_income"


class TDistributionRule(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/ACTIVE/SUPERSEDED
    status = models.CharField(max_length=32, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    rule_name = models.CharField(max_length=128)
    applies_to = models.CharField(max_length=16)  # 转让/许可/作价
    team_pct = models.DecimalField(max_digits=6, decimal_places=4)
    institute_pct = models.DecimalField(max_digits=6, decimal_places=4)
    individual_pct = models.DecimalField(max_digits=6, decimal_places=4)
    min_team_pct = models.DecimalField(max_digits=6, decimal_places=4)
    policy_ref = models.CharField(max_length=256, null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "t_distribution_rule"


class TDistributionRecord(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/GENERATED/PUBLISHED/CONFIRMED/DISPUTED/HELD/ISSUED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    income = models.ForeignKey(TIncome, on_delete=models.CASCADE, db_column="income_id")  # 1:1
    deal = models.ForeignKey(TDeal, on_delete=models.CASCADE, db_column="deal_id")
    rule = models.ForeignKey(
        TDistributionRule, on_delete=models.SET_NULL, db_column="rule_id", null=True, blank=True
    )
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    team_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    institute_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    individual_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    breakdown = models.JSONField(default=list)  # [{user_id,pct,amount,basis}]
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    dispute_note = models.TextField(null=True, blank=True)
    # DISPUTE/ARBITRATION/OBJECTION/OTHER
    held_reason = models.CharField(max_length=32, null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "t_distribution_record"


class TPublicity(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/PUBLISHED/IN_PROGRESS/OBJECTION_PENDING/OBJECTION_RESOLVED/COMPLETED/TERMINATED
    status = models.CharField(max_length=32, default="PUBLISHED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    deal = models.ForeignKey(TDeal, on_delete=models.CASCADE, db_column="deal_id")
    publish_start_at = models.DateTimeField()
    publish_end_at = models.DateTimeField()
    duration_days = models.IntegerField(default=15)
    url = models.CharField(max_length=512, null=True, blank=True)
    summary_json = models.JSONField(default=dict)
    objections = models.JSONField(default=list)
    objection_open = models.BooleanField(default=False)
    public_snapshot_hash = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        db_table = "t_publicity"


class TAnnualReport(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/GENERATED/PUBLISHED/EXPORTED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    report_year = models.IntegerField()
    total_deals = models.IntegerField(default=0)
    total_contract_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_income = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_distributed = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    top_deals = models.JSONField(default=list)
    distribution_summary = models.JSONField(null=True, blank=True)
    report_file_url = models.CharField(max_length=512, null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "t_annual_report"
        unique_together = [("tenant_id", "report_year", "legal_entity_id")]
