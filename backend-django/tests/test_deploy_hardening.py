"""部署收口（E-8）：默认启动不带人造凭据、不自动灌演示数据、不暴露排障面。"""
from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_runtime_secret_check_requires_strong_value(monkeypatch, settings):
    """判据是**生效值**而非 env 是否存在：默认值/过短拒绝，32 字符以上通过。

    r4-I3：上一版要求「必须显式设置 ARK_JWT_SECRET」，会误杀
    `from .prod import *` 且用别的密钥源（Vault/自定义 env 名）覆盖
    `settings.JWT_SECRET` 的合法部署。现在只看最终生效值。
    """
    from core.startup import validate_runtime_secrets

    settings.DEBUG = False
    monkeypatch.delenv("ARK_JWT_SECRET", raising=False)

    settings.JWT_SECRET = "dev-secret-change-me-please-use-32-bytes-min!"
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    settings.JWT_SECRET = "short"
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    settings.JWT_SECRET = ""
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    settings.JWT_SECRET = "Z" * 32
    validate_runtime_secrets()  # 通过，不抛（即使 env 没设）


def test_secret_check_reads_effective_setting_not_env(monkeypatch, settings):
    """r2-② 回归：自定义 settings 覆盖 settings.JWT_SECRET（env 看起来合规）也必须被拦。"""
    from core.startup import validate_runtime_secrets

    settings.DEBUG = False
    monkeypatch.setenv("ARK_JWT_SECRET", "Z" * 40)  # env 合规
    settings.JWT_SECRET = "short"                   # 但真正签名用的是它
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()


def test_secret_check_ignores_settings_module_name(monkeypatch, settings):
    """I-1 回归：判据是运行期 DEBUG，不是 settings 模块名。

    部署方常用 `config/settings/prod_site.py` 之类 `from .prod import *` 的自定义模块；
    只要它是生产形态（DEBUG=False），自检就必须生效——即使当前
    `DJANGO_SETTINGS_MODULE` 指向别的模块（测试进程里是 config.settings.test）。
    """
    import os

    from core.startup import validate_runtime_secrets

    assert os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings.test"
    settings.DEBUG = False
    monkeypatch.delenv("ARK_JWT_SECRET", raising=False)
    settings.JWT_SECRET = "dev-secret-change-me-please-use-32-bytes-min!"
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    settings.JWT_SECRET = "Z" * 32
    validate_runtime_secrets()

    settings.DEBUG = True  # dev 形态放行（连弱值也不管，只在非 DEBUG 生效）
    settings.JWT_SECRET = "short"
    validate_runtime_secrets()


def test_prod_settings_module_defers_secret_check_to_runtime(monkeypatch, settings):
    """r4-C2 的取舍：prod **不在 import 期**校验密钥。

    import 期拿不到「最终生效」的 settings（自定义 `from .prod import *` 可能用
    别的密钥源覆盖 `JWT_SECRET`），在 import 期校验会误杀合法部署；因此改由
    `core.apps.ready()`（每个 Django 进程都会执行）在运行期校验生效值。
    """
    import importlib
    import sys

    import config.settings.base as base

    from core.startup import validate_runtime_secrets

    monkeypatch.setenv("ARK_JWT_SECRET", "short")
    monkeypatch.setattr(base, "JWT_SECRET", "short")
    sys.modules.pop("config.settings.prod", None)
    prod = importlib.import_module("config.settings.prod")  # import 通过
    assert prod.DEBUG is False
    sys.modules.pop("config.settings.prod", None)

    settings.DEBUG = False
    settings.JWT_SECRET = "short"
    with pytest.raises(ImproperlyConfigured):  # 运行期必拒
        validate_runtime_secrets()


def test_prod_settings_defers_missing_env_to_runtime(monkeypatch, settings):
    """I-R3-5：没给 env 时 prod 可以 import（允许自定义 settings 自定密钥源），
    但运行期自检必须拒绝最终生效的弱值。"""
    import importlib
    import sys

    import config.settings.base as base

    from core.startup import validate_runtime_secrets

    monkeypatch.delenv("ARK_JWT_SECRET", raising=False)
    monkeypatch.setattr(base, "JWT_SECRET", "dev-secret-change-me-please-use-32-bytes-min!")
    sys.modules.pop("config.settings.prod", None)
    prod = importlib.import_module("config.settings.prod")
    assert prod.DEBUG is False
    sys.modules.pop("config.settings.prod", None)

    settings.DEBUG = False
    settings.JWT_SECRET = "short"
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()


