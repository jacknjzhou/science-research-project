"""专家评审域 N 模型（对齐 n_schema.sql，db_table 保留）。

n_review_task 8 态：DRAFT→DRAWN→INVITING→QUORUM→IN_REVIEW→COLLECTING→CONCLUDED/CANCELLED。
"""
from __future__ import annotations

from django.db import models


class NExpert(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # CANDIDATE/ACTIVE/SUSPENDED/BLACKLIST
    status = models.CharField(max_length=32, default="CANDIDATE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    name = models.CharField(max_length=64)
    gender = models.CharField(max_length=8, null=True, blank=True)
    title = models.CharField(max_length=64, null=True, blank=True)
    education = models.CharField(max_length=32, null=True, blank=True)
    org_name = models.CharField(max_length=128, null=True, blank=True)
    dept = models.CharField(max_length=128, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    email = models.CharField(max_length=128, null=True, blank=True)
    user_id = models.BigIntegerField(null=True, blank=True)  # 空=纯外部专家
    source = models.CharField(max_length=16, default="EXTERNAL")  # INTERNAL/EXTERNAL
    field_tags = models.JSONField(default=list)
    expertise_level = models.CharField(max_length=16, default="EXPERT")
    avoid_orgs = models.JSONField(default=list)
    avoid_person_ids = models.JSONField(default=list)
    bank_account = models.JSONField(null=True, blank=True)
    cv_doc_ids = models.JSONField(default=list)
    last_review_at = models.DateTimeField(null=True, blank=True)
    review_count = models.IntegerField(default=0)

    class Meta:
        db_table = "n_expert"


class NExpertGroup(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="ACTIVE")  # ACTIVE/INACTIVE
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    name = models.CharField(max_length=128)
    criteria = models.JSONField(default=dict)
    expert_ids = models.JSONField(default=list)

    class Meta:
        db_table = "n_expert_group"


class NReviewTask(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/DRAWN/INVITING/QUORUM/IN_REVIEW/COLLECTING/CONCLUDED/CANCELLED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    # MID_CHECK/FINAL_ACCEPT/OUTPUT_EVAL/PROJECT_APPLY/OTHER
    biz_type = models.CharField(max_length=24)
    target_type = models.CharField(max_length=32, null=True, blank=True)
    target_id = models.BigIntegerField(null=True, blank=True)
    project_id = models.BigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=256)
    review_method = models.CharField(max_length=16, default="RANDOM")
    plan_count = models.IntegerField(default=3)
    draw_rule = models.JSONField(default=dict)
    conclusion = models.CharField(max_length=16, null=True, blank=True)
    score_summary = models.JSONField(null=True, blank=True)
    drawn_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    concluded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "n_review_task"


class NReviewInvitation(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    task_id = models.BigIntegerField()
    expert_id = models.BigIntegerField()
    seat_no = models.IntegerField(default=0)
    avoid_hit = models.BooleanField(default=False)
    # PENDING/ACCEPT/DECLINE/EXPIRED
    response = models.CharField(max_length=16, default="PENDING")
    invited_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "n_review_invitation"


class NReviewScore(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    task_id = models.BigIntegerField()
    expert_id = models.BigIntegerField()
    target_type = models.CharField(max_length=32, null=True, blank=True)
    target_id = models.BigIntegerField(null=True, blank=True)
    dimension_scores = models.JSONField(default=list)
    total_score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comment = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=16, default="SUBMITTED")  # SUBMITTED/ABSTAIN
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "n_review_score"


class NReviewFee(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="UNPAID")  # UNPAID/PAID
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    task_id = models.BigIntegerField()
    expert_id = models.BigIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    pay_channel = models.CharField(max_length=32, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    voucher_code = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "n_review_fee"
