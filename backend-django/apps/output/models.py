"""成果域 R 模型（对齐 r_schema.sql 全部表结构，db_table 保留）。

R_OUTPUT 8 态 / 12 output_type；claim_status 独立 6 态；
title_hash 规范化标题哈希（去重主键候选）；专利阶段 stage 挂主档。
"""
from __future__ import annotations

from django.db import models


class ROutput(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # AUTO_FETCHED/PENDING_CLAIM/CLAIMED/ASSIGNED_TO_PROJECT/COUNTED_FOR_PERFORMANCE/
    # MANUAL_DRAFT/PENDING_REVIEW/REJECTED
    status = models.CharField(max_length=32, default="PENDING_CLAIM")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    output_type = models.CharField(max_length=32)  # PAPER/PATENT/SOFTWARE/... 12 种
    title = models.CharField(max_length=512)
    title_en = models.CharField(max_length=512, null=True, blank=True)
    abstract = models.TextField(null=True, blank=True)
    publish_date = models.DateField(null=True, blank=True)
    authors = models.JSONField(default=list)
    external_author_names = models.JSONField(default=list)
    affiliations = models.JSONField(default=list)
    project_ids = models.JSONField(default=list)
    language = models.CharField(max_length=16, null=True, blank=True)
    # CNKI/WOS/SCOPUS/WANFANG/CNIPA/CROSSREF/ALTMETRIC/MANUAL/FETCH
    source = models.CharField(max_length=32, default="MANUAL")
    is_claimed = models.BooleanField(default=False)
    # UNCLAIMED/PENDING/CLAIMED/REJECTED/NOT_MINE/DOUBTFUL
    claim_status = models.CharField(max_length=32, default="UNCLAIMED")
    match_confidence = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    simhash = models.CharField(max_length=64, null=True, blank=True)
    title_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    master_output_id = models.BigIntegerField(null=True, blank=True)
    department_id = models.BigIntegerField(null=True, blank=True)
    stage = models.CharField(max_length=16, default="PRE_APPLY")  # T18 专利阶段
    annual_fee_due = models.DateField(null=True, blank=True)
    agency_id = models.BigIntegerField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "r_output"


class RPaperExt(models.Model):
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
    output_id = models.BigIntegerField(unique=True)
    journal_name = models.CharField(max_length=256, null=True, blank=True)
    journal_issn = models.CharField(max_length=32, null=True, blank=True)
    level_code = models.CharField(max_length=32, null=True, blank=True)
    volume = models.CharField(max_length=32, null=True, blank=True)
    issue = models.CharField(max_length=32, null=True, blank=True)
    page_range = models.CharField(max_length=64, null=True, blank=True)
    doi = models.CharField(max_length=128, null=True, blank=True)
    keywords = models.JSONField(default=list)
    category = models.CharField(max_length=32, null=True, blank=True)
    jcr_partition = models.CharField(max_length=16, null=True, blank=True)
    cas_partition = models.CharField(max_length=16, null=True, blank=True)
    impact_factor = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    cited_times = models.IntegerField(default=0)
    is_highly_cited = models.BooleanField(default=False)
    esi_top1 = models.BooleanField(default=False)
    wos_record_id = models.CharField(max_length=64, null=True, blank=True)
    scopus_id = models.CharField(max_length=64, null=True, blank=True)
    cnki_id = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "r_paper_ext"


class RPatentExt(models.Model):
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
    output_id = models.BigIntegerField(unique=True)
    patent_type = models.CharField(max_length=32, null=True, blank=True)
    application_no = models.CharField(max_length=64, null=True, blank=True)
    application_date = models.DateField(null=True, blank=True)
    grant_no = models.CharField(max_length=64, null=True, blank=True)
    grant_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    # PENDING/EXAMINING/SUBSTANTIVE/GRANTED/ANNUTY_DUE/INVALID/ABANDONED
    legal_status = models.CharField(max_length=32, default="PENDING")
    inventors = models.JSONField(default=list)
    applicants = models.JSONField(default=list)
    agency_name = models.CharField(max_length=128, null=True, blank=True)
    annuity_due_date = models.DateField(null=True, blank=True)
    annuity_paid_year = models.IntegerField(null=True, blank=True)
    maintain_years = models.IntegerField(null=True, blank=True)
    license_status = models.CharField(max_length=32, null=True, blank=True)
    is_transferable = models.BooleanField(default=False)

    class Meta:
        db_table = "r_patent_ext"


class RSoftwareExt(models.Model):
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
    output_id = models.BigIntegerField(unique=True)
    register_no = models.CharField(max_length=64, null=True, blank=True)
    register_date = models.DateField(null=True, blank=True)
    copyright_owners = models.JSONField(default=list)
    first_release_date = models.DateField(null=True, blank=True)
    source_code_lines = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "r_software_ext"


class RStandardExt(models.Model):
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
    output_id = models.BigIntegerField(unique=True)
    standard_type = models.CharField(max_length=32, null=True, blank=True)
    standard_no = models.CharField(max_length=64, null=True, blank=True)
    publish_date = models.DateField(null=True, blank=True)
    drafting_unit_rank = models.CharField(max_length=32, null=True, blank=True)
    main_drafters = models.JSONField(default=list)

    class Meta:
        db_table = "r_standard_ext"


class RAwardExt(models.Model):
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
    output_id = models.BigIntegerField(unique=True)
    award_name = models.CharField(max_length=256, null=True, blank=True)
    award_level = models.CharField(max_length=32, null=True, blank=True)
    award_grade = models.CharField(max_length=16, null=True, blank=True)
    award_date = models.DateField(null=True, blank=True)
    awarding_body = models.CharField(max_length=256, null=True, blank=True)
    winner_rank = models.JSONField(default=list)

    class Meta:
        db_table = "r_award_ext"


class RBookExt(models.Model):
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
    output_id = models.BigIntegerField(unique=True)
    publisher = models.CharField(max_length=256, null=True, blank=True)
    isbn = models.CharField(max_length=32, null=True, blank=True)
    book_date = models.DateField(null=True, blank=True)
    book_type = models.CharField(max_length=32, null=True, blank=True)
    word_count = models.IntegerField(null=True, blank=True)
    role = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        db_table = "r_book_ext"


class RClaimRecord(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="DONE")  # DONE/REVOKED
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    output_id = models.BigIntegerField()
    user_id = models.BigIntegerField()
    action = models.CharField(max_length=32)  # CLAIM/REJECT/MARK_NOT_MINE/EDIT
    edited_fields = models.JSONField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    action_at = models.DateTimeField(auto_now_add=True)
    batch_id = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "r_claim_record"


class RMetricSnapshot(models.Model):
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
    output_id = models.BigIntegerField()
    snapshot_date = models.DateField()
    cited_times = models.IntegerField(default=0)
    altmetric = models.IntegerField(default=0)
    downloads = models.IntegerField(default=0)
    impact_factor = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "r_metric_snapshot"


class RDataset(models.Model):
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
    output_id = models.BigIntegerField(unique=True)
    storage_url = models.CharField(max_length=512, null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    format = models.CharField(max_length=64, null=True, blank=True)
    license = models.CharField(max_length=64, null=True, blank=True)
    doi = models.CharField(max_length=128, null=True, blank=True)
    download_count = models.IntegerField(default=0)
    citation_count = models.IntegerField(default=0)

    class Meta:
        db_table = "r_dataset"


class ROutputProject(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="ACTIVE")  # ACTIVE/REVOKED
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    output_id = models.BigIntegerField()
    project_id = models.BigIntegerField()
    relation_type = models.CharField(max_length=32, default="CONTRIBUTION")
    contribution_pct = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "r_output_project"


class RJournalSource(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    name = models.CharField(max_length=256)
    issn = models.CharField(max_length=32, null=True, blank=True)
    year_from = models.IntegerField(null=True, blank=True)
    year_to = models.IntegerField(null=True, blank=True)
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "r_journal_source"


class RJournalLevel(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    paper_type = models.CharField(max_length=32, null=True, blank=True)
    indexed = models.BooleanField(default=True)
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "r_journal_level"


class RJournalLevelSource(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    level_id = models.BigIntegerField()
    source_id = models.BigIntegerField()
    year_from = models.IntegerField(null=True, blank=True)
    year_to = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "r_journal_level_source"


class RPaperReprint(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    output_id = models.BigIntegerField()
    name = models.CharField(max_length=256)
    type = models.CharField(max_length=32, null=True, blank=True)
    reprint_date = models.DateField(null=True, blank=True)
    remark = models.TextField(null=True, blank=True)
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "r_paper_reprint"


class RPushItem(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    type = models.CharField(max_length=16)
    source_db = models.CharField(max_length=32)
    title = models.CharField(max_length=512)
    authors = models.JSONField(default=list)
    year = models.IntegerField(null=True, blank=True)
    raw_doi = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=16, default="PUSHED")
    pushed_at = models.DateTimeField(auto_now_add=True)
    dedup_key = models.CharField(max_length=64)
    output_id = models.BigIntegerField(null=True, blank=True)
    deleted = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "r_push_item"


class RPatentFee(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    patent_id = models.BigIntegerField()
    year = models.IntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    paid_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, default="UNPAID")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "r_patent_fee"


class RAgency(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    name = models.CharField(max_length=256)
    contact = models.CharField(max_length=256, null=True, blank=True)
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "r_agency"
