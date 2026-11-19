#!/usr/bin/env python
"""Django 管理入口。"""
import os
import sys


def _validate_if_prod() -> None:
    """E-8：非 DEBUG 形态的管理命令也过完整守卫（密钥 + 默认口令，豁免命令除外）。

    这里曾经只校验密钥，于是 `manage.py check` / `manage.py shell` 在「库里仍是
    admin/Admin@123456」时照样 exit 0 —— 运维在坏状态上看到的是「一切正常」。
    现在与 wsgi/asgi 走同一套判定，只有修复类命令（migrate、rotate_demo_credentials…）
    豁免，否则门禁会锁死自己的修复路径。
    """
    from django.conf import settings

    if settings.DEBUG:
        return
    # 默认口令扫描要查库，必须先让 app registry 就绪（`ready()` 顺带完成密钥校验）；
    # 未就绪时查询会抛 AppRegistryNotReady，看起来像「检查失败」而不是「配置失败」。
    import django

    django.setup()
    from core.startup import enforce_process_guard

    enforce_process_guard()


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
