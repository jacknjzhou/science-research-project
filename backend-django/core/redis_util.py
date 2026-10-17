"""Redis 连接惰性单例；测试可注入 fakeredis（set_client）。"""
from __future__ import annotations

import threading

from django.conf import settings

_lock = threading.Lock()
_client = None  # type: ignore[var-annotated]


def get_client():
    """返回 redis 客户端；连接失败返回 None（调用方放行，对齐 Go nil 守卫）。"""
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            try:
                import redis

                host, _, port = settings.REDIS_ADDR.partition(":")
                _client = redis.Redis(
                    host=host or "127.0.0.1",
                    port=int(port or 6379),
                    socket_connect_timeout=0.5,
                    socket_timeout=1,
                )
                _client.ping()
            except Exception:
                _client = _NoneClient()
    return _client


class _NoneClient:
    """连接不可用时的空实现：所有操作静默失败。"""

    def get(self, *a, **k):
        return None

    def set(self, *a, **k):
        return None

    def delete(self, *a, **k):
        return None

    def setnx(self, *a, **k):
        return None


def set_client(client) -> None:
    """测试注入。"""
    global _client
    with _lock:
        _client = client


def reset_client() -> None:
    """测试复位。"""
    global _client
    with _lock:
        _client = None
