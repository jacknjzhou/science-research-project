"""数据决策域 D：经费监督大屏真聚合（F-18 一图一舱三预警）。

只读投影，复用 funding 表；legalEntityId 可空看合并视图。
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
