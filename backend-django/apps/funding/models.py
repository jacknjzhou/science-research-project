"""经费域 F 最小底座：f_f_income（dataio funding.income 全链路配套）。

Phase 2 将在此 app 扩展预算/报销/收入/拨出/结转/间接费/科目管理全量表；
本文件仅承载 Go dataio 依赖的到款表（导入/导出/撤销语义对齐）。
"""
from __future__ import annotations

from django.db import models


class FIncome(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # 到款编号（编号中心）
    tenant_id = models.BigIntegerField()
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    legal_entity_id = models.BigIntegerField(default=1)
    receipt_no = models.CharField(max_length=128, null=True, blank=True)  # 收款编号
    receipt_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payer_name = models.CharField(max_length=256, null=True, blank=True)
    purpose_text = models.CharField(max_length=512, null=True, blank=True)  # 摘要
    bank_flow_no = models.CharField(max_length=128, null=True, blank=True)  # 银行流水号（同租户唯一幂等键）
    # UNCLAIMED/CLAIMED（被业务引用后禁止撤销导入批次）
    claim_status = models.CharField(max_length=16, default="UNCLAIMED")
    claimed_project_id = models.BigIntegerField(null=True, blank=True)
    remark = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "f_f_income"
