#!/usr/bin/env python
"""Django 管理入口。"""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "找不到 Django，请先安装依赖（见 pyproject.toml）。"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
