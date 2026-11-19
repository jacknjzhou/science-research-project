"""启动期安全自检（E-8）。

放在独立模块而不是 `config/settings/prod.py`，是因为**判定依据必须是运行期
`settings.DEBUG`，不能是「settings 模块名字符串」**——部署方常用自定义
`config/settings/prod_site.py` 之类的模块 `from .prod import *`，那种情况下
按模块名触发自检会被静默跳过，而进程其实已经是生产形态。

调用点：`config/wsgi.py`、`config/asgi.py`（服务进程真正对外时）与
`config/settings/prod.py`（选中 prod 配置即尽早失败），另外 `manage.py` 在
非 DEBUG 形态下也跑一次，避免 `manage.py` 被当成「安全的旁路」。
"""
from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

# 仓库内置的默认值（与 base.SECRET_KEY 缺省一致）与常见占位串，一律拒用
INSECURE_SECRETS = frozenset(
    {
        "",
        "dev-secret-change-me-please-use-32-bytes-min!",
        "secret",
        "changeme",
        "change-me",
        "please-change-me",
    }
)
SECRET_MIN_LEN = 32
SECRET_HINT = "生成方式：openssl rand -base64 32"


def validate_runtime_secrets() -> None:
    """生产形态（`settings.DEBUG is False`）的 JWT 密钥硬化检查。

    抛 `ImproperlyConfigured`（Django 对配置错误的约定异常），让进程在
    bind 端口之前退出，避免「带着公开默认密钥上线」这种静默事故。

    判据只有运行期状态：
      · 必须由环境变量 `ARK_JWT_SECRET` 显式提供（不接受仓库缺省值）；
      · 不得是仓库内置默认值 / 常见占位串；
      · 长度不少于 `SECRET_MIN_LEN`。
    """
    from django.conf import settings as dj_settings

    if getattr(dj_settings, "DEBUG", False):
        return  # 本地 dev 形态：允许使用仓库缺省密钥

    raw = os.environ.get("ARK_JWT_SECRET")
    if not raw:
        raise ImproperlyConfigured(
            f"生产环境必须显式设置 ARK_JWT_SECRET（当前未设置，用的是仓库缺省密钥）。{SECRET_HINT}"
        )
    if raw.strip() in INSECURE_SECRETS:
        raise ImproperlyConfigured(
            f"ARK_JWT_SECRET 仍是仓库内置的演示默认值，任何读过代码的人都能伪造令牌。{SECRET_HINT}"
        )
    if len(raw) < SECRET_MIN_LEN:
        raise ImproperlyConfigured(
            f"ARK_JWT_SECRET 长度 {len(raw)} 不足 {SECRET_MIN_LEN} 字符，强度不足。{SECRET_HINT}"
        )