def _seed(*args, **kwargs):
    from django.core.management import call_command

    return call_command("seed_demo", *args, **kwargs)


def test_seed_demo_blocked_without_optin(monkeypatch, settings):
    """容器/生产形态默认不播种：没有开关就 CommandError，绝不静默建演示账号。"""
    from django.core.management.base import CommandError

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.delenv("ARK_SEED_DEMO", raising=False)
    with pytest.raises(CommandError, match="默认不播种"):
        _seed(verbosity=0)


def test_seed_demo_requires_env_password_outside_dev(monkeypatch, settings):
    """即便显式开了播种，非开发形态也必须给口令——内置口令不许进生产。"""
    from django.core.management.base import CommandError

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.setenv("ARK_SEED_DEMO", "1")
    monkeypatch.delenv("ARK_SEED_PASSWORD", raising=False)
    with pytest.raises(CommandError, match="ARK_SEED_PASSWORD"):
        _seed(verbosity=0)


@pytest.mark.django_db
def test_seed_demo_uses_env_password(monkeypatch, settings):
    """给了 ARK_SEED_PASSWORD，则所有演示账号用它——库里不应出现 admin/Admin@123456。"""
    import bcrypt
    from apps.sysadmin.models import SysUser

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.setenv("ARK_SEED_DEMO", "1")
    monkeypatch.setenv("ARK_SEED_PASSWORD", "Str0ng-Demo-Passw0rd!")
    _seed(verbosity=0)

    admin = SysUser.objects.get(tenant_id=1, username="admin")
    assert bcrypt.checkpw(b"Str0ng-Demo-Passw0rd!", admin.password_hash.encode())
    assert not bcrypt.checkpw(b"Admin@123456", admin.password_hash.encode())


def test_docs_default_off_in_non_debug(monkeypatch, settings):
    """自省文档默认关：生产（DEBUG=False）不设变量就没有 /docs 与 /openapi.json。"""
    from core import ninja as core_ninja

    settings.DEBUG = False
    monkeypatch.delenv("ARK_API_DOCS", raising=False)
    assert core_ninja.docs_enabled() is False

    monkeypatch.setenv("ARK_API_DOCS", "1")
    assert core_ninja.docs_enabled() is True  # 内网排障显式开


def test_docs_can_be_forced_off_in_debug(monkeypatch, settings):
    settings.DEBUG = True
    monkeypatch.setenv("ARK_API_DOCS", "0")
    from core import ninja as core_ninja

    assert core_ninja.docs_enabled() is False


@pytest.mark.django_db
def test_seed_rotates_existing_default_password(monkeypatch, settings):
    """C-2 回归：先按旧默认口令建出 admin（模拟升级前的环境），再以 ARK_SEED_PASSWORD
    播种——旧口令必须立刻失效，否则「默认口令」等于永久后门。"""
    import bcrypt
    from apps.sysadmin.models import SysUser

    SysUser.objects.create(
        tenant_id=1,
        username="admin",
        real_name="系统管理员",
        status="ACTIVE",
        password_hash=bcrypt.hashpw(b"Admin@123456", bcrypt.gensalt()).decode(),
        creator_id=1,
    )

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.setenv("ARK_SEED_DEMO", "1")
    monkeypatch.setenv("ARK_SEED_PASSWORD", "R0tated-Str0ng-Pass!")
    _seed(verbosity=0)

    admin = SysUser.objects.get(tenant_id=1, username="admin")
    assert bcrypt.checkpw(b"R0tated-Str0ng-Pass!", admin.password_hash.encode())
    assert not bcrypt.checkpw(b"Admin@123456", admin.password_hash.encode())


