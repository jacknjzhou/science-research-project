"""ASGI 入口。"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_asgi_application()

# E-8：非 DEBUG 形态启动即校验密钥强度（不依赖 settings 模块名）
from django.conf import settings  # noqa: E402
from core.startup import validate_runtime_secrets  # noqa: E402

if not settings.DEBUG:
    validate_runtime_secrets()
