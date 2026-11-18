"""数据迁移：policy.csv 新增 R-PARTNER 外部机构门户权限域（M2-a），幂等再同步。

DB 是 casbin 唯一权威（core/auth/casbin_util.DbAdapter），只改 CSV 不重同步则运行时无效。
"""
from django.conf import settings
from django.db import migrations

from apps.sysadmin.permissions import sync_permissions_from_csv


def sync(apps, schema_editor):
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


def desync(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sysadmin", "0008_syspartnerorg_sysuser_org"),
    ]

    operations = [
        migrations.RunPython(sync, desync),
    ]
