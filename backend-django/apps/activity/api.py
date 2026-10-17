"""学术活动域 V API（对齐 Go modules/activity：handler.go + mapper.go）。

状态机：DRAFT→SUBMITTED→(DEPT_REVIEW)→APPROVED→HELD→ARCHIVED，任意非终态可 CANCELLED。
单级审批：SUBMITTED approve(level<=1)→DEPT_REVIEW；level>1 或 DEPT_REVIEW→APPROVED。
"""
from __future__ import annotations

from datetime import datetime

from django.db.models import Count, Q
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.activity.models import VActivity, VActivityParticipant, VActivityReview
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    ok,
    read_json,
    read_json_soft,
)

ALLOWED_TRANSITIONS = {
    "DRAFT": {"SUBMITTED", "CANCELLED"},
    "RETURNED": {"SUBMITTED", "CANCELLED"},
    "SUBMITTED": {"DEPT_REVIEW", "APPROVED", "REJECTED", "RETURNED", "CANCELLED"},
    "DEPT_REVIEW": {"APPROVED", "REJECTED", "RETURNED", "CANCELLED"},
    "APPROVED": {"HELD", "CANCELLED"},
    "HELD": {"ARCHIVED"},
}


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = max(int(request.GET.get("page", "1") or "1"), 1)
        size = min(max(int(request.GET.get("size", "20") or "20"), 1), 200)
    except ValueError:
        page, size = 1, 20
    return page, size, size, (page - 1) * size


