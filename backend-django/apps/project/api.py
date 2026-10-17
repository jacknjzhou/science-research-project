"""项目过程域 E API（对齐 Go modules/project 全部手工实现端点）。

读：/project/mine、/project/{id}、tasks、milestones
动作：progress-report / mid-check / change-request(+approve) / approve-batch / final-accept
分类：/project-categories CRUD + scan-warnings + /projects/{id}/category
申报计划：/apply-plans CRUD + start/stop/auto-stop + applications + approve + to-project
任务书：/projects/extract-taskbook（LLM 降级语义）
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.notify.models import SysNotification
from apps.project.mappings import (
    to_api_category,
    to_api_change_request,
    to_api_final_accept,
    to_api_milestone,
    to_api_mid_check,
    to_api_progress_report,
    to_api_project,
    to_api_task,
)
from apps.project.models import (
    EApplication,
    EApplyPlan,
    EChangeRequest,
    EFinalAccept,
    EMidCheck,
    EMilestone,
    EProgressReport,
    EProject,
    EProjectCategory,
    ETask,
)
from core import approval
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


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s.replace("Z", "+0000"), fmt).date()
        except Exception:
            continue
    return None


def _get_project_or_404(project_id: int) -> EProject:
    p = EProject.objects.filter(id=project_id, deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    return p


# ---------------------------------------------------------------------------
# 项目读端点
# ---------------------------------------------------------------------------
def list_my_projects(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = EProject.objects.filter(tenant_id=d.tenant_id, deleted=0)
    # R-ADMIN 全量视角（管理员应看到所有信息）；其他角色按 PI 过滤
    if not approval.has_role(d.roles, "R-ADMIN"):
        qs = qs.filter(pi_user_id=d.user_id)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("project_type"):
        qs = qs.filter(project_type=request.GET["project_type"])
    if request.GET.get("kw"):
        qs = qs.filter(title__icontains=request.GET["kw"])
    total = qs.count()
    rows = qs.order_by("-updated_at", "-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_project(p) for p in rows], "total": total, "page": page, "size": size})


def get_project(request: HttpRequest, id: int):
    return ok(request, to_api_project(_get_project_or_404(id)))


def list_tasks(request: HttpRequest, id: int):
    _get_project_or_404(id)
    qs = ETask.objects.filter(project_id=id, deleted=0)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return ok(request, {"list": [to_api_task(t) for t in qs.order_by("id")]})


def list_milestones(request: HttpRequest, id: int):
    _get_project_or_404(id)
    rows = EMilestone.objects.filter(project_id=id, deleted=0).order_by("id")
    return ok(request, {"list": [to_api_milestone(m) for m in rows]})


def update_task(request: HttpRequest, id: int, task_id: int):
    _get_project_or_404(id)
    body = read_json(request)
    status = body.get("status")
    if not status:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    task = ETask.objects.filter(id=task_id, project_id=id, deleted=0).first()
    if task is None:
        raise ApiError(404, CODE_NOT_FOUND, "任务不存在")
    task.status = status
    if body.get("owner_user_id") is not None:
        task.owner_user_id = body["owner_user_id"]
    pp = body.get("progress_percent")
    if pp is not None:
        task.progress_percent = max(0, min(int(pp), 100))
    task.save()
    return ok(request, to_api_task(task))


# ---------------------------------------------------------------------------
# 过程动作端点
# ---------------------------------------------------------------------------
def create_progress_report(request: HttpRequest, id: int):
    d = domain_from(request)
    _get_project_or_404(id)
    body = read_json(request)
    period = body.get("period")
    report_type = body.get("report_type")
    if not period or not report_type:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    r = EProgressReport.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, project_id=id,
        period=period, report_type=report_type,
        content_rich=body.get("content_rich"),
        progress_percent=body.get("progress_percent") or 0,
        issues_text=body.get("issues_text"), next_plan=body.get("next_plan"),
        attachment_ids=body.get("attachment_ids") or [],
    )
    return ok(request, to_api_progress_report(r))


def create_mid_check(request: HttpRequest, id: int):
    d = domain_from(request)
    _get_project_or_404(id)
    body = read_json(request)
    check_round = body.get("check_round")
    if check_round is None:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    r = EMidCheck.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, project_id=id,
        check_round=check_round, check_date=_parse_date(body.get("check_date")),
        plan_id=body.get("plan_id"), template_id=body.get("template_id"),
        expert_ids=[],
    )
    return ok(request, to_api_mid_check(r))


def create_change_request(request: HttpRequest, id: int):
    d = domain_from(request)
    _get_project_or_404(id)
    body = read_json(request)
    change_type = body.get("change_type")
    if not change_type:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    code = body.get("code") or f"CR-{dj_tz.localdate():%Y%m%d}-{time.time_ns() % 1000000:06d}"
    r = EChangeRequest.objects.create(
        code=code, tenant_id=d.tenant_id, creator_id=d.user_id, project_id=id,
        change_type=change_type, old_value=body.get("old_value"),
        new_value=body.get("new_value"), reason=body.get("reason"),
        status="SUBMITTED",
    )
    return ok(request, to_api_change_request(r))


def _advance_change(d, project_id: int, change_id: int, to_status: str, comment: str,
                    action: str) -> EChangeRequest | tuple[int, str]:
    """变更单推进核心（对齐 approveChangeOne/rejectChangeOne；两级开关 off 默认）。"""
    row = EChangeRequest.objects.filter(id=change_id).first()
    if row is None or row.project_id != project_id:
        return 404, "变更单不存在"
    two_step = approval.twostep_enabled()
    is_admin = approval.has_role(d.roles, "R-ADMIN")
    if action == "APPROVE":
        if two_step:
            if row.status == "SUBMITTED":
                if not is_admin and not approval.has_role(d.roles, "R-MANAGER"):
                    return 403, "首审需要 R-MANAGER 角色"
                to_status, step = "APPROVING", 1
            elif row.status == "APPROVING":
                if not is_admin and not approval.has_role(d.roles, "R-LEADER"):
                    return 403, "终审需要 R-LEADER 角色"
                to_status, step = "EFFECTIVE", 2
            else:
                return 409, "状态不允许审批"
        elif row.status not in ("SUBMITTED", "APPROVING"):
            return 409, "状态不允许或变更单不存在"
        else:
            to_status, step = "EFFECTIVE", 1
    else:  # REJECT
        if row.project_id != project_id or row.status not in ("SUBMITTED", "APPROVING"):
            return 409, "状态不允许驳回"
        to_status, step = "REJECTED", 1

    n = EChangeRequest.objects.filter(id=change_id, project_id=project_id, status=row.status).update(
        status=to_status, updated_at=dj_tz.now()
    )
    if n == 0:
        return 409, "状态不允许或变更单不存在"
    approval.log(
        d.tenant_id, "CHANGE_REQUEST", change_id, step, d.user_id,
        approval.first_role_of(d.roles), action, comment,
    )
    return EChangeRequest.objects.get(id=change_id)


def approve_change_request(request: HttpRequest, id: int, change_id: int):
    d = domain_from(request)
    body = read_json(request)
    result = _advance_change(d, id, change_id, "", body.get("comment"), "APPROVE")
    if isinstance(result, tuple):
        status_code, msg = result
        code_map = {404: CODE_NOT_FOUND, 403: CODE_FORBIDDEN, 409: CODE_CONFLICT}
        raise ApiError(status_code, code_map[status_code], msg)
    return ok(request, to_api_change_request(result))


def approve_change_batch(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    ids = body.get("ids")
    action = body.get("action")
    comment = body.get("comment")
    if not ids or not isinstance(ids, list) or not action:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    if action not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 仅支持 APPROVE/REJECT")
    results = []
    ok_n = 0
    for cid in ids:
        row = EChangeRequest.objects.filter(id=cid).first()
        if row is None:
            results.append({"id": cid, "ok": False, "err": "变更单不存在"})
            continue
        result = _advance_change(d, row.project_id, cid, "", comment, action)
        if isinstance(result, tuple):
            results.append({"id": cid, "ok": False, "err": result[1]})
        else:
            ok_n += 1
            results.append({"id": cid, "ok": True})
    return ok(request, {"total": len(ids), "ok": ok_n, "results": results})


def create_final_accept(request: HttpRequest, id: int):
    d = domain_from(request)
    _get_project_or_404(id)
    body = read_json(request)
    r = EFinalAccept.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, project_id=id,
        finance_report_id=body.get("finance_report_id"),
        apply_at=dj_tz.now(),
    )
    return ok(request, to_api_final_accept(r))


# ---------------------------------------------------------------------------
# T21 项目分类 + 预警
# ---------------------------------------------------------------------------
def list_project_categories(request: HttpRequest):
    d = domain_from(request)
    rows = EProjectCategory.objects.filter(tenant_id=d.tenant_id, deleted=0).order_by("id")
    return ok(request, {"list": [to_api_category(c) for c in rows]})


def create_project_category(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    code = body.get("code")
    name = body.get("name")
    if not code or not name:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    if EProjectCategory.objects.filter(tenant_id=d.tenant_id, code=code, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "分类编码已存在")
    c = EProjectCategory.objects.create(
        tenant_id=d.tenant_id, code=code, name=name,
        level=body.get("level") or "NORMAL",
        mgmt_fee_pct=body.get("mgmt_fee_pct") or 0,
        midcheck_from=_parse_date(body.get("midcheck_from")),
        midcheck_to=_parse_date(body.get("midcheck_to")),
        closing_from=_parse_date(body.get("closing_from")),
        closing_to=_parse_date(body.get("closing_to")),
    )
    return ok(request, to_api_category(c))


def update_project_category(request: HttpRequest, id: int):
    d = domain_from(request)
    c = EProjectCategory.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if c is None:
        raise ApiError(404, CODE_NOT_FOUND, "分类不存在")
    body = read_json(request)
    for f in ("name", "level"):
        if body.get(f) is not None:
            setattr(c, f, body[f])
    if body.get("mgmt_fee_pct") is not None:
        c.mgmt_fee_pct = body["mgmt_fee_pct"]
    for f in ("midcheck_from", "midcheck_to", "closing_from", "closing_to"):
        if f in body:
            setattr(c, f, _parse_date(body.get(f)))
    c.save()
    return ok(request, to_api_category(c))


def delete_project_category(request: HttpRequest, id: int):
    d = domain_from(request)
    n = EProjectCategory.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).update(
        deleted=1, updated_at=dj_tz.now()
    )
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "分类不存在")
    return ok(request, {"id": id, "deleted": True})


def attach_project_category(request: HttpRequest, id: int):
    d = domain_from(request)
    body = read_json(request)
    category_id = body.get("category_id")
    if category_id is None:
        raise ApiError(400, CODE_BAD_REQUEST, "category_id 必填")
    n = EProject.objects.filter(id=id, deleted=0).update(category_id=category_id, updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    return ok(request, {"id": id, "category_id": category_id})


def _in_window(c_from: date | None, c_to: date | None, lead_days: int = 15) -> bool:
    if c_from is None or c_to is None:
        return False
    today = dj_tz.localdate()
    return (c_from - timedelta(days=lead_days)) <= today <= c_to


def scan_warnings(request: HttpRequest):
    """EXECUTING 项目 × 分类窗口（窗口前 15 天起）→ 通知 PI；同用户同标题未读去重。"""
    d = domain_from(request)
    today = dj_tz.localdate()
    rows = EProject.objects.filter(
        tenant_id=d.tenant_id, deleted=0, status="EXECUTING", category_id__isnull=False
    )
    sent = 0
    for p in rows:
        c = EProjectCategory.objects.filter(id=p.category_id, tenant_id=d.tenant_id, deleted=0).first()
        if c is None:
            continue
        kind = title = due = None
        if _in_window(c.midcheck_from, c.midcheck_to):
            kind, title, due = "MIDCHECK_DUE", "中检窗口提醒", f"{c.midcheck_to:%Y-%m-%d}"
        elif _in_window(c.closing_from, c.closing_to):
            kind, title, due = "CLOSING_DUE", "结项窗口提醒", f"{c.closing_to:%Y-%m-%d}"
        else:
            continue
        dedupe_title = f"{kind}：{p.title}"
        if SysNotification.objects.filter(user_id=p.pi_user_id, title=dedupe_title, read_at__isnull=True).exists():
            continue
        SysNotification.objects.create(
            tenant_id=d.tenant_id, user_id=p.pi_user_id, typ="WARNING", title=dedupe_title,
            content=f"项目《{p.title}》{title}，截止 {due}，请及时安排中检/结项材料",
            biz_ref=f"project/{p.id}",
        )
        sent += 1
    return ok(request, {"sent": sent, "scanned_at": f"{today:%Y-%m-%d}"})


# ---------------------------------------------------------------------------
# T22 任务书解析（LLM 未配置 → 降级人工录入）
# ---------------------------------------------------------------------------
def extract_taskbook(request: HttpRequest):
    f = request.FILES.get("file")
    if f is None:
        raise ApiError(400, CODE_BAD_REQUEST, "缺少 file 字段（multipart pdf）")
    raw = f.read()
    if not raw:
        raise ApiError(400, CODE_BAD_REQUEST, "文件内容为空")
    text = _extract_pdf_text(raw)
    if not text.strip():
        return ok(request, {"ok": False, "confidence": 0, "message": "PDF 文本抽取失败（可能为扫描件），请人工录入"})
    from django.conf import settings

    if not settings.LLM_BASE_URL:
        return ok(request, {"ok": False, "confidence": 0, "raw_text": text[:2000], "message": "LLM 未配置，请人工录入"})
    # svc-ai / LLM 调用（Phase 4 接入；当前仅文本版解析交由 LLM 网关）
    try:
        from core.llm import extract_taskbook

        parsed = extract_taskbook(text)
        return ok(request, parsed)
    except Exception as exc:  # 降级不阻塞
        return ok(request, {"ok": False, "confidence": 0, "raw_text": text[:2000],
                            "message": f"LLM 解析失败：{exc}，请人工录入"})


def _extract_pdf_text(raw: bytes) -> str:
    """轻量 PDF 文本抽取：pdfplumber 起步；扫描件返回空串触发降级。"""
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# T25 申报计划 + 申报单
# ---------------------------------------------------------------------------
def list_apply_plans(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = EApplyPlan.objects.filter(tenant_id=d.tenant_id)
    total = qs.count()
    rows = qs.order_by("-created_at", "-id")[offset : offset + limit]
    return ok(request, {
        "list": [
            {"id": r.id, "name": r.name, "category_id": r.category_id, "source": r.source,
             "start_at": f"{r.start_at:%Y-%m-%d}", "end_at": f"{r.end_at:%Y-%m-%d}",
             "need_review": r.need_review, "status": r.status}
            for r in rows
        ],
        "total": total, "page": page, "size": size,
    })


def create_apply_plan(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    name = body.get("name")
    start_at = _parse_date(body.get("start_at"))
    end_at = _parse_date(body.get("end_at"))
    if not name or start_at is None or end_at is None:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    r = EApplyPlan.objects.create(
        tenant_id=d.tenant_id, name=name, category_id=body.get("category_id"),
        source=body.get("source"), start_at=start_at, end_at=end_at,
        need_review=body.get("need_review", True),
        guide_file_id=body.get("guide_file_id"),
    )
    return ok(request, {"id": r.id, "name": r.name, "status": r.status,
                        "start_at": f"{r.start_at:%Y-%m-%d}", "end_at": f"{r.end_at:%Y-%m-%d}"})


def start_apply_plan(request: HttpRequest, id: int):
    d = domain_from(request)
    n = EApplyPlan.objects.filter(id=id, tenant_id=d.tenant_id, status="DRAFT").update(
        status="OPEN", updated_at=dj_tz.now()
    )
    if n == 0:
        raise ApiError(409, CODE_CONFLICT, "仅 DRAFT 可开启")
    return ok(request, {"id": id, "status": "OPEN"})


def stop_apply_plan(request: HttpRequest, id: int):
    d = domain_from(request)
    n = EApplyPlan.objects.filter(id=id, tenant_id=d.tenant_id, status="OPEN").update(
        status="STOPPED", updated_at=dj_tz.now()
    )
    if n == 0:
        raise ApiError(409, CODE_CONFLICT, "仅 OPEN 可停止")
    return ok(request, {"id": id, "status": "STOPPED"})


def auto_stop_plans(request: HttpRequest):
    d = domain_from(request)
    n = EApplyPlan.objects.filter(
        tenant_id=d.tenant_id, status="OPEN", end_at__lt=dj_tz.localdate()
    ).update(status="STOPPED", updated_at=dj_tz.now())
    return ok(request, {"stopped": n})


def create_plan_application(request: HttpRequest, id: int):
    d = domain_from(request)
    plan = EApplyPlan.objects.filter(id=id, tenant_id=d.tenant_id).first()
    if plan is None:
        raise ApiError(404, CODE_NOT_FOUND, "申报计划不存在")
    today = dj_tz.localdate()
    if plan.status != "OPEN" or not (plan.start_at <= today <= plan.end_at):
        raise ApiError(409, CODE_CONFLICT, "申报计划未开启或不在申报窗口内")
    body = read_json(request)
    project_name = body.get("project_name")
    if not project_name:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    amount = body.get("apply_amount") or 0
    r = EApplication.objects.create(
        tenant_id=d.tenant_id, plan=plan, project_name=project_name,
        apply_amount=amount, applicant_id=d.user_id,
        attachment_ids=body.get("attachment_ids") or [],
    )
    return ok(request, {"id": r.id, "status": r.status, "project_name": r.project_name})


def list_plan_applications(request: HttpRequest, id: int):
    d = domain_from(request)
    plan = EApplyPlan.objects.filter(id=id, tenant_id=d.tenant_id).first()
    if plan is None:
        raise ApiError(404, CODE_NOT_FOUND, "申报计划不存在")
    rows = EApplication.objects.filter(tenant_id=d.tenant_id, plan_id=id).order_by("-created_at", "-id")
    out = []
    # 形式审查视图：申请人「主持+参与」项目摘要（member_ids JSON 跨库兼容，Python 端过滤）
    all_projects = list(EProject.objects.filter(tenant_id=d.tenant_id, deleted=0))
    for a in rows:
        pi_qs = [
            p for p in all_projects
            if p.pi_user_id == a.applicant_id
            or any(m.get("user_id") == a.applicant_id for m in (p.member_ids or []) if isinstance(m, dict))
        ]
        budget = sum(p.total_budget for p in pi_qs)
        out.append({
            "id": a.id, "plan_id": a.plan_id, "project_name": a.project_name,
            "apply_amount": f"{float(a.apply_amount):.2f}", "applicant_id": a.applicant_id,
            "attachment_ids": a.attachment_ids or [], "status": a.status,
            "project_id": a.project_id,
            "pi_project_count": len(pi_qs),
            "pi_budget_total": f"{float(budget):.2f}",
        })
    return ok(request, {"list": out})


def approve_application(request: HttpRequest, id: int):
    """两级（T19 语义）：R-MANAGER SUBMITTED→COLLEGE_PASSED；R-LEADER COLLEGE_PASSED→SCHOOL_PASSED。
    R-ADMIN 直通角色校验但仍按级推进；两级开关 off 时一步到 SCHOOL_PASSED。"""
    d = domain_from(request)
    body = read_json(request)
    action = body.get("action")
    comment = body.get("comment")
    if action not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 仅支持 APPROVE/REJECT")
    app = EApplication.objects.filter(id=id, tenant_id=d.tenant_id).first()
    if app is None:
        raise ApiError(404, CODE_NOT_FOUND, "申报单不存在")
    is_admin = approval.has_role(d.roles, "R-ADMIN")
    two_step = approval.twostep_enabled()

    if action == "REJECT":
        pairs = {"SUBMITTED": "COLLEGE_REJECTED", "COLLEGE_PASSED": "SCHOOL_REJECTED"}
        if app.status not in pairs:
            raise ApiError(409, CODE_CONFLICT, "状态不允许驳回")
        to = pairs[app.status]
        n = EApplication.objects.filter(id=id, status=app.status).update(status=to, updated_at=dj_tz.now())
        if n == 0:
            raise ApiError(500, 50002, "驳回失败")
        approval.log(d.tenant_id, "APPLICATION", id, 1, d.user_id,
                     approval.first_role_of(d.roles), "REJECT", comment)
        return ok(request, {"id": id, "status": to})

    # 批准推进
    if two_step:
        moves = {
            "SUBMITTED": ("COLLEGE_PASSED", 1, "R-MANAGER", "首审需要 R-MANAGER 角色"),
            "COLLEGE_PASSED": ("SCHOOL_PASSED", 2, "R-LEADER", "终审需要 R-LEADER 角色"),
        }
        if app.status not in moves:
            raise ApiError(409, CODE_CONFLICT, "状态不允许审批")
        to, step, need_role, deny_msg = moves[app.status]
        if not is_admin and not approval.has_role(d.roles, need_role):
            raise ApiError(403, CODE_FORBIDDEN, deny_msg)
        from_status = app.status
    else:
        if app.status not in ("SUBMITTED", "COLLEGE_PASSED"):
            raise ApiError(409, CODE_CONFLICT, "状态不允许审批")
        to, step, from_status = "SCHOOL_PASSED", 1, app.status
    n = EApplication.objects.filter(id=id, status=from_status).update(status=to, updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(500, 50002, "审批失败")
    approval.log(d.tenant_id, "APPLICATION", id, step, d.user_id,
                 approval.first_role_of(d.roles), "APPROVE", comment)
    return ok(request, {"id": id, "status": to})


def application_to_project(request: HttpRequest, id: int):
    """SCHOOL_PASSED → 生成 E_PROJECT 草稿（幂等：project_id 已存在直接回显）。"""
    d = domain_from(request)
    app = EApplication.objects.filter(id=id, tenant_id=d.tenant_id).first()
    if app is None:
        raise ApiError(404, CODE_NOT_FOUND, "申报单不存在")
    if app.status != "SCHOOL_PASSED":
        raise ApiError(409, CODE_CONFLICT, "仅学校通过的申报单可转立项")
    if app.project_id is not None:
        return ok(request, {"project_id": app.project_id, "duplicated": True})
    plan = EApplyPlan.objects.filter(id=app.plan_id, tenant_id=d.tenant_id).first()
    if plan is None:
        raise ApiError(404, CODE_NOT_FOUND, "申报计划不存在")
    p = EProject.objects.create(
        tenant_id=d.tenant_id, status="EXECUTING", creator_id=d.user_id,
        application_id=app.id, title=app.project_name,
        project_type=plan.source or None, pi_user_id=app.applicant_id,
        member_ids=[], legal_entity_id=1, total_budget=app.apply_amount,
    )
    EApplication.objects.filter(id=id, project_id__isnull=True).update(project_id=p.id, updated_at=dj_tz.now())
    return ok(request, {"project_id": p.id, "duplicated": False})


# ---------------------------------------------------------------------------
# 单一写者导出（N 域回写唯一入口；签名权威勿漂移，见 Go writeback.go 注释）
#   - set_mid_check_experts(mid_check_id, expert_user_ids) error
#   - conclude_mid_check(mid_check_id, project_id, conclusion, score_detail) error
#   - conclude_final_accept(final_accept_id, status) error
# ---------------------------------------------------------------------------

def set_mid_check_experts(mid_check_id: int, expert_user_ids: list[int]) -> None:
    """N.invite(MID_CHECK) 回填 E_MID_CHECK.expert_ids。"""
    mc = EMidCheck.objects.filter(id=mid_check_id, deleted=0).first()
    if mc is None:
        return
    mc.expert_ids = list(expert_user_ids)
    mc.save(update_fields=["expert_ids", "updated_at"])


def conclude_mid_check(mid_check_id: int, project_id: int, conclusion: str,
                       score_detail: Any) -> None:
    """N.conclude(MID_CHECK) 回写中检结论与打分明细。"""
    mc = EMidCheck.objects.filter(id=mid_check_id, deleted=0).first()
    if mc is None:
        return
    mc.conclusion = conclusion
    mc.score_detail = score_detail
    mc.save(update_fields=["conclusion", "score_detail", "updated_at"])


def conclude_final_accept(final_accept_id: int, status: str) -> None:
    """N.conclude(FINAL_ACCEPT) 回写结题验收状态（APPROVED/REJECTED/NEED_SUPPLEMENT）。"""
    fa = EFinalAccept.objects.filter(id=final_accept_id, deleted=0).first()
    if fa is None:
        return
    fa.status = status
    if status == "APPROVED":
        fa.accept_at = dj_tz.now()
    fa.save(update_fields=["status", "accept_at", "updated_at"])
