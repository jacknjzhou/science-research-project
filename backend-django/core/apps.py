"""core 作为 Django app：承载跨域平台模型（审批流水等）。"""
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    label = "core"

    def ready(self) -> None:  # noqa: D401
        """所有 Django 进程（wsgi/asgi/celery/manage/django-admin）统一过密钥自检。

        这里**只校验密钥**（纯 settings，不查库）：`ready()` 期间访问数据库会触发
        Django 的 "Accessing the database during app initialization" 警告，且在
        `migrate` 之前数据库可能还不存在。默认口令账号的扫描放在
        `enforce_serving_guard()`（wsgi/asgi 启动时）与 `manage.py` 非豁免命令里。
        """
        from core.startup import validate_runtime_secrets

        validate_runtime_secrets()
