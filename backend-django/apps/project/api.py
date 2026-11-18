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
from decimal import Decimal, InvalidOperation
from typing import Any

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.notify.models import SysNotification
from apps.project.mappings import (
    _num2,
    to_api_category,
    to_api_eval_template,
    to_api_change_request,
    to_api_change_version,
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
    EArchiveChecklist,
    EChangeRequest,
    EChangeVersion,
    EEvalTemplate,
    EReport,
    EFinalAccept,
    EHealthHistory,
    EMidCheck,
    EMilestone,
    EProgressReport,
    EProject,
    EProjectCategory,
    ETask,
)
from apps.funding.mappings import code_of
from apps.sysadmin.mappings import fmt_ts
from core import approval
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_CONFLICT_REF,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
    CODE_UNKNOWN_PARAM,
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


# ---------------------------------------------------------------------------
# M1-d B2：项目八要素看板（只读聚合，金额一律 Money=string）
# ---------------------------------------------------------------------------
def _board_outputs(tenant_id: int, project_id: int) -> int:
    """R_OUTPUT.project_ids 为 JSONB 数组，元素可能是 int 或 str（见 R 域写入面），两者都算。

    无 DB 端 JSON 包含查询可移植写法（sqlite 测试库），故按租户取 id 列后在 Python 过滤。
    """
    from apps.output.models import ROutput

    rows = ROutput.objects.filter(tenant_id=tenant_id, deleted=0).values_list("project_ids", flat=True)
    target = {project_id, str(project_id)}
    n = 0
    for ids in rows:
        if isinstance(ids, list) and any(i in target for i in ids):
            n += 1
    return n


def project_board(request: HttpRequest, id: int):
    from decimal import Decimal

    from django.db.models import Count, Sum

    from apps.funding.api import _execution_of
    from apps.procure.models import GContract
    from apps.sysadmin.models import SysUser

    p = _get_project_or_404(id)
    tenant_id = p.tenant_id

    # 经费：复用 03 F 域口径（预算批复/到账/已用/冻结/结余 + 两率）
    fund = _execution_of(tenant_id, id)

    # 进度：里程碑（ACHIEVED=完成）与任务（COMPLETED=完成）
    ms = EMilestone.objects.filter(tenant_id=tenant_id, project_id=id, deleted=0)
    tasks = ETask.objects.filter(tenant_id=tenant_id, project_id=id, deleted=0)
    progress = {
        "milestonesTotal": ms.count(),
        "milestonesDone": ms.filter(status="ACHIEVED").count(),
        "tasksTotal": tasks.count(),
        "tasksDone": tasks.filter(status="COMPLETED").count(),
    }

    # 人员：项目成员快照，查无此人仅返回 id（name=None）
    member_ids = [m for m in (p.member_ids or []) if isinstance(m, int)]
    names = dict(
        SysUser.objects.filter(tenant_id=tenant_id, id__in=member_ids).values_list("id", "real_name")
    )
    members = [{"userId": uid, "name": names.get(uid)} for uid in member_ids]

    # 质量：项目当前健康度 + 最近一次健康度快照
    last = (
        EHealthHistory.objects.filter(tenant_id=tenant_id, project_id=id)
        .order_by("-created_at", "-id")
        .first()
    )
    quality = {
        "healthScore": p.health_score,
        "riskLevel": p.risk_level,
        "lastCheckAt": fmt_ts(last.created_at) if last else None,
    }

    # 外包：09 G 合同台账（project_id 过滤）
    agg = GContract.objects.filter(tenant_id=tenant_id, project_id=id, deleted=0).aggregate(
        n=Count("id"), s=Sum("amount")
    )
    outsource = {"contracts": agg["n"] or 0, "amountTotal": _num2(agg["s"] or Decimal("0"))}

    # 变更：按状态计数
    by_status: dict[str, int] = {}
    for st in EChangeRequest.objects.filter(tenant_id=tenant_id, project_id=id, deleted=0).values_list(
        "status", flat=True
    ):
        by_status[st] = by_status.get(st, 0) + 1
    changes = {"total": sum(by_status.values()), "byStatus": by_status}

    # 成果：04 R 只读引用
    outputs = {"total": _board_outputs(tenant_id, id)}

    return ok(
        request,
        {
            "fund": fund,
            "progress": progress,
            "members": members,
            "quality": quality,
            "outsource": outsource,
            "changes": changes,
            "outputs": outputs,
        },
    )


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
    # 契约 camelCase（checkRound/templateId）与既有 snake_case 双读，兼容老调用方
    check_round = body.get("checkRound", body.get("check_round"))
    if check_round is None:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    r = EMidCheck.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, project_id=id,
        check_round=check_round,
        check_date=_parse_date(body.get("checkDate") or body.get("check_date")),
        plan_id=body.get("planId", body.get("plan_id")),
        template_id=_resolve_template_id(d.tenant_id, body, "MID_CHECK"),
        expert_ids=[],
    )
    return ok(request, to_api_mid_check(r))