@pytest.mark.django_db
def test_seed_rotates_partner_and_expert_accounts(monkeypatch, settings):
    """外部机构与外部专家账号同样走轮换——它们也是固定演示口令。"""
    import bcrypt
    from apps.sysadmin.models import SysUser

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.setenv("ARK_SEED_DEMO", "1")
    monkeypatch.setenv("ARK_SEED_PASSWORD", "Ext-0nly-Passw0rd!")
    _seed(verbosity=0)
    _seed(verbosity=0)  # 第二遍幂等：仍是同一口令，不重复写

    for username, old in (("partner", "Partner@123456"), ("expert_ext", "Expert@123456")):
        u = SysUser.objects.get(tenant_id=1, username=username)
        assert bcrypt.checkpw(b"Ext-0nly-Passw0rd!", u.password_hash.encode()), username
        assert not bcrypt.checkpw(old.encode(), u.password_hash.encode()), username


def test_empty_env_password_is_treated_as_absent(monkeypatch, settings):
    """compose 传入空串（`${ARK_SEED_PASSWORD:-}`）时等价于没给口令 → 必须拒绝播种。"""
    from django.core.management.base import CommandError

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.setenv("ARK_SEED_DEMO", "1")
    monkeypatch.setenv("ARK_SEED_PASSWORD", "")
    with pytest.raises(CommandError, match="ARK_SEED_PASSWORD"):
        _seed(verbosity=0)


# —— r2-①：旧数据卷残留公开默认口令 → 生产拒绝启动，轮换命令可恢复 ——

