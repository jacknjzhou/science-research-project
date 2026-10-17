"""学术活动域 V 模型（对齐 v_activity 三表，db_table 保留）。"""
from __future__ import annotations

from django.db import models


class VActivity(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/DEPT_REVIEW/APPROVED/HELD/ARCHIVED/REJECTED/RETURNED/CANCELLED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    activity_type = models.CharField(max_length=32)  # CONFERENCE/LECTURE/SEMINAR/TRAINING/OTHER
    level = models.CharField(max_length=16, null=True, blank=True)
    host_mode = models.CharField(max_length=16, null=True, blank=True)
    title = models.CharField(max_length=256)
    theme = models.CharField(max_length=256, null=True, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    venue = models.CharField(max_length=256, null=True, blank=True)
    online_url = models.CharField(max_length=512, null=True, blank=True)
    host_unit = models.CharField(max_length=128, null=True, blank=True)
    organizer_dept_id = models.BigIntegerField(null=True, blank=True)
    invited_experts = models.JSONField(default=list)
    est_attendees = models.IntegerField(null=True, blank=True)
    project_id = models.BigIntegerField(null=True, blank=True)
    budget_subject_code = models.CharField(max_length=64, null=True, blank=True)
    budget_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    agenda = models.JSONField(default=list)
    attachment_ids = models.JSONField(default=list)
    minutes_rich = models.TextField(null=True, blank=True)
    sign_in_count = models.IntegerField(null=True, blank=True)
    hold_proof_ids = models.JSONField(default=list)
    submit_at = models.DateTimeField(null=True, blank=True)
    approve_at = models.DateTimeField(null=True, blank=True)
    archive_at = models.DateTimeField(null=True, blank=True)
    cancel_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "v_activity"


class VActivityParticipant(models.Model):
    id = models.BigAutoField(primary_key=True)
    activity_id = models.BigIntegerField()
    user_id = models.BigIntegerField(null=True, blank=True)  # 空=外部专家
    guest_name = models.CharField(max_length=64, null=True, blank=True)
    role = models.CharField(max_length=16)  # SPEAKER/CHAIR/MEMBER/ATTENDEE
    report_title = models.CharField(max_length=256, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "v_activity_participant"


class VActivityReview(models.Model):
    id = models.BigAutoField(primary_key=True)
    activity_id = models.BigIntegerField()
    review_level = models.SmallIntegerField()
    reviewer_id = models.BigIntegerField()
    action = models.CharField(max_length=16)  # APPROVE/REJECT/RETURN
    opinion = models.CharField(max_length=512, null=True, blank=True)
    acted_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField()

    class Meta:
        db_table = "v_activity_review"
