"""跨域平台模型（对齐 Go 迁移 000010：通用两级审核动作流水）。"""
from django.db import models


class SysApprovalLog(models.Model):
    """审核动作流水：biz_type + biz_id 定位业务单据；step 0=提交 1=首审 2=终审。

    action: SUBMIT / APPROVE / REJECT / RETURN。业务表 status 仍是状态唯一真源。
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.BigIntegerField()
    biz_type = models.CharField(max_length=64)
    biz_id = models.BigIntegerField()
    step = models.IntegerField(default=1)
    actor_id = models.BigIntegerField()
    actor_role = models.CharField(max_length=64, blank=True, default="")
    action = models.CharField(max_length=16)
    comment = models.TextField(null=True, blank=True)
    acted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sys_approval_log"