_CHANGE_SEVERITIES = ("GENERAL", "MAJOR")


def _change_new_value(body: dict) -> dict | None:
    v = body.get("newValue", body.get("new_value"))
    return v if isinstance(v, dict) else v


def _change_conflict(p: EProject, change_type: str, new_value: Any) -> bool:
    """生效前冲突检查：预算变更后额度低于已支出即冲突（detail 4.4）。"""
    if change_type != "BUDGET" or not isinstance(new_value, dict):
        return False
    raw = new_value.get("totalBudget", new_value.get("total_budget"))
    if raw is None:
        return False
    try:
        target = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return target < (p.spent_amount or Decimal("0.00"))


def _change_snapshot(p: EProject) -> dict:
    """变更前项目快照（版本留痕：回滚/审计据此还原）。"""
    return {
        "title": p.title,
        "endDate": p.end_date.isoformat() if p.end_date else None,
        "memberIds": list(p.member_ids or []),
        "totalBudget": str(p.total_budget or "0.00"),
    }


def _change_version(tenant_id: int, user_id: int, change: EChangeRequest, p: EProject) -> EChangeVersion:
    """提交时落版本快照（version_no 自增 per 变更单）。"""
    last = EChangeVersion.objects.filter(change=change, deleted=0).order_by("-version_no").first()
    return EChangeVersion.objects.create(
        tenant_id=tenant_id, creator_id=user_id, change=change,
        version_no=(last.version_no + 1) if last else 1,
        snapshot=_change_snapshot(p),
    )


def _apply_change(p: EProject, row: EChangeRequest) -> dict | None:
    """生效回写（P-7 映射）：DELAY→end_date / TITLE→title / MEMBER→member_ids / BUDGET→预算。

    BUDGET 额外同步 F 域预算：活跃 FBudget.total_approved 按差额调整、首条预算行
    amount_adjusted 记增量；返回调剂明细（落版本快照 budgetAdjustment）。
    """
    nv = row.new_value if isinstance(row.new_value, dict) else {}
    fields: list[str] = []
    if row.change_type == "TITLE":
        new_title = nv.get("title")
        if new_title:
            p.title = str(new_title)[:256]
            fields.append("title")
    elif row.change_type == "DELAY":
        raw = nv.get("endDate", nv.get("end_date"))
        if raw:
            p.end_date = _parse_date(raw)
            fields.append("end_date")
    elif row.change_type == "MEMBER":
        members = nv.get("memberIds", nv.get("member_ids"))
        if isinstance(members, list):
            p.member_ids = members
            fields.append("member_ids")
    elif row.change_type == "BUDGET":
        raw = nv.get("totalBudget", nv.get("total_budget"))
        if raw is not None:
            try:
                target = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                target = None
            if target is not None:
                old_total = p.total_budget or Decimal("0.00")
                delta = (target - old_total).quantize(Decimal("0.01"))
                p.total_budget = target.quantize(Decimal("0.01"))
                fields.append("total_budget")
                if fields:
                    p.save(update_fields=fields + ["updated_at"])
                    fields = []
                return _sync_change_budget(row.project_id, row.tenant_id, delta, str(target))
    if fields:
        p.save(update_fields=fields + ["updated_at"])
    return None


