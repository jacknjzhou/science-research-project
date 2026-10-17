"""申报域模型：镜像迁移 000001 的 p_guideline / p_application（Phase 1 实现范围）。

其余 P 表（p_template/p_application_doc/p_budget_draft/p_review_*/p_task_book）
随后续 Phase（评审、模板、任务书解析落库）建表。
"""
from django.db import models


class PGuideline(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="DRAFT")  # DRAFT/PUBLISHED/CLOSED
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    title = models.CharField(max_length=256)
    project_type = models.CharField(max_length=64)  # sys_dict(project_type) item_code
    funding_source = models.CharField(max_length=128, null=True, blank=True)
    target_disciplines = models.JSONField(default=list)  # [{code,label}]
    apply_start_at = models.DateTimeField(null=True, blank=True)
    apply_end_at = models.DateTimeField(null=True, blank=True)
    total_envelope = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    content_rich = models.TextField(null=True, blank=True)
    attachment_ids = models.JSONField(default=list)
    publish_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "p_guideline"


class PApplicationDoc(models.Model):
    """申报书分节正文（对应镜像迁移的 p_application_doc）。

    section_code 对齐前端 EditorView SECTIONS 9 节：
    background/objective/content/route/innovation/foundation/schedule/budget_note/attachments。
    PUT sections/{code} 逐节 upsert，doc_version 自增；GET documents 全节输出。
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    application = models.ForeignKey("PApplication", on_delete=models.CASCADE, db_column="application_id")
    section_code = models.CharField(max_length=64)
    content_rich = models.TextField(null=True, blank=True)
    word_count = models.IntegerField(default=0)
    doc_version = models.IntegerField(default=1)
    updated_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "p_application_doc"
        unique_together = ("application", "section_code")


class PApplication(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # PRJ 编号（编号中心）
    tenant_id = models.BigIntegerField()
    # DRAFT/SUBMITTED/FORMAL_CHECK/RECOMMENDED/UNDER_REVIEW/INTERVIEWING/
    # DECIDED/PUBLISHED/SIGNED/EXECUTING/REJECTED/WITHDRAWN
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    guideline_id = models.BigIntegerField(null=True, blank=True)
    template_id = models.BigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=256)
    project_type = models.CharField(max_length=64)
    pi_user_id = models.BigIntegerField()
    member_ids = models.JSONField(default=list)
    department_id = models.BigIntegerField(null=True, blank=True)
    abstract = models.TextField(null=True, blank=True)
    research_target = models.TextField(null=True, blank=True)
    technical_route = models.TextField(null=True, blank=True)
    expected_output = models.TextField(null=True, blank=True)
    duration_months = models.IntegerField(null=True, blank=True)
    total_budget = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    is_horizontal = models.BooleanField(default=False)
    funding_channel = models.CharField(max_length=64, null=True, blank=True)
    ai_draft_marked = models.BooleanField(default=False)
    submit_at = models.DateTimeField(null=True, blank=True)
    withdraw_at = models.DateTimeField(null=True, blank=True)
    withdraw_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "p_application"
