"""N 域门户（M2-c）：外部专家自助注册、审核与信用档案。

设计要点：
- 申请建 `NExpert(status="CANDIDATE")`，审核通过置 `ACTIVE` 并授 `R-EXPERT`；
- 驳回置 `SUSPENDED`（拒绝态，`_my_expert_or_403` 会拒掉，管理员可再改回）；
- 通知：站内信 + best-effort 邮件（Task 8 统一切到 `notify_user`）。
"""
from __future__ import annotations

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.expertreview.api import page_args, _my_expert_or_403
from apps.expertreview.models import NExpert
from apps.expertreview.mappings import fmt_ts, to_api_expert
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
    ok,
    read_json,
)

APPLICANT_SOURCE = "EXTERNAL"


def _notify_both(tenant_id: int, user_id: int, typ: str, title: str, content: str, biz_ref: str) -> None:
    """统一投递（C5）：站内信 + 邮件，best-effort 永不阻断主流程。"""
    try:
        from apps.notify.email import notify_user

        if not user_id:
            return
        notify_user(tenant_id, user_id, typ, title, content, biz_ref)
    except Exception:  # noqa: BLE001 - 通知失败不影响业务
        pass


def _expert_code(expert_id: int) -> str:
    return f"NEX-{dj_tz.localdate().year}-{expert_id:06d}"


def to_api_expert_application(r: NExpert) -> dict:
    """审核台视图：档案主体 + 申请/审核元信息（键名 snake_case，对齐 N 域）。"""
    base = to_api_expert(r)
    base.update(
        {
            "audited_at": fmt_ts(r.updated_at) if r.status != "CANDIDATE" else None,
            "audit_user_id": r.modifier_id,
            "reject_reason": r.remark if r.status == "SUSPENDED" else None,
        }
    )
    return base


def apply_expert(request: HttpRequest):
    """外部用户自助申请成为评审专家。"""
    d = domain_from(request)
    body = read_json(request)
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(400, CODE_BAD_REQUEST, "姓名必填")
    if len(name) > 64:
        raise ApiError(400, CODE_BAD_REQUEST, "姓名过长")
    if not d.user_id:
        raise ApiError(403, CODE_FORBIDDEN, "未认证")
    existing = NExpert.objects.filter(
        tenant_id=d.tenant_id, user_id=d.user_id, deleted=0
    ).first()
    if existing is not None and existing.status in ("CANDIDATE", "ACTIVE"):
        raise ApiError(409, CODE_CONFLICT, "已提交过专家申请")

    tags = body.get("field_tags")
    if tags is not None and not isinstance(tags, list):
        raise ApiError(400, CODE_BAD_REQUEST, "field_tags 必须为数组")

    if existing is not None:
        # 终审 I-4：被驳回/停用的申请可重新提交——复用原档案复位为待审，
        # 而不是再建一条（否则 (tenant,user) 维度会堆出多条幽灵档案）。
        existing.status = "CANDIDATE"
        existing.name = name
        existing.title = (body.get("title") or "").strip()[:64] or existing.title
        existing.org_name = (body.get("org_name") or "").strip()[:128] or existing.org_name
        existing.email = (body.get("email") or "").strip()[:128] or existing.email
        existing.phone = (body.get("phone") or "").strip()[:32] or existing.phone
        if tags is not None:
            existing.field_tags = [str(t) for t in tags if str(t).strip()]
        existing.reject_reason = None
        existing.modifier_id = d.user_id
        existing.save()
        return ok(request, {"id": existing.id, "status": existing.status, "code": existing.code})

    e = NExpert.objects.create(
        tenant_id=d.tenant_id,
        status="CANDIDATE",
        name=name,
        title=body.get("title"),
        org_name=body.get("org_name"),
        phone=body.get("phone"),
        email=body.get("email"),
        user_id=d.user_id,
        source=APPLICANT_SOURCE,
        field_tags=[str(t) for t in (tags or [])],
        cv_doc_ids=[int(x) for x in (body.get("cv_doc_ids") or []) if str(x).isdigit()],
        expertise_level="EXPERT",
        creator_id=d.user_id,
    )
    e.code = _expert_code(e.id)
    e.save(update_fields=["code", "updated_at"])

    _notify_both(
        d.tenant_id, d.user_id, "MESSAGE", "专家申请已提交",
        "您的评审专家申请已提交，等待科研管理部门审核", f"expert-apply:{e.id}",
    )
    _notify_role_inapp(
        d.tenant_id, "R-MANAGER", "TODO", "新的专家申请",
        f"{name} 提交了评审专家申请", f"expert-apply:{e.id}",
    )
    return ok(request, to_api_expert_application(e))