def _sync_change_budget(project_id: int, tenant_id: int, delta: Decimal, target: str) -> dict:
    """预算调剂联动 F 域：活跃 FBudget 与首条预算行同步（F 域单据表 M2 补，先以快照承载）。"""
    from apps.funding.models import FBudget, FBudgetLine

    b = FBudget.objects.filter(
        project_id=project_id, tenant_id=tenant_id, deleted=0
    ).exclude(status="CLOSED").order_by("-id").first()
    if b is None:
        return {"budget": None, "delta": str(delta), "target": target}
    b.total_approved = (b.total_approved or Decimal("0.00")) + delta
    b.save(update_fields=["total_approved", "updated_at"])
    line = FBudgetLine.objects.filter(budget_id=b.id, deleted=0).order_by("id").first()
    if line is not None:
        line.amount_adjusted = (line.amount_adjusted or Decimal("0.00")) + delta
        line.save(update_fields=["amount_adjusted", "updated_at"])
    return {
        "budget": b.code, "delta": str(delta), "target": target,
        "budgetLineId": line.id if line is not None else None,
    }


def create_change_request(request: HttpRequest, id: int):
    d = domain_from(request)
    p = _get_project_or_404(id)
    body = read_json(request)
    change_type = body.get("changeType") or body.get("change_type")
    if not change_type:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    severity = body.get("severity") or "GENERAL"
    if severity not in _CHANGE_SEVERITIES:
        raise ApiError(400, CODE_BAD_REQUEST, "severity 须为 GENERAL/MAJOR")
    new_value = _change_new_value(body)
    r = EChangeRequest.objects.create(
        code=body.get("code"), tenant_id=d.tenant_id, creator_id=d.user_id, project_id=id,
        change_type=change_type, severity=severity,
        old_value=body.get("oldValue", body.get("old_value")),
        new_value=new_value, reason=body.get("reason"),
        status="SUBMITTED",
    )
    if not r.code:
        r.code = code_of("CHG", r.id)
        r.save(update_fields=["code"])

    v = _change_version(d.tenant_id, d.user_id, r, p)
    r.snapshot_ref = f"E_CHANGE_VERSION#{v.id}"
    r.save(update_fields=["snapshot_ref"])

    if severity == "MAJOR":
        return ok(request, to_api_change_request(r))

    # GENERAL：内部备案，冲突先拦（顺序=先 conflict 再 log/生效，Review Focus 2）
    if _change_conflict(p, change_type, new_value):
        r.conflict_flag = 1
        r.status = "ROLLED_BACK"
        r.save(update_fields=["conflict_flag", "status", "updated_at"])
        raise ApiError(409, CODE_CONFLICT, "预算冲突：变更后预算低于已支出，已回退")

    adjusted = _apply_change(p, r)
    r.status = "EFFECTIVE"
    r.approved_at = dj_tz.now()
    r.approval_status = "APPROVED"
    if adjusted is not None:
        v.snapshot = {**v.snapshot, "budgetAdjustment": adjusted}
        v.save(update_fields=["snapshot"])
    r.save(update_fields=["status", "approved_at", "approval_status", "updated_at"])
    approval.log(
        d.tenant_id, "CHANGE_REQUEST", r.id, 1, d.user_id,
        approval.first_role_of(d.roles), "EFFECTIVE", "一般变更内部备案",
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

    # 生效前冲突检查（P-6：必须先于 approval.log 与状态推进，否则冲突变更会被审批生效）
    p = EProject.objects.filter(id=project_id, deleted=0).first()
    if to_status == "EFFECTIVE" and p is not None and _change_conflict(
        p, row.change_type, row.new_value
    ):
        EChangeRequest.objects.filter(id=change_id).update(
            status="ROLLED_BACK", conflict_flag=1, updated_at=dj_tz.now()
        )
        return 409, "预算冲突：变更后预算低于已支出，已回退"

    n = EChangeRequest.objects.filter(id=change_id, project_id=project_id, status=row.status).update(
        status=to_status, updated_at=dj_tz.now()
    )
    if n == 0:
        return 409, "状态不允许或变更单不存在"
    adjusted = None
    if to_status == "EFFECTIVE" and p is not None:
        adjusted = _apply_change(p, row)
        if adjusted is not None:
            ver = EChangeVersion.objects.filter(change=row, deleted=0).order_by("-version_no").first()
            if ver is not None:
                ver.snapshot = {**(ver.snapshot or {}), "budgetAdjustment": adjusted}
                ver.save(update_fields=["snapshot"])
        EChangeRequest.objects.filter(id=change_id).update(
            approved_at=dj_tz.now(), approval_status="APPROVED"
        )
    approval.log(
        d.tenant_id, "CHANGE_REQUEST", change_id, step, d.user_id,
        approval.first_role_of(d.roles), action, comment,
    )
    return EChangeRequest.objects.get(id=change_id)


def get_change_versions(request: HttpRequest, id: int, change_id: int):
    """变更版本快照列表（M1-d B4）；跨项目/不存在一律 404。"""
    d = domain_from(request)
    _get_project_or_404(id)
    row = EChangeRequest.objects.filter(
        id=change_id, project_id=id, tenant_id=d.tenant_id, deleted=0
    ).first()
    if row is None:
        raise ApiError(404, CODE_NOT_FOUND, "变更单不存在")
    rows = [
        to_api_change_version(v) for v in
        EChangeVersion.objects.filter(change=row, deleted=0).order_by("version_no")
    ]
    return ok(request, {"list": rows})


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
        finance_report_id=body.get("financeReportId", body.get("finance_report_id")),
        template_id=_resolve_template_id(d.tenant_id, body, "FINAL_ACCEPT"),
        output_summary=body.get("outputSummary", body.get("output_summary")),
        apply_at=dj_tz.now(),
    )
    return ok(request, to_api_final_accept(r))


