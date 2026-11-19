"""E-7：间接费试算端点策略再同步（Casbin 运行时权威是 DB）。"""
from django.db import migrations


def _resync(apps, schema_editor):
    from django.conf import settings

    from apps.sysadmin.permissions import sync_permissions_from_csv

    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


class Migration(migrations.Migration):
    dependencies = [("sysadmin", "0017_resync_permissions")]
    operations = [migrations.RunPython(_resync, migrations.RunPython.noop)]
