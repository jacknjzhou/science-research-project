"""数据迁移：policy.csv 新增归档清单补传权限（project/*/archive-checklist POST）幂等再同步。"""
from django.conf import settings
from django.db import migrations

from apps.sysadmin.permissions import sync_permissions_from_csv


def sync(apps, schema_editor):
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


def desync(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sysadmin", "0004_resync_permissions"),
    ]

    operations = [
        migrations.RunPython(sync, desync),
    ]
