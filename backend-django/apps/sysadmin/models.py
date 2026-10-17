"""系统管理域模型：镜像 Go 迁移 000001/000013/000014 的 sys_* 表结构。

表名/字段名保持与 Go 版一致（snake_case + 既有约束语义），
迁移由 Django 接管为 schema 唯一真源（plan §六）。
"""
from __future__ import annotations

from django.db import models


class SysLegalEntity(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    credit_code = models.CharField(max_length=64, null=True, blank=True)
    entity_type = models.CharField(max_length=16)
    short_code = models.CharField(max_length=16, null=True, blank=True)
    consolidated = models.BooleanField(default=False)
    status = models.CharField(max_length=32, default="ACTIVE")
    tenant_id = models.BigIntegerField()
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "sys_legal_entity"


class SysOrg(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    parent_id = models.BigIntegerField(null=True, blank=True)
    org_type = models.CharField(max_length=16, default="DEPT")
    legal_entity_id = models.BigIntegerField(null=True, blank=True)
    sort_no = models.IntegerField(default=0)
    status = models.CharField(max_length=32, default="ACTIVE")
    tenant_id = models.BigIntegerField()
    deleted = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sys_org"


class SysUser(models.Model):
    id = models.BigAutoField(primary_key=True)
    username = models.CharField(max_length=64)
    real_name = models.CharField(max_length=64)
    email = models.CharField(max_length=128, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    staff_no = models.CharField(max_length=64, null=True, blank=True)
    employment_status = models.CharField(max_length=16, default="ONBOARD")
    security_level = models.CharField(max_length=16, default="INTERNAL")
    status = models.CharField(max_length=32, default="ACTIVE")
    # NULL=无口令账号（dev/外联身份），一律拒登（对齐 Go 语义）
    password_hash = models.CharField(max_length=100, null=True, blank=True)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(null=True, blank=True)
    deleted = models.SmallIntegerField(default=0)
    creator_id = models.BigIntegerField()
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remark = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "sys_user"
        indexes = [models.Index(fields=["tenant_id", "username"])]


class SysRole(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=64)
    is_builtin = models.BooleanField(default=True)
    tenant_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sys_role"


class SysUserRole(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(SysUser, on_delete=models.CASCADE, db_column="user_id")
    role = models.ForeignKey(SysRole, on_delete=models.CASCADE, db_column="role_id")
    tenant_id = models.BigIntegerField()
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sys_user_role"


class SysAdminDuty(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(SysUser, on_delete=models.CASCADE, db_column="user_id")
    duty_type = models.CharField(max_length=16)
    tenant_id = models.BigIntegerField()
    legal_entity_id = models.BigIntegerField(null=True, blank=True)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sys_admin_duty"


class SysDict(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    tenant_id = models.BigIntegerField()
    remark = models.TextField(null=True, blank=True)
    deleted = models.SmallIntegerField(default=0)  # 000013：软删后同码可重建
    creator_id = models.BigIntegerField(null=True, blank=True)
    modifier_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sys_dict"


class SysDictItem(models.Model):
    id = models.BigAutoField(primary_key=True)
    dict = models.ForeignKey(
        SysDict, on_delete=models.CASCADE, db_column="dict_id", related_name="items"
    )
    item_code = models.CharField(max_length=64)
    item_label = models.CharField(max_length=128)
    parent_id = models.BigIntegerField(null=True, blank=True)  # 树形（科目/分类）
    ext_json = models.JSONField(null=True, blank=True)  # ratio_limit/applies_to 等
    sort_no = models.IntegerField(default=0)
    i18n_json = models.JSONField(null=True, blank=True)  # 多语言
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    tenant_id = models.BigIntegerField()

    class Meta:
        db_table = "sys_dict_item"


class PageGrant(models.Model):
    """页面可见性矩阵（PRD 2.9）：白名单制，role_code='*' 表示所有已登录角色。"""

    id = models.BigAutoField(primary_key=True)
    page_name = models.CharField(max_length=64)
    role_code = models.CharField(max_length=64)
    tenant_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sys_page_grant"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "page_name", "role_code"], name="uk_page_grant"
            )
        ]


class SysPermission(models.Model):
    """接口操作权限目录（Django auth_permission 风格）。

    code     —— 权限码（codename），如 "activities.x.submit.post"
    obj/act  —— Casbin 策略对象：路径模板 + HTTP 方法（一条权限 = 一条策略模板）
    domain   —— 业务域（取路径第一段），用于管理界面分组
    """

    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=128)
    name = models.CharField(max_length=256)
    obj = models.CharField(max_length=128)
    act = models.CharField(max_length=16)
    domain = models.CharField(max_length=32, default="misc")
    tenant_id = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sys_permission"
        constraints = [
            models.UniqueConstraint(fields=["obj", "act"], name="uk_permission_obj_act"),
            models.UniqueConstraint(fields=["code"], name="uk_permission_code"),
        ]

    def __str__(self):
        return f"{self.code} ({self.act} {self.obj})"


class SysRolePermission(models.Model):
    """角色-权限指派（Django Group.permissions M2M 风格）。

    casbin enforcer 从本表动态加载策略：管理端授权/回收后 load_policy() 热生效。
    """

    id = models.BigAutoField(primary_key=True)
    role = models.ForeignKey(SysRole, on_delete=models.CASCADE, db_column="role_id")
    permission = models.ForeignKey(
        SysPermission, on_delete=models.CASCADE, db_column="permission_id"
    )
    granted_by = models.BigIntegerField(null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sys_role_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission"], name="uk_role_permission"
            )
        ]
