"""数据迁移：policy.csv 新增 M2-b 终审补口权限（评审决议 / 领导签署），幂等再同步。

policy.csv 是权限的**源**，但 casbin 运行时的权威在 DB（core/auth/casbin_util.py 的
DbAdapter 每次 enforce 都查 sys_role_permission），新增策略行必须伴随一次数据迁移，
否则线上（含空库 migrate 之后）不生效。
"""
from django.conf import settings
from django.db import migrations

from apps.sysadmin.permissions import sync_permissions_from_csv


def sync(apps, schema_editor):
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


class Migration(migrations.Migration):
    dependencies = [("sysadmin", "0012_resync_permissions")]
    operations = [migrations.RunPython(sync, migrations.RunPython.noop)]