def _make_admin_with(password: str):
    import bcrypt

    from apps.sysadmin.models import SysUser

    user, _ = SysUser.objects.get_or_create(
        tenant_id=1, username="admin",
        defaults={"real_name": "管理员", "status": "ACTIVE", "creator_id": 1,
                  "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()},
    )
    return user


@pytest.mark.django_db
def test_default_credentials_block_production_start(settings):
    from core.startup import assert_no_default_credentials

    _make_admin_with("Admin@123456")
    settings.DEBUG = False
    with pytest.raises(ImproperlyConfigured) as e:
        assert_no_default_credentials()
    assert "admin" in str(e.value)

    settings.DEBUG = True  # dev 形态不拦（本地演示需要默认口令）
    assert_no_default_credentials()


@pytest.mark.django_db
def test_rotate_command_clears_defaults_and_unblocks_start(settings):
    import bcrypt
    from django.core.management import call_command

    from core.startup import assert_no_default_credentials

    user = _make_admin_with("Admin@123456")
    settings.DEBUG = False

    call_command("rotate_demo_credentials", "--password", "Fresh-Str0ng-Pass!")
    user.refresh_from_db()
    assert bcrypt.checkpw(b"Fresh-Str0ng-Pass!", user.password_hash.encode())
    assert not bcrypt.checkpw(b"Admin@123456", user.password_hash.encode())

    assert_no_default_credentials()  # 不再拦


@pytest.mark.django_db
def test_rotate_command_skips_real_password(settings):
    """只动「确实等于默认口令」的账号，真实用户不受影响。"""
    import bcrypt
    from django.core.management import call_command

    user = _make_admin_with("Real-User-Pass!2026")
    before = user.password_hash
    call_command("rotate_demo_credentials", "--password", "Fresh-Str0ng-Pass!")
    user.refresh_from_db()
    assert user.password_hash == before


# —— r3：门禁 fail-closed / 跨租户 / 禁用账号 / 轮换完整性 ——

@pytest.mark.django_db
def test_gate_is_cross_tenant(settings):
    """I-R3-1：其他租户的默认口令账号同样拦截。"""
    import bcrypt

    from apps.sysadmin.models import SysUser
    from core.startup import assert_no_default_credentials, find_default_credential_accounts

    SysUser.objects.create(
        tenant_id=2, username="admin", real_name="租户2管理员", status="ACTIVE", creator_id=1,
        password_hash=bcrypt.hashpw(b"Admin@123456", bcrypt.gensalt()).decode(),
    )
    settings.DEBUG = False
    assert "admin" in find_default_credential_accounts()
    with pytest.raises(ImproperlyConfigured):
        assert_no_default_credentials()


@pytest.mark.django_db
def test_gate_ignores_non_active_accounts(settings):
    """I-R3-3：停用/锁定账号登录会被 403 拒掉，不该阻断启动。"""
    import bcrypt

    from apps.sysadmin.models import SysUser
    from core.startup import assert_no_default_credentials, find_default_credential_accounts

    SysUser.objects.create(
        tenant_id=1, username="admin", real_name="已停用", status="DISABLED", creator_id=1,
        password_hash=bcrypt.hashpw(b"Admin@123456", bcrypt.gensalt()).decode(),
    )
    settings.DEBUG = False
    assert find_default_credential_accounts() == []
    assert_no_default_credentials()  # 放行


@pytest.mark.django_db
def test_gate_fails_closed_when_db_unreachable(settings, monkeypatch):
    """C-R3-1：连不上库时不能当作「没有默认口令」放行。"""
    from django.db import OperationalError

    from core import startup

    settings.DEBUG = False
    monkeypatch.setattr(startup, "_account_table_ready", lambda: None)
    with pytest.raises(ImproperlyConfigured):
        startup.assert_no_default_credentials(attempts=1, delay=0)


@pytest.mark.django_db
def test_gate_allows_when_table_missing(settings, monkeypatch):
    """首次 migrate 之前（表还没建）放行。"""
    from core import startup

    settings.DEBUG = False
    monkeypatch.setattr(startup, "_account_table_ready", lambda: False)
    startup.assert_no_default_credentials(attempts=1, delay=0)


@pytest.mark.django_db
def test_rotate_rejects_fallback_default_password(settings):
    """I-R3-2：`Demo@123456` 也是默认口令，不能用来「修好」。"""
    from django.core.management.base import CommandError
    from django.core.management import call_command

    _make_admin_with("Admin@123456")
    with pytest.raises(CommandError):
        call_command("rotate_demo_credentials", "--password", "Demo@123456")


@pytest.mark.django_db
def test_rotate_reports_remaining_accounts(monkeypatch, settings):
    """轮换后自检：若仍有默认口令账号（例如 hash 异常未命中），命令必须报错而不是报成功。"""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.sysadmin.management.commands import rotate_demo_credentials as cmd

    _make_admin_with("Admin@123456")
    monkeypatch.setattr(cmd, "find_default_credential_accounts", lambda active_only=True: ["admin"])
    with pytest.raises(CommandError):
        call_command("rotate_demo_credentials", "--password", "Fresh-Str0ng-Pass!")


# —— r4 回归（seed 口令强度 / 进程级守卫 / 部分 schema fail-closed）——

def test_seed_demo_rejects_builtin_default_password(monkeypatch, settings):
    """r4-C1：`ARK_SEED_PASSWORD=Demo@123456` 也能造出公开 R-ADMIN，必须拒绝。"""
    from django.core.management.base import CommandError

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.setenv("ARK_SEED_DEMO", "1")
    legend = ("Demo@123456", "Admin@123456", "Partner@123456")
    for pwd in legend:
        monkeypatch.setenv("ARK_SEED_PASSWORD", pwd)
        with pytest.raises(CommandError):
            _seed()


def test_seed_demo_rejects_short_password(monkeypatch, settings):
    from django.core.management.base import CommandError

    settings.ALLOW_DEMO_SEED = False
    monkeypatch.setenv("ARK_SEED_DEMO", "1")
    monkeypatch.setenv("ARK_SEED_PASSWORD", "Ab1!x")  # 5 位
    with pytest.raises(CommandError):
        _seed()


@pytest.mark.django_db
def test_process_guard_blocks_non_exempt_command(settings, monkeypatch):
    """r4-C2：`django-admin` / worker / 其它进程也要被拦，不只 wsgi/asgi。

    守卫挂在 `core.apps.ready()`，用 `manage.py <cmd>` 模拟「非豁免命令」。
    """
    from core import startup

    settings.DEBUG = False
    settings.JWT_SECRET = "Z" * 40
    _make_admin_with("Admin@123456")
    monkeypatch.setattr(startup, "_current_management_command", lambda: "runserver", raising=False)
    with pytest.raises(ImproperlyConfigured):
        startup.enforce_process_guard()


@pytest.mark.django_db
def test_process_guard_exempts_remediation_commands(settings, monkeypatch):
    """修复类命令不能被自己的守卫挡住（否则永远无法自愈）。"""
    from core import startup

    settings.DEBUG = False
    settings.JWT_SECRET = "Z" * 40
    _make_admin_with("Admin@123456")
    for cmd in ("migrate", "rotate_demo_credentials", "seed_demo", "test"):
        monkeypatch.setattr(startup, "_current_management_command", lambda c=cmd: c, raising=False)
        startup.enforce_process_guard()  # 不抛


@pytest.mark.django_db
def test_gate_fails_closed_when_schema_is_partial(settings, monkeypatch):
    """r4-I1：库里有别的表但没有 sys_user（权限只暴露部分表/残缺 schema）→ 不能放行。"""
    from core import startup

    settings.DEBUG = False
    monkeypatch.setattr(startup, "_account_table_ready", lambda: None)
    with pytest.raises(ImproperlyConfigured):
        startup.assert_no_default_credentials(attempts=1, delay=0)


def test_account_table_ready_treats_partial_schema_as_unknown(settings, monkeypatch):
    """三态判定本身：有表但无 sys_user → None（未知，fail-closed）。"""
    from django.db import connection

    from core import startup

    monkeypatch.setattr(
        connection.introspection, "table_names", lambda *a, **k: ["other_table"]
    )
    assert startup._account_table_ready() is None
    monkeypatch.setattr(connection.introspection, "table_names", lambda *a, **k: [])
    assert startup._account_table_ready() is False
    monkeypatch.setattr(
        connection.introspection, "table_names", lambda *a, **k: ["sys_user"]
    )
    assert startup._account_table_ready() is True


# —— r5 回归（manage 命令也要拦 / 测试配置不可部署）——

@pytest.mark.django_db
def test_manage_command_gate_blocks_check_on_default_credentials(settings, monkeypatch):
    """r5-C1：`manage.py check` 在旧库上不能 exit 0——运维必须看到「库里有默认口令」。"""
    from core import startup

    settings.DEBUG = False
    settings.JWT_SECRET = "Z" * 40
    _make_admin_with("Admin@123456")
    monkeypatch.setattr(startup, "_current_management_command", lambda: "check", raising=False)
    with pytest.raises(ImproperlyConfigured):
        startup.enforce_process_guard()


@pytest.mark.django_db
def test_manage_command_gate_still_allows_remediation(settings, monkeypatch):
    """修复命令不被拦（否则 `manage.py rotate_demo_credentials` 永远跑不起来）。"""
    from core import startup

    settings.DEBUG = False
    settings.JWT_SECRET = "Z" * 40
    _make_admin_with("Admin@123456")
    monkeypatch.setattr(
        startup, "_current_management_command", lambda: "rotate_demo_credentials", raising=False
    )
    startup.enforce_process_guard()


def test_test_settings_module_is_not_deployable(settings, monkeypatch):
    """r5-I2：`config.settings.test` 带内置密钥与播种开关，不能被当成部署配置。"""
    from core import startup

    settings.DEBUG = False
    settings.JWT_SECRET = "Z" * 40
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.test")
    monkeypatch.setattr(startup, "running_under_tests", lambda: False, raising=False)
    with pytest.raises(ImproperlyConfigured):
        startup.validate_runtime_secrets()

    # pytest 进程里放行（否则套件自身无法启动）
    monkeypatch.setattr(startup, "running_under_tests", lambda: True, raising=False)
    startup.validate_runtime_secrets()


def test_demo_seed_switch_ignored_outside_debug_and_tests(settings, monkeypatch):
    """r5-I2：`ALLOW_DEMO_SEED` 只在 DEBUG/测试进程生效，避免「一份配置到处播种」。"""
    from django.core.management.base import CommandError

    from core import startup

    settings.ALLOW_DEMO_SEED = True
    settings.DEBUG = False
    settings.JWT_SECRET = "Z" * 40
    monkeypatch.delenv("ARK_SEED_DEMO", raising=False)
    monkeypatch.delenv("ARK_SEED_PASSWORD", raising=False)
    monkeypatch.setattr(startup, "running_under_tests", lambda: False, raising=False)
    with pytest.raises(CommandError):  # 视为未授权播种
        _seed()
