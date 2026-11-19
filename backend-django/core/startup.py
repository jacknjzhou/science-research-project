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


def running_under_tests() -> bool:
    """当前进程是不是测试进程（pytest / manage.py test）。

    只用来判断「测试专用配置能否生效」，不用于放宽任何生产检查。
    """
    import sys

    if "pytest" in sys.modules:
        return True
    return _current_management_command() == "test"


def _assert_settings_module_deployable() -> None:
    """`config.settings.test` / `.dev` 不是部署形态，误用即拒绝服务。

    这两份配置带着仓库内置的密钥与「允许播种演示账号」开关；一旦被当成生产
    settings 用（`DJANGO_SETTINGS_MODULE=config.settings.test gunicorn …`），
    守卫看到的一切都是「合规」的，攻击面却是公开的。因此在服务进程里直接拒绝。
    """
    import os

    from django.conf import settings as dj_settings

    if running_under_tests():
        return

    # 判据一：settings 里带 `IS_TEST_SETTINGS` 标记。用模块名判断会被
    # `from config.settings.test import *` 这种别名绕过（r6-C2），而 `import *`
    # 会把普通模块级变量一起复制过来，所以标记比模块名可靠。
    if getattr(dj_settings, "IS_TEST_SETTINGS", False):
        raise ImproperlyConfigured(
            "这份 settings 是测试配置（IS_TEST_SETTINGS），不能作为部署配置。"
            "请使用 config.settings.prod（或你自己的生产 settings）。"
        )

    module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    if module == "config.settings.test":
        raise ImproperlyConfigured(
            "config.settings.test 仅供 pytest 使用，不能作为部署配置。"
            "请使用 config.settings.prod（或你自己的生产 settings）。"
        )


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

    _assert_settings_module_deployable()

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
# 升级自 E-8 之前的库可能仍带这些口令；生产启动逐一探测，命中即拒绝服务。
DEFAULT_SEED_PASSWORDS: tuple[str, ...] = (
    "Admin@123456",
    "Manager@123456",
    "Staff@123456",
    "Finance@123456",
    "Partner@123456",
    "Expert@123456",
    "Demo@123456",
)
KNOWN_DEFAULT_PASSWORDS = {
    "admin": ("Admin@123456",),
    "manager": ("Manager@123456",),
    "staff": ("Staff@123456",),
    "finance": ("Finance@123456",),
    "partner": ("Partner@123456",),
    "expert_ext": ("Expert@123456",),
}
# 上一版 compose 用同一个默认口令播全部演示账号
FALLBACK_DEFAULT_PASSWORDS = ("Demo@123456",)

# 单账号最多试几个候选口令（自身默认 + 兜底），控制启动期 bcrypt 开销
_MAX_CANDIDATES = 2


def _known_defaults_for(username: str) -> tuple[str, ...]:
    own = KNOWN_DEFAULT_PASSWORDS.get(username, ())
    return (own + FALLBACK_DEFAULT_PASSWORDS)[:_MAX_CANDIDATES]


def _matches_default(password_hash: str, username: str) -> bool:
    import bcrypt

    hashed = password_hash.encode()
    for pwd in _known_defaults_for(username):
        try:
            if bcrypt.checkpw(pwd.encode(), hashed):
                return True
        except ValueError:  # 非法 hash → 交给业务层
            return False
    return False


def find_default_credential_accounts(*, active_only: bool = True) -> list[str]:
    """返回仍在用仓库默认口令的账号（跨全部租户，只探测已知演示用户名）。

    `active_only=True` 只看能真正登录的账号（状态 ACTIVE）——锁定/停用账号登录会被
    403 拒掉，不该阻断启动；但 `rotate_demo_credentials` 会连这些账号一起轮换。
    """
    from apps.sysadmin.models import SysUser

    qs = SysUser.objects.filter(username__in=list(KNOWN_DEFAULT_PASSWORDS), deleted=0)
    if active_only:
        qs = qs.filter(status="ACTIVE")
    hits: list[str] = []
    for username, password_hash in qs.values_list("username", "password_hash").iterator():
        if not password_hash:
            continue
        if _matches_default(str(password_hash), username) and username not in hits:
            hits.append(username)
    return hits


def _account_table_ready() -> bool | None:
    """`True`=可以扫描、`False`=空库（首次 migrate 前）、`None`=状态未知（fail-closed）。

    只有「库连得上且一张表都没有」才算首次初始化；库里有别的表却没有 `sys_user`
    （权限只暴露部分表、残缺 schema、迁移没跑全）一律按未知处理，不能静默放行。
    """
    from django.db import DatabaseError, connection

    try:
        tables = connection.introspection.table_names()
    except DatabaseError:
        return None
    if "sys_user" in tables:
        return True
    if not tables:
        return False
    return None


