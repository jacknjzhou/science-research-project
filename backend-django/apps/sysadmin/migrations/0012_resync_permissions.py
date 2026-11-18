"""数据迁移：policy.csv 新增 M2-b 外部机构业务域权限，幂等再同步。"""
from django.conf import settings
from django.db import migrations

from apps.sysadmin.permissions import sync_permissions_from_csv


def sync(apps, schema_editor):
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


def desync(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sysadmin", "0011_m2a_uk_ptn_credit"),
    ]

    operations = [
        migrations.RunPython(sync, desync),
    ]
