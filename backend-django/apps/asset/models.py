"""资产与耗材域 A 模型（对齐 design/10-资产与耗材管理-A.ddl.sql，db_table 保留）。

资产卡 7 态（PENDING_RECEIPT→IN_USE→…→DISPOSED）/ 耗材库存 5 态（SKU+批次+效期）/
流水 8 型（出入库/领用/归还/盘盈亏）/ 折旧 (asset_id,period) 唯一幂等 / 处置单 6 态。
治理列：全表携带 legal_entity_id / security_level；折旧/资产另带 policy_pack_id。
"""
from __future__ import annotations

from django.db import models


class AAsset(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # AST-年-序6
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # PENDING_RECEIPT/IN_USE/IDLE/UNDER_MAINT/TRANSFERRING/PENDING_DISPOSE/DISPOSED
    status = models.CharField(max_length=32, default="PENDING_RECEIPT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    asset_type = models.CharField(max_length=16, default="FIXED")  # FIXED/INTANGIBLE
    category_code = models.CharField(max_length=64)
    name = models.CharField(max_length=256)
    brand = models.CharField(max_length=128, null=True, blank=True)
    model = models.CharField(max_length=128, null=True, blank=True)
    serial_no = models.CharField(max_length=128, null=True, blank=True)
    value = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # 原值
    purchase_date = models.DateField(null=True, blank=True)
    in_date = models.DateField(null=True, blank=True)
    # STRAIGHT_LINE/WORKLOAD/ACCELERATED/NONE
    depr_method = models.CharField(max_length=16, default="STRAIGHT_LINE")
    depr_years = models.SmallIntegerField(null=True, blank=True)
    depr_accum = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    custodian_id = models.BigIntegerField(null=True, blank=True)
    dept_id = models.BigIntegerField(null=True, blank=True)
    location = models.CharField(max_length=256, null=True, blank=True)
    # PURCHASE/SELF_DEV/DONATION/TRANSFER
    source_type = models.CharField(max_length=16, default="PURCHASE")
    source_ref = models.BigIntegerField(null=True, blank=True)  # G_CONTRACT/验收单逻辑引用
    project_id = models.BigIntegerField(null=True, blank=True)
    usage_rate = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    share_flag = models.BooleanField(default=False)
    open_flag = models.BooleanField(default=False)

    class Meta:
        db_table = "a_asset"


class AConsumable(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    # IN_STOCK/LOW_STOCK/NEAR_EXPIRY/EXPIRED/STAGNANT
    status = models.CharField(max_length=32, default="IN_STOCK")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=256)
    category = models.CharField(max_length=32, default="CONSUMABLE")  # REAGENT/CONSUMABLE/COMPONENT/OFFICE
    is_hazard = models.BooleanField(default=False)
    hazard_level = models.CharField(max_length=16, null=True, blank=True)
    msds_url = models.CharField(max_length=512, null=True, blank=True)
    stock_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    unit = models.CharField(max_length=16, null=True, blank=True)
    batch_no = models.CharField(max_length=64, null=True, blank=True)
    produce_date = models.DateField(null=True, blank=True)
    expire_date = models.DateField(null=True, blank=True)
    safe_stock = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    location = models.CharField(max_length=256, null=True, blank=True)
    custodian_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "a_consumable"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "batch_no", "sku"],
                condition=models.Q(deleted=0),
                name="uk_consumable_sku",
            )
        ]


class AStockTxn(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    # STOCK_IN/STOCK_OUT/REQUISITION/RETURN/RETURN_TO_STOCK/HAZARD_DISPOSE/COUNT_GAIN/COUNT_LOSS
    type = models.CharField(max_length=24)
    # REQUESTED/DOUBLE_CONFIRM/ISSUED
    status = models.CharField(max_length=32, default="ISSUED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    ref_asset_id = models.BigIntegerField(null=True, blank=True)
    ref_sku = models.CharField(max_length=64, null=True, blank=True)
    ref_batch_no = models.CharField(max_length=64, null=True, blank=True)
    qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    project_id = models.BigIntegerField(null=True, blank=True)
    operator_id = models.BigIntegerField()
    double_confirm_by = models.BigIntegerField(null=True, blank=True)
    related_expense_id = models.BigIntegerField(null=True, blank=True)
    txn_time = models.DateTimeField(auto_now_add=True)
    balance_after = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    fifo_exempt = models.BooleanField(default=False)

    class Meta:
        db_table = "a_stock_txn"


class ADepreciation(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    # DRAFT/CALCULATED/POSTED/REVERSED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    asset = models.ForeignKey(AAsset, on_delete=models.CASCADE, db_column="asset_id")
    period = models.CharField(max_length=7)  # YYYY-MM
    depr_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    alloc_project_ids = models.JSONField(default=list)  # [{project_id,ratio,amount}]
    voucher_id = models.BigIntegerField(null=True, blank=True)
    posted = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "a_depreciation"
        constraints = [
            models.UniqueConstraint(fields=["asset_id", "period"], name="uk_depr_asset_period")
        ]


class ADisposal(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # DSP-年-序6
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    # APPLIED/APPRAISED/APPROVED/EXECUTING/BOOKED/ARCHIVED
    status = models.CharField(max_length=32, default="APPLIED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    asset = models.ForeignKey(AAsset, on_delete=models.CASCADE, db_column="asset_id")
    method = models.CharField(max_length=16)  # SCRAP/SELL/TRANSFER/DESTROY
    appraisal = models.JSONField(null=True, blank=True)
    residual_value = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    approval_chain = models.JSONField(default=list)
    related_voucher = models.BigIntegerField(null=True, blank=True)
    archive_ref = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "a_disposal"
