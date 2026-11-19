"""部署收口（E-8）：默认启动不带人造凭据、不自动灌演示数据、不暴露排障面。"""
from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_runtime_secret_check_requires_strong_value(monkeypatch, settings):
    """四段：缺 env、仍是仓库默认值、过短 → 拒绝；32 字符以上 → 通过。"""
    from core.startup import validate_runtime_secrets

    settings.DEBUG = False
    monkeypatch.delenv("ARK_JWT_SECRET", raising=False)
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    monkeypatch.setenv("ARK_JWT_SECRET", "dev-secret-change-me-please-use-32-bytes-min!")
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    monkeypatch.setenv("ARK_JWT_SECRET", "short")
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    monkeypatch.setenv("ARK_JWT_SECRET", "Z" * 32)
    validate_runtime_secrets()  # 通过，不抛


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
    with pytest.raises(ImproperlyConfigured):
        validate_runtime_secrets()

    settings.DEBUG = True  # dev 形态放行
    validate_runtime_secrets()


def test_prod_settings_module_refuses_to_import_without_secret(monkeypatch):
    """选中 prod 配置即在 import 期失败（gunicorn bind 之前）。"""
    import importlib
    import sys

    monkeypatch.delenv("ARK_JWT_SECRET", raising=False)
    sys.modules.pop("config.settings.prod", None)
    with pytest.raises(ImproperlyConfigured):
        importlib.import_module("config.settings.prod")
    sys.modules.pop("config.settings.prod", None)


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
