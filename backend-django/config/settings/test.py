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
