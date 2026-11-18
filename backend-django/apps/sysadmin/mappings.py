"""API 形状映射（对齐 Go sysadmin/mapper.go + mapper_dict.go）。

铁律：password_hash 永不进入返回值。
时间：RFC3339（UTC，与 Go 版一致）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from apps.sysadmin.models import SysDict, SysDictItem, SysPartnerOrg, SysRole, SysUser


def fmt_ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def fmt_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


def to_api_user(u: SysUser, roles: list[str]) -> dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "real_name": u.real_name,
        "employment_status": u.employment_status,
        "security_level": u.security_level,
        "status": u.status,
        "tenant_id": u.tenant_id,
        "deleted": u.deleted,
        "creator_id": u.creator_id,
        "email": u.email,
        "phone": u.phone,
        "staff_no": u.staff_no,
        "remark": u.remark,
        "legal_entity_id": u.legal_entity_id,
        "roles": roles,
        "created_at": fmt_ts(u.created_at),
        "updated_at": fmt_ts(u.updated_at),
    }


def to_api_role(r: SysRole) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "name": r.name,
        "is_builtin": r.is_builtin,
        "tenant_id": r.tenant_id,
        "created_at": fmt_ts(r.created_at),
        "updated_at": fmt_ts(r.updated_at),
    }


def to_api_dict(d: SysDict) -> dict[str, Any]:
    return {
        "id": d.id,
        "code": d.code,
        "name": d.name,
        "tenant_id": d.tenant_id,
        "remark": d.remark,
        "creator_id": d.creator_id,
        "modifier_id": d.modifier_id,
        "created_at": fmt_ts(d.created_at),
        "updated_at": fmt_ts(d.updated_at),
    }


def to_api_dict_item(i: SysDictItem) -> dict[str, Any]:
    return {
        "id": i.id,
        "dict_id": i.dict_id,
        "item_code": i.item_code,
        "item_label": i.item_label,
        "parent_id": i.parent_id,
        "ext": i.ext_json,
        "i18n": i.i18n_json,
        "sort_no": i.sort_no,
        "effective_from": fmt_date(i.effective_from),
        "effective_to": fmt_date(i.effective_to),
        "active": i.active,
        "tenant_id": i.tenant_id,
    }


def dict_item_list(rows) -> list[dict[str, Any]]:
    return [to_api_dict_item(r) for r in rows]


def to_api_partner_org(o: SysPartnerOrg) -> dict[str, Any]:
    """外部合作机构（U 域沿用 snake_case，对齐 to_api_user 风格）。"""
    return {
        "id": o.id,
        "code": o.code,
        "tenant_id": o.tenant_id,
        "name": o.name,
        "short_name": o.short_name,
        "credit_code": o.credit_code,
        "org_type": o.org_type,
        "contact_name": o.contact_name,
        "contact_phone": o.contact_phone,
        "contact_email": o.contact_email,
        "address": o.address,
        "qualification_json": o.qualification_json,
        "status": o.status,
        "audit_user_id": o.audit_user_id,
        "audited_at": fmt_ts(o.audited_at),
        "reject_reason": o.reject_reason,
        "deleted": o.deleted,
        "creator_id": o.creator_id,
        "remark": o.remark,
        "created_at": fmt_ts(o.created_at),
        "updated_at": fmt_ts(o.updated_at),
    }
