"""安全收口期次回归（E-1..E-5）——每条用例都必须在未修复源码上失败。

约定：
- 跨租户用例显式 `bearer(uid, roles, tenant_id=2)`，默认 bearer 的 tenant_id 是 1；
- 只断言「不该发生的事没发生」，不断言内部实现细节。
"""
from __future__ import annotations

import json

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def _login(client: Client, username: str, password: str, tenant_id: int = 1):
    return client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {"username": username, "password": password, "tenant_id": tenant_id}
        ),
        content_type="application/json",
    )


# ---------------------------------------------------------------- E-3 登录后门


def test_dev_login_disabled_when_not_debug(settings, monkeypatch):
    """生产（DEBUG=False）即便设了 ARK_DEV_LOGIN=1 也不得开后门。"""
    from core.auth.api import _dev_login_enabled

    settings.DEBUG = False
    monkeypatch.setenv("ARK_DEV_LOGIN", "1")
    assert _dev_login_enabled() is False
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 401
    assert r.json()["code"] == 40102


def test_dev_login_disabled_without_env_flag(settings, monkeypatch):
    """DEBUG=True 但未显式开 ARK_DEV_LOGIN，同样不放行。"""
    from core.auth.api import _dev_login_enabled

    settings.DEBUG = True
    monkeypatch.delenv("ARK_DEV_LOGIN", raising=False)
    assert _dev_login_enabled() is False
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 401
    assert r.json()["code"] == 40102


def test_dev_login_enabled_issues_minimal_roles(settings, monkeypatch):
    """显式开关打开时，签发的角色域只含 R-STAFF（不再固定带 R-MANAGER）。"""
    from core.auth.api import _dev_login_enabled
    from core.auth.jwt_util import parse_token

    settings.DEBUG = True
    monkeypatch.setenv("ARK_DEV_LOGIN", "1")
    assert _dev_login_enabled() is True
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 200
    data = r.json()["data"]
    claims = parse_token(data["access_token"])
    roles = claims.get("roles") or []
    assert roles == ["R-STAFF"]
    assert "R-MANAGER" not in roles
