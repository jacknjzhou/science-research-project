"""数据迁移：policy.csv 新增条目（前端 404 补端点权限）幂等再同步。"""
from django.conf import settings
from django.db import migrations

from apps.sysadmin.permissions import sync_permissions_from_csv


def sync(apps, schema_editor):
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


def desync(apps, schema_editor):
    # 幂等同步，无需回滚动作
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sysadmin", "0003_seed_permissions"),
    ]

    operations = [
        migrations.RunPython(sync, desync),
    ]
