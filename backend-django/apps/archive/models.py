"""科研档案域 O 模型（对齐 o_schema.sql 五表，db_table 保留）。"""
from __future__ import annotations

from django.db import models


class ODocument(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="UPLOADING")  # UPLOADING/STORED/MISSING
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    name = models.CharField(max_length=256)
    doc_type = models.CharField(max_length=64, null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    bucket = models.CharField(max_length=64, null=True, blank=True)
    object_key = models.CharField(max_length=512, null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, null=True, blank=True)
    uploader_id = models.BigIntegerField(null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    source_module = models.CharField(max_length=8, null=True, blank=True)
    source_id = models.BigIntegerField(null=True, blank=True)
    text_content = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "o_document"


class OArchive(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # ARC-年-序
    tenant_id = models.BigIntegerField()
    # PENDING_SUBMIT/SUBMITTED/CHECKING/PASSED/ARCHIVED/REJECTED/DESTROYED
    status = models.CharField(max_length=32, default="PENDING_SUBMIT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    title = models.CharField(max_length=256)
    # PROJECT/OUTPUT/EXPENSE/CONTRACT/ACTIVITY/OTHER
    archive_type = models.CharField(max_length=24, default="OTHER")
    source_module = models.CharField(max_length=8, null=True, blank=True)
    source_id = models.BigIntegerField(null=True, blank=True)
    source_code = models.CharField(max_length=64, null=True, blank=True)
    owner_dept_id = models.BigIntegerField(null=True, blank=True)
    retention_years = models.IntegerField(default=10)
    submitter_id = models.BigIntegerField(null=True, blank=True)
    submit_at = models.DateTimeField(null=True, blank=True)
    archivist_id = models.BigIntegerField(null=True, blank=True)
    filed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "o_archive"


class OArchiveItem(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    archive_id = models.BigIntegerField()
    doc_id = models.BigIntegerField(null=True, blank=True)  # 可空 = 缺
    status = models.CharField(max_length=16, default="MISSING")  # MISSING/FILLED/CHECKED
    created_at = models.DateTimeField(auto_now_add=True)
    category_code = models.CharField(max_length=64)
    category_name = models.CharField(max_length=128, null=True, blank=True)
    required = models.BooleanField(default=True)
    sort_no = models.IntegerField(default=0)

    class Meta:
        db_table = "o_archive_item"


class OArchiveCheck(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    archive_id = models.BigIntegerField()
    result = models.CharField(max_length=8, default="WARN")  # PASS/FAIL/WARN
    created_at = models.DateTimeField(auto_now_add=True)
    check_type = models.CharField(max_length=16)  # AUTHENTICITY/INTEGRITY/USABILITY/SECURITY
    detail = models.JSONField(default=dict)
    checked_at = models.DateTimeField(null=True, blank=True)
    checker_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "o_archive_check"


class OBorrow(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # BORROW-年-序
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="SUBMITTED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    archive_id = models.BigIntegerField()
    borrower_user_id = models.BigIntegerField()
    purpose = models.CharField(max_length=512, null=True, blank=True)
    borrow_type = models.CharField(max_length=16, default="READ")  # READ/COPY
    approved_by = models.BigIntegerField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "o_borrow"
