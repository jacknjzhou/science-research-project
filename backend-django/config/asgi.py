"""ASGI 入口。

启动守卫见 `core/apps.py::CoreConfig.ready()`（wsgi/asgi 共用一条路径，避免重复扫描）。
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_asgi_application()
