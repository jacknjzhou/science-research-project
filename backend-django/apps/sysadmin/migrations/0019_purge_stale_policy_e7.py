"""E-7 收口：清掉 policy.csv 已移除的悬空授权 + 再同步（R2-M2）。

`sync_permissions_from_csv` 只增不删，旧库上 `GET /api/v1/disclosure/*` 这类
早已在 CSV 里删掉的行会永久留在 DB（Casbin 运行时权威是 DB），等于给未来
可能出现的 detail GET 预授权。本迁移先按当前 CSV 全量清理悬空指派，再同步。
"""
from django.db import migrations


def _purge_and_resync(apps, schema_editor):
    from django.conf import settings

    from apps.sysadmin.permissions import (
        purge_stale_policy_rows,
        sync_permissions_from_csv,
    )

    purge_stale_policy_rows(settings.CASBIN_POLICY_PATH)
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


class Migration(migrations.Migration):
    dependencies = [("sysadmin", "0018_resync_permissions_e7")]
    operations = [migrations.RunPython(_purge_and_resync, migrations.RunPython.noop)]
