"""测试配置：sqlite + fakeredis，无需外部服务。"""
from .base import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# 测试用 fakeredis（tests/conftest.py 注入）

# 测试形态：允许 seed_demo（套件需要演示账号做鉴权夹具）
ALLOW_DEMO_SEED = True

# 测试形态同样走 E-8 进程守卫（`core/apps.ready()`），因此必须给一个强密钥——
# 不允许出现「靠测试环境绕过生产自检」的隐性豁免。
JWT_SECRET = "test-only-secret-please-do-not-use-in-production-0123456789"
