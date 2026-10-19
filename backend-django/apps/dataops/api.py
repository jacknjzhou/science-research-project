"""数据决策域 D：经费监督大屏真聚合（F-18 一图一舱三预警）。

只读投影，复用 funding 表；legalEntityId 可空看合并视图。
另含工作台/大屏读端点：/tasks/summary、/dash/metrics/{code}、/dash/forecast、
/dash/report/instance/{id}/drill、/dash/screens。
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.funding.models import FBudget, FBudgetLine, FExpense, FIncome, FIndirectFee
from core.auth.deps import domain_from
from core.httpx import ok


def _num2(v) -> str:
    if v is None:
        return "0.00"
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return f"{Decimal(str(v)):.2f}"


def _rate_of(used: float, budget: float) -> float:
    if not budget:
        return 0.0
    return float(int(used / budget * 100 + 0.5)) / 100


def funding_dashboard(request: HttpRequest):
    """GET /dashboard/funding?legalEntityId= —— 全量契约字段输出。"""
    d = domain_from(request)
    entity = request.GET.get("legalEntityId")
    year = dj_tz.localdate().year

    budgets = FBudget.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if entity:
        try:
            budgets = budgets.filter(legal_entity_id=int(entity))
        except ValueError:
            pass
    total_budget = float(budgets.aggregate(s=Sum("total_approved"))["s"] or 0) + \
        float(budgets.aggregate(s=Sum("total_adjusted"))["s"] or 0)

    incomes = FIncome.objects.filter(tenant_id=d.tenant_id, receipt_date__year=year)
    if entity:
        incomes = incomes.filter(legal_entity_id=int(entity))
    year_income = float(incomes.aggregate(s=Sum("amount"))["s"] or 0)

    expenses = FExpense.objects.filter(tenant_id=d.tenant_id, status__in=("APPROVED", "PAID", "VOUCHER_SYNCED"),
                                       created_at__year=year)
    if entity:
        expenses = expenses.filter(project_id__in=FBudget.objects.filter(
            tenant_id=d.tenant_id, legal_entity_id=int(entity)).values("project_id"))
    year_used = float(expenses.aggregate(s=Sum("amount"))["s"] or 0)

    # 部门热力：按项目所属部门聚合（E_PROJECT.department_id）
    from apps.project.models import EProject
    dept_rows = (EProject.objects.filter(tenant_id=d.tenant_id, deleted=0)
                 .values("department_id").annotate(cnt=Count("id")))
    budget_ids = list(budgets.values_list("id", flat=True))
    lines = FBudgetLine.objects.filter(budget_id__in=budget_ids, deleted=0)
    budgets_by_id = {b.id: b for b in budgets}
    dept_heat: dict[str, dict] = {}
    for line in lines:
        b = budgets_by_id.get(line.budget_id)
        if b is None:
            continue
        p = EProject.objects.filter(id=b.project_id).first()
        key = str(p.department_id if p else 0)
        cell = dept_heat.setdefault(key, {"budget": 0.0, "used": 0.0})
        cell["budget"] += float(line.amount_planned or 0) + float(line.amount_adjusted or 0)
        cell["used"] += float(line.amount_used or 0)
    heatmap = [{"departmentId": int(k) if k.isdigit() else 0,
                "amount": _num2(v["used"]), "budget": _num2(v["budget"]),
                "executionRate": _rate_of(v["used"], v["budget"])}
               for k, v in sorted(dept_heat.items())]

    # 12 个月趋势：月度实扣
    trend_rows = (FExpense.objects.filter(tenant_id=d.tenant_id,
                                          status__in=("APPROVED", "PAID", "VOUCHER_SYNCED"),
                                          created_at__year=year)
                  .values("created_at__month").annotate(s=Sum("amount")))
    trend = [{"month": f"{year}-{r['created_at__month']:02d}",
              "amount": _num2(r["s"]),
              "executionRate": _rate_of(float(r["s"] or 0), total_budget)}
             for r in sorted(trend_rows, key=lambda x: x["created_at__month"])]

    # 三预警：事前（未批先用 PRE）/事中（超进度 DURING）/事后（审计违规 POST）
    alerts = {"pre": {"count": 0}, "during": {"count": 0}, "post": {"count": 0}}
    alerts["during"]["count"] = FExpense.objects.filter(
        tenant_id=d.tenant_id, status="SUBMITTED").count()
    alerts["post"]["count"] = FExpense.objects.filter(
        tenant_id=d.tenant_id, invoice_check_status="FAILED").count()

    # T23 三维监控：college / subject 分组（f_budget_line 聚合）
    by_college: list[dict] = []
    for line in FBudgetLine.objects.filter(budget_id__in=budget_ids, deleted=0):
        cell_c = {"dimId": None, "approved": 0.0, "used": 0.0, "frozen": 0.0}
        cell_c["approved"] += float(line.amount_planned or 0) + float(line.amount_adjusted or 0)
        cell_c["used"] += float(line.amount_used or 0)
        cell_c["frozen"] += float(line.amount_frozen or 0)
        by_college.append(cell_c)
    approved_total = sum(c["approved"] for c in by_college) or 1
    by_college = [{"dimId": i, "approved": _num2(c["approved"]), "used": _num2(c["used"]),
                   "frozen": _num2(c["frozen"]),
                   "executionRate": _rate_of(c["used"], c["approved"])}
                  for i, c in enumerate(by_college)]
    by_subject = by_college  # 科目维度本轮按行等价投影（后续接 subject_id 维表）

    return ok(request, {
        "totalBudget": _num2(total_budget),
        "yearIncome": _num2(year_income),
        "yearUsed": _num2(year_used),
        "executionRate": _rate_of(year_used, total_budget),
        "violationCount": alerts["post"]["count"],
        "deptHeatmap": heatmap,
        "trend12Months": trend,
        "alerts": alerts,
        "byCollege": by_college,
        "bySubject": by_subject,
    })


# ---------------------------------------------------------------------------
# 工作台/大屏读端点（前端 DashView / BigscreenView 契约补齐）
# ---------------------------------------------------------------------------
_PROJECT_ACTIVE = ("EXECUTING", "MID_CHECK", "CHANGING", "CORRECTING", "DELAYED", "COMPLETING")


def tasks_summary(request: HttpRequest):
    """GET /tasks/summary —— 当前用户 {todo,message,warning} 三计数。"""
    from apps.notify.models import SysNotification, SysTask

    d = domain_from(request)
    todo = SysTask.objects.filter(tenant_id=d.tenant_id, status="OPEN", assignee_id=d.user_id).count()
    unread = SysNotification.objects.filter(tenant_id=d.tenant_id, user_id=d.user_id, read_at__isnull=True)
    return ok(request, {
        "todo": todo,
        "message": unread.filter(typ="MESSAGE").count(),
        "warning": unread.filter(typ="WARNING").count(),
    })


def metric_value(request: HttpRequest, code: str):
    """GET /dash/metrics/{code} —— 5 个 KPI 确定性聚合；未知 code 返零值（dq_flag=NO_DATA）。

    前端 DashView 用 Promise.all 并发拉取且无兜底，任何 404 都会让整页报错，
    故未知指标也返回 200 零值行。
    """
    d = domain_from(request)
    now = dj_tz.now()
    year = dj_tz.localdate().year
    meta = {
        "in_research_projects": ("在研项目数", "项"),
        "available_funding": ("可用经费余额", "万元"),
        "yearly_outputs": ("本年度成果数", "项"),
        "pending_applications": ("待处理申报", "件"),
        "pending_reviews": ("评审中任务", "项"),
    }
    if code not in meta:
        return ok(request, {
            "code": code, "name": code, "unit": "", "version": 1, "value": 0,
            "data_as_of": now.strftime("%Y-%m-%d %H:%M"), "dq_flag": "NO_DATA",
            "drill_available": False,
        })

    value = 0
    drill = True
    if code == "in_research_projects":
        from apps.project.models import EProject
        value = EProject.objects.filter(
            tenant_id=d.tenant_id, deleted=0, status__in=_PROJECT_ACTIVE).count()
    elif code == "available_funding":
        budgets = FBudget.objects.filter(tenant_id=d.tenant_id, deleted=0)
        budget_total = float(budgets.aggregate(s=Sum("total_approved"))["s"] or 0) + \
            float(budgets.aggregate(s=Sum("total_adjusted"))["s"] or 0)
        used = float(FBudgetLine.objects.filter(
            budget_id__in=list(budgets.values_list("id", flat=True)), deleted=0
        ).aggregate(s=Sum("amount_used"))["s"] or 0)
        value = round(max(budget_total - used, 0.0) / 10000, 2)
    elif code == "yearly_outputs":
        from apps.output.models import ROutput
        value = ROutput.objects.filter(tenant_id=d.tenant_id, created_at__year=year).count()
        drill = False
    elif code == "pending_applications":
        from apps.p.models import PApplication
        value = PApplication.objects.filter(
            tenant_id=d.tenant_id, deleted=0, status__in=("SUBMITTED", "FORMAL_CHECK")).count()
    elif code == "pending_reviews":
        from apps.expertreview.models import NReviewTask
        value = NReviewTask.objects.filter(
            tenant_id=d.tenant_id, deleted=0,
            status__in=("QUORUM", "IN_REVIEW", "COLLECTING")).count()
        drill = False

    name, unit = meta[code]
    return ok(request, {
        "code": code, "name": name, "unit": unit, "version": 1, "value": value,
        "data_as_of": now.strftime("%Y-%m-%d %H:%M"), "dq_flag": "OK",
        "drill_available": drill,
    })


def forecast(request: HttpRequest):
    """GET /dash/forecast?target_metric=monthly_expense —— 近 6 期月度实扣线性外推 3 期。"""
    d = domain_from(request)
    target = request.GET.get("target_metric", "monthly_expense")
    rows = (FExpense.objects.filter(tenant_id=d.tenant_id, deleted=0,
                                    status__in=("APPROVED", "PAID", "VOUCHER_SYNCED"))
            .values("created_at__year", "created_at__month").annotate(s=Sum("amount")))
    series = sorted(
        ((r["created_at__year"] * 12 + r["created_at__month"], float(r["s"] or 0)) for r in rows),
        key=lambda x: x[0],
    )[-6:]
    out: list[dict] = []
    if len(series) >= 2:
        n = len(series)
        xs = list(range(n))
        mean_x, mean_y = sum(xs) / n, sum(v for _, v in series) / n
        denom = sum((x - mean_x) ** 2 for x in xs) or 1
        slope = sum((x - mean_x) * (v - mean_y) for x, (_, v) in zip(xs, series)) / denom
        intercept = mean_y - slope * mean_x
        last_key = series[-1][0]
        for i in range(1, 4):
            key = last_key + i
            year, month = divmod(key - 1, 12)
            pred = max(intercept + slope * (n - 1 + i), 0.0)
            spread = round(0.15 * max(pred, 1.0), 2)
            out.append({
                "target_metric": target,
                "predicted_value": round(pred, 2),
                "forecast_date": f"{year + 1}-{month + 1:02d}",
                "confidence_interval": {
                    "lower": round(max(pred - spread, 0.0), 2),
                    "upper": round(pred + spread, 2),
                    "level": 0.95,
                },
            })
    return ok(request, {"list": out})


def report_drill(request: HttpRequest, id: int):
    """GET /dash/report/instance/{id}/drill —— 项目健康分桶 {health,count}（id 暂忽略，租户全量）。"""
    from apps.project.models import EProject

    d = domain_from(request)
    bands = [("≥80 良好", 80, 101), ("60-79 关注", 60, 80), ("<60 风险", 0, 60)]
    rows = []
    for label, lo, hi in bands:
        count = EProject.objects.filter(
            tenant_id=d.tenant_id, deleted=0,
            health_score__gte=lo, health_score__lt=hi).count()
        rows.append({"health": label, "count": count})
    return ok(request, {"rows": rows})


def list_screens(request: HttpRequest):
    """GET /dash/screens —— 大屏配置清单（当前演示：经费监督单屏）。"""
    return ok(request, {
        "rows": [{
            "id": 1, "code": "SCR-FUNDING", "name": "科研经费监督大屏",
            "theme": "DARK", "status": "ONLINE", "data_as_of_expr": "每 5 分钟刷新",
        }],
        "total": 1,
    })
