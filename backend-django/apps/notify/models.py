"""通知中心模型（对齐 Go 迁移 000003/000004 语义）。"""
from __future__ import annotations

from django.db import models


class SysNotification(models.Model):
    """读模型：写入侧按用户扇出，读路径只按 user_id 查询。

    typ：TODO 待办 / MESSAGE 站内消息 / WARNING 预警 / ANNOUNCE 公告。
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    user_id = models.BigIntegerField()  # 收件人
    typ = models.CharField(max_length=16, default="TODO")
    title = models.CharField(max_length=200)
    content = models.TextField(null=True, blank=True)
    biz_ref = models.CharField(max_length=128, null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sys_notification"


class SysImportLog(models.Model):
    """导入日志：snapshot 存成功行原始键，支持撤销（dataio 底座配套）。"""

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    user_id = models.BigIntegerField()
    biz_type = models.CharField(max_length=64)
    filename = models.CharField(max_length=256, null=True, blank=True)
    total_rows = models.IntegerField(default=0)
    ok_rows = models.IntegerField(default=0)
    fail_rows = models.IntegerField(default=0)
    snapshot = models.JSONField(null=True, blank=True)
    undone = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sys_import_log"


class SysTask(models.Model):
    """任务中心（T20）：按角色/用户投递的待办任务。"""

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    assignee_id = models.BigIntegerField(null=True, blank=True)
    role_code = models.CharField(max_length=64, null=True, blank=True)
    typ = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    biz_ref = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=32, default="OPEN")
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sys_task"
