"""通知中心 API（对齐 Go modules/notify 端点行为）。

读路径只按 user_id 查询（读模型，写入侧已扇出）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.notify.models import SysNotification
from core.auth.deps import domain_from
from core.httpx import ApiError, CODE_BAD_REQUEST, CODE_NOT_FOUND, ok, read_json


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    def _int(name: str, default: int) -> int:
        raw = request.GET.get(name, "")
        if not raw or not raw.isdigit():
            return default
        return int(raw)

    page = max(_int("page", 1), 1)
    size = min(max(_int("size", 20), 1), 200)
    return page, size, size, (page - 1) * size


def _fmt(r: SysNotification) -> dict:
    return {
        "id": r.id,
        "typ": r.typ,
        "title": r.title,
        "content": r.content,
        "biz_ref": r.biz_ref,
        "read": r.read_at is not None,
        "read_at": r.read_at.astimezone(timezone.utc).isoformat() if r.read_at else None,
        "created_at": r.created_at.astimezone(timezone.utc).isoformat(),
    }


def list_notifications(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    typ = request.GET.get("typ")
    qs = SysNotification.objects.filter(tenant_id=d.tenant_id, user_id=d.user_id)
    if typ:
        qs = qs.filter(typ=typ)
    unread = request.GET.get("unread")
    if unread == "1":
        qs = qs.filter(read_at__isnull=True)
    total = qs.count()
    rows = qs.order_by("-created_at", "-id")[offset : offset + limit]
    return ok(request, {"list": [_fmt(r) for r in rows], "total": total, "page": page, "size": size})


def unread_count(request: HttpRequest):
    d = domain_from(request)
    n = SysNotification.objects.filter(
        tenant_id=d.tenant_id, user_id=d.user_id, read_at__isnull=True
    ).count()
    return ok(request, {"count": n})


def mark_all_read(request: HttpRequest):
    d = domain_from(request)
    n = SysNotification.objects.filter(
        tenant_id=d.tenant_id, user_id=d.user_id, read_at__isnull=True
    ).update(read_at=dj_tz.now())
    return ok(request, {"updated": n})


def mark_read(request: HttpRequest, id: int):
    d = domain_from(request)
    row = SysNotification.objects.filter(
        id=id, tenant_id=d.tenant_id, user_id=d.user_id
    ).first()
    if row is None:
        raise ApiError(404, CODE_NOT_FOUND, "通知不存在")
    if row.read_at is None:
        row.read_at = dj_tz.now()
        row.save()
    return ok(request, _fmt(row))
