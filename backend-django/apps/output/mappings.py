"""成果域 R 契约映射（对齐 Go output/mapper.go）。

match_confidence 契约声明为 number → float 输出；其余 NUMERIC 定标字符串。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone as dj_tz

from apps.output.models import RClaimRecord, ROutput


def num2(v) -> str:
    if v is None:
        return "0"
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return f"{Decimal(str(v)):.2f}"


def num_float(v):
    """NUMERIC → float（契约 number 字段：match_confidence/contribution_pct）。"""
    if v is None:
        return None
    return float(v)


def fmt_ts(t):
    if t is None:
        return None
    return dj_tz.localtime(t).isoformat()


def fmt_date(d):
    if d is None:
        return None
    return f"{d:%Y-%m-%d}"


def to_api_output(r: ROutput) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "tenant_id": r.tenant_id,
        "status": r.status,
        "output_type": r.output_type,
        "title": r.title,
        "title_en": r.title_en,
        "abstract": r.abstract,
        "publish_date": fmt_date(r.publish_date),
        "authors": r.authors or [],
        "external_author_names": r.external_author_names or [],
        "affiliations": r.affiliations or [],
        "project_ids": r.project_ids or [],
        "language": r.language,
        "source": r.source,
        "is_claimed": r.is_claimed,
        "claim_status": r.claim_status,
        "match_confidence": num_float(r.match_confidence),
        "department_id": r.department_id,
        "legal_entity_id": r.legal_entity_id,
        "security_level": r.security_level,
        "created_at": fmt_ts(r.created_at),
        "updated_at": fmt_ts(r.updated_at),
        "remark": r.remark,
    }


def to_api_claim_record(r: RClaimRecord) -> dict[str, Any]:
    return {
        "id": r.id, "code": r.code, "tenant_id": r.tenant_id, "status": r.status,
        "output_id": r.output_id, "user_id": r.user_id, "action": r.action,
        "edited_fields": r.edited_fields, "reason": r.reason,
        "confidence": num_float(r.confidence),
        "action_at": fmt_ts(r.action_at), "batch_id": r.batch_id,
        "created_at": fmt_ts(r.created_at), "updated_at": fmt_ts(r.updated_at),
        "remark": r.remark,
    }
