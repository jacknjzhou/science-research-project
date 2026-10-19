"""科研诚信与伦理域 C 模型（对齐 design/06-科研诚信与伦理-C.ddl.sql，db_table 保留）。

案卷 9 态 / 分派 6 态 / 意见 3 态 / 会议 4 态 / 批件 5 态 / 修正案 5 态 /
不良事件 4 态 / 年度复审 5 态 / 失信档案双状态机（主状态 + 独立调查 + 申诉）/
检测 4 态 / 人遗备案 6 态。涉密正文不入库，仅留 x_ref（C-19）。
"""
from __future__ import annotations

from django.db import models


class CEthicsCase(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # ETH-年-序
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/FORMAL_CHECK/UNDER_REVIEW/NEEDS_REVISION/APPROVED/REJECTED/MONITORING/EXPIRED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    review_type = models.CharField(max_length=32)  # HUMAN/ANIMAL/BIO_SAFETY/HGR/DATA_EXPORT
    project_id = models.BigIntegerField(null=True, blank=True)
    applicant_user_id = models.BigIntegerField()
    department_id = models.BigIntegerField(null=True, blank=True)
    protocol_title = models.CharField(max_length=512)
    protocol_summary = models.TextField(null=True, blank=True)
    methodology = models.TextField(null=True, blank=True)
    risk_level = models.CharField(max_length=16, default="MED")  # HIGH/MED/LOW
    materials = models.JSONField(default=list)
    informed_consent_url = models.CharField(max_length=512, null=True, blank=True)
    risk_assessment = models.JSONField(default=dict)
    ai_prescreen = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decision_date = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    next_review_at = models.DateField(null=True, blank=True)
    is_emergency = models.BooleanField(default=False)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    x_ref = models.CharField(max_length=64, null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "c_ethics_case"


class CReviewerAssign(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # ASSIGNED/ACCEPTED/RECUSED/COMPLETED/TIMEOUT/REASSIGNED
    status = models.CharField(max_length=32, default="ASSIGNED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.ForeignKey(CEthicsCase, on_delete=models.CASCADE, db_column="case_id")
    reviewer_user_id = models.BigIntegerField()
    role = models.CharField(max_length=16)  # CHIEF/BOARD
    assigned_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateTimeField(null=True, blank=True)
    conflict_of_interest = models.BooleanField(default=False)
    coi_reason = models.CharField(max_length=256, null=True, blank=True)

    class Meta:
        db_table = "c_reviewer_assign"


class CReviewOpinion(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/SUPERSEDED
    status = models.CharField(max_length=32, default="SUBMITTED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.ForeignKey(CEthicsCase, on_delete=models.CASCADE, db_column="case_id")
    reviewer_user_id = models.BigIntegerField()  # 对 PI 匿名展示
    score = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    comments = models.TextField(null=True, blank=True)
    objection = models.JSONField(default=dict)
    risks_identified = models.JSONField(default=list)
    # APPROVE/APPROVE_WITH_CHANGES/REJECT
    recommendation = models.CharField(max_length=32)

    class Meta:
        db_table = "c_review_opinion"


class CMeetingRecord(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # SCHEDULED/IN_PROGRESS/MINUTED/FINALIZED
    status = models.CharField(max_length=32, default="SCHEDULED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.ForeignKey(CEthicsCase, on_delete=models.CASCADE, db_column="case_id")
    meeting_date = models.DateTimeField()
    attendees = models.JSONField(default=list)
    quorum_met = models.BooleanField(default=False)
    discussion_text = models.TextField(null=True, blank=True)
    # APPROVE/APPROVE_WITH_CHANGES/REJECT/CONTINUE
    decision = models.CharField(max_length=32, null=True, blank=True)
    vote_result = models.JSONField(default=dict)

    class Meta:
        db_table = "c_meeting_record"


class CDecisionLetter(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/ISSUED/PUBLISHED/REVOKED/EXPIRED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.OneToOneField(CEthicsCase, on_delete=models.CASCADE, db_column="case_id")
    # APPROVE/APPROVE_WITH_CHANGES/REJECT
    decision_type = models.CharField(max_length=32)
    letter_no = models.CharField(max_length=64)  # 对外可验证
    letter_url = models.CharField(max_length=512, null=True, blank=True)
    verify_url = models.CharField(max_length=512, null=True, blank=True)
    qr_code_url = models.CharField(max_length=512, null=True, blank=True)
    signature_url = models.CharField(max_length=512, null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "c_decision_letter"


class CAmendment(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/UNDER_REVIEW/APPROVED/REJECTED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.ForeignKey(CEthicsCase, on_delete=models.CASCADE, db_column="case_id")
    change_summary = models.TextField()
    materials = models.JSONField(default=list)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "c_amendment"


class CAeReport(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # REPORTED/ASSESSING/ACTIONED/CLOSED
    status = models.CharField(max_length=32, default="REPORTED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.ForeignKey(CEthicsCase, on_delete=models.CASCADE, db_column="case_id")
    event_date = models.DateTimeField()
    severity = models.CharField(max_length=16)  # SERIOUS/NON_SERIOUS/SUSAR
    description = models.TextField()
    action_taken = models.TextField(null=True, blank=True)
    reported_at = models.DateTimeField(auto_now_add=True)
    assessed_by = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "c_ae_report"


class CAnnualReview(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/SUBMITTED/UNDER_REVIEW/APPROVED/OVERDUE
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.ForeignKey(CEthicsCase, on_delete=models.CASCADE, db_column="case_id")
    review_year = models.SmallIntegerField()
    progress_summary = models.TextField(null=True, blank=True)
    incidents = models.JSONField(default=list)
    next_plan = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "c_annual_review"
        unique_together = [("case", "review_year")]


class CIntegrityPledge(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/SIGNED/REVOKED
    status = models.CharField(max_length=32, default="SIGNED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    user_id = models.BigIntegerField()
    pledge_type = models.CharField(max_length=32)  # 字典 c_pledge_type
    content_version = models.CharField(max_length=32)
    read_seconds = models.IntegerField(default=0)
    signed_at = models.DateTimeField(auto_now_add=True)
    signature_url = models.CharField(max_length=512, null=True, blank=True)
    ip = models.CharField(max_length=64, null=True, blank=True)
    ua = models.CharField(max_length=256, null=True, blank=True)
    biz_ref_type = models.CharField(max_length=32, null=True, blank=True)
    biz_ref_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "c_integrity_pledge"


class CIntegrityRecord(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # CREATED/APPEALING/CLOSED
    status = models.CharField(max_length=32, default="CREATED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    user_id = models.BigIntegerField()
    event_type = models.CharField(max_length=32)
    # PLAGIARISM/DATA_FABRICATION/DUAL_SUBMISSION/EXPENSE_VIOLATION/COI_UNDISCLOSED/OTHER
    event_type_code = models.CharField(max_length=32)
    discovered_date = models.DateField(null=True, blank=True)
    evidence = models.JSONField(default=list)
    investigation = models.JSONField(default=dict)
    case_no = models.CharField(max_length=64, null=True, blank=True)
    # INVESTIGATING/SUSTAINED/UNSUSTAINED/CLOSED
    investigation_status = models.CharField(max_length=32, default="INVESTIGATING")
    decision = models.TextField(null=True, blank=True)
    sanction = models.CharField(max_length=64, null=True, blank=True)
    sanction_effective_until = models.DateField(null=True, blank=True)
    is_public = models.BooleanField(default=False)
    # NONE/FILED/REVIEWING/UPHELD/OVERTURNED
    appeal_status = models.CharField(max_length=32, default="NONE")
    appeal_deadline = models.DateField(null=True, blank=True)
    appeal_reason = models.TextField(null=True, blank=True)
    appealed_at = models.DateTimeField(null=True, blank=True)
    appeal_resolved_at = models.DateTimeField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")

    class Meta:
        db_table = "c_integrity_record"


class CMisconductScan(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # PENDING/RUNNING/DONE/FAILED
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    target_type = models.CharField(max_length=32)  # PAPER/DEAL/OUTPUT
    target_id = models.BigIntegerField()
    scan_type = models.CharField(max_length=32)  # TEXT_DUP/IMAGE_DUP/DATA_ANOMALY
    score = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    confidence = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    report_url = models.CharField(max_length=512, null=True, blank=True)
    verdict = models.CharField(max_length=32, null=True, blank=True)  # CLEAN/SUSPECTED/CONFIRMED
    engine = models.CharField(max_length=32, null=True, blank=True)
    # MANUAL/ON_REGISTER/PRE_FUNDING/SCHEDULED
    triggered_by = models.CharField(max_length=32, default="MANUAL")
    scanned_at = models.DateTimeField(auto_now_add=True)
    investigation_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "c_misconduct_scan"


class CHgrFiling(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/NATIONAL_RECEIVED/APPROVED/REJECTED/EXPIRED
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    case = models.ForeignKey(
        CEthicsCase, on_delete=models.SET_NULL, db_column="case_id", null=True, blank=True
    )
    project_id = models.BigIntegerField()
    filing_type = models.CharField(max_length=32, null=True, blank=True)
    # COLLECT/PRESERVE/INTL_COOP/DEVELOP
    filing_type_code = models.CharField(max_length=32)
    filing_no = models.CharField(max_length=64, null=True, blank=True)
    national_approval_no = models.CharField(max_length=64, null=True, blank=True)  # 外部回传号
    submission_date = models.DateField(null=True, blank=True)
    approval_status = models.CharField(max_length=32, null=True, blank=True)
    approval_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    sync_batch_id = models.CharField(max_length=64, null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    x_ref = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "c_hgr_filing"
