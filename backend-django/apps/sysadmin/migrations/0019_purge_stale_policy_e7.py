"""E-7 收口：清掉已下线端点的悬空授权 + 再同步（R2-M2 / R3-I3）。

`sync_permissions_from_csv` 只增不删，旧库上 `GET /api/v1/disclosure/*` 这类
早已在 CSV 里删掉的行会永久留在 DB（Casbin 运行时权威是 DB），等于给未来可能
出现的 detail GET 预授权。

**只删 STALE_POLICY 里列出的已知下线规则**（当前 1 条 `GET /api/v1/disclosure/*`），
不做全表扫描：运行期通过管理界面自定义的
角色-授权（CSV 里本来就没有对应行）必须保留，广谱清理会误删它们。
"""
from django.db import migrations

STALE_POLICY = [
    # (obj, act)：004 期删除的披露详情 GET，CSV 已无此行
    ("/api/v1/disclosure/*", "GET"),
]


def _purge_and_resync(apps, schema_editor):
    from django.conf import settings

    from apps.sysadmin.models import SysPermission, SysRolePermission
    from apps.sysadmin.permissions import sync_permissions_from_csv

    for obj, act in STALE_POLICY:
        perms = SysPermission.objects.filter(obj=obj, act=act)
        SysRolePermission.objects.filter(permission__in=perms).delete()
        perms.delete()
    sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)


class Migration(migrations.Migration):
    dependencies = [("sysadmin", "0018_resync_permissions_e7")]
    operations = [migrations.RunPython(_purge_and_resync, migrations.RunPython.noop)]
