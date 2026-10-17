"""URL 入口：healthz（公开）+ /api/v1（ninja）。"""
from django.http import JsonResponse
from django.urls import path

from config.api import api  # noqa: F401  注册全部路由
from core.httpx import envelope_ok_data, trace_of


def healthz(request):
    from django.conf import settings

    trace = trace_of(request)
    return JsonResponse(
        envelope_ok_data(
            {"ok": True, "env": "dev" if settings.DEBUG else "prod"}, trace
        ),
        headers={"X-Trace-Id": trace},
    )


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("api/v1/", api.urls),
]