def _notify_role_inapp(tenant_id: int, role_code: str, typ: str, title: str,
                       content: str, biz_ref: str) -> None:
    try:
        from apps.notify.email import notify_inapp
        from apps.sysadmin.models import SysRole, SysUserRole

        role = SysRole.objects.filter(code=role_code, tenant_id=tenant_id).first()
        if role is None:
            return
        for uid in SysUserRole.objects.filter(role_id=role.id).values_list("user_id", flat=True):
            notify_inapp(tenant_id, uid, typ, title, content, biz_ref)
    except Exception:  # noqa: BLE001
        pass


def list_expert_applications(request: HttpRequest):
    """审核台列表：缺省只看待审 CANDIDATE。"""
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = NExpert.objects.filter(tenant_id=d.tenant_id, deleted=0)
    status = request.GET.get("status") or "CANDIDATE"
    if status != "ALL":
        qs = qs.filter(status=status)
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(
        request,
        {"list": [to_api_expert_application(r) for r in rows],
         "total": total, "page": page, "size": size},
    )


def audit_expert_application(request: HttpRequest, id: int):
    """APPROVE → ACTIVE + 授 R-EXPERT；REJECT → SUSPENDED（必填理由）。"""
    from django.db import transaction

    d = domain_from(request)
    body = read_json(request)
    action = (body.get("action") or "").upper()
    if action not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 须为 APPROVE 或 REJECT")

    with transaction.atomic():
        e = (
            NExpert.objects.select_for_update()
            .filter(id=id, tenant_id=d.tenant_id, deleted=0)
            .first()
        )
        if e is None:
            raise ApiError(404, CODE_NOT_FOUND, "专家申请不存在")
        if e.status != "CANDIDATE":
            raise ApiError(409, CODE_CONFLICT, "仅待审申请可审核")

        if action == "APPROVE":
            role = _grant_expert_role(d.tenant_id, e.user_id)
            if role is None:
                raise ApiError(400, CODE_BAD_REQUEST, "角色未初始化，请先执行 seed_demo")
            e.status = "ACTIVE"
        else:
            reason = (body.get("reason") or "").strip()
            if not reason:
                raise ApiError(400, CODE_BAD_REQUEST, "驳回必须填写理由")
            e.status = "SUSPENDED"
            e.remark = reason

        e.modifier_id = d.user_id
        e.save()

    if action == "APPROVE":
        _notify_both(d.tenant_id, e.user_id or 0, "ANNOUNCE", "专家申请已通过",
                     "您已成为评审专家，可接收评审邀请", f"expert-apply:{e.id}")
    else:
        _notify_both(d.tenant_id, e.user_id or 0, "MESSAGE", "专家申请未通过",
                     f"驳回理由：{e.remark}", f"expert-apply:{e.id}")
    return ok(request, to_api_expert_application(e))


def _grant_expert_role(tenant_id: int, user_id: int | None):
    """授予 R-EXPERT（外部账号只允许外部角色，内部角色不会因此追加）。

    终审 I-5：授角色前必须确认目标用户属于**本租户**且未删除——否则审核台可
    跨租户给别人发权限（专家档案的 user_id 一旦被写脏就会放大成提权面）。
    """
    if not user_id:
        return None
    from apps.sysadmin.models import SysRole, SysUserRole, SysUser

    owner = SysUser.objects.filter(id=user_id, tenant_id=tenant_id, deleted=0).first()
    if owner is None:
        raise ApiError(400, CODE_BAD_REQUEST, "专家档案绑定的用户不存在或不属于本租户")

    role = SysRole.objects.filter(code="R-EXPERT", tenant_id=tenant_id).first()
    if role is None:
        return None
    SysUserRole.objects.get_or_create(user_id=user_id, role_id=role.id, tenant_id=tenant_id)
    return role


# ---------------------------------------------------------------- 信用档案与门户只读（Task 5）

_ON_TIME_HOURS = 72


