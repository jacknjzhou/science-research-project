"""对象存储底座（对齐 Go platform/storage MinIO 封装）。

本地后端兜底：未配置 MINIO_ENDPOINT 时写 BASE_DIR/storage/（开发/测试可用）；
配置 MinIO 后走 minio SDK（依赖 minio 包，懒加载）。
"""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings


def is_configured() -> bool:
    """MinIO 是否已配置（未配置时走本地后端，仍可上传/下载/四性检测）。"""
    return bool(os.environ.get("MINIO_ENDPOINT"))


def default_bucket() -> str:
    return os.environ.get("MINIO_BUCKET", "ark-docs")


def put(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    if is_configured():
        from minio import Minio  # noqa: 懒加载，未装包且未配置时不可达
        import io
        client = _client()
        client.put_object(default_bucket(), object_key, io.BytesIO(data), len(data),
                          content_type=content_type)
        return
    p = _local_path(object_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def get(object_key: str) -> bytes:
    if is_configured():
        from minio import Minio
        client = _client()
        resp = client.get_object(default_bucket(), object_key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
    return _local_path(object_key).read_bytes()


def remove(object_key: str) -> None:
    if is_configured():
        from minio import Minio
        _client().remove_object(default_bucket(), object_key)
        return
    p = _local_path(object_key)
    if p.exists():
        p.unlink()


def _client():
    from minio import Minio
    endpoint = os.environ["MINIO_ENDPOINT"]
    return Minio(endpoint,
                 access_key=os.environ.get("MINIO_ACCESS_KEY", ""),
                 secret_key=os.environ.get("MINIO_SECRET_KEY", ""),
                 secure=os.environ.get("MINIO_SECURE", "false").lower() == "true")


def _local_path(object_key: str) -> Path:
    base = Path(getattr(settings, "ARK_STORAGE_DIR",
                        Path(settings.BASE_DIR) / "storage"))
    return base / object_key
