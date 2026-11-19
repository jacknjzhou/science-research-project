"""生产/容器配置：DEBUG 恒关（E-3 冒烟后门的第一道门）。

compose 与 Dockerfile 通过 `DJANGO_SETTINGS_MODULE=config.settings.prod` 显式选用；
未设置时 manage.py/wsgi.py 仍回落到 dev（本地开发便利），但因此 **dev 形态下
`settings.DEBUG=True`，`ark/ark` 仅剩 `ARK_DEV_LOGIN=1` 一把锁**——部署时必须
用本配置，或在环境里显式设置 `DJANGO_SETTINGS_MODULE`。

E-8：本配置**拒绝启动**于弱密钥。`base.SECRET_KEY` 的缺省值写死在仓库里，
一旦被带进生产，任何读过仓库的人都能伪造任意用户（含 R-ADMIN）的 JWT，
因此这里把它变成硬失败，而不是「能跑就行」的告警。
"""
from .base import *  # noqa: F401,F403

DEBUG = False

# 允许的主机：容器内以服务名互访，对外由 frontend(nginx) 反代
ALLOWED_HOSTS = ["*"]

# 自检实现见 core/startup.py：判据是运行期 DEBUG，不依赖 settings 模块名，
# 因此自定义 `from .prod import *` 的模块同样受保护（wsgi/asgi/manage.py 兜底）。
import os  # noqa: E402

from core.startup import validate_secret_value  # noqa: E402

# import 期快失败：只在运维确实提供了 `ARK_JWT_SECRET` 时校验本模块定义的值。
# 没提供时不在这里拦——允许 `from .prod import *` 的自定义 settings 用自己的
# 密钥来源（例如 Vault 注入后覆盖 `JWT_SECRET`）；运行期由 wsgi/asgi/manage.py
# 调 `validate_runtime_secrets()` 校验**最终生效**的 `settings.JWT_SECRET`。
# 二者都不覆盖的情况（缺 env 且无覆盖）会在运行期被拒。
if os.environ.get("ARK_JWT_SECRET"):
    validate_secret_value(str(JWT_SECRET or ""), origin="config.settings.prod.JWT_SECRET")
