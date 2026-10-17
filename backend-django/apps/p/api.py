"""申报域 P API（对齐 Go modules/p 全部端点）。

路由：GET|POST /apply/guidelines、GET /apply/guidelines/{id}、
     GET|POST /apply/applications、GET /apply/applications/{id}
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.p.mappings import num2, to_api_application, to_api_guideline
from apps.p.models import PApplication, PGuideline
from core.auth.deps import domain_from
from core.httpx import ApiError, CODE_BAD_REQUEST, CODE_CONFLICT, CODE_NOT_FOUND, CODE_UNKNOWN_PARAM, ok, read_json


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = int(request.GET.get("page", "1") or "1")
    except ValueError:
        page = 1
    try:
        size = int(request.GET.get("size", "20") or "20")
    except ValueError:
        size = 20
    page = max(page, 1)
    size = min(max(size, 1), 200)
    return page, size, size, (page - 1) * size


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.replace("Z", "+0000"), fmt).astimezone(timezone.utc)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# 申报指南（P-02）
# ---------------------------------------------------------------------------
def list_guidelines(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PGuideline.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("project_type"):
        qs = qs.filter(project_type=request.GET["project_type"])
    if request.GET.get("keyword"):
        kw = request.GET["keyword"]
        qs = qs.filter(title__icontains=kw)
    total = qs.count()
    rows = qs.order_by("-updated_at", "-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_guideline(g) for g in rows], "total": total, "page": page, "size": size})


def get_guideline(request: HttpRequest, id: int):
    g = PGuideline.objects.filter(id=id, deleted=0).first()
    if g is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return ok(request, to_api_guideline(g))


def upsert_guideline(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    code = body.get("code")
    title = body.get("title")
    project_type = body.get("project_type")
    if not code or not title or not project_type:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    status = body.get("status") or "DRAFT"
    if status not in ("DRAFT", "PUBLISHED", "CLOSED"):
        raise ApiError(400, CODE_UNKNOWN_PARAM, "status 非法")
    envelope = None
    if body.get("total_envelope"):
        try:
            envelope = num2(body["total_envelope"]) and body["total_envelope"]
        except Exception:
            raise ApiError(400, CODE_BAD_REQUEST, "总盘子金额格式错误") from None

    g = PGuideline.objects.filter(tenant_id=d.tenant_id, code=code, deleted=0).first()
    if g is None:
        g = PGuideline(tenant_id=d.tenant_id, code=code, creator_id=d.user_id, status=status)
    g.title = title
    g.project_type = project_type
    g.status = status
    g.funding_source = body.get("funding_source")
    g.remark = body.get("remark")
    g.content_rich = body.get("content_rich")
    g.target_disciplines = body.get("target_disciplines") or []
    g.attachment_ids = body.get("attachment_ids") or []
    g.apply_start_at = _parse_dt(body.get("apply_start_at"))
    g.apply_end_at = _parse_dt(body.get("apply_end_at"))
    if envelope is not None:
        g.total_envelope = envelope
    # 首次以 PUBLISHED 落库时记 publish_at（对齐 Go）
    if status == "PUBLISHED" and g.publish_at is None:
        g.publish_at = dj_tz.now()
    g.modifier_id = d.user_id
    g.save()
    return ok(request, to_api_guideline(g))


# ---------------------------------------------------------------------------
# 申报书（P-05）
# ---------------------------------------------------------------------------
def list_applications(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PApplication.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("project_type"):
        qs = qs.filter(project_type=request.GET["project_type"])
    total = qs.count()
    rows = qs.order_by("-updated_at", "-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_application(a) for a in rows], "total": total, "page": page, "size": size})


def get_application(request: HttpRequest, id: int):
    a = PApplication.objects.filter(id=id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return ok(request, to_api_application(a))


def create_application(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    title = body.get("title")
    project_type = body.get("project_type")
    pi_user_id = body.get("pi_user_id")
    if not title or not project_type or pi_user_id is None:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    total_budget = None
    if body.get("total_budget"):
        try:
            total_budget = round(float(body["total_budget"]), 2)
        except Exception:
            raise ApiError(400, CODE_UNKNOWN_PARAM, "预算格式错误") from None
    a = PApplication.objects.create(
        tenant_id=d.tenant_id, status="DRAFT", creator_id=d.user_id,
        title=title, project_type=project_type, pi_user_id=pi_user_id,
        member_ids=body.get("member_ids") or [],
        department_id=body.get("department_id"),
        abstract=body.get("abstract"),
        total_budget=total_budget,
        is_horizontal=bool(body.get("is_horizontal")),
    )
    return ok(request, to_api_application(a))


# ---------------------------------------------------------------------------
# 申报书撤回/终止（契约超前于 Go 版，按契约语义补齐）
# ---------------------------------------------------------------------------
# 可撤回状态：未进入评审（UNDER_REVIEW 及之后不可撤回）
_WITHDRAWABLE = {"DRAFT", "SUBMITTED", "FORMAL_CHECK", "RECOMMENDED"}
# 可终止状态：已进入评审及之后的流转中状态
_TERMINABLE = {"UNDER_REVIEW", "INTERVIEWING", "DECIDED", "PUBLISHED", "SIGNED", "EXECUTING"}


def _get_app_or_404(app_id: int) -> PApplication:
    a = PApplication.objects.filter(id=app_id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a


def _require_reason(body: dict) -> str:
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise ApiError(400, CODE_BAD_REQUEST, "理由必填")
    if len(reason) > 512:
        raise ApiError(400, CODE_BAD_REQUEST, "理由长度不能超过512")
    return reason


def withdraw_application(request: HttpRequest, id: int):
    """撤回申报：未进入评审前 PI 可主动撤回 → WITHDRAWN；进入评审后 409。"""
    d = domain_from(request)
    body = read_json(request)
    reason = _require_reason(body)
    a = _get_app_or_404(id)
    if a.status not in _WITHDRAWABLE:
        raise ApiError(409, CODE_CONFLICT, "当前状态不可撤回，已进入评审的申报只能终止")
    a.status = "WITHDRAWN"
    a.withdraw_at = dj_tz.now()
    a.withdraw_reason = reason
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_application(a))


def terminate_application(request: HttpRequest, id: int):
    """终止申报：已进入评审（UNDER_REVIEW 及之后）仅可终止，终态映射 REJECTED。"""
    d = domain_from(request)
    body = read_json(request)
    reason = _require_reason(body)
    a = _get_app_or_404(id)
    if a.status not in _TERMINABLE:
        raise ApiError(409, CODE_CONFLICT, "当前状态不可终止，未进入评审的申报应使用撤回")
    a.status = "REJECTED"
    a.withdraw_at = dj_tz.now()
    a.withdraw_reason = reason
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_application(a))
