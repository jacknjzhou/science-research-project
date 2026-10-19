"""通用两级审核服务（对齐 Go platform/approval：流水 + 规则 + 开关）。"""
from __future__ import annotations

from typing import Iterable

from django.conf import settings

from core.models import SysApprovalLog


def twostep_enabled() -> bool:
    return settings.APPROVAL_TWOSTEP


def has_role(roles: Iterable[str], want: str) -> bool:
    return want in set(roles)


def first_role_of(roles: Iterable[str]) -> str:
    roles = list(roles)
    return roles[0] if roles else ""


def log(
    tenant_id: int,
    biz_type: str,
    biz_id: int,
    step: int,
    actor_id: int,
    actor_role: str,
    action: str,
    comment: str | None = None,
) -> None:
    """审核流水（best-effort：失败不阻断业务，对齐 Go Log）。"""
    try:
        SysApprovalLog.objects.create(
            tenant_id=tenant_id, biz_type=biz_type, biz_id=biz_id,
            step=step, actor_id=actor_id, actor_role=actor_role or "",
            action=action, comment=comment,
        )
    except Exception:
        pass


def list_logs(tenant_id: int, biz_type: str, biz_id: int):
    return list(
        SysApprovalLog.objects.filter(
            tenant_id=tenant_id, biz_type=biz_type, biz_id=biz_id
        ).order_by("acted_at", "id")
    )