# ---------------------------------------------------------------------------
# M1-d B3：统一评估模板（一套配置支撑中检与验收）
# ---------------------------------------------------------------------------
_EVAL_SCENES = ("MID_CHECK", "FINAL_ACCEPT")
_EVAL_TEMPLATE_STATUSES = ("ACTIVE", "DISABLED")


def _resolve_template_id(tenant_id: int, body: dict, scene: str) -> int | None:
    """校验并归一 templateId（可选）：必须存在、未删、同租户、场景匹配。

    场景不匹配即 40001——一套模板只服务一种评估，跨场景复用会把评分项带错。
    """
    raw = body.get("templateId", body.get("template_id"))
    if raw is None or raw == "":
        return None
    try:
        tid = int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, CODE_BAD_REQUEST, "templateId 须为整数")
    tpl = EEvalTemplate.objects.filter(
        id=tid, tenant_id=tenant_id, deleted=0, status="ACTIVE"
    ).first()
    if tpl is None:
        raise ApiError(404, CODE_NOT_FOUND, "评估模板不存在")
    if tpl.scene != scene:
        raise ApiError(400, CODE_BAD_REQUEST, "评估模板场景不匹配")
    return tid


def _get_eval_template_or_404(tenant_id: int, template_id: int) -> EEvalTemplate:
    t = EEvalTemplate.objects.filter(id=template_id, tenant_id=tenant_id, deleted=0).first()
    if t is None:
        raise ApiError(404, CODE_NOT_FOUND, "评估模板不存在")
    return t


