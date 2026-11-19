"""ASGI 入口。"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_asgi_application()

# E-8：非 DEBUG 形态启动即校验密钥强度（不依赖 settings 模块名）
from django.conf import settings  # noqa: E402
from core.startup import (  # noqa: E402
    assert_no_default_credentials,
    validate_runtime_secrets,
)

if not settings.DEBUG:
    validate_runtime_secrets()
    # E-8：升级自旧版本的库可能仍带公开默认口令 → 拒绝起来，等运维轮换
    assert_no_default_credentials()
