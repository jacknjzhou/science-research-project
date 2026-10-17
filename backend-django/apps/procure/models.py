"""采购与合同域 G 模型（对齐 design/09-采购与合同管理-G.ddl.sql，db_table 保留）。

申请 6 态（冻结联动 F）/ 供应商 4 态（黑名单硬拦截）/ 招标 3 态（废标回退）/
合同 8 态（评审四方会签）/ 付款计划 5 态（累计≤合同额硬拦截）/ 订单 5 态 / 外协 4 态。
新错误码：40910 超预算冻结失败 / 40911 付款累计超合同额 / 40913 黑名单拦截 / 40916 重复转资产。
"""
from __future__ import annotations

from django.db import models


class GRequisition(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # REQ-年-序
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # DRAFT/SUBMITTED/WAY_DECIDED/BIDDING/ORDERED/CANCELLED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project_id = models.BigIntegerField()
    applicant_id = models.BigIntegerField()
    category = models.CharField(max_length=16)  # 设备/试剂耗材/软件/服务/外协…
    item_name = models.CharField(max_length=256)
    spec = models.TextField(null=True, blank=True)
    est_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    budget_subject_code = models.CharField(max_length=64, null=True, blank=True)
    frozen_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    # 公开招标/邀请招标/竞争性谈判/单一来源/询价/自行采购
    purchase_way = models.CharField(max_length=16, null=True, blank=True)
    way_basis_rule_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "g_requisition"


class GSupplier(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # PENDING/IN_LIBRARY/REJECTED/EXPIRED
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    name = models.CharField(max_length=256)
    credit_code = models.CharField(max_length=64, null=True, blank=True)
    type = models.CharField(max_length=16, default="供应商")  # 供应商/外协单位
    qualification_json = models.JSONField(default=list)
    grade = models.CharField(max_length=2, default="C")
    blacklist = models.BooleanField(default=False)
    qualification_expire_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "g_supplier"


class GBid(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # PUBLICIZING/AWARDED/CHALLENGE
    status = models.CharField(max_length=32, default="PUBLICIZING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    requisition = models.ForeignKey(GRequisition, on_delete=models.CASCADE, db_column="requisition_id")
    method = models.CharField(max_length=16)  # 同 purchase_way 6 种
    publish_at = models.DateTimeField(null=True, blank=True)
    bid_open_at = models.DateTimeField(null=True, blank=True)
    award_at = models.DateTimeField(null=True, blank=True)
    bids_json = models.JSONField(default=list)
    invited_supplier_ids = models.JSONField(default=list)
    winner_supplier_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "g_bid"


class GContract(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # CON-年-序 / OSC-年-序
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # DRAFT/REVIEW/TO_SIGN/ACTIVE/AMENDING/SETTLING/ARCHIVED/TERMINATED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    requisition = models.ForeignKey(
        GRequisition, on_delete=models.SET_NULL, db_column="requisition_id", null=True, blank=True
    )
    contract_type = models.CharField(max_length=16)  # 采购/技术服务/横向/外协分包
    project_id = models.BigIntegerField(null=True, blank=True)
    supplier = models.ForeignKey(
        GSupplier, on_delete=models.PROTECT, db_column="supplier_id", null=True, blank=True
    )
    party_a = models.CharField(max_length=256, null=True, blank=True)
    party_b = models.CharField(max_length=256, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="CNY")
    pay_terms_json = models.JSONField(null=True, blank=True)
    deliverables_json = models.JSONField(null=True, blank=True)
    sign_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    sign_method = models.CharField(max_length=8, null=True, blank=True)  # 电子签/异地/纸质
    archive_checklist_id = models.BigIntegerField(null=True, blank=True)
    ai_parse_json = models.JSONField(null=True, blank=True)
    ai_risk_json = models.JSONField(null=True, blank=True)
    outsource = models.BooleanField(default=False)

    class Meta:
        db_table = "g_contract"


class GContractPayment(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # PLANNED/DUE/PAID/VOUCHER_SYNCED/CANCELLED
    status = models.CharField(max_length=32, default="PLANNED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    contract = models.ForeignKey(GContract, on_delete=models.CASCADE, db_column="contract_id")
    phase = models.CharField(max_length=8)  # 预付/到货/验收/质保
    plan_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    plan_date = models.DateField(null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    paid_at = models.DateTimeField(null=True, blank=True)
    expense_id = models.BigIntegerField(null=True, blank=True)  # F_EXPENSE 回填

    class Meta:
        db_table = "g_contract_payment"


class GOrder(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # ORD-年-序
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # DRAFT/CONFIRMED/EXECUTING/COMPLETED/CANCELLED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    requisition = models.ForeignKey(GRequisition, on_delete=models.CASCADE, db_column="requisition_id")
    contract = models.ForeignKey(
        GContract, on_delete=models.SET_NULL, db_column="contract_id", null=True, blank=True
    )
    supplier = models.ForeignKey(GSupplier, on_delete=models.PROTECT, db_column="supplier_id")
    order_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="CNY")
    order_date = models.DateField(null=True, blank=True)
    expect_delivery_date = models.DateField(null=True, blank=True)
    # PENDING/DELIVERED/ACCEPTED/REJECTED/RETURNED
    delivery_status = models.CharField(max_length=16, default="PENDING")
    delivered_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    acceptance_by = models.BigIntegerField(null=True, blank=True)
    converted_asset = models.BooleanField(default=False)
    converted_target_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "g_order"


class GOutsource(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # EXECUTING/SETTLING/COMPLETED/TERMINATED
    status = models.CharField(max_length=32, default="EXECUTING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    contract = models.ForeignKey(GContract, on_delete=models.CASCADE, db_column="contract_id")
    outsource_unit = models.ForeignKey(GSupplier, on_delete=models.PROTECT, db_column="outsource_unit_id")
    outsource_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payout_subject_code = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "g_outsource"