def list_eval_templates(request: HttpRequest):
    d = domain_from(request)
    qs = EEvalTemplate.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("scene"):
        qs = qs.filter(scene=request.GET["scene"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    rows = [to_api_eval_template(t) for t in qs.order_by("-id")]
    return ok(request, {"list": rows})


def create_eval_template(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误（name 必填）")
    scene = body.get("scene") or "MID_CHECK"
    if scene not in _EVAL_SCENES:
        raise ApiError(400, CODE_BAD_REQUEST, "scene 须为 MID_CHECK/FINAL_ACCEPT")
    sections = body.get("sections")
    if sections is not None and not isinstance(sections, list):
        raise ApiError(400, CODE_BAD_REQUEST, "sections 须为数组")
    rubric = body.get("scoreRubric", body.get("score_rubric"))
    if rubric is not None and not isinstance(rubric, dict):
        raise ApiError(400, CODE_BAD_REQUEST, "scoreRubric 须为对象")
    r = EEvalTemplate.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, name=name, scene=scene,
        sections=sections or [], score_rubric=rubric or {},
        status=body.get("status") or "ACTIVE", remark=body.get("remark"),
    )
    return ok(request, to_api_eval_template(r))


def update_eval_template(request: HttpRequest, id: int):
    d = domain_from(request)
    t = _get_eval_template_or_404(d.tenant_id, id)
    body = read_json(request)
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise ApiError(400, CODE_BAD_REQUEST, "name 不能为空")
        t.name = name
    if "scene" in body:
        if body["scene"] not in _EVAL_SCENES:
            raise ApiError(400, CODE_BAD_REQUEST, "scene 须为 MID_CHECK/FINAL_ACCEPT")
        t.scene = body["scene"]
    if "sections" in body:
        if not isinstance(body["sections"], list):
            raise ApiError(400, CODE_BAD_REQUEST, "sections 须为数组")
        t.sections = body["sections"]
    rubric = body.get("scoreRubric", body.get("score_rubric"))
    if rubric is not None:
        if not isinstance(rubric, dict):
            raise ApiError(400, CODE_BAD_REQUEST, "scoreRubric 须为对象")
        t.score_rubric = rubric
    if "status" in body:
        if body["status"] not in _EVAL_TEMPLATE_STATUSES:
            raise ApiError(400, CODE_BAD_REQUEST, "status 须为 ACTIVE/DISABLED")
        t.status = body["status"]
    if "remark" in body:
        t.remark = body["remark"]
    t.modifier_id = d.user_id
    t.save()
    return ok(request, to_api_eval_template(t))


def delete_eval_template(request: HttpRequest, id: int):
    d = domain_from(request)
    t = _get_eval_template_or_404(d.tenant_id, id)
    t.deleted = 1
    t.modifier_id = d.user_id
    t.save(update_fields=["deleted", "modifier_id", "updated_at"])
    return ok(request, {"id": t.id})


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


def _notify(user_id: int, typ: str, title: str, content: str, biz_ref: str, tenant_id: int):
    """通知触达（best-effort：永不阻断业务，对齐 funding/api.py:116 范式）。"""
    if user_id and user_id > 0:
        try:
            SysNotification.objects.create(
                tenant_id=tenant_id, user_id=user_id, typ=typ,
                title=title, content=content, biz_ref=biz_ref)
        except Exception:
            pass


def _notify_role(tenant_id: int, role: str, typ: str, title: str, content: str, biz_ref: str):
    """按角色广播通知（best-effort，E 域自建同款，对齐 funding/api.py:122-137）。"""
    try:
        from apps.sysadmin.models import SysRole, SysUser, SysUserRole
        r = SysRole.objects.filter(code=role, tenant_id=tenant_id).first()
        if r is None:
            return
        uids = list(SysUserRole.objects.filter(role=r).values_list("user_id", flat=True))
        for uid in SysUser.objects.filter(id__in=uids, status="ACTIVE").values_list("id", flat=True):
            _notify(uid, typ, title, content, biz_ref, tenant_id)
    except Exception:
        pass


def _issue_report(project_id: int, tenant_id: int, user_id: int, doc_type: str, title: str,
                  conclusion: str | None, score_detail: Any,
                  mid_check_id: int | None = None,
                  final_accept_id: int | None = None) -> int:
    """签发评估批文（幂等：同 (doc_type, mid_check_id|final_accept_id) 命中即复用）。

    批文是评估结论的正式文本载体，一次评估只出一份；重复 conclude 不重复签发。
    """
    qs = EReport.objects.filter(tenant_id=tenant_id, project_id=project_id,
                                doc_type=doc_type, deleted=0)
    if mid_check_id is not None:
        qs = qs.filter(mid_check_id=mid_check_id)
    elif final_accept_id is not None:
        qs = qs.filter(final_accept_id=final_accept_id)
    old = qs.first()
    if old is not None:
        return old.id
    rp = EReport.objects.create(
        tenant_id=tenant_id, creator_id=user_id, project_id=project_id,
        doc_type=doc_type, title=title, conclusion=conclusion,
        score_detail=score_detail, status="ISSUED", issued_at=dj_tz.now(),
        mid_check_id=mid_check_id, final_accept_id=final_accept_id,
    )
    rp.code = code_of("RPT", rp.id)
    rp.save(update_fields=["code"])
    return rp.id


def conclude_mid_check(mid_check_id: int, project_id: int, conclusion: str,
                       score_detail: Any) -> None:
    """N.conclude(MID_CHECK) 回写中检结论与打分明细，并签发批文（B3）。"""
    mc = EMidCheck.objects.filter(id=mid_check_id, deleted=0).first()
    if mc is None:
        return
    mc.conclusion = conclusion
    mc.score_detail = score_detail
    mc.save(update_fields=["conclusion", "score_detail", "updated_at"])

    p = EProject.objects.filter(id=project_id, deleted=0).first()
    title = f"{p.title if p else '项目'} 中期检查批文"
    report_id = _issue_report(
        project_id=project_id, tenant_id=mc.tenant_id, user_id=mc.creator_id,
        doc_type="MID_CHECK", title=title, conclusion=conclusion,
        score_detail=score_detail, mid_check_id=mc.id,
    )
    if mc.approval_doc_id != report_id:
        mc.approval_doc_id = report_id
        mc.save(update_fields=["approval_doc_id", "updated_at"])
    try:  # 通知 best-effort：任何异常都不阻断结论落库
        _notify_role(mc.tenant_id, "R-MANAGER", "MID_CHECK", title,
                     f"第 {mc.check_round} 轮中检结论 {conclusion}，批文已生成", f"mid-check:{mc.id}")
    except Exception:
        pass


def conclude_final_accept(final_accept_id: int, status: str) -> None:
    """N.conclude(FINAL_ACCEPT) 回写结题验收状态；仅通过时签发批文（B3）。"""
    fa = EFinalAccept.objects.filter(id=final_accept_id, deleted=0).first()
    if fa is None:
        return
    fa.status = status
    if status == "APPROVED":
        fa.accept_at = dj_tz.now()
    fa.save(update_fields=["status", "accept_at", "updated_at"])
    if status != "APPROVED":
        return

    p = EProject.objects.filter(id=fa.project_id, deleted=0).first()
    title = f"{p.title if p else '项目'} 结题验收批文"
    report_id = _issue_report(
        project_id=fa.project_id, tenant_id=fa.tenant_id, user_id=fa.creator_id,
        doc_type="FINAL_ACCEPT", title=title, conclusion=fa.conclusion,
        score_detail=fa.output_summary, final_accept_id=fa.id,
    )
    if fa.approval_doc_id != report_id:
        fa.approval_doc_id = report_id
        fa.save(update_fields=["approval_doc_id", "updated_at"])
    try:  # 通知 best-effort：任何异常都不阻断结论落库
        _notify_role(fa.tenant_id, "R-MANAGER", "FINAL_ACCEPT", title,
                     "结题验收通过，批文已生成", f"final-accept:{fa.id}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 风险预警 / 归档清单（前端 ProjectView 契约补齐，camelCase）
# ---------------------------------------------------------------------------
_ARCHIVE_DEFAULT_ITEMS = [
    {"item": "结题报告", "required": True, "mime": "application/pdf", "docId": None, "uploaded": False},
    {"item": "成果清单", "required": True, "mime": "application/pdf", "docId": None, "uploaded": False},
    {"item": "经费决算表", "required": True, "mime": "application/pdf", "docId": None, "uploaded": False},
    {"item": "审计报告", "required": False, "mime": "application/pdf", "docId": None, "uploaded": False},
    {"item": "原始数据说明", "required": False, "mime": "application/pdf", "docId": None, "uploaded": False},
]


def _get_project_or_404(project_id: int) -> EProject:
    p = EProject.objects.filter(id=project_id, deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    return p


def list_risk_warnings(request: HttpRequest, id: int):
    """GET /project/{id}/risk-warnings —— 确定性规则生成 ERiskWarning[]。

    规则：经费执行率（>100% HIGH / ≥90% MID）、里程碑逾期（HIGH）、
    健康分（<60 HIGH / <80 MID）、项目风险级（HIGH → HIGH）。
    """
    p = _get_project_or_404(id)
    warnings: list[dict] = []

    total, spent = float(p.total_budget or 0), float(p.spent_amount or 0)
    if total > 0:
        rate = spent / total
        if rate > 1.0:
            warnings.append((("FUNDING"), "HIGH",
                             f"经费执行率 {rate * 100:.1f}%，已超出预算",
                             "冻结后续报销并启动预算调整流程"))
        elif rate >= 0.9:
            warnings.append((("FUNDING"), "MID",
                             f"经费执行率 {rate * 100:.1f}%，接近预算上限",
                             "控制非必要支出，评估预算追加需求"))

    today = dj_tz.localdate()
    overdue = [m for m in EMilestone.objects.filter(project=p, deleted=0)
               if m.due_date and m.due_date < today and not m.actual_date]
    if overdue:
        names = "、".join(m.name for m in overdue[:3])
        warnings.append((("MILESTONE"), "HIGH",
                         f"{len(overdue)} 个里程碑已逾期（{names}）",
                         "限期提交整改说明，必要时发起变更申请"))

    if p.health_score < 60:
        warnings.append((("HEALTH"), "HIGH",
                         f"项目健康分 {p.health_score}，处于风险区间",
                         "约谈项目负责人并制定健康度恢复计划"))
    elif p.health_score < 80:
        warnings.append((("HEALTH"), "MID",
                         f"项目健康分 {p.health_score}，需持续关注",
                         "跟进滞后任务与经费执行进度"))

    if p.risk_level == "HIGH":
        warnings.append((("HEALTH"), "HIGH",
                         "项目风险等级为 HIGH",
                         "纳入重点监控清单，按周汇报进展"))

    rows = [{"warningId": i + 1, "level": lv, "source": src, "title": title,
             "suggestion": sug, "disposition": "待处理"}
            for i, (src, lv, title, sug) in enumerate(warnings)]
    return ok(request, rows)


def _get_checklist_or_init(request: HttpRequest, project: EProject, stage: str) -> EArchiveChecklist:
    """幂等取归档清单：无行则按默认模板初始化落库。"""
    row = EArchiveChecklist.objects.filter(project=project, code=stage).first()
    if row is None:
        row = EArchiveChecklist.objects.create(
            tenant_id=project.tenant_id, code=stage,
            creator_id=domain_from(request).user_id or 0,
            project=project, items=_ARCHIVE_DEFAULT_ITEMS, status="DRAFT", passed=False,
        )
    return row


def _checklist_payload(row: EArchiveChecklist) -> dict:
    """EArchiveChecklist → 前端 camelCase 契约（ProjectView 文档页签）。"""
    items = row.items or _ARCHIVE_DEFAULT_ITEMS
    required = [i for i in items if i.get("required")]
    completed = [i for i in required if i.get("uploaded")]
    blocked = [i["item"] for i in required if not i.get("uploaded")]
    pct = round(len(completed) / len(required) * 100) if required else 100
    return {
        "checklistJson": items,
        "requiredCount": len(required),
        "completedCount": len(completed),
        "completeness": f"{pct}%",
        "status": row.status,
        "blockedItems": blocked,
    }


def get_archive_checklist(request: HttpRequest, id: int):
    """GET /project/{id}/archive-checklist?stage= —— EArchiveChecklist 幂等初始化 + 契约输出。"""
    p = _get_project_or_404(id)
    stage = request.GET.get("stage") or "FINAL"
    row = _get_checklist_or_init(request, p, stage)
    return ok(request, _checklist_payload(row))


def update_checklist_item(request: HttpRequest, id: int):
    """POST /project/{id}/archive-checklist?stage= —— 标记清单项补传/撤销。

    body: {item: 清单项名, doc_id: O 域文档 id | null, uploaded: bool（缺省 true）}。
    doc_id 须真实存在（o_document），否则 40902 引用冲突。
    """
    p = _get_project_or_404(id)
    body = read_json(request)
    item_name = (body.get("item") or "").strip()
    if not item_name:
        raise ApiError(400, CODE_BAD_REQUEST, "item 必填")
    uploaded = bool(body.get("uploaded", True))
    doc_id = body.get("doc_id")
    if uploaded and not doc_id:
        raise ApiError(400, CODE_BAD_REQUEST, "补传必须携带 doc_id（先 POST /documents 上传）")
    if doc_id is not None:
        from apps.archive.models import ODocument
        if not ODocument.objects.filter(id=int(doc_id), deleted=0).exists():
            raise ApiError(409, CODE_CONFLICT_REF, "doc_id 对应文档不存在")

    stage = request.GET.get("stage") or "FINAL"
    row = _get_checklist_or_init(request, p, stage)
    items = [dict(i) for i in (row.items or _ARCHIVE_DEFAULT_ITEMS)]
    target = next((i for i in items if i.get("item") == item_name), None)
    if target is None:
        raise ApiError(400, CODE_UNKNOWN_PARAM, f"未知清单项：{item_name}")
    target["uploaded"] = uploaded
    target["docId"] = int(doc_id) if doc_id else None
    row.items = items
    required = [i for i in items if i.get("required")]
    row.passed = bool(required) and all(i.get("uploaded") for i in required)
    row.save()
    return ok(request, _checklist_payload(row))
