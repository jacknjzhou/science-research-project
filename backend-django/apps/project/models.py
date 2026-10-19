"""项目过程域模型：镜像迁移 000001 E_* + 000011 分类 + 000012 申报计划。"""
from django.db import models


class EProject(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # PRJ-年-序
    tenant_id = models.BigIntegerField()
    # EXECUTING/MID_CHECK/CHANGING/CORRECTING/DELAYED/COMPLETING/CLOSED/TERMINATED
    status = models.CharField(max_length=32, default="EXECUTING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    application_id = models.BigIntegerField()
    title = models.CharField(max_length=512)
    project_type = models.CharField(max_length=64, null=True, blank=True)
    pi_user_id = models.BigIntegerField()
    member_ids = models.JSONField(default=list)
    department_id = models.BigIntegerField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    actual_end_date = models.DateField(null=True, blank=True)
    total_budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    received_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    spent_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    health_score = models.IntegerField(default=100)
    risk_level = models.CharField(max_length=16, default="LOW")
    ethics_case_id = models.BigIntegerField(null=True, blank=True)
    policy_pack_id = models.BigIntegerField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    category_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "E_PROJECT"


class ETask(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    parent_task_id = models.BigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=256)
    description = models.TextField(null=True, blank=True)
    owner_user_id = models.BigIntegerField(null=True, blank=True)
    member_ids = models.JSONField(default=list)
    dep_task_ids = models.JSONField(default=list)
    planned_start = models.DateField(null=True, blank=True)
    planned_end = models.DateField(null=True, blank=True)
    actual_start = models.DateField(null=True, blank=True)
    actual_end = models.DateField(null=True, blank=True)
    progress_percent = models.IntegerField(default=0)
    weight = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)

    class Meta:
        db_table = "E_TASK"


class EMilestone(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="PENDING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    name = models.CharField(max_length=256)
    due_date = models.DateField(null=True, blank=True)
    actual_date = models.DateField(null=True, blank=True)
    evidence_docs = models.JSONField(default=list)
    owner_user_id = models.BigIntegerField(null=True, blank=True)
    deliverable_type = models.CharField(max_length=64, null=True, blank=True)
    weight = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)

    class Meta:
        db_table = "E_MILESTONE"


class EProgressReport(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    period = models.CharField(max_length=32)
    report_type = models.CharField(max_length=32, default="SELF")
    content_rich = models.TextField(null=True, blank=True)
    progress_percent = models.IntegerField(default=0)
    issues_text = models.TextField(null=True, blank=True)
    next_plan = models.TextField(null=True, blank=True)
    attachment_ids = models.JSONField(default=list)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "E_PROGRESS_REPORT"


class EMidCheck(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="PLANNED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    check_round = models.IntegerField(default=1)
    check_date = models.DateField(null=True, blank=True)
    plan_id = models.BigIntegerField(null=True, blank=True)
    template_id = models.BigIntegerField(null=True, blank=True)
    expert_ids = models.JSONField(default=list)
    conclusion = models.CharField(max_length=32, null=True, blank=True)
    score_detail = models.JSONField(null=True, blank=True)
    report = models.ForeignKey(EProgressReport, on_delete=models.SET_NULL, db_column="report_id", null=True, blank=True)
    correct_deadline = models.DateField(null=True, blank=True)
    status_overdue = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "E_MID_CHECK"


class EChangeRequest(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/APPROVING/APPROVED/REJECTED/RETURNED/ROLLED_BACK/EFFECTIVE
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    change_type = models.CharField(max_length=32)  # DELAY/BUDGET/MEMBER/TITLE/SCOPE
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    approval_status = models.CharField(max_length=32, default="PENDING")
    approved_at = models.DateTimeField(null=True, blank=True)
    impact_analysis = models.JSONField(null=True, blank=True)
    conflict_flag = models.SmallIntegerField(default=0)
    snapshot_ref = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        db_table = "E_CHANGE_REQUEST"


class EFinalAccept(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="APPLIED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    apply_at = models.DateTimeField(null=True, blank=True)
    accept_at = models.DateTimeField(null=True, blank=True)
    output_summary = models.JSONField(null=True, blank=True)
    finance_report_id = models.BigIntegerField(null=True, blank=True)
    expert_ids = models.JSONField(default=list)
    conclusion = models.CharField(max_length=32, null=True, blank=True)
    attachment_ids = models.JSONField(default=list)
    archive_checklist_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "E_FINAL_ACCEPT"


class EProjectDoc(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    category = models.CharField(max_length=32)
    file_url = models.CharField(max_length=512)
    file_name = models.CharField(max_length=256, null=True, blank=True)
    mime_type = models.CharField(max_length=128, null=True, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    version = models.IntegerField(default=1)
    checksum = models.CharField(max_length=128, null=True, blank=True)
    uploaded_by = models.BigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")

    class Meta:
        db_table = "E_PROJECT_DOC"


class EProjectCategory(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    level = models.CharField(max_length=16, default="NORMAL")
    budget_template = models.JSONField(default=list)
    mgmt_fee_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    midcheck_from = models.DateField(null=True, blank=True)
    midcheck_to = models.DateField(null=True, blank=True)
    closing_from = models.DateField(null=True, blank=True)
    closing_to = models.DateField(null=True, blank=True)
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "e_project_category"
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "code"], name="uk_e_category_code")
        ]


class EApplyPlan(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    name = models.CharField(max_length=256)
    category_id = models.BigIntegerField(null=True, blank=True)
    source = models.CharField(max_length=64, null=True, blank=True)
    start_at = models.DateField()
    end_at = models.DateField()
    need_review = models.BooleanField(default=True)
    guide_file_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, default="DRAFT")  # DRAFT/OPEN/STOPPED
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "E_APPLY_PLAN"


class EApplication(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    plan = models.ForeignKey(EApplyPlan, on_delete=models.CASCADE, db_column="plan_id")
    project_name = models.CharField(max_length=512)
    apply_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    applicant_id = models.BigIntegerField()
    attachment_ids = models.JSONField(default=list)
    # SUBMITTED/COLLEGE_PASSED/COLLEGE_REJECTED/SCHOOL_PASSED/SCHOOL_REJECTED
    status = models.CharField(max_length=32, default="SUBMITTED")
    project_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "E_APPLICATION"


class EHealthHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    health_score = models.IntegerField(default=100)
    risk_level = models.CharField(max_length=16, default="LOW")
    reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "E_HEALTH_HISTORY"


class EArchiveChecklist(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    project = models.ForeignKey(EProject, on_delete=models.CASCADE, db_column="project_id")
    items = models.JSONField(default=list)
    passed = models.BooleanField(default=False)

    class Meta:
        db_table = "E_ARCHIVE_CHECKLIST"
