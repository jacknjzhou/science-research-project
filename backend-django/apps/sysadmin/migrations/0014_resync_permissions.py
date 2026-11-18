"""M2-b 终审 r3：批复权限再同步（新增 :change-pi 两行）。"""
from __future__ import annotations

from django.conf import settings
from django.db import migrations


def sync_permissions(apps, schema_editor):
    from apps.sysadmin.permissions import sync_permissions_from_csv

    sync_permissions_from_csv(getattr(settings, "CASBIN_POLICY_PATH", None))


class Migration(migrations.Migration):
    dependencies = [("sysadmin", "0013_resync_permissions")]
    operations = [migrations.RunPython(sync_permissions, migrations.RunPython.noop)]