def assert_no_default_credentials(*, attempts: int = 5, delay: float = 2.0) -> None:
    """生产启动前：库中不得残留仓库默认口令的账号。

    升级自 E-8 之前的部署，数据卷里往往还有 `admin/Admin@123456`；此时容器若静默
    起来，等于把 R-ADMIN 挂在公开口令上。这里 fail-closed：
      · 只有「表尚未创建」才放行（首次 migrate 之前）；
      · 连不上库 / 权限错误 → 有限重试后**拒绝启动**（不能当作「没有默认口令」）。
    """
    import time

    from django.conf import settings as dj_settings
    from django.db import DatabaseError

    if getattr(dj_settings, "DEBUG", False):
        return

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        ready = _account_table_ready()
        if ready is False:
            return  # 首次 migrate 之前
        if ready is True:
            try:
                hits = find_default_credential_accounts()
            except DatabaseError as exc:  # 权限/只读副本/连接中断
                last_error = exc
            else:
                if hits:
                    names = "、".join(hits)
                    raise ImproperlyConfigured(
                        f"检测到仍在使用仓库默认口令的账号：{names}。这些口令是公开的，等同没有口令。\n"
                        "请先执行一次性修复（轮换为强口令）再启动：\n"
                        "  python manage.py rotate_demo_credentials --password '<新强口令>'\n"
                        "（容器内：docker compose run --rm --no-deps backend python manage.py "
                        "rotate_demo_credentials --password '<新强口令>'）\n"
                        "或直接删除演示库/清空数据卷重新初始化。"
                    )
                return
        else:
            last_error = last_error or RuntimeError("无法读取数据库表清单")
        if attempt < attempts:
            time.sleep(delay)

    raise ImproperlyConfigured(
        "启动自检无法确认数据库中的默认口令状态（不会在未知状态下启动）："
        f"{last_error}. 请先确保数据库可用并执行 migrate，然后重试启动。"
    )


# —— 进程级守卫：所有 Django 进程（wsgi/asgi/celery/manage/django-admin）都必须过 ——
# 这些管理命令允许在「库里有默认口令」时运行——它们正是用来修复/初始化状态的。
GUARD_EXEMPT_COMMANDS = frozenset({
    # 修复/初始化：不豁免则无法自愈
    "migrate", "makemigrations", "showmigrations",
    "rotate_demo_credentials", "seed_demo", "createsuperuser",
    # 无服务的本地调试/导出
    "test", "shell", "dbshell", "dumpdata", "loaddata", "flush", "collectstatic",
    # 纯信息输出：不该因为库有问题而看不出这是哪个版本
    "help", "version",
})


def _current_management_command() -> str | None:
    """识别「这是哪条管理命令」，仅用于判断豁免。

    `python -m django <cmd>` 的 `argv[0]` 是 `.../django/__main__.py`，不是
    `manage.py`——早期版本漏了这一形态，于是 `python -m django migrate` 被当成
    「未知命令」走完整守卫，恢复库时会被自己的门禁挡住。
    """
    import sys

    argv = list(getattr(sys, "argv", []))
    if len(argv) < 2:
        return None
    entry = os.path.basename(argv[0])
    is_entry = entry.startswith(("manage.py", "django-admin")) or (
        entry == "__main__.py" and f"{os.sep}django{os.sep}" in argv[0]
    )
    if is_entry:
        return argv[1].split(":")[0]
    return None


def enforce_process_guard() -> None:
    """非 DEBUG 形态下，任何 Django 进程启动都要过两道关：

    1. JWT 密钥强度（校验**最终生效**的 `settings.JWT_SECRET`，不限定来自哪个
       环境变量——自定义 settings 用自己的密钥源同样受检）；
    2. 库中不得残留公开默认口令账号；但初始化/修复类管理命令除外（否则无法自愈）。
    """
    from django.conf import settings as dj_settings

    if getattr(dj_settings, "DEBUG", False):
        return
    validate_runtime_secrets()
    if running_under_tests():
        return
    if _current_management_command() in GUARD_EXEMPT_COMMANDS:
        return
    assert_no_default_credentials()


def enforce_serving_guard() -> None:
    """服务进程（wsgi/asgi）启动时：密钥 + 默认口令双检，任一不过就拒绝启动。"""
    validate_runtime_secrets()
    assert_no_default_credentials()
