#!/usr/bin/env python
"""Django 管理入口。"""
import os
import sys


def _validate_if_prod() -> None:
    """E-8：非 DEBUG 形态的管理命令也校验密钥（生产旁路不允许）。"""
    from django.conf import settings

    if not settings.DEBUG:
        from core.startup import validate_runtime_secrets

        validate_runtime_secrets()


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    _validate_if_prod()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "找不到 Django，请先安装依赖（见 pyproject.toml）。"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
