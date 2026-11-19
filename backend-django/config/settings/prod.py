"""生产/容器配置：DEBUG 恒关（E-3 冒烟后门的第一道门）。

compose 与 Dockerfile 通过 `DJANGO_SETTINGS_MODULE=config.settings.prod` 显式选用；
未设置时 manage.py/wsgi.py 仍回落到 dev（本地开发便利），但因此 **dev 形态下
`settings.DEBUG=True`，`ark/ark` 仅剩 `ARK_DEV_LOGIN=1` 一把锁**——部署时必须
用本配置，或在环境里显式设置 `DJANGO_SETTINGS_MODULE`。
"""
from .base import *  # noqa: F401,F403

DEBUG = False

# 允许的主机：容器内以服务名互访，对外由 frontend(nginx) 反代
ALLOWED_HOSTS = ["*"]
