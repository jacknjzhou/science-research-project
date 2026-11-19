from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    label = "core"

    def ready(self) -> None:
        """E-8：每个 Django 进程在**配置已确定之后**过同一套启动守卫。

        为什么放在这里，而不是 `manage.py`：
        `manage.py` 里的自检必须在 `django.setup()` 之前跑，那时 `--settings` /
        `--pythonpath` 还没被解析，于是 `manage.py runserver --settings=prod` 会先用
        默认 dev 配置初始化一次，再被静默降级——守卫看起来在，实际没生效（r6-C1）。
        `ready()` 由 Django 在 settings 解析完成后调用，wsgi/asgi/celery/manage/
        django-admin 全覆盖，且此时 `sys.argv` 里已经有子命令，可以判断豁免。

        这里会查库（扫描默认口令账号），因此局部屏蔽 Django 的
        "Accessing the database during app initialization" 告警——这是有意为之的
        启动期检查，不是顺手查询。
        """
        import warnings

        from core.startup import enforce_process_guard

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Accessing the database during app initialization.*",
                category=RuntimeWarning,
            )
            enforce_process_guard()
