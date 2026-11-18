"""M2-c：把新增的专家门户策略再同步到 DB（Casbin 运行时权威是 DB）。"""
from django.db import migrations


def _resync(apps, schema_editor):
    from django.conf import settings

    from apps.sysadmin.permissions import sync_permissions_from_csv

    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


class Migration(migrations.Migration):
    dependencies = [("sysadmin", "0014_resync_permissions")]
    operations = [migrations.RunPython(_resync, migrations.RunPython.noop)]
