"""申报域 P API 形状（对齐 Go p/mapper.go）。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.p.models import PApplication, PGuideline
from apps.sysadmin.mappings import fmt_ts


def num2(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return f"{float(v):.2f}"


def to_api_guideline(g: PGuideline) -> dict[str, Any]:
    return {
        "id": g.id,
        "code": g.code,
        "status": g.status,
        "modifier_id": g.modifier_id,
        "created_at": fmt_ts(g.created_at),
        "updated_at": fmt_ts(g.updated_at),
        "remark": g.remark,
        "apply_start_at": fmt_ts(g.apply_start_at),
        "apply_end_at": fmt_ts(g.apply_end_at),
        "publish_at": fmt_ts(g.publish_at),
        "funding_source": g.funding_source,
        "target_disciplines": g.target_disciplines or [],
        "total_envelope": num2(g.total_envelope),
        "content_rich": g.content_rich,
        "attachment_ids": g.attachment_ids or [],
        "title": g.title,
        "project_type": g.project_type,
    }


def to_api_application(a: PApplication) -> dict[str, Any]:
    return {
        "id": a.id,
        "tenant_id": a.tenant_id,
        "status": a.status,
        "deleted": a.deleted,
        "creator_id": a.creator_id,
        "title": a.title,
        "project_type": a.project_type,
        "pi_user_id": a.pi_user_id,
        "member_ids": a.member_ids or [],
        "is_horizontal": a.is_horizontal,
        "ai_draft_marked": a.ai_draft_marked,
        "total_budget": num2(a.total_budget),
        "code": a.code,
        "remark": a.remark,
        "abstract": a.abstract,
        "funding_channel": a.funding_channel,
        "duration_months": a.duration_months,
        "submit_at": fmt_ts(a.submit_at),
        "withdraw_at": fmt_ts(a.withdraw_at),
        "withdraw_reason": a.withdraw_reason,
        "created_at": fmt_ts(a.created_at),
        "updated_at": fmt_ts(a.updated_at),
    }
