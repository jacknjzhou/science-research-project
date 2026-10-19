"""人员与团队域 S 模型（对齐 design/07-人员与团队-S.ddl.sql，db_table 保留）。

S_STAFF 与 sys_user 1:1（user_id 唯一）；团队生命周期 6 态；成员关系规范化主存
（S_MEMBERSHIP，team.member_ids 仅快照）；客座 6 态 / 学生 / 画像快照（人日唯一）/
合作网络边（a<b 无向边）/ 人才计划 5 态。敏感列（id_card/bank）哈希落库，响应脱敏。
"""
from __future__ import annotations

from django.db import models


class SStaff(models.Model):
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
    user_id = models.BigIntegerField()  # 1:1 sys_user
    hr_code = models.CharField(max_length=64)
    name = models.CharField(max_length=64)
    name_en = models.CharField(max_length=128, null=True, blank=True)
    gender = models.CharField(max_length=8, null=True, blank=True)
    birth_year = models.IntegerField(null=True, blank=True)
    id_card_hash = models.CharField(max_length=128, null=True, blank=True)  # 敏感
    bank_card_hash = models.CharField(max_length=128, null=True, blank=True)  # 敏感
    email = models.CharField(max_length=128, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    department_id = models.BigIntegerField()
    secondary_dept_ids = models.JSONField(default=list)
    # FORMAL/POSTDOC/VISITING_SCHOLAR/GUEST/TEMPORARY/STUDENT
    staff_type = models.CharField(max_length=24, default="FORMAL")
    position = models.CharField(max_length=32, null=True, blank=True)
    title = models.CharField(max_length=64, null=True, blank=True)
    education = models.CharField(max_length=32, null=True, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    leave_date = models.DateField(null=True, blank=True)
    # ONBOARD/RESIGNED/RETIRED/VISITING/GUEST/REHIRE
    employment_status = models.CharField(max_length=16, default="ONBOARD")
    photo_url = models.CharField(max_length=512, null=True, blank=True)
    orcid = models.CharField(max_length=32, null=True, blank=True)
    wos_researcher_id = models.CharField(max_length=64, null=True, blank=True)
    scopus_id = models.CharField(max_length=64, null=True, blank=True)
    cnki_author_id = models.CharField(max_length=64, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    research_expertise = models.JSONField(default=list)
    external_appointments = models.JSONField(default=list)
    is_pi = models.BooleanField(default=False)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    policy_pack_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "s_staff"


class STeam(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # FORMING/ACTIVE/EVALUATING/CHANGING/RENEWAL/DISSOLVED
    status = models.CharField(max_length=32, default="FORMING")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    name = models.CharField(max_length=128)
    team_type = models.CharField(max_length=32, default="PI_GROUP")
    pi_staff = models.ForeignKey(
        SStaff, on_delete=models.SET_NULL, db_column="pi_staff_id", null=True, blank=True
    )
    pi_user_id = models.BigIntegerField(null=True, blank=True)
    department_id = models.BigIntegerField(null=True, blank=True)
    member_ids = models.JSONField(default=list)  # 快照；权威成员见 S_MEMBERSHIP
    formed_date = models.DateField(null=True, blank=True)
    evaluation_cycle = models.CharField(max_length=32, null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")

    class Meta:
        db_table = "s_team"


class SMembership(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="ACTIVE")  # ACTIVE/LEFT
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    team = models.ForeignKey(STeam, on_delete=models.CASCADE, db_column="team_id")
    staff = models.ForeignKey(SStaff, on_delete=models.CASCADE, db_column="staff_id")
    user_id = models.BigIntegerField(null=True, blank=True)
    role = models.CharField(max_length=16, default="MEMBER")  # LEADER/CORE/MEMBER/STUDENT/VISITOR
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    contribution_summary = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "s_membership"


class SVisitor(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # APPLIED/APPROVED/REJECTED/ACTIVE/EXPIRED/TERMINATED
    status = models.CharField(max_length=32, default="APPLIED")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    staff = models.ForeignKey(SStaff, on_delete=models.CASCADE, db_column="staff_id")
    host_pi_staff = models.ForeignKey(
        SStaff, on_delete=models.SET_NULL, db_column="host_pi_staff_id",
        null=True, blank=True, related_name="hosted_visitors"
    )
    host_team = models.ForeignKey(
        STeam, on_delete=models.SET_NULL, db_column="host_team_id", null=True, blank=True
    )
    home_institution = models.CharField(max_length=256, null=True, blank=True)
    visit_type = models.CharField(max_length=16, default="SHORT_TERM")
    start_date = models.DateField()
    end_date = models.DateField()
    funding_source = models.CharField(max_length=64, null=True, blank=True)
    project_id = models.BigIntegerField(null=True, blank=True)
    permissions_scope = models.JSONField(default=dict)
    reminder_stage = models.CharField(max_length=16, default="NONE")

    class Meta:
        db_table = "s_visitor"


class SStudent(models.Model):
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
    staff = models.ForeignKey(SStaff, on_delete=models.CASCADE, db_column="staff_id")
    student_type = models.CharField(max_length=24)  # PHD/MASTER/UNDERGRAD/POSTDOC...
    supervisor_staff = models.ForeignKey(
        SStaff, on_delete=models.SET_NULL, db_column="supervisor_staff_id",
        null=True, blank=True, related_name="supervised_students"
    )
    supervisor_user_id = models.BigIntegerField(null=True, blank=True)
    enroll_year = models.IntegerField(null=True, blank=True)
    graduate_year = models.IntegerField(null=True, blank=True)
    thesis_topic = models.CharField(max_length=256, null=True, blank=True)
    associated_project_ids = models.JSONField(default=list)

    class Meta:
        db_table = "s_student"


class SPortrait(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="ACTIVE")  # ACTIVE/ARCHIVED
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    staff = models.ForeignKey(SStaff, on_delete=models.CASCADE, db_column="staff_id")
    snapshot_date = models.DateField()
    project_count_total = models.IntegerField(default=0)
    project_count_active = models.IntegerField(default=0)
    funding_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    funding_yearly = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    output_count_papers = models.IntegerField(default=0)
    output_count_patents = models.IntegerField(default=0)
    h_index = models.IntegerField(default=0)
    total_citations = models.IntegerField(default=0)
    top_journals = models.JSONField(default=list)
    expertise_tags = models.JSONField(default=list)
    collaboration_score = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    mentoring_count = models.IntegerField(default=0)
    # RISING/STABLE/MATURE
    career_stage = models.CharField(max_length=16, default="STABLE")
    ai_summary = models.TextField(null=True, blank=True)
    integrity_flag = models.BooleanField(default=False)

    class Meta:
        db_table = "s_portrait"
        unique_together = [("staff", "snapshot_date")]


class SCollabGraph(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    status = models.CharField(max_length=32, default="ACTIVE")  # ACTIVE/ARCHIVED
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    staff_a_id = models.BigIntegerField()  # 约定 a<b
    staff_b_id = models.BigIntegerField()
    snapshot_date = models.DateField()
    weight = models.IntegerField(default=0)
    first_year = models.IntegerField(null=True, blank=True)
    last_year = models.IntegerField(null=True, blank=True)
    shared_projects = models.JSONField(default=list)
    shared_papers = models.JSONField(default=list)
    centrality_score = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    community_id = models.IntegerField(null=True, blank=True)
    legal_entity_id = models.BigIntegerField(default=1)

    class Meta:
        db_table = "s_collab_graph"
        unique_together = [("staff_a_id", "staff_b_id", "snapshot_date")]


class STalentPlan(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    # CANDIDATE/ACTIVE/COMPLETED/EXPIRED/REVOKED
    status = models.CharField(max_length=32, default="ACTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)
    staff = models.ForeignKey(SStaff, on_delete=models.CASCADE, db_column="staff_id")
    plan_name = models.CharField(max_length=64)
    plan_code = models.CharField(max_length=64, null=True, blank=True)
    level = models.CharField(max_length=16, null=True, blank=True)  # NATIONAL/MINISTRY/PROVINCE/INSTITUTE
    awarded_year = models.IntegerField(null=True, blank=True)
    duration_years = models.IntegerField(null=True, blank=True)
    end_year = models.IntegerField(null=True, blank=True)
    batch = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "s_talent_plan"
