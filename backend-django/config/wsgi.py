"""WSGI 入口。

启动守卫不在这里调用：`CoreConfig.ready()` 已在 `django.setup()` 阶段跑完整检查
（密钥强度 + 默认口令扫描），wsgi/asgi 再调一次只会重复查库（r7-I2）。
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_wsgi_application()