def _expert_credit(tenant_id: int, expert_id: int) -> dict:
    """专家信用档案（计算式，不落新表）：响应率/按时率/弃权率/均分。"""
    from decimal import Decimal

    from django.db.models import Avg
    from django.utils import timezone as dj_tz

    from apps.expertreview.models import NReviewInvitation, NReviewScore
    from core.httpx import CODE_NOT_FOUND

    e = NExpert.objects.filter(id=expert_id, tenant_id=tenant_id, deleted=0).first()
    if e is None:
        raise ApiError(404, CODE_NOT_FOUND, "专家不存在")

    invs = list(
        NReviewInvitation.objects.filter(tenant_id=tenant_id, expert_id=expert_id)
    )
    invited = len(invs)
    accepted = sum(1 for i in invs if i.response == "ACCEPT")
    declined = sum(1 for i in invs if i.response == "DECLINE")
    expired = sum(1 for i in invs if i.response == "EXPIRED")
    responded = [i for i in invs if i.responded_at is not None]
    on_time = sum(
        1
        for i in responded
        if i.responded_at - i.invited_at <= dj_tz.timedelta(hours=_ON_TIME_HOURS)
    )
    scores = NReviewScore.objects.filter(tenant_id=tenant_id, expert_id=expert_id)
    abstain = scores.filter(status="ABSTAIN").count()
    avg = scores.aggregate(v=Avg("total_score"))["v"]

    def _rate(num: int, den: int) -> str:
        if den <= 0:
            return "0.00"
        return f"{Decimal(num) / Decimal(den):.2f}"

    return {
        "expert_id": e.id,
        "name": e.name,
        "review_count": e.review_count or 0,
        "invited_count": invited,
        "accepted_count": accepted,
        "declined_count": declined,
        "expired_count": expired,
        "accept_rate": _rate(accepted, invited),
        "on_time_rate": _rate(on_time, len(responded)),
        "abstain_count": abstain,
        "avg_score": None if avg is None else f"{Decimal(avg):.2f}",
        "last_review_at": fmt_ts(e.last_review_at),
    }


def get_expert_credit(request: HttpRequest, id: int):
    """管理端看任意专家信用（R-MANAGER/R-LEADER）。"""
    d = domain_from(request)
    return ok(request, _expert_credit(d.tenant_id, id))


def portal_credit(request: HttpRequest):
    d = domain_from(request)
    expert = _my_expert_or_403(d)
    return ok(request, _expert_credit(d.tenant_id, expert.id))


def portal_reviews(request: HttpRequest):
    """我的评审邀请（含任务标题/状态/响应）。"""
    from apps.expertreview.models import NReviewInvitation, NReviewTask

    d = domain_from(request)
    expert = _my_expert_or_403(d)
    invs = list(
        NReviewInvitation.objects.filter(tenant_id=d.tenant_id, expert_id=expert.id)
        .order_by("-id")[:100]
    )
    task_ids = [i.task_id for i in invs]
    tasks = {
        t.id: t
        for t in NReviewTask.objects.filter(tenant_id=d.tenant_id, id__in=task_ids, deleted=0)
    }
    rows = []
    for i in invs:
        t = tasks.get(i.task_id)
        rows.append(
            {
                "id": i.id,
                "task_id": i.task_id,
                "title": t.title if t else None,
                "biz_type": t.biz_type if t else None,
                "task_status": t.status if t else None,
                "response": i.response,
                "invited_at": fmt_ts(i.invited_at),
                "responded_at": fmt_ts(i.responded_at),
            }
        )
    return ok(request, {"list": rows, "total": len(rows)})


def portal_activities(request: HttpRequest):
    """受邀学术活动（C3「学术活动邀请」只读面）。"""
    from apps.activity.models import VActivity, VActivityParticipant

    d = domain_from(request)
    if not d.user_id:
        raise ApiError(403, CODE_FORBIDDEN, "未认证")
    parts = list(
        VActivityParticipant.objects.filter(
            tenant_id=d.tenant_id, user_id=d.user_id, activity_id__gt=0
        ).order_by("-id")[:100]
    )
    ids = [p.activity_id for p in parts]
    acts = {a.id: a for a in VActivity.objects.filter(tenant_id=d.tenant_id, id__in=ids, deleted=0)}
    rows = []
    for p in parts:
        a = acts.get(p.activity_id)
        if a is None:
            continue
        rows.append(
            {
                "id": a.id,
                "title": a.title,
                "activity_type": a.activity_type,
                "status": a.status,
                "start_at": fmt_ts(a.start_at),
                "venue": a.venue,
                "role": p.role,
            }
        )
    return ok(request, {"list": rows, "total": len(rows)})
