"""URL 入口：healthz（公开）+ /api/v1（ninja）+ 契约 stub 兜底。"""
from django.http import JsonResponse
from django.urls import path

from config.api import api  # noqa: F401  注册全部路由
from core.httpx import envelope_ok_data, trace_of
from core.stub import stub_view


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
    # 契约 stub 兜底：命中契约但未手工实现的端点返回合规占位（X-Stub: true）
    path("api/v1/<path:rest>", stub_view, name="contract-stub"),
]
