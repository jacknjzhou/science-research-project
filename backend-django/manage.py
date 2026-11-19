#!/usr/bin/env python
"""Django 管理入口。

启动守卫不在这里——`--settings` / `--pythonpath` 要到 `execute_from_command_line`
里才会被解析，在这里自检会先用默认 `config.settings.dev` 初始化一次，于是
`manage.py runserver --settings=config.settings.prod` 被静默降级成 dev 形态，
守卫看起来在、实际没有生效（E-8 终审 r6-C1）。守卫统一放在
`core/apps.py::CoreConfig.ready()`，那时配置已确定，且覆盖 wsgi/asgi/celery/
manage/django-admin 所有入口。

这里只负责：把守卫抛出的配置错误变成一行可读的 stderr 提示 + exit 1，
而不是让运维在 traceback 里找原因。
"""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.exceptions import ImproperlyConfigured
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "找不到 Django，请先安装依赖（见 pyproject.toml）。"
        ) from exc
    try:
        execute_from_command_line(sys.argv)
    except ImproperlyConfigured as exc:
        sys.stderr.write(f"[启动自检] 拒绝启动：{exc}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
