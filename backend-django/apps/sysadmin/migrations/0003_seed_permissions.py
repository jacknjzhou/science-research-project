"""数据迁移：把 config/casbin/policy.csv 的策略规则灌入权限目录（幂等）。"""
from django.conf import settings
from django.db import migrations

from apps.sysadmin.permissions import sync_permissions_from_csv


def sync(apps, schema_editor):
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


def desync(apps, schema_editor):
    # 回滚仅清指派，保留权限目录（目录本身无副作用）
    apps.get_model("sysadmin", "SysRolePermission").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sysadmin", "0002_syspermission_sysrolepermission"),
    ]

    operations = [
        migrations.RunPython(sync, desync),
    ]