def _parse_ts(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return dj_tz.make_aware(datetime.strptime(str(s)[:26], fmt))
        except ValueError:
            continue
    return None


def _parse_d(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_activity_or_404(activity_id: int) -> VActivity:
    a = VActivity.objects.filter(id=activity_id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "活动不存在")
    return a


def to_api_activity(a: VActivity) -> dict:
    return {
        "id": a.id, "tenant_id": a.tenant_id, "status": a.status,
        "security_level": a.security_level, "activity_type": a.activity_type,
        "title": a.title, "invited_experts": a.invited_experts or [],
        "agenda": a.agenda or [], "attachment_ids": a.attachment_ids or [],
        "hold_proof_ids": a.hold_proof_ids or [],
        "budget_amount": (f"{a.budget_amount:.2f}" if a.budget_amount is not None else None),
        "creator_id": a.creator_id, "deleted": a.deleted,
        "code": a.code, "level": a.level, "host_mode": a.host_mode,
        "theme": a.theme, "venue": a.venue, "online_url": a.online_url,
        "host_unit": a.host_unit, "budget_subject_code": a.budget_subject_code,
        "minutes_rich": a.minutes_rich, "cancel_reason": a.cancel_reason,
        "remark": a.remark, "organizer_dept_id": a.organizer_dept_id,
        "project_id": a.project_id, "est_attendees": a.est_attendees,
        "sign_in_count": a.sign_in_count, "modifier_id": a.modifier_id,
        "start_at": (a.start_at.isoformat() if a.start_at else None),
        "end_at": (a.end_at.isoformat() if a.end_at else None),
        "submit_at": (a.submit_at.isoformat() if a.submit_at else None),
        "approve_at": (a.approve_at.isoformat() if a.approve_at else None),
        "archive_at": (a.archive_at.isoformat() if a.archive_at else None),
        "cancel_at": (a.cancel_at.isoformat() if a.cancel_at else None),
        "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
    }


def to_api_participant(p: VActivityParticipant) -> dict:
    return {"id": p.id, "activity_id": p.activity_id, "user_id": p.user_id,
            "guest_name": p.guest_name, "role": p.role, "report_title": p.report_title}


def to_api_review(r: VActivityReview) -> dict:
    return {"id": r.id, "activity_id": r.activity_id, "review_level": r.review_level,
            "reviewer_id": r.reviewer_id, "action": r.action, "opinion": r.opinion,
            "acted_at": r.acted_at.isoformat()}


def _apply_body(a: VActivity, b: dict, security_default: str = "INTERNAL") -> None:
    if not b.get("activity_type") or not b.get("title"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    a.activity_type = b["activity_type"]
    a.title = b["title"]
    a.level = b.get("level")
    a.host_mode = b.get("host_mode")
    a.theme = b.get("theme")
    a.start_at = _parse_ts(b.get("start_at"))
    a.end_at = _parse_ts(b.get("end_at"))
    a.venue = b.get("venue")
    a.online_url = b.get("online_url")
    a.host_unit = b.get("host_unit")
    a.organizer_dept_id = b.get("organizer_dept_id")
    a.invited_experts = b.get("invited_experts") or []
    a.est_attendees = b.get("est_attendees")
    a.project_id = b.get("project_id")
    a.budget_subject_code = b.get("budget_subject_code")
    if b.get("budget_amount"):
        try:
            a.budget_amount = b["budget_amount"]
        except Exception:
            raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误") from None
    a.agenda = b.get("agenda") or []
    a.attachment_ids = b.get("attachment_ids") or []
    a.security_level = b.get("security_level") or security_default
    a.remark = b.get("remark")


def list_activities(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = VActivity.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("activity_type"):
        qs = qs.filter(activity_type=v)
    if v := request.GET.get("level"):
        qs = qs.filter(level=v)
    if v := request.GET.get("host_mode"):
        qs = qs.filter(host_mode=v)
    if v := request.GET.get("organizer_dept_id"):
        try:
            qs = qs.filter(organizer_dept_id=int(v))
        except ValueError:
            pass
    if v := _parse_d(request.GET.get("from")):
        qs = qs.filter(start_at__gte=v)
    if v := _parse_d(request.GET.get("to")):
        qs = qs.filter(start_at__lte=v)
    if v := request.GET.get("keyword"):
        qs = qs.filter(Q(title__icontains=v) | Q(theme__icontains=v))
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_activity(a) for a in rows],
                        "total": total, "page": page, "size": size})


def get_activity(request: HttpRequest, id: int):
    a = _get_activity_or_404(id)
    parts = list(VActivityParticipant.objects.filter(activity_id=id))
    revs = list(VActivityReview.objects.filter(activity_id=id).order_by("id"))
    out = to_api_activity(a)
    out["participants"] = [to_api_participant(p) for p in parts]
    out["reviews"] = [to_api_review(r) for r in revs]
    return ok(request, out)


def create_activity(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    a = VActivity(tenant_id=d.tenant_id, status="DRAFT", creator_id=d.user_id)
    _apply_body(a, b)
    a.save()
    return ok(request, to_api_activity(a))


def update_activity(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_activity_or_404(id)
    if a.status not in ("DRAFT", "RETURNED"):
        raise ApiError(409, CODE_CONFLICT, "活动不存在或状态不可编辑（仅 DRAFT/RETURNED）")
    b = read_json(request)
    _apply_body(a, b)
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_activity(a))


def delete_activity(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_activity_or_404(id)
    a.deleted = 1
    a.modifier_id = d.user_id
    a.save(update_fields=["deleted", "modifier_id", "updated_at"])
    return ok(request, {"id": id, "deleted": True})


def _transition(request: HttpRequest, id: int, to: str):
    d = domain_from(request)
    a = _get_activity_or_404(id)
    if to not in ALLOWED_TRANSITIONS.get(a.status, set()):
        raise ApiError(409, CODE_CONFLICT, f"非法状态迁移：{a.status}→{to}")
    a.status = to
    a.modifier_id = d.user_id
    if to == "SUBMITTED":
        a.submit_at = dj_tz.now()
    elif to == "APPROVED":
        a.approve_at = dj_tz.now()
    elif to == "CANCELLED":
        a.cancel_at = dj_tz.now()
    a.save()
    return ok(request, to_api_activity(a))


def submit_activity(request: HttpRequest, id: int):
    return _transition(request, id, "SUBMITTED")


def _next_on_approve(from_status: str, level: int, action: str) -> str | None:
    if action == "REJECT" and from_status in ("SUBMITTED", "DEPT_REVIEW"):
        return "REJECTED"
    if action == "RETURN" and from_status in ("SUBMITTED", "DEPT_REVIEW"):
        return "RETURNED"
    if action == "APPROVE":
        if from_status == "SUBMITTED":
            return "DEPT_REVIEW" if level <= 1 else "APPROVED"
        if from_status == "DEPT_REVIEW":
            return "APPROVED"
    return None


def approve_activity(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_activity_or_404(id)
    b = read_json(request)
    action = b.get("action")
    if not action:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    level = int(b.get("review_level") or 1)
    to = _next_on_approve(a.status, level, action)
    if to is None:
        raise ApiError(409, CODE_CONFLICT, f"非法审批：当前态 {a.status} 不支持该动作/层级")
    VActivityReview.objects.create(
        activity_id=id, review_level=level, reviewer_id=d.user_id,
        action=action, opinion=b.get("opinion"), tenant_id=d.tenant_id)
    a.status = to
    a.modifier_id = d.user_id
    if to == "APPROVED":
        a.approve_at = dj_tz.now()
    a.save()
    return ok(request, to_api_activity(a))


def hold_activity(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_activity_or_404(id)
    if a.status != "APPROVED":
        raise ApiError(409, CODE_CONFLICT, "仅 APPROVED 可标记举办")
    b = read_json_soft(request)
    a.status = "HELD"
    a.sign_in_count = b.get("sign_in_count")
    a.hold_proof_ids = b.get("hold_proof_ids") or []
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_activity(a))


def archive_activity(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_activity_or_404(id)
    if a.status != "HELD":
        raise ApiError(409, CODE_CONFLICT, "仅 HELD 可归档")
    b = read_json(request)
    if not b.get("minutes_rich"):
        raise ApiError(400, 40002, "归档需填纪要")
    a.status = "ARCHIVED"
    a.minutes_rich = b["minutes_rich"]
    a.archive_at = dj_tz.now()
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_activity(a))


def cancel_activity(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_activity_or_404(id)
    if a.status not in ALLOWED_TRANSITIONS or "CANCELLED" not in ALLOWED_TRANSITIONS.get(a.status, set()):
        raise ApiError(409, CODE_CONFLICT, "终态不可取消")
    b = read_json_soft(request)
    a.status = "CANCELLED"
    a.cancel_reason = b.get("cancel_reason")
    a.cancel_at = dj_tz.now()
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_activity(a))


def activity_calendar(request: HttpRequest):
    d = domain_from(request)
    month = request.GET.get("month") or dj_tz.localdate().strftime("%Y-%m")
    try:
        start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise ApiError(400, 40003, "month 需 YYYY-MM") from None
    end = (start.replace(day=28) + dj_tz.timedelta(days=4)).replace(day=1)
    rows = list(VActivity.objects.filter(
        tenant_id=d.tenant_id, deleted=0, start_at__gte=start, start_at__lt=end).order_by("start_at"))
    return ok(request, {"month": month, "list": [to_api_activity(a) for a in rows]})


def activity_stats(request: HttpRequest):
    d = domain_from(request)
    group_by = request.GET.get("group_by") or "activity_type"
    qs = VActivity.objects.filter(tenant_id=d.tenant_id, deleted=0)
    field = {"activity_type": "activity_type", "level": "level",
             "organizer_dept_id": "organizer_dept_id"}.get(group_by)
    buckets = []
    if group_by == "month":
        rows = qs.values_list("created_at", flat=True)
        agg: dict[str, int] = {}
        for t in rows:
            k = t.strftime("%Y-%m") if t else ""
            agg[k] = agg.get(k, 0) + 1
        buckets = [{"key": k, "count": c} for k, c in sorted(agg.items())]
    elif field:
        for r in qs.values(field).annotate(c=Count("id")):
            buckets.append({"key": r[field] if r[field] is not None else "", "count": r["c"]})
    else:
        for r in qs.values("activity_type").annotate(c=Count("id")):
            buckets.append({"key": r["activity_type"], "count": r["c"]})
    return ok(request, {"buckets": buckets})


def list_participants(request: HttpRequest, id: int):
    rows = list(VActivityParticipant.objects.filter(activity_id=id).order_by("id"))
    return ok(request, {"list": [to_api_participant(p) for p in rows]})


def add_participant(request: HttpRequest, id: int):
    d = domain_from(request)
    _get_activity_or_404(id)
    b = read_json(request)
    if not b.get("role"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    if not b.get("user_id") and not b.get("guest_name"):
        raise ApiError(400, 40004, "user_id 与 guest_name 至少给一个")
    p = VActivityParticipant.objects.create(
        activity_id=id, user_id=b.get("user_id"), guest_name=b.get("guest_name"),
        role=b["role"], report_title=b.get("report_title"), tenant_id=d.tenant_id)
    return ok(request, to_api_participant(p))


def remove_participant(request: HttpRequest, id: int, pid: int):
    n, _ = VActivityParticipant.objects.filter(id=pid, activity_id=id).delete()
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "参与人不存在")
    return ok(request, {"id": pid, "deleted": True})
