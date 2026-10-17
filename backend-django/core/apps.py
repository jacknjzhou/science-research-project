"""core 作为 Django app：承载跨域平台模型（审批流水等）。"""
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    label = "core"
