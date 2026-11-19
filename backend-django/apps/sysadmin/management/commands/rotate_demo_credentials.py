"""一次性口令轮换：把仍使用仓库默认口令的演示账号换成运维给定的强口令。

E-8 配套：升级自旧版本的库可能残留 `admin/Admin@123456` 等公开口令；生产启动会
因此拒绝服务（见 `core/startup.py::assert_no_default_credentials`）。本命令是
唯一的修复入口——它只动「当前口令确实等于已知默认值」的账号，不会误伤真实用户。

用法：
    python manage.py rotate_demo_credentials --password 'New-Str0ng-Pass!'
    python manage.py rotate_demo_credentials --password '…' --dry-run
"""
from __future__ import annotations

import os
import sys

import bcrypt
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.sysadmin.models import SysUser
from core.startup import DEFAULT_SEED_PASSWORDS, KNOWN_DEFAULT_PASSWORDS, _known_defaults_for, find_default_credential_accounts


class Command(BaseCommand):
    help = "把仍在使用仓库默认口令的演示账号轮换为运维指定口令（E-8）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help="新口令；省略则从环境变量 ARK_ROTATE_PASSWORD 或标准输入读取（避免进 argv/ps）",
        )
        parser.add_argument("--dry-run", action="store_true", help="只列出将被轮换的账号")

    def handle(self, *args, **options):
        new_pwd = options.get("password") or os.environ.get("ARK_ROTATE_PASSWORD") or ""
        if not new_pwd and not sys.stdin.isatty():
            new_pwd = sys.stdin.readline().strip()
        if not new_pwd:
            raise CommandError("缺少新口令：用 --password、ARK_ROTATE_PASSWORD 或标准输入提供。")
        if len(new_pwd) < 10:
            raise CommandError("新口令至少 10 位（演示账号也是真实登录入口）。")
        if new_pwd in DEFAULT_SEED_PASSWORDS:
            raise CommandError("新口令不得是仓库内置的默认口令（含 Demo@123456）。")

        hashed = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt()).decode()
        rotated: list[str] = []
        rows = SysUser.objects.filter(
            username__in=list(KNOWN_DEFAULT_PASSWORDS), deleted=0
        ).order_by("tenant_id", "id")
        for row in rows:
            username = row.username
            if row is None or not row.password_hash:
                continue
            current = row.password_hash.encode()
            hit = False
            for pwd in _known_defaults_for(username):
                try:
                    if bcrypt.checkpw(pwd.encode(), current):
                        hit = True
                        break
                except ValueError:
                    hit = False
                    break
            if not hit:
                continue
            rotated.append(f"{username}@{row.tenant_id}")
            if options["dry_run"]:
                continue
            row.password_hash = hashed
            row.save(update_fields=["password_hash"])

        verb = "将轮换" if options["dry_run"] else "已轮换"
        if rotated:
            self.stdout.write(self.style.SUCCESS(f"{verb} {len(rotated)} 个账号：{'、'.join(rotated)}"))
        else:
            self.stdout.write("没有发现仍在使用默认口令的账号。")
        if not options["dry_run"] and rotated:
            # 自检：轮换后 gate 必须能放行（否则说明还有漏网账号）
            remaining = find_default_credential_accounts(active_only=False)
            if remaining:
                raise CommandError(
                    f"仍有账号使用默认口令：{'、'.join(remaining)}；请检查后重试。"
                )
            self.stdout.write(self.style.SUCCESS("自检通过：已无默认口令账号。"))
