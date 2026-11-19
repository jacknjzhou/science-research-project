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

    env_raw = os.environ.get("ARK_JWT_SECRET")
    if not env_raw:
        raise ImproperlyConfigured(
            f"生产环境必须显式设置 ARK_JWT_SECRET（当前未设置，用的是仓库缺省密钥）。{SECRET_HINT}"
        )

    # 校验**真正用于签名**的值：`core/auth/jwt_util` 读的是 settings.JWT_SECRET，
    # 自定义 settings 可以直接把它覆盖成弱值（而环境变量看起来是合规的）。
    validate_secret_value(
        str(getattr(dj_settings, "JWT_SECRET", "") or ""),
        origin="settings.JWT_SECRET",
    )


def validate_secret_value(value: str, *, origin: str = "JWT_SECRET") -> None:
    """校验一个具体的密钥值（供 settings 模块在 import 期自检自己定义的值）。"""
    if not value:
        raise ImproperlyConfigured(f"{origin} 为空，无法签发令牌。{SECRET_HINT}")
    if value.strip() in INSECURE_SECRETS:
        raise ImproperlyConfigured(
            f"{origin} 是仓库内置的演示默认值，任何读过代码的人都能伪造令牌。{SECRET_HINT}"
        )
    if len(value) < SECRET_MIN_LEN:
        raise ImproperlyConfigured(
            f"{origin} 长度 {len(value)} 不足 {SECRET_MIN_LEN} 字符"
            f"（注意自定义 settings 覆盖 settings.JWT_SECRET 也会生效）。{SECRET_HINT}"
        )


# —— 已知的仓库默认口令（seed_demo 用过的全部固定值）——
# 升级自 E-8 之前的库可能仍带这些口令；生产启动时逐一探测，命中即拒绝服务。
KNOWN_DEFAULT_PASSWORDS = {
    "admin": ("Admin@123456",),
    "manager": ("Manager@123456",),
    "staff": ("Staff@123456",),
    "finance": ("Finance@123456",),
    "partner": ("Partner@123456",),
    "expert_ext": ("Expert@123456",),
}
# 兜底：任何演示账号都可能被上一版 compose 的默认口令覆盖
FALLBACK_DEFAULT_PASSWORDS = ("Demo@123456",)


def _known_defaults_for(username: str) -> tuple[str, ...]:
    return KNOWN_DEFAULT_PASSWORDS.get(username, ()) + FALLBACK_DEFAULT_PASSWORDS


def find_default_credential_accounts() -> list[str]:
    """返回仍在用仓库默认口令的账号名（只探测已知演示账号，成本可控）。"""
    import bcrypt
    from django.db import DatabaseError

    from apps.sysadmin.models import SysUser

    hits: list[str] = []
    for username in KNOWN_DEFAULT_PASSWORDS:
        row = (
            SysUser.objects.filter(tenant_id=1, username=username, deleted=0)
            .values_list("password_hash", flat=True)
            .first()
        )
        if not row:
            continue
        hashed = str(row).encode()
        for pwd in _known_defaults_for(username):
            try:
                if bcrypt.checkpw(pwd.encode(), hashed):
                    hits.append(username)
                    break
            except ValueError:  # 非法 hash → 交给业务层处理
                break
    return hits


def assert_no_default_credentials() -> None:
    """生产启动前：库中不得残留仓库默认口令的账号。

    升级自 E-8 之前的部署，数据卷里往往还有 `admin/Admin@123456`；此时容器若静默
    起来，等于把 R-ADMIN 挂在公开口令上。这里 fail-closed，并给出一次性修法。
    """
    from django.conf import settings as dj_settings
    from django.db import DatabaseError, OperationalError, ProgrammingError

    if getattr(dj_settings, "DEBUG", False):
        return
    try:
        hits = find_default_credential_accounts()
    except (OperationalError, ProgrammingError, DatabaseError):
        return  # 表尚未创建（首次 migrate 之前）：交给 migrate 之后的下一次启动
    if hits:
        names = "、".join(hits)
        raise ImproperlyConfigured(
            f"检测到仍在使用仓库默认口令的账号：{names}。这些口令是公开的，等同没有口令。\n"
            "请先执行一次性修复（轮换为强口令）再启动：\n"
            "  python manage.py rotate_demo_credentials --password '<新强口令>'\n"
            "或直接删除演示库/清空数据卷重新初始化。"
        )
