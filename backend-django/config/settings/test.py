"""测试配置：sqlite + fakeredis，无需外部服务。"""
import os
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

# 测试形态同样走 E-8 进程守卫（`core/apps.ready()`）。密钥**随机生成**而不是
# 写死：写死的强密钥看起来「合规」，一旦这份配置被 `import *` 进生产就是已知密钥
# （r6-C2）。随机值让「误用测试配置」最多是「重启后令牌全失效」，而不是可伪造。
import secrets as _secrets

JWT_SECRET = os.environ.get("ARK_JWT_SECRET") or _secrets.token_urlsafe(48)

# 供 `core.startup._assert_settings_module_deployable()` 识别：`import *` 也会复制它，
# 所以别名绕过同样被拦。删除本行也不会变成可部署——密钥是随机的。
IS_TEST_SETTINGS = True
