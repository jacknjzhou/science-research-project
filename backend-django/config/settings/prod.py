"""生产/容器配置：DEBUG 恒关（E-3 冒烟后门的第一道门）。

compose 与 Dockerfile 通过 `DJANGO_SETTINGS_MODULE=config.settings.prod` 显式选用；
未设置时 manage.py/wsgi.py 仍回落到 dev（本地开发便利），但因此 **dev 形态下
`settings.DEBUG=True`，`ark/ark` 仅剩 `ARK_DEV_LOGIN=1` 一把锁**——部署时必须
用本配置，或在环境里显式设置 `DJANGO_SETTINGS_MODULE`。

E-8：本配置**拒绝启动**于弱密钥。`base.SECRET_KEY` 的缺省值写死在仓库里，
一旦被带进生产，任何读过仓库的人都能伪造任意用户（含 R-ADMIN）的 JWT，
因此这里把它变成硬失败，而不是「能跑就行」的告警。
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False

# 允许的主机：容器内以服务名互访，对外由 frontend(nginx) 反代
ALLOWED_HOSTS = ["*"]

# 仓库内置的默认值（与 base.SECRET_KEY 缺省一致）与常见占位串，一律拒用
_INSECURE_SECRETS = frozenset(
    {
        "",
        "dev-secret-change-me-please-use-32-bytes-min!",
        "secret",
        "changeme",
        "change-me",
        "please-change-me",
    }
)
_SECRET_MIN_LEN = 32
_HINT = "生成方式：openssl rand -base64 32"


def validate_prod_secrets() -> None:
    """生产启动前置检查：JWT 密钥必须由环境显式提供且足够强。

    抛 `ImproperlyConfigured`（Django 对配置错误的约定异常），让 gunicorn 在
    bind 端口之前就退出，避免「带着公开默认密钥上线」这种静默事故。
    """
    raw = os.environ.get("ARK_JWT_SECRET")
    if not raw:
        raise ImproperlyConfigured(
            f"生产环境必须显式设置 ARK_JWT_SECRET（当前未设置，用的是仓库缺省密钥）。{_HINT}"
        )
    if raw.strip() in _INSECURE_SECRETS:
        raise ImproperlyConfigured(
            f"ARK_JWT_SECRET 仍是仓库内置的演示默认值，任何读过代码的人都能伪造令牌。{_HINT}"
        )
    if len(raw) < _SECRET_MIN_LEN:
        raise ImproperlyConfigured(
            f"ARK_JWT_SECRET 长度 {len(raw)} 不足 {_SECRET_MIN_LEN} 字符，强度不足。{_HINT}"
        )


# 仅在「本模块被当作 settings 加载」时自检：测试进程用 config.settings.test，
# 导入本模块只为调用 validate_prod_secrets()，不应在 import 期抛错。
if os.environ.get("DJANGO_SETTINGS_MODULE", "").startswith("config.settings.prod"):
    validate_prod_secrets()
