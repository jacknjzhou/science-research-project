"""数据迁移：policy.csv 新增机构审核台（R-MANAGER）权限，幂等再同步（M2-a Task 5）。"""
from django.conf import settings
from django.db import migrations

from apps.sysadmin.permissions import sync_permissions_from_csv


def sync(apps, schema_editor):
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


def desync(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sysadmin", "0009_resync_permissions"),
    ]

    operations = [
        migrations.RunPython(sync, desync),
    ]
