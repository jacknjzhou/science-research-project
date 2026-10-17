"""涉密管理与多法人治理域 X 模型。

自建四表（对齐 design/11-*.ddl.sql）：X_SECURITY_POLICY / X_ACCESS_GRANT /
X_SEC_LOG（SM3 哈希链，append-only）/ X_PERSONNEL_SEC；
复用 common：法人读写 sys_legal_entity（apps.sysadmin.SysLegalEntity），
输出审批落 x_flow_audit（本 app 承载模型，含 X 契约扩展列 approver/payload_digest 等）。
"""
from __future__ import annotations

from django.db import models


class XSecurityPolicy(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # SEC-年-序6
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    # DRAFT/ACTIVE/SUPERSEDED（同租户同模块集合仅一套 ACTIVE）
    status = models.CharField(max_length=32, default="DRAFT")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    version = models.IntegerField(default=1)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    matrix_json = models.JSONField(default=dict)
    applied_modules = models.JSONField(default=list)  # {P,E,F,R,T,G,A,C,D...}
    policy_pack_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "x_security_policy"


class XAccessGrant(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # SEC-年-序6
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    # EFFECTIVE/FROZEN/REVOKED
    status = models.CharField(max_length=32, default="EFFECTIVE")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    subject_user_id = models.BigIntegerField()
    # LEGAL_ENTITY/DEPT/PROJECT/SECURITY_LEVEL
    scope_type = models.CharField(max_length=16)
    scope_ref = models.BigIntegerField(null=True, blank=True)
    granted_level = models.CharField(max_length=16, default="INTERNAL")
    # INTERNET/OFFICE/SECRET_NET
    network_zone = models.CharField(max_length=16, default="OFFICE")
    mfa_bound = models.BooleanField(default=False)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "x_access_grant"


class XSecLog(models.Model):
    """追加不可改：无 status/deleted/updated_at（对齐 DDL 设计取舍）。"""
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    actor_id = models.BigIntegerField()
    actor_role = models.CharField(max_length=32, null=True, blank=True)
    # INTERNET/OFFICE/SECRET_NET
    network_zone = models.CharField(max_length=16, default="OFFICE")
    action = models.CharField(max_length=32)
    object_type = models.CharField(max_length=32)
    object_id = models.BigIntegerField()
    field_diff_json = models.JSONField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    granted_level = models.CharField(max_length=16, null=True, blank=True)
    # ALLOW/DENY
    result = models.CharField(max_length=8)
    risk_flag = models.SmallIntegerField(default=0)  # 0 常规/1 风险/2 高危
    hash_prev = models.CharField(max_length=128, null=True, blank=True)
    hash_self = models.CharField(max_length=128)
    occurred_at = models.DateTimeField()  # 显式传入（参与哈希链计算，禁用 auto_now_add）
    source_ip = models.CharField(max_length=64, null=True, blank=True)
    device_id = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        db_table = "x_sec_log"


class XPersonnelSec(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # SEC-年-序6
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(default=1)
    security_level = models.CharField(max_length=16, default="INTERNAL")
    # PENDING_REVIEW/GRANTED/RE_REVIEW/FROZEN/CLEARED_OUT
    status = models.CharField(max_length=32, default="PENDING_REVIEW")
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    user_id = models.BigIntegerField()  # 一人一份涉密档案（唯一）
    staff_id = models.BigIntegerField(null=True, blank=True)
    secret_eligible = models.BooleanField(default=False)
    granted_level = models.CharField(max_length=16, default="INTERNAL")
    # UNCLASSIFIED/DOWN_CLASSIFY/DECLASSIFY（工作态）
    classify_status = models.CharField(max_length=16, default="UNCLASSIFIED")
    review_date = models.DateField(null=True, blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    training_records = models.JSONField(default=list)
    leave_clearance = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "x_personnel_sec"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "user_id"],
                condition=models.Q(deleted=0),
                name="uk_personnel_sec_user",
            )
        ]


class XFlowAudit(models.Model):
    """输出/跨网审批（common.x_flow_audit + X 契约扩展列：双审人/内容指纹/放行范围）。"""
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, null=True, blank=True)  # EXF-年-序6
    direction = models.CharField(max_length=8, default="DOWN")  # DOWN/UP
    object_type = models.CharField(max_length=32)
    object_id = models.BigIntegerField()
    from_domain = models.CharField(max_length=16, default="SECRET_NET")
    to_domain = models.CharField(max_length=16, default="OFFICE")
    applicant_id = models.BigIntegerField()
    reason = models.TextField(null=True, blank=True)
    second_verifier_id = models.BigIntegerField(null=True, blank=True)
    # APPLIED/PRE_REVIEW/SEC_REVIEW/RELEASED/REJECTED/RECORDED
    status = models.CharField(max_length=32, default="APPLIED")
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(null=True, blank=True)
    security_level = models.CharField(max_length=16, default="SECRET")
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # —— X 契约扩展列（X-06 双审 + 指纹防篡改）——
    approver1_id = models.BigIntegerField(null=True, blank=True)  # 初审（项目负责人）
    approver2_id = models.BigIntegerField(null=True, blank=True)  # 复审（安全管理员）
    payload_digest = models.CharField(max_length=128, null=True, blank=True)
    desensitize_note = models.TextField(null=True, blank=True)
    release_scope = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "x_flow_audit"
