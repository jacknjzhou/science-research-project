"""跨租户脏引用审计（G 域，终审 r2 要求）。

历史窗口内 `create_bid` / `create_contract` 曾接受跨租户的 `requisition_id`，可能留下
「合同/招标/订单挂在他租户采购申请上」的脏行。本命令只读，用来在升级后核对并决定是否
需要修数（配合 `payment_callback` / `award_bid` 新增的租户守卫）。

用法：
    python manage.py audit_cross_tenant_refs            # 只统计
    python manage.py audit_cross_tenant_refs --verbose  # 逐行打印
退出码：发现脏行返回 1，便于 CI/运维脚本判断。
"""
from django.core.management.base import BaseCommand

from apps.procure.models import GBid, GContract, GOrder


class Command(BaseCommand):
    help = "审计 G 域合同/招标/订单是否挂在他租户的采购申请上（只读）"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--verbose", action="store_true", help="逐行打印脏记录")

    def handle(self, *args, **options) -> None:
        verbose = bool(options.get("verbose"))
        total = 0
        for label, model in (
            ("G_CONTRACT", GContract),
            ("G_BID", GBid),
            ("G_ORDER", GOrder),
        ):
            # M-2：软删行同样可能被历史数据引用，纳入审计（deleted=1 会另标）
            qs = model.objects.filter(
                requisition_id__isnull=False
            ).exclude(requisition__isnull=True)
            dirty = [
                row
                for row in qs.select_related("requisition").only(
                    "id", "code", "tenant_id", "deleted", "requisition__tenant_id"
                )
                if row.requisition is not None
                and row.tenant_id != row.requisition.tenant_id
            ]
            total += len(dirty)
            self.stdout.write(f"{label}: {len(dirty)} 条跨租户引用")
            if verbose:
                for row in dirty:
                    self.stdout.write(
                        f"  - {label} id={row.id} code={row.code} "
                        f"deleted={row.deleted} tenant_id={row.tenant_id} "
                        f"requisition.tenant_id={row.requisition.tenant_id}"
                    )
        if total:
            self.stdout.write(self.style.WARNING(f"合计 {total} 条脏行，需要修数"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("合计 0 条脏行"))
