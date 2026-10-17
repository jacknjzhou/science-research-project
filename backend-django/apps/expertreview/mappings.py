"""专家评审域 N 契约映射（对齐 Go expertreview/mapper.go）。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone as dj_tz

from apps.expertreview.models import NExpert, NReviewInvitation, NReviewScore, NReviewTask


def num2(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return f"{Decimal(str(v)):.2f}"


def fmt_ts(t):
    if t is None:
        return None
    return dj_tz.localtime(t).isoformat()


def to_api_expert(r: NExpert) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "name": r.name, "gender": r.gender, "title": r.title,
        "org_name": r.org_name, "user_id": r.user_id, "source": r.source,
        "field_tags": r.field_tags or [], "expertise_level": r.expertise_level,
        "avoid_orgs": r.avoid_orgs or [], "avoid_person_ids": r.avoid_person_ids or [],
        "security_level": r.security_level,
        "last_review_at": fmt_ts(r.last_review_at), "review_count": r.review_count,
        "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
    }


def to_api_review_task(r: NReviewTask) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "biz_type": r.biz_type,
        "target_type": r.target_type, "target_id": r.target_id, "project_id": r.project_id,
        "title": r.title, "review_method": r.review_method, "plan_count": r.plan_count,
        "draw_rule": r.draw_rule or {}, "status": r.status,
        "conclusion": r.conclusion, "score_summary": r.score_summary,
        "security_level": r.security_level,
        "drawn_at": fmt_ts(r.drawn_at), "started_at": fmt_ts(r.started_at),
        "concluded_at": fmt_ts(r.concluded_at),
        "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
    }


def to_api_invitation(r: NReviewInvitation, expert_name: str | None = None) -> dict[str, Any]:
    return {
        "id": r.id, "task_id": r.task_id, "expert_id": r.expert_id,
        "expert_name": expert_name, "seat_no": r.seat_no,
        "avoid_hit": r.avoid_hit, "response": r.response,
    }


def to_api_score(r: NReviewScore) -> dict[str, Any]:
    return {
        "id": r.id, "task_id": r.task_id, "expert_id": r.expert_id,
        "target_type": r.target_type, "target_id": r.target_id,
        "dimension_scores": r.dimension_scores or [],
        "total_score": num2(r.total_score), "comment": r.comment, "status": r.status,
    }
