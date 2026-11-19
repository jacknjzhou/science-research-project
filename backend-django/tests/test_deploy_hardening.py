"""部署收口（E-8）：默认启动不带人造凭据、不自动灌演示数据、不暴露排障面。"""
from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_prod_requires_strong_jwt_secret(monkeypatch):
    from config.settings import prod

    monkeypatch.delenv("ARK_JWT_SECRET", raising=False)
    with pytest.raises(ImproperlyConfigured):
        prod.validate_prod_secrets()

    monkeypatch.setenv("ARK_JWT_SECRET", "dev-secret-change-me-please-use-32-bytes-min!")
    with pytest.raises(ImproperlyConfigured):
        prod.validate_prod_secrets()

    monkeypatch.setenv("ARK_JWT_SECRET", "short")
    with pytest.raises(ImproperlyConfigured):
        prod.validate_prod_secrets()

    monkeypatch.setenv("ARK_JWT_SECRET", "Z" * 32)
    prod.validate_prod_secrets()  # 通过，不抛


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
