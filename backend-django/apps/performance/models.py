"""科研绩效域 M 模型（对齐 m_schema.sql 五表，db_table 保留）。"""
from __future__ import annotations

from django.db import models


class MScheme(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # PERF-年-序
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="DRAFT")  # DRAFT/ACTIVE/SUPERSEDED
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    legal_entity_id = models.BigIntegerField(null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=128)
    period_type = models.CharField(max_length=16)  # YEAR/QUARTER/MONTH
    scope_dept_id = models.BigIntegerField(null=True, blank=True)
    scope_staff_type = models.CharField(max_length=32, null=True, blank=True)
    effective_period = models.CharField(max_length=32)
    version = models.IntegerField(default=1)
    active = models.BooleanField(default=False)

    class Meta:
        db_table = "m_scheme"


class MSchemeFactor(models.Model):
    id = models.BigAutoField(primary_key=True)
    scheme_id = models.BigIntegerField()
    tenant_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    creator_id = models.BigIntegerField()
    factor_code = models.CharField(max_length=64)
    factor_name = models.CharField(max_length=128, null=True, blank=True)
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    scoring_rule = models.JSONField(default=dict)
    max_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_source = models.CharField(max_length=32)  # R_OUTPUT/E_PROJECT/F_INCOME/T_DEAL/MANUAL
    clause_ref = models.CharField(max_length=256, null=True, blank=True)
    sort_no = models.IntegerField(default=0)

    class Meta:
        db_table = "m_scheme_factor"


class MRecord(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # CALCULATED/CONFIRMED/APPROVED/PAID/VOIDED
    status = models.CharField(max_length=32, default="CALCULATED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    legal_entity_id = models.BigIntegerField(null=True, blank=True)
    scheme_id = models.BigIntegerField()
    staff_user_id = models.BigIntegerField()
    period = models.CharField(max_length=32)
    dept_id = models.BigIntegerField(null=True, blank=True)
    total_score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rank = models.IntegerField(null=True, blank=True)
    calc_detail = models.JSONField(default=dict)
    calc_batch = models.CharField(max_length=64, null=True, blank=True)
    calc_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.BigIntegerField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    approve_by = models.BigIntegerField(null=True, blank=True)
    approve_at = models.DateTimeField(null=True, blank=True)
    appeal_reason = models.CharField(max_length=512, null=True, blank=True)
    void_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "m_record"


class MRecordItem(models.Model):
    id = models.BigAutoField(primary_key=True)
    record_id = models.BigIntegerField()
    tenant_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    factor_code = models.CharField(max_length=64)
    metric_value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    raw_score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    weighted_score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    evidence = models.JSONField(default=list)

    class Meta:
        db_table = "m_record_item"


class MPayout(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # PAY-年-序
    tenant_id = models.BigIntegerField()
    # DRAFT/APPROVING/APPROVED/PAID/REJECTED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    legal_entity_id = models.BigIntegerField(null=True, blank=True)
    record_id = models.BigIntegerField()
    payee_user_id = models.BigIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    period = models.CharField(max_length=32, null=True, blank=True)
    pay_channel = models.CharField(max_length=32, null=True, blank=True)
    approver_ids = models.JSONField(default=list)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    voucher_code = models.CharField(max_length=64, null=True, blank=True)
    reject_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "m_payout"
