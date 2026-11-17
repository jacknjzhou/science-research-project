"""经费域 F API（对齐 Go modules/funding 全部 40 条路由）。

科目：/subjects、/subjects/tree（CRUD 守卫）
预算：/budgets 编制/批复/调整/追加（T14 行级冻结-实扣-释放，F-10）
到款：/incomes 登记/认领（T21 管理费）/银行流水批量导入
报销：/expenses 填单（三重指纹 40903）/提交（预算冻结+审批链）/审批/批量
外拨：/outwards 两级审批后实扣（F-24）
结转：/carryovers 结题守卫，批复生成下年度到账行（F-25）
间接费：/indirect-fees 计提（费率 0~0.30，40904）
执行：/funding/execution（project/college/subject 三维）、/funding/warnings（惰性计算）
AI：/expense/ai-invoice-review（LLM 不可用降级 REVIEW，PRD 2.4 仅建议不直写）
预警配置：/funding/warn-configs CRUD
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.funding.mappings import (
    code_of,
    fmt_ts,
    num2,
    num4,
    to_api_approval,
    to_api_budget,
    to_api_carryover,
    to_api_expense,
    to_api_income,
    to_api_invoice,
    to_api_loan,
    to_api_line,
    to_api_outward,
    to_api_subject,
    to_api_travel_standard,
    to_api_warn_config,
)
from apps.funding.models import (
    FAccountingEntry,
    FBudget,
    FBudgetLine,
    FCarryover,
    FCostPool,
    FExpense,
    FExpenseApproval,
    FIncome,
    FIndirectFee,
    FInvoice,
    FLoan,
    FOutward,
    FSettlement,
    FSubject,
    FTravelStandard,
    FVoucherSync,
    FWarnConfig,
)
from apps.notify.models import SysNotification
from apps.project.models import EProject, EProjectCategory
from core import approval
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_CONFLICT_REF,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
    ok,
    read_json,
    read_json_any,
)


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = max(int(request.GET.get("page", "1") or "1"), 1)
        size = min(max(int(request.GET.get("size", "20") or "20"), 1), 200)
    except ValueError:
        page, size = 1, 20
    return page, size, size, (page - 1) * size


def _money(s) -> Decimal | None:
    try:
        return Decimal(str(s)).quantize(Decimal("0.01"))
    except Exception:
        return None


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(s), fmt).date()
        except ValueError:
            continue
    return None


def _d2(v: Decimal) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"))


def _notify(user_id: int, typ: str, title: str, content: str, biz_ref: str, tenant_id: int):
    """通知触达（best-effort：永不阻断业务，对齐 Go Handler.notify）。"""
    if user_id and user_id > 0:
        try:
            SysNotification.objects.create(
                tenant_id=tenant_id, user_id=user_id, typ=typ,
                title=title, content=content, biz_ref=biz_ref)
        except Exception:
            pass


def _notify_role(tenant_id: int, role: str, typ: str, title: str, content: str, biz_ref: str):
    try:
        from apps.sysadmin.models import SysRole, SysUserRole, SysUser
        r = SysRole.objects.filter(code=role, tenant_id=tenant_id).first()
        if r is None:
            return
        uids = SysUserRole.objects.filter(role=r).values_list("user_id", flat=True)
        for uid in SysUser.objects.filter(id__in=uids, status="ACTIVE").values_list("id", flat=True):
            _notify(uid, typ, title, content, biz_ref, tenant_id)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 科目字典（F-01 / T15）
# ---------------------------------------------------------------------------
def list_subjects(request: HttpRequest):
    d = domain_from(request)
    rows = FSubject.objects.filter(tenant_id=d.tenant_id, deleted=0).order_by("sort_no", "id")
    return ok(request, {"list": [to_api_subject(s) for s in rows], "total": rows.count()})


def subjects_tree(request: HttpRequest):
    d = domain_from(request)
    rows = list(FSubject.objects.filter(tenant_id=d.tenant_id, deleted=0).order_by("sort_no", "id"))

    def node(s: FSubject):
        return {"id": s.id, "code": s.code, "name": s.name, "parent_id": s.parent_id,
                "level": s.level, "category": s.category, "is_leaf": s.is_leaf,
                "ratio_limit": num4(s.ratio_limit), "sort_no": s.sort_no, "children": []}

    by_id = {s.id: node(s) for s in rows}
    roots = []
    for s in rows:
        n = by_id[s.id]
        if s.parent_id and s.parent_id in by_id:
            by_id[s.parent_id]["children"].append(n)
        else:
            roots.append(n)
    return ok(request, roots)


def create_subject(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    name, category = b.get("name"), b.get("category")
    if not name or not category:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    level = 1
    parent_id = b.get("parent_id")
    if parent_id:
        p = FSubject.objects.filter(id=parent_id, tenant_id=d.tenant_id, deleted=0).first()
        if p is None:
            raise ApiError(404, CODE_NOT_FOUND, "上级科目不存在")
        level = p.level + 1
    s = FSubject.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, code=b.get("code"),
        name=name, parent_id=parent_id, level=level, category=category,
        is_leaf=bool(b.get("is_leaf", True)),
        ratio_limit=_money(b["ratio_limit"]) if b.get("ratio_limit") else None,
        applies_to=b.get("applies_to"), sort_no=b.get("sort_no") or 0,
        remark=b.get("remark"),
    )
    return ok(request, to_api_subject(s))


def update_subject(request: HttpRequest, id: int):
    d = domain_from(request)
    s = FSubject.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "科目不存在")
    b = read_json(request)
    if b.get("name") is not None:
        s.name = b["name"]
    if b.get("ratio_limit") is not None:
        s.ratio_limit = _money(b["ratio_limit"])
    if b.get("sort_no") is not None:
        s.sort_no = b["sort_no"]
    if b.get("remark") is not None:
        s.remark = b["remark"]
    s.modifier_id = d.user_id
    s.save()
    return ok(request, to_api_subject(s))


def delete_subject(request: HttpRequest, id: int):
    d = domain_from(request)
    if FSubject.objects.filter(parent_id=id, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "存在下级科目，禁止删除")
    if FBudgetLine.objects.filter(subject_id=id, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "科目已被预算引用，禁止删除")
    n = FSubject.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).update(deleted=1, updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "科目不存在")
    return ok(request, {"id": id})


# ---------------------------------------------------------------------------
# 预算（F-02/03/04 + T14 追加）
# ---------------------------------------------------------------------------
def _get_budget_or_404(budget_id: int) -> FBudget:
    b = FBudget.objects.filter(id=budget_id, deleted=0).first()
    if b is None:
        raise ApiError(404, CODE_NOT_FOUND, "预算不存在")
    return b


def create_budget(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    mode = b.get("mode")
    lines = b.get("lines") or []
    if not b.get("project_id") or not b.get("legal_entity_id") or not lines:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    if mode not in ("预算制", "包干制"):
        raise ApiError(400, CODE_BAD_REQUEST, "mode 仅支持 预算制/包干制")
    total = Decimal("0")
    for l in lines:
        amt = _money(l.get("amount"))
        if amt is None:
            raise ApiError(400, CODE_BAD_REQUEST, "金额格式错误")
        total += amt
    with transaction.atomic():
        bud = FBudget.objects.create(
            tenant_id=d.tenant_id, creator_id=d.user_id,
            project_id=b["project_id"], legal_entity_id=b["legal_entity_id"],
            mode=mode, total_approved=_d2(total),
        )
        for l in lines:
            FBudgetLine.objects.create(
                tenant_id=d.tenant_id, creator_id=d.user_id,
                budget_id=bud.id, subject_id=l["subject_id"],
                amount_planned=_money(l["amount"]),
            )
        bud.code = code_of("BUD", bud.id)
        bud.save(update_fields=["code"])
    return ok(request, to_api_budget(bud))


def get_budget(request: HttpRequest, id: int):
    bud = _get_budget_or_404(id)
    lines = FBudgetLine.objects.filter(budget_id=bud.id, deleted=0).order_by("id")
    m = to_api_budget(bud)
    m["lines"] = [to_api_line(l) for l in lines]
    return ok(request, m)


def list_budgets(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FBudget.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("project_id"):
        qs = qs.filter(project_id=request.GET["project_id"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_budget(b) for b in rows], "total": total, "page": page, "size": size})


def list_budget_lines(request: HttpRequest, id: int):
    rows = FBudgetLine.objects.filter(budget_id=id, deleted=0).order_by("id")
    return ok(request, {"list": [to_api_line(l) for l in rows], "total": rows.count()})


def submit_budget(request: HttpRequest, id: int):
    n = FBudget.objects.filter(id=id, deleted=0, status="DRAFT").update(status="SUBMITTED", updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(409, CODE_CONFLICT, "仅 DRAFT 状态可提交")
    return ok(request, to_api_budget(FBudget.objects.get(id=id)))


def approve_budget(request: HttpRequest, id: int):
    d = domain_from(request)
    n = FBudget.objects.filter(id=id, deleted=0, status="SUBMITTED").update(
        status="EXECUTING", approved_at=dj_tz.now(), approved_by=d.user_id, updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(409, CODE_CONFLICT, "仅 SUBMITTED 状态可批复")
    return ok(request, to_api_budget(FBudget.objects.get(id=id)))


def adjust_budget(request: HttpRequest, id: int):
    d = domain_from(request)
    b = read_json(request)
    lines = b.get("lines") or []
    if not lines:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    with transaction.atomic():
        bud = FBudget.objects.filter(id=id, deleted=0, status="EXECUTING").first()
        if bud is None:
            raise ApiError(409, CODE_CONFLICT, "仅 EXECUTING 状态可调整")
        total_delta = Decimal("0")
        for l in lines:
            delta = _money(l.get("delta"))
            if delta is None:
                raise ApiError(400, CODE_BAD_REQUEST, "delta 格式错误")
            total_delta += delta
            n = FBudgetLine.objects.filter(id=l["line_id"], budget_id=bud.id, deleted=0).update(
                amount_adjusted=F("amount_adjusted") + delta, updated_at=dj_tz.now())
            if n == 0:
                raise ApiError(404, CODE_NOT_FOUND, "预算行不存在")
        bud.total_adjusted = _d2(bud.total_adjusted + total_delta)
        bud.version += 1
        bud.modifier_id = d.user_id
        bud.save()
    return ok(request, to_api_budget(FBudget.objects.get(id=id)))


def line_balance(request: HttpRequest, lineId: int):
    l = FBudgetLine.objects.filter(id=lineId, deleted=0).first()
    if l is None:
        raise ApiError(404, CODE_NOT_FOUND, "预算行不存在")
    return ok(request, to_api_line(l))


def append_budget(request: HttpRequest, id: int):
    """T14 预算追加（F-23）：EXECUTING → ADJUSTING，pending_delta 头/行同步累计。"""
    d = domain_from(request)
    b = read_json(request)
    lines = b.get("lines") or []
    if not lines:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    total = Decimal("0")
    for l in lines:
        delta = _money(l.get("delta"))
        if delta is None or delta <= 0:
            raise ApiError(400, CODE_BAD_REQUEST, "delta 须为正数")
        total += delta
    n = FBudget.objects.filter(id=id, deleted=0, status="EXECUTING").update(
        pending_delta=F("pending_delta") + total, status="ADJUSTING", updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(409, CODE_CONFLICT, "仅 EXECUTING 预算可追加")
    for l in lines:
        n2 = FBudgetLine.objects.filter(id=l["line_id"], budget_id=id, deleted=0).update(
            pending_delta=F("pending_delta") + _money(l["delta"]), updated_at=dj_tz.now())
        if n2 == 0:
            raise ApiError(404, CODE_NOT_FOUND, "预算行不存在")
    _notify_role(d.tenant_id, "R-LEADER", "TODO", "预算追加待批复",
                 f"预算 #{id} 追加申请 ¥{num2(total)}，待领导批复", f"budget/{id}/append")
    return ok(request, {"budget_id": id, "pending_delta": num2(total)})


def approve_budget_append(request: HttpRequest, id: int):
    d = domain_from(request)
    with transaction.atomic():
        n = FBudget.objects.filter(id=id, deleted=0, status="ADJUSTING").update(
            total_approved=F("total_approved") + F("pending_delta"), pending_delta=Decimal("0"),
            version=F("version") + 1, status="EXECUTING", updated_at=dj_tz.now())
        if n == 0:
            raise ApiError(409, CODE_CONFLICT, "仅 ADJUSTING 状态可批复追加")
        FBudgetLine.objects.filter(budget_id=id, deleted=0).exclude(pending_delta=0).update(
            amount_adjusted=F("amount_adjusted") + F("pending_delta"), pending_delta=Decimal("0"),
            updated_at=dj_tz.now())
    return ok(request, to_api_budget(FBudget.objects.get(id=id)))


# ---------------------------------------------------------------------------
# 到款（F-05/F-06 + T21 管理费）
# ---------------------------------------------------------------------------
def create_income(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    amount = _money(b.get("amount"))
    if not b.get("legal_entity_id") or amount is None:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    inc = FIncome.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, legal_entity_id=b["legal_entity_id"],
        receipt_no=b.get("receipt_no"), receipt_date=_parse_date(b.get("receipt_date")),
        amount=amount, payer_name=b.get("payer_name"), payer_bank=b.get("payer_bank"),
        purpose_text=b.get("purpose_text"), bank_flow_no=b.get("bank_flow_no"),
    )
    inc.code = code_of("INC", inc.id)
    inc.save(update_fields=["code"])
    return ok(request, to_api_income(inc))


def list_incomes(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FIncome.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("claim_status"):
        qs = qs.filter(claim_status=request.GET["claim_status"])
    if request.GET.get("project_id"):
        qs = qs.filter(project_id=request.GET["project_id"])
    if request.GET.get("kw"):
        kw = request.GET["kw"]
        qs = qs.filter(Q(payer_name__icontains=kw) | Q(purpose_text__icontains=kw) | Q(bank_flow_no__icontains=kw))
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_income(i) for i in rows], "total": total, "page": page, "size": size})


def _calc_mgmt_fee(project_id: int, amount: Decimal) -> Decimal | None:
    """T21：项目分类 mgmt_fee_pct → amount × pct / 100（无分类/无费率 → None）。"""
    p = EProject.objects.filter(id=project_id, deleted=0).first()
    if p is None or p.category_id is None:
        return None
    c = EProjectCategory.objects.filter(id=p.category_id, deleted=0).first()
    if c is None or not c.mgmt_fee_pct:
        return None
    return _d2(amount * Decimal(str(c.mgmt_fee_pct)) / Decimal("100"))


def _post_accounting_entry(
    tenant_id: int,
    user_id: int,
    source_txn_type: str,
    source_txn_id: int,
    project_id: int | None,
    legal_entity_id: int,
    period: str,
    fin_lines: list[dict],
    bud_lines: list[dict],
) -> FAccountingEntry:
    """平行记账双分录落库（F-21 / detail 4.5）。

    幂等键：(tenant_id, source_txn_type, source_txn_id, period, deleted=0) ——
    已存在则原样返回既有行（不重算不重写）。借贷不平先于任何写入抛 42200。
    分录行格式：{"subject": "<科目码>", "direction": "debit"|"credit", "amount": "1234.00"}。
    """
    existing = (
        FAccountingEntry.objects.filter(
            tenant_id=tenant_id, source_txn_type=source_txn_type,
            source_txn_id=source_txn_id, period=period, deleted=0,
        ).first()
    )
    if existing is not None:
        return existing

    def _sum(lines: list[dict], direction: str) -> Decimal:
        return sum(
            (_d2(Decimal(str(x["amount"]))) for x in lines if x["direction"] == direction),
            Decimal("0"),
        )

    fin_debit, fin_credit = _sum(fin_lines, "debit"), _sum(fin_lines, "credit")
    bud_debit, bud_credit = _sum(bud_lines, "debit"), _sum(bud_lines, "credit")
    if fin_debit != fin_credit or bud_debit != bud_credit:
        raise ApiError(422, "42200", "借贷不平")

    ae = FAccountingEntry.objects.create(
        tenant_id=tenant_id,
        source_txn_type=source_txn_type,
        source_txn_id=source_txn_id,
        project_id=project_id,
        legal_entity_id=legal_entity_id,
        period=period,
        fin_entry_json={"lines": fin_lines},
        bud_entry_json={"lines": bud_lines},
        status="POSTED",
        posted_finance=True,
        posted_budget=True,
        reconcile_status="BALANCED",
        creator_id=user_id,
        modifier_id=user_id,
    )
    ae.code = code_of("ACC", ae.id)
    ae.save(update_fields=["code", "updated_at"])
    return ae


def claim_income(request: HttpRequest, id: int):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("project_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    with transaction.atomic():
        inc = FIncome.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0, claim_status="UNCLAIMED").first()
        if inc is None:
            raise ApiError(409, CODE_CONFLICT, "仅 UNCLAIMED 状态可认领")
        inc.claim_status = "CLAIMED"
        inc.project_id = b["project_id"]
        inc.claimed_by = d.user_id
        inc.claimed_at = dj_tz.now()
        inc.modifier_id = d.user_id
        fee = _calc_mgmt_fee(b["project_id"], inc.amount)
        if fee is not None:
            inc.mgmt_fee = fee
        inc.save()
        # 平行记账（F-21/4.5）：income.claimed → 借 银行存款 / 贷 非同级财政拨款收入
        _post_accounting_entry(
            tenant_id=d.tenant_id, user_id=d.user_id,
            source_txn_type="INCOME", source_txn_id=inc.id,
            project_id=inc.project_id, legal_entity_id=inc.legal_entity_id,
            period=dj_tz.localdate().strftime("%Y%m"),
            fin_lines=[
                {"subject": "1002", "direction": "debit", "amount": str(inc.amount)},
                {"subject": "4601", "direction": "credit", "amount": str(inc.amount)},
            ],
            bud_lines=[
                {"subject": "8001", "direction": "debit", "amount": str(inc.amount)},
                {"subject": "8201", "direction": "credit", "amount": str(inc.amount)},
            ],
        )
    return ok(request, to_api_income(inc))


def import_bank_flow(request: HttpRequest):
    """F-06 批量导入：bank_flow_no 幂等键，同租户已存在跳过。幂等检查失败必须显式失败。"""
    d = domain_from(request)
    rows = read_json_any(request)
    if not isinstance(rows, list) or not rows:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误：非空数组必填")
    imported = skipped = 0
    for r in rows:
        flow = r.get("bank_flow_no")
        amount = _money(r.get("amount"))
        if not flow or amount is None:
            raise ApiError(400, CODE_BAD_REQUEST, "bank_flow_no/amount 必填")
        if FIncome.objects.filter(tenant_id=d.tenant_id, bank_flow_no=flow, deleted=0).exists():
            skipped += 1
            continue
        FIncome.objects.create(
            tenant_id=d.tenant_id, creator_id=d.user_id, legal_entity_id=1,
            receipt_no=r.get("receipt_no"), receipt_date=_parse_date(r.get("receipt_date")),
            amount=amount, payer_name=r.get("payer_name"), purpose_text=r.get("purpose_text"),
            bank_flow_no=flow,
        )
        imported += 1
    return ok(request, {"imported": imported, "skipped": skipped})


# ---------------------------------------------------------------------------
# 报销（F-07/F-09/F-10 + 指纹查重）
# ---------------------------------------------------------------------------
def _fingerprint(no: str, amount: str, dt: str) -> str:
    return hashlib.sha256(f"{no}|{amount}|{dt}".encode()).hexdigest()


def create_expense(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    amount = _money(b.get("amount"))
    if (not b.get("project_id") or not b.get("legal_entity_id") or amount is None
            or not b.get("expense_type")):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    if b["expense_type"] not in ("EQUIPMENT", "MATERIAL", "TRAVEL", "MEETING", "LABOR", "EXPERT", "OTHER"):
        raise ApiError(400, CODE_BAD_REQUEST, "expense_type 非法")
    submit_mode = b.get("submit_mode") or "预算制"
    if submit_mode not in ("预算制", "包干制"):
        raise ApiError(400, CODE_BAD_REQUEST, "submit_mode 仅支持 预算制/包干制")
    # 差旅匹配元数据（M1-a A3/P98，随填单提交；匹配在 submit 时点做，warn-only）
    # 键名 camelCase 对齐契约 03-F ExpenseCreateRequest（终审收口 Task 8 Important①）
    travel_staff_category = b.get("travelStaffCategory")
    travel_city_tier = b.get("travelCityTier")
    # 关联借款（冲销溯源）：借款须存在于本租户（40401；状态不设限，冲销时点再校验）
    related_loan_id = b.get("relatedLoanId")
    if related_loan_id is not None:
        loan = FLoan.objects.filter(id=related_loan_id, tenant_id=d.tenant_id, deleted=0).first()
        if loan is None:
            raise ApiError(404, CODE_NOT_FOUND, "关联借款不存在")
    fp_hash = None
    invoice_no = b.get("invoice_no")
    invoice_date = b.get("invoice_date")
    if invoice_no:
        fp_hash = _fingerprint(invoice_no, str(b["amount"]), invoice_date or "")
    try:
        e = FExpense.objects.create(
            tenant_id=d.tenant_id, creator_id=d.user_id,
            project_id=b["project_id"], budget_line_id=b.get("budget_line_id"),
            legal_entity_id=b["legal_entity_id"], applicant_user_id=d.user_id,
            amount=amount, expense_category=b.get("expense_category"),
            expense_type=b["expense_type"], description=b.get("description"),
            fingerprint_invoice_no=invoice_no, fingerprint_amount=amount,
            fingerprint_invoice_date=_parse_date(invoice_date), fingerprint_hash=fp_hash,
            submit_mode=submit_mode,
            travel_staff_category=travel_staff_category,
            travel_city_tier=travel_city_tier,
            related_loan_id=related_loan_id,
        )
    except Exception:
        raise ApiError(409, "40903", "同一发票（号码+金额+日期）已存在在途报销单") from None
    e.code = code_of("EXP", e.id)
    e.save(update_fields=["code"])
    return ok(request, to_api_expense(e))


def list_expenses(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FExpense.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("project_id"):
        qs = qs.filter(project_id=request.GET["project_id"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("applicant_user_id"):
        qs = qs.filter(applicant_user_id=request.GET["applicant_user_id"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_expense(e) for e in rows], "total": total, "page": page, "size": size})


def get_expense(request: HttpRequest, id: int):
    e = FExpense.objects.filter(id=id, deleted=0).first()
    if e is None:
        raise ApiError(404, CODE_NOT_FOUND, "报销单不存在")
    steps = FExpenseApproval.objects.filter(expense_id=e.id, deleted=0).order_by("step_order")
    m = to_api_expense(e)
    m["approvals"] = [to_api_approval(s) for s in steps]
    return ok(request, m)


def submit_expense(request: HttpRequest, id: int):
    """提交事务链：DRAFT→SUBMITTED → 指纹查重 40903 → 预算冻结 40902 → 审批链生成。
    任一环节失败回退 DRAFT（对齐 Go 逐段回退语义）。"""
    d = domain_from(request)
    with transaction.atomic():
        e = FExpense.objects.filter(id=id, deleted=0, status="DRAFT").select_for_update().first()
        if e is None:
            raise ApiError(409, CODE_CONFLICT, "仅 DRAFT 状态可提交")
        # 三重指纹查重（提交时点）
        if e.fingerprint_hash:
            taken = (FExpense.objects.filter(
                tenant_id=d.tenant_id, fingerprint_hash=e.fingerprint_hash, deleted=0
            ).exclude(status__in=("REJECTED", "RETURNED")).exclude(id=e.id).first())
            if taken is not None:
                raise ApiError(409, "40903", "同一发票（号码+金额+日期）已存在在途报销单")
        # 预算冻结（F-10）：FOR UPDATE 校验余额
        if e.submit_mode == "预算制" and e.budget_line_id:
            line = FBudgetLine.objects.select_for_update().filter(id=e.budget_line_id, deleted=0).first()
            if line is None:
                raise ApiError(404, CODE_NOT_FOUND, "预算行不存在")
            if line.remaining < e.amount:
                raise ApiError(409, CODE_CONFLICT_REF, "预算行可支余额不足，冻结失败")
            line.amount_frozen = _d2(line.amount_frozen + e.amount)
            line.save(update_fields=["amount_frozen", "updated_at"])
            e.frozen_at = dj_tz.now()
        # 差旅超标提示（A3/P98，warn-only）：仅 TRAVEL 且带了匹配元数据才查标准；
        # 冻结成功后同事务内计算，任何异常不阻断提交（不 raise，不回滚）。
        e.travel_over_limit = False
        if e.expense_type == "TRAVEL" and e.travel_staff_category and e.travel_city_tier:
            # FExpense 无差旅日期字段 → 以提交当日为匹配基准（标准 effective 窗口按今天取）
            matched = _match_travel_standard(d.tenant_id, e.travel_staff_category, e.travel_city_tier, dj_tz.localdate())
            if matched is not None and e.amount > matched.total_cap:
                e.travel_over_limit = True
        e.status = "SUBMITTED"
        e.submitted_at = dj_tz.now()
        e.modifier_id = d.user_id
        e.save()
        # 审批链（F-09 简化规则路由）：<10 万 1 步 R-MANAGER，≥10 万 2 步
        steps = ["R-MANAGER"]
        if e.amount >= Decimal("100000"):
            steps.append("R-LEADER")
        for i, role in enumerate(steps):
            FExpenseApproval.objects.create(
                tenant_id=d.tenant_id, creator_id=d.user_id,
                expense_id=e.id, step_order=i + 1, role=role,
            )
    _notify_role(d.tenant_id, steps[0], "EXPENSE_APPROVAL", f"待审批：报销单 {e.code or e.id}",
                 f"金额 {num2(e.amount)} 元，请及时审批", f"expense/{e.id}")
    return ok(request, to_api_expense(FExpense.objects.get(id=id)))


def _approve_one(d, expense_id: int, action: str, comment: str):
    """单条报销审批核心（对齐 Go approveOne）。返回错误 tuple 或 None。"""
    e = FExpense.objects.filter(id=expense_id, deleted=0).first()
    if e is None:
        return 404, CODE_NOT_FOUND, "报销单不存在"
    if e.status not in ("SUBMITTED", "AI_REVIEW", "HUMAN_REVIEW"):
        return 409, CODE_CONFLICT, "单据不在审批中状态"
    step = FExpenseApproval.objects.filter(expense_id=expense_id, status="PENDING").order_by("step_order").first()
    if step is None:
        return 409, CODE_CONFLICT, "无待审步骤"
    if step.role not in set(d.roles) and "R-ADMIN" not in set(d.roles):
        return 403, CODE_FORBIDDEN, f"当前步骤需要 {step.role} 角色"
    with transaction.atomic():
        n = FExpenseApproval.objects.filter(id=step.id, status="PENDING").update(
            status="DONE", action=action, comment=comment,
            approver_user_id=d.user_id, acted_at=dj_tz.now(), updated_at=dj_tz.now())
        if n == 0:
            return 409, CODE_CONFLICT, "无待审步骤"
        steps = FExpenseApproval.objects.filter(expense_id=expense_id, deleted=0)
        done = steps.filter(status="DONE").count()
        final = done == steps.count()
        if action == "APPROVE" and final:
            new_status = "APPROVED"
        elif action == "REJECT":
            new_status = "REJECTED"
        elif action == "RETURN":
            new_status = "RETURNED"
        else:
            new_status = "HUMAN_REVIEW"
        # 预算动作（F-10）：末步批准 → 冻结转实扣；驳回/退回 → 解冻
        if action == "APPROVE" and final and e.budget_line_id and e.submit_mode == "预算制":
            FBudgetLine.objects.filter(id=e.budget_line_id, deleted=0).update(
                amount_frozen=F("amount_frozen") - e.amount,
                amount_used=F("amount_used") + e.amount, updated_at=dj_tz.now())
            # 平行记账（F-21/4.5）：expense.approved → 借 业务活动费用 / 贷 银行存款
            _post_accounting_entry(
                tenant_id=e.tenant_id, user_id=d.user_id,
                source_txn_type="EXPENSE", source_txn_id=e.id,
                project_id=e.project_id, legal_entity_id=e.legal_entity_id,
                period=dj_tz.localdate().strftime("%Y%m"),
                fin_lines=[
                    {"subject": "5001", "direction": "debit", "amount": str(e.amount)},
                    {"subject": "1002", "direction": "credit", "amount": str(e.amount)},
                ],
                bud_lines=[
                    {"subject": "7201", "direction": "debit", "amount": str(e.amount)},
                    {"subject": "8001", "direction": "credit", "amount": str(e.amount)},
                ],
            )
        if action in ("REJECT", "RETURN") and e.budget_line_id and e.submit_mode == "预算制":
            FBudgetLine.objects.filter(id=e.budget_line_id, deleted=0).update(
                amount_frozen=F("amount_frozen") - e.amount,
                amount_released=F("amount_released") + e.amount, updated_at=dj_tz.now())
        approval.log(d.tenant_id, "EXPENSE", expense_id, step.step_order, d.user_id,
                     step.role or "", action, comment)
        FExpense.objects.filter(id=expense_id).update(status=new_status, updated_at=dj_tz.now())
    # 触达报销人（best-effort）
    title, content = {
        "APPROVE": ("报销审批通过" if final else "报销进入下一审批步",
                    f"报销单 {e.code or e.id} 已通过第 {step.step_order} 步" if not final
                    else f"报销单 {e.code or e.id} 已全部审批通过并实扣预算"),
        "REJECT": ("报销被驳回", f"报销单 {e.code or e.id} 被驳回：预算已解冻，可修改后重新提交"),
        "RETURN": ("报销被退回", f"报销单 {e.code or e.id} 被退回修改：预算已解冻"),
    }[action]
    _notify(e.applicant_user_id, "EXPENSE_RESULT", title, content, f"expense/{expense_id}", d.tenant_id)
    return None


def approval_action(request: HttpRequest, id: int):
    d = domain_from(request)
    b = read_json(request)
    action = b.get("action")
    if action not in ("APPROVE", "REJECT", "RETURN"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 仅支持 APPROVE/REJECT/RETURN")
    err = _approve_one(d, id, action, b.get("comment"))
    if err:
        code, biz_code, msg = err
        raise ApiError(code, biz_code, msg)
    return ok(request, to_api_expense(FExpense.objects.get(id=id)))


def approval_batch(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    ids, action = b.get("ids"), b.get("action")
    if not ids or not isinstance(ids, list) or action not in ("APPROVE", "REJECT", "RETURN"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误：ids 非空数组 + action")
    results, ok_n = [], 0
    for eid in ids:
        err = _approve_one(d, eid, action, b.get("comment"))
        if err:
            results.append({"id": eid, "ok": False, "err": err[2]})
        else:
            ok_n += 1
            results.append({"id": eid, "ok": True})
    return ok(request, {"total": len(ids), "ok": ok_n, "results": results})


# ---------------------------------------------------------------------------
# 外拨（F-24，T14 两级审批）
# ---------------------------------------------------------------------------
def create_outward(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    amount = _money(b.get("amount"))
    if (not b.get("project_id") or not b.get("to_unit") or amount is None or amount <= 0):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误（金额须为正数）")
    o = FOutward.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        project_id=b["project_id"], budget_id=b.get("budget_id"),
        budget_line_id=b.get("budget_line_id"), amount=amount,
        to_unit=b["to_unit"], reason=b.get("reason"),
    )
    return ok(request, to_api_outward(o))


def list_outwards(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FOutward.objects.filter(tenant_id=d.tenant_id, deleted=0)
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_outward(o) for o in rows], "total": total, "page": page, "size": size})


def outward_action(request: HttpRequest, id: int):
    """两级：R-MANAGER 一级 → R-LEADER 终审；终审后预算行实扣（余额不足 40902）。
    R-LEADER/R-ADMIN 持双角色一次打通（一级已批则直接终审）。"""
    d = domain_from(request)
    b = read_json(request)
    action = b.get("action")
    if action not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 仅 APPROVE|REJECT")
    is_leader = "R-LEADER" in set(d.roles) or "R-ADMIN" in set(d.roles)
    with transaction.atomic():
        o = FOutward.objects.select_for_update().filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
        if o is None:
            raise ApiError(404, CODE_NOT_FOUND, "外拨单不存在")
        if action == "REJECT":
            if o.status not in ("PENDING",):
                raise ApiError(409, CODE_CONFLICT, "状态不允许该操作")
            o.status = "REJECTED"
            o.approved_by = d.user_id
            o.approved_at = dj_tz.now()
            o.save()
            return ok(request, to_api_outward(o))
        # APPROVE
        if not is_leader:
            if o.status != "PENDING" or o.first_approved_by is not None:
                raise ApiError(409, CODE_CONFLICT, "仅 PENDING 且未一级批复可批")
            o.first_approved_by = d.user_id
            o.first_approved_at = dj_tz.now()
            o.save()
            return ok(request, to_api_outward(o))
        # 终审（先补一级）
        if o.first_approved_by is None:
            o.first_approved_by = d.user_id
            o.first_approved_at = dj_tz.now()
            o.save()
        if o.status != "PENDING":
            raise ApiError(409, CODE_CONFLICT, "单据不在待终审状态")
        if o.budget_line_id:
            line = FBudgetLine.objects.select_for_update().filter(id=o.budget_line_id, deleted=0).first()
            if line is None or line.remaining < o.amount:
                raise ApiError(409, CODE_CONFLICT_REF, "预算行余额不足，外拨无法入账")
            line.amount_used = _d2(line.amount_used + o.amount)
            line.save(update_fields=["amount_used", "updated_at"])
        o.status = "APPROVED"
        o.approved_by = d.user_id
        o.approved_at = dj_tz.now()
        o.save()
        # 平行记账（F-21/4.5）：外拨终审（PAID 语义）→ 借 对外拨付款 / 贷 银行存款
        # FOutward 无 legal_entity_id 字段：从项目取，缺省 1（对齐 M1-a create_loan 先例）。
        _out_legal_entity = (
            EProject.objects.filter(id=o.project_id, deleted=0)
            .values_list("legal_entity_id", flat=True).first()
        ) or 1
        _post_accounting_entry(
            tenant_id=o.tenant_id, user_id=d.user_id,
            source_txn_type="DISBURSEMENT", source_txn_id=o.id,
            project_id=o.project_id, legal_entity_id=_out_legal_entity,
            period=dj_tz.localdate().strftime("%Y%m"),
            fin_lines=[
                {"subject": "7701", "direction": "debit", "amount": str(o.amount)},
                {"subject": "1002", "direction": "credit", "amount": str(o.amount)},
            ],
            bud_lines=[
                {"subject": "7501", "direction": "debit", "amount": str(o.amount)},
                {"subject": "8001", "direction": "credit", "amount": str(o.amount)},
            ],
        )
    _notify(o.creator_id, "MESSAGE", "外拨已批复",
            f"外拨单 #{o.id} 已终审通过并从预算扣减", f"outward/{o.id}", d.tenant_id)
    return ok(request, to_api_outward(FOutward.objects.get(id=id)))


# ---------------------------------------------------------------------------
# 结转（F-25）
# ---------------------------------------------------------------------------
def create_carryover(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    amount = _money(b.get("amount"))
    if (not b.get("project_id") or amount is None or amount <= 0
            or not b.get("fiscal_year") or not b.get("target_year")):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    if int(b["target_year"]) <= int(b["fiscal_year"]):
        raise ApiError(400, CODE_BAD_REQUEST, "目标年度须晚于来源年度")
    p = EProject.objects.filter(id=b["project_id"], deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    if p.status != "CLOSED":
        raise ApiError(409, CODE_CONFLICT, "仅结题（CLOSED）项目可发起结转")
    co = FCarryover.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        project_id=b["project_id"], fiscal_year=int(b["fiscal_year"]),
        target_year=int(b["target_year"]), amount=amount, remark=b.get("remark"),
    )
    return ok(request, to_api_carryover(co))


def list_carryovers(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FCarryover.objects.filter(tenant_id=d.tenant_id, deleted=0)
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_carryover(c) for c in rows], "total": total, "page": page, "size": size})


def carryover_action(request: HttpRequest, id: int):
    """批复（R-MANAGER/R-LEADER/R-ADMIN）→ 生成下年度 F_INCOME 结转到账行（幂等键 CRO-<id>）。"""
    d = domain_from(request)
    b = read_json(request)
    action = b.get("action")
    if action not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 仅 APPROVE|REJECT")
    co = FCarryover.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if co is None:
        raise ApiError(404, CODE_NOT_FOUND, "结转单不存在")
    if action == "REJECT":
        if co.status != "PENDING":
            raise ApiError(409, CODE_CONFLICT, "仅 PENDING 可操作")
        co.status = "REJECTED"
        co.save(update_fields=["status", "updated_at"])
        return ok(request, to_api_carryover(co))
    if co.status != "PENDING":
        raise ApiError(409, CODE_CONFLICT, "仅 PENDING 可操作")
    co.status = "APPROVED"
    co.save(update_fields=["status", "updated_at"])
    if co.income_id is None:
        flow = f"CRO-{co.id}"
        inc, created = FIncome.objects.get_or_create(
            tenant_id=d.tenant_id, bank_flow_no=flow, deleted=0,
            defaults={
                "creator_id": d.user_id, "legal_entity_id": 1,
                "receipt_date": dj_tz.localdate(), "amount": co.amount,
                "purpose_text": f"项目 #{co.project_id} 结转 {co.fiscal_year}→{co.target_year}",
            })
        co.income_id = inc.id
        co.save(update_fields=["income_id", "updated_at"])
    return ok(request, to_api_carryover(co))


# ---------------------------------------------------------------------------
# 间接费（F-12）
# ---------------------------------------------------------------------------
def _sum_claimed_income(tenant_id: int, project_id: int) -> Decimal:
    r = FIncome.objects.filter(
        tenant_id=tenant_id, project_id=project_id, claim_status="CLAIMED", deleted=0
    ).aggregate(t=Sum("amount"))
    return _d2(r["t"] or 0)


def _sum_expense(tenant_id: int, project_id: int, statuses: tuple) -> Decimal:
    r = FExpense.objects.filter(
        tenant_id=tenant_id, project_id=project_id, deleted=0, status__in=statuses
    ).aggregate(t=Sum("amount"))
    return _d2(r["t"] or 0)


def _sum_budget_approved(tenant_id: int, project_id: int) -> Decimal:
    r = FBudget.objects.filter(
        tenant_id=tenant_id, project_id=project_id, deleted=0,
        status__in=("EXECUTING", "ADJUSTING", "RE_APPROVED", "CLOSED")
    ).aggregate(t=Sum("total_approved"))
    return _d2(r["t"] or 0)


def calculate_indirect_fee(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    rate = float(b.get("rate") if b.get("rate") is not None else 0.20)
    if rate < 0 or rate > 0.30:
        raise ApiError(422, "40904", "间接费率须在 0~0.30 内")
    if not b.get("project_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    p = EProject.objects.filter(id=b["project_id"], deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    income = _sum_claimed_income(d.tenant_id, p.id)
    used = _sum_expense(d.tenant_id, p.id, ("APPROVED", "PAID", "VOUCHER_SYNCED"))
    budget = _sum_budget_approved(d.tenant_id, p.id)
    indirect = _d2(income * Decimal(str(rate)))
    period = f"{dj_tz.localdate():%Y%m}"
    detail = {"rate": rate, "base": "claimed_income", "income": num2(income), "formula": "income * rate"}
    fee, _ = FIndirectFee.objects.update_or_create(
        project_id=p.id, tenant_id=d.tenant_id, deleted=0,
        defaults={
            "creator_id": d.user_id,
            "legal_entity_id": p.legal_entity_id, "period": period,
            "total_budget": budget, "actual_income": income, "actual_expense": used,
            "indirect_rate": Decimal(str(rate)).quantize(Decimal("0.0001")),
            "indirect_amount": indirect,
            "performance_rate": Decimal("0"), "performance_amount": Decimal("0"),
            "calc_detail": detail, "modifier_id": d.user_id,
        })
    return ok(request, {
        "id": fee.id, "projectId": fee.project_id, "period": fee.period,
        "actualIncome": num2(fee.actual_income), "indirectRate": num4(fee.indirect_rate),
        "indirectAmount": num2(fee.indirect_amount),
    })


def page_indirect_fees(request: HttpRequest):
    """契约 GET /indirect-fees/calculate：计提记录分页（projectId 可选过滤）。"""
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FIndirectFee.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("project_id"):
        qs = qs.filter(project_id=request.GET["project_id"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [{
        "id": f.id, "project_id": f.project_id, "period": f.period,
        "total_budget": num2(f.total_budget), "actual_income": num2(f.actual_income),
        "actual_expense": num2(f.actual_expense),
        "indirect_rate": num4(f.indirect_rate), "indirect_amount": num2(f.indirect_amount),
        "calc_detail": f.calc_detail,
    } for f in rows], "total": total, "page": page, "size": size})


def list_indirect_fees(request: HttpRequest):
    d = domain_from(request)
    pid = request.GET.get("project_id")
    if not pid:
        raise ApiError(400, CODE_BAD_REQUEST, "project_id 必填")
    rows = FIndirectFee.objects.filter(project_id=pid, tenant_id=d.tenant_id, deleted=0)
    return ok(request, {"list": [{
        "id": f.id, "project_id": f.project_id, "period": f.period,
        "total_budget": num2(f.total_budget), "actual_income": num2(f.actual_income),
        "actual_expense": num2(f.actual_expense),
        "indirect_rate": num4(f.indirect_rate), "indirect_amount": num2(f.indirect_amount),
        "calc_detail": f.calc_detail,
    } for f in rows], "total": rows.count()})


# ---------------------------------------------------------------------------
# 执行率聚合 + 预警（T23）
# ---------------------------------------------------------------------------
def _execution_of(tenant_id: int, project_id: int) -> dict:
    budget = _sum_budget_approved(tenant_id, project_id)
    income = _sum_claimed_income(tenant_id, project_id)
    used = _sum_expense(tenant_id, project_id, ("APPROVED", "PAID", "VOUCHER_SYNCED"))
    frozen = _sum_expense(tenant_id, project_id, ("SUBMITTED", "AI_REVIEW", "HUMAN_REVIEW"))
    remaining = budget - used - frozen
    rate = float(used / budget) if budget > 0 else 0.0
    rate_income = float(used / income) if income > 0 else 0.0
    return {
        "projectId": project_id,
        "budgetApproved": num2(budget), "incomeTotal": num2(income),
        "used": num2(used), "frozen": num2(frozen), "remaining": num2(remaining),
        "execRateByBudget": rate, "execRateByIncome": rate_income,
    }


def funding_execution(request: HttpRequest):
    d = domain_from(request)
    dim = request.GET.get("dim", "project")
    if dim in ("college", "subject"):
        # 口径与 executionOf 一致：approved=计划+调整、used=实扣、frozen=冻结
        # college：按项目承担部门分组；subject：按预算科目分组
        budgets = {b.id: b.project_id for b in FBudget.objects.filter(tenant_id=d.tenant_id, deleted=0)}
        lines = list(FBudgetLine.objects.filter(budget_id__in=set(budgets), deleted=0))
        projects = ({p.id: (p.department_id or 0)
                     for p in EProject.objects.filter(tenant_id=d.tenant_id, deleted=0)}
                    if dim == "college" else None)

        def dim_key(bl: FBudgetLine) -> int:
            if projects is None:
                return bl.subject_id
            return projects.get(budgets.get(bl.budget_id), 0)

        groups: dict[int, list[FBudgetLine]] = {}
        for bl in lines:
            groups.setdefault(dim_key(bl), []).append(bl)
        out = []
        for dim_id in sorted(groups):
            sub = groups[dim_id]
            approved = sum(bl.amount_planned + bl.amount_adjusted for bl in sub)
            used = sum(bl.amount_used for bl in sub)
            frozen = sum(bl.amount_frozen for bl in sub)
            rate = float(used / approved) if approved > 0 else 0.0
            out.append({
                "dimId": dim_id, "approved": num2(approved), "used": num2(used),
                "frozen": num2(frozen), "remaining": num2(approved - used - frozen), "execRate": rate,
            })
        return ok(request, {"list": out, "total": len(out)})
    pid = request.GET.get("project_id")
    if not pid:
        raise ApiError(400, CODE_BAD_REQUEST, "project_id 必填")
    return ok(request, _execution_of(d.tenant_id, int(pid)))


def funding_warnings(request: HttpRequest):
    """惰性计算不落库：WARN ≥80%；CRITICAL ≥100%；DEADLINE_RISK 结题窗口 30 天内且 <100%。"""
    d = domain_from(request)
    pid = request.GET.get("project_id")
    qs = EProject.objects.filter(
        tenant_id=d.tenant_id, deleted=0,
        status__in=("EXECUTING", "MID_CHECK", "CHANGING", "CORRECTING", "COMPLETING", "DELAYED"))
    if pid:
        qs = qs.filter(id=pid)
    out = []
    today = dj_tz.localdate()
    for p in qs.order_by("id"):
        m = _execution_of(d.tenant_id, p.id)
        rate = m["execRateByBudget"]
        level = message = None
        if rate >= 1.0:
            level, message = "CRITICAL", "经费执行率已达 100%，请关注后续支出合规性"
        elif rate >= 0.8:
            level, message = "WARN", "经费执行率已超过 80%，请评估剩余预算安排"
        deadline = p.actual_end_date or p.end_date
        if level != "CRITICAL" and deadline:
            days = (deadline - today).days
            if 0 <= days <= 30 and rate < 1.0:
                level, message = "DEADLINE_RISK", f"距结题窗口 {days} 天，执行率 {rate*100:.1f}%，存在突击支出风险"
        if not level:
            continue
        out.append({
            "projectId": p.id, "projectCode": p.code, "projectName": p.title,
            "level": level, "execRate": rate,
            "deadline": f"{deadline:%Y-%m-%d}" if deadline else None,
            "message": message,
        })
        if level == "CRITICAL":
            _notify(p.pi_user_id, "FUNDING_WARNING", f"经费预警：项目 {p.title}",
                    message, f"project/{p.id}", d.tenant_id)
    return ok(request, {"list": out, "total": len(out)})


# ---------------------------------------------------------------------------
# AI 发票审核（F-15，仅建议永不直写）
# ---------------------------------------------------------------------------
AI_CONFIDENCE_FLOOR = 0.85


def _degraded_review(reason: str) -> dict:
    return {"verdict": "REVIEW", "confidence": 0,
            "issues": [{"rule": "SERVICE_DEGRADED", "reason": reason}], "available": False}


def _normalize_verdict(v: str) -> str:
    v = (v or "").upper()
    return v if v in ("PASS", "REJECT") else "REVIEW"


def ai_invoice_review(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("expenseId"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    e = FExpense.objects.filter(id=b["expenseId"], deleted=0).first()
    if e is None:
        raise ApiError(404, CODE_NOT_FOUND, "报销单不存在")
    from django.conf import settings

    if not settings.LLM_BASE_URL:
        return ok(request, _degraded_review("AI 审核通道未配置"))
    exec_m = _execution_of(d.tenant_id, e.project_id)
    ctx = {
        "expense": to_api_expense(e),
        "execution": {"budgetApproved": exec_m["budgetApproved"], "used": exec_m["used"],
                      "frozen": exec_m["frozen"], "execRateByBudget": exec_m["execRateByBudget"]},
        "rules": [
            "报销金额不得超过该预算科目可支余额",
            "同一发票（号码+金额+开票日期）仅可报销一次",
            "劳务费/专家咨询费需核对人员名单合理性",
            "差旅费需与项目研究内容相关",
        ],
    }
    system = ('你是科研经费合规审核助手。只输出一个 JSON 对象，'
              '格式 {"verdict":"PASS|REVIEW|REJECT","confidence":0到1,"issues":[{"rule":"...","reason":"..."}]}，'
              '不要输出其它文字。AI 结论仅是建议，不确定时用 REVIEW。')
    try:
        from core.llm import chat_json

        verdict = chat_json(system, json.dumps(ctx, ensure_ascii=False))
    except Exception as exc:
        return ok(request, _degraded_review(f"AI 服务暂不可用：{exc}"))
    v = _normalize_verdict(verdict.get("verdict"))
    conf = float(verdict.get("confidence") or 0)
    if conf < AI_CONFIDENCE_FLOOR:
        v = "REVIEW"
        conf = max(conf, 0.0)
    return ok(request, {
        "verdict": v, "confidence": conf,
        "issues": [{"rule": i.get("rule"), "reason": i.get("reason")} for i in (verdict.get("issues") or [])],
        "available": True,
    })


# ---------------------------------------------------------------------------
# 预警配置（T15）
# ---------------------------------------------------------------------------
WARN_KINDS = {"EXEC_RATE", "DEADLINE", "ANNUAL_FEE", "MIDCHECK", "CLOSING"}


def list_warn_configs(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FWarnConfig.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("warn_kind"):
        qs = qs.filter(warn_kind=request.GET["warn_kind"])
    if request.GET.get("enabled") in ("true", "false"):
        qs = qs.filter(enabled=request.GET["enabled"] == "true")
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_warn_config(w) for w in rows], "total": total, "page": page, "size": size})


def create_warn_config(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if b.get("warn_kind") not in WARN_KINDS:
        raise ApiError(400, CODE_BAD_REQUEST, "warn_kind 非法（EXEC_RATE|DEADLINE|ANNUAL_FEE|MIDCHECK|CLOSING）")
    w = FWarnConfig.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        project_category_id=b.get("project_category_id"), warn_kind=b["warn_kind"],
        threshold_pct=_money(b["threshold_pct"]) if b.get("threshold_pct") else None,
        ahead_days=b.get("ahead_days"), level=b.get("level") or "P2",
        channel=b.get("channel") or "INBOX", cron_expr=b.get("cron_expr"),
        template=b.get("template"), enabled=bool(b.get("enabled", True)), remark=b.get("remark"),
    )
    return ok(request, to_api_warn_config(w))


def update_warn_config(request: HttpRequest, id: int):
    d = domain_from(request)
    w = FWarnConfig.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if w is None:
        raise ApiError(404, CODE_NOT_FOUND, "配置不存在")
    b = read_json(request)
    if b.get("project_category_id") is not None:
        w.project_category_id = b["project_category_id"]
    if b.get("threshold_pct") is not None:
        w.threshold_pct = _money(b["threshold_pct"])
    if b.get("ahead_days") is not None:
        w.ahead_days = b["ahead_days"]
    if b.get("level"):
        w.level = b["level"]
    if b.get("channel"):
        w.channel = b["channel"]
    if b.get("cron_expr") is not None:
        w.cron_expr = b["cron_expr"]
    if b.get("template") is not None:
        w.template = b["template"]
    if b.get("enabled") is not None:
        w.enabled = b["enabled"]
    if b.get("remark") is not None:
        w.remark = b["remark"]
    w.modifier_id = d.user_id
    w.save()
    return ok(request, to_api_warn_config(w))


def delete_warn_config(request: HttpRequest, id: int):
    d = domain_from(request)
    n = FWarnConfig.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).update(deleted=1, updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "配置不存在")
    return ok(request, {"id": id})


# ---------------------------------------------------------------------------
# 差旅费用标准（A3）
# ---------------------------------------------------------------------------
def _ts_conflict_exists(tenant_id: int, staff_category: str, city_tier: str, exclude_id: int | None = None) -> bool:
    """同 (tenant, staffCategory, cityTier) 是否已存在 ACTIVE 记录（应用层唯一校验）。"""
    qs = FTravelStandard.objects.filter(
        tenant_id=tenant_id, staff_category=staff_category, city_tier=city_tier,
        status="ACTIVE", deleted=0,
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def _match_travel_standard(tenant_id: int, staff_category: str, city_tier: str, on: date) -> "FTravelStandard | None":
    """按 (staffCategory, cityTier) 在 on 日生效的 ACTIVE 标准（Task 7 复用）。

    命中规则：ACTIVE 且 effective_from ≤ on ≤ effective_to（effective_to 空=长期有效）。
    """
    return (
        FTravelStandard.objects.filter(
            tenant_id=tenant_id, staff_category=staff_category, city_tier=city_tier,
            status="ACTIVE", deleted=0,
            effective_from__lte=on,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on))
        .order_by("-effective_from", "-id")
        .first()
    )


def list_travel_standards(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FTravelStandard.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("staffCategory"):
        qs = qs.filter(staff_category=request.GET["staffCategory"])
    if request.GET.get("cityTier"):
        qs = qs.filter(city_tier=request.GET["cityTier"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_travel_standard(w) for w in rows], "total": total, "page": page, "size": size})


def create_travel_standard(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    staff_category = b.get("staffCategory")
    city_tier = b.get("cityTier")
    if not staff_category or not city_tier or not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    for k in ("accommodationCap", "mealsCap", "transportCap"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    effective_from = _parse_date(b.get("effectiveFrom"))
    if effective_from is None:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    effective_to = _parse_date(b.get("effectiveTo"))
    if effective_from and effective_to and effective_to < effective_from:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    status = b.get("status") or "ACTIVE"
    if status not in ("ACTIVE", "DISABLED"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    with transaction.atomic():
        if status == "ACTIVE" and _ts_conflict_exists(d.tenant_id, staff_category, city_tier):
            raise ApiError(409, CODE_CONFLICT, "同员工类别与城市类别已存在生效中的差旅标准")
        w = FTravelStandard.objects.create(
            tenant_id=d.tenant_id, creator_id=d.user_id,
            name=b["name"], staff_category=staff_category, city_tier=city_tier,
            accommodation_cap=_money(b["accommodationCap"]) or Decimal("0"),
            meals_cap=_money(b["mealsCap"]) or Decimal("0"),
            transport_cap=_money(b["transportCap"]) or Decimal("0"),
            effective_from=effective_from, effective_to=effective_to,
            status=status, remark=b.get("remark"),
        )
    return ok(request, to_api_travel_standard(w))


def update_travel_standard(request: HttpRequest, id: int):
    d = domain_from(request)
    w = FTravelStandard.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if w is None:
        raise ApiError(404, CODE_NOT_FOUND, "差旅标准不存在")
    b = read_json(request)
    with transaction.atomic():
        if b.get("name") is not None:
            w.name = b["name"]
        if b.get("staffCategory") is not None:
            w.staff_category = b["staffCategory"]
        if b.get("cityTier") is not None:
            w.city_tier = b["cityTier"]
        if b.get("accommodationCap") is not None:
            w.accommodation_cap = _money(b["accommodationCap"]) or Decimal("0")
        if b.get("mealsCap") is not None:
            w.meals_cap = _money(b["mealsCap"]) or Decimal("0")
        if b.get("transportCap") is not None:
            w.transport_cap = _money(b["transportCap"]) or Decimal("0")
        if b.get("effectiveFrom") is not None:
            v = _parse_date(b["effectiveFrom"])
            if v is None:
                raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
            w.effective_from = v
        if b.get("effectiveTo") is not None:
            w.effective_to = _parse_date(b["effectiveTo"])
        if b.get("status") is not None:
            if b["status"] not in ("ACTIVE", "DISABLED"):
                raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
            w.status = b["status"]
        if b.get("remark") is not None:
            w.remark = b["remark"]
        if w.effective_from and w.effective_to and w.effective_to < w.effective_from:
            raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
        if w.status == "ACTIVE" and _ts_conflict_exists(d.tenant_id, w.staff_category, w.city_tier, exclude_id=w.id):
            raise ApiError(409, CODE_CONFLICT, "同员工类别与城市类别已存在生效中的差旅标准")
        w.save()
    return ok(request, to_api_travel_standard(w))


def delete_travel_standard(request: HttpRequest, id: int):
    d = domain_from(request)
    n = FTravelStandard.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).update(deleted=1, updated_at=dj_tz.now())
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "差旅标准不存在")
    return ok(request, {"id": id})


def match_travel_standard(request: HttpRequest):
    d = domain_from(request)
    staff_category = request.GET.get("staffCategory")
    city_tier = request.GET.get("cityTier")
    if not staff_category or not city_tier:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    on = _parse_date(request.GET.get("date")) or dj_tz.localdate()
    w = _match_travel_standard(d.tenant_id, staff_category, city_tier, on)
    if w is None:
        raise ApiError(404, CODE_NOT_FOUND, "无生效的差旅标准")
    return ok(request, to_api_travel_standard(w))


# ---------------------------------------------------------------------------
# 发票（M1-a A1）：CRUD + bind/void + is_duplicated
# ---------------------------------------------------------------------------
def _invoice_duplicated(tenant_id: int, number: str, total: Decimal, issue_date, exclude_id: int | None = None) -> bool:
    """同租户存在其他非 VOID 发票且 (number, totalAmount, issueDate) 三元组全等。

    仅标记不拦截（is_duplicated=true 仍创建）；硬拦截走 /expenses 创建时的
    三重指纹查重 40903（互不影响）。issue_date 为空则只比对 (number, total)。
    """
    qs = FInvoice.objects.filter(
        tenant_id=tenant_id, deleted=0,
        number=number, total_amount=total,
    ).exclude(status="VOID")
    if issue_date is not None:
        qs = qs.filter(issue_date=issue_date)
    else:
        qs = qs.filter(issue_date__isnull=True)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def _get_invoice_or_404(request_domain_tenant_id: int, id: int) -> "FInvoice":
    inv = FInvoice.objects.filter(id=id, tenant_id=request_domain_tenant_id, deleted=0).first()
    if inv is None:
        raise ApiError(404, CODE_NOT_FOUND, "发票不存在")
    return inv


def list_invoices(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FInvoice.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("expenseId"):
        qs = qs.filter(expense_id=request.GET["expenseId"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_invoice(i) for i in rows], "total": total, "page": page, "size": size})


def create_invoice(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    number = b.get("number")
    if not number:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    total = _money(b.get("totalAmount"))
    if total is None or total <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    issue_date = _parse_date(b.get("issueDate")) if b.get("issueDate") else None
    invoice_type = b.get("invoiceType") or "ELECTRONIC"
    if invoice_type not in ("GENERAL", "SPECIAL", "ELECTRONIC", "ITINERARY"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    with transaction.atomic():
        inv = FInvoice.objects.create(
            tenant_id=d.tenant_id, creator_id=d.user_id,
            status="DRAFT", number=number,
            invoice_code=b.get("invoiceCode"), invoice_type=invoice_type,
            seller_name=b.get("sellerName"), seller_tax_id=b.get("sellerTaxId"),
            buyer_name=b.get("buyerName"), buyer_tax_id=b.get("buyerTaxId"),
            amount_excl_tax=_money(b.get("amountExclTax")) or Decimal("0"),
            tax_amount=_money(b.get("taxAmount")) or Decimal("0"),
            total_amount=total, issue_date=issue_date,
            remark=b.get("remark"),
        )
        # code=INV-年-序 回填（对齐 create_income 先建后回填模式）
        inv.code = code_of("INV", inv.id)
        inv.save(update_fields=["code"])
        # 新建即重算标记：与既有非 VOID 票三元组全等 → true（仅标记不拦截；排除自身）
        inv.is_duplicated = _invoice_duplicated(
            d.tenant_id, number, total, issue_date, exclude_id=inv.id)
        if inv.is_duplicated:
            inv.save(update_fields=["is_duplicated"])
    return ok(request, to_api_invoice(inv))


def get_invoice(request: HttpRequest, id: int):
    d = domain_from(request)
    inv = _get_invoice_or_404(d.tenant_id, id)
    return ok(request, to_api_invoice(inv))


def update_invoice(request: HttpRequest, id: int):
    d = domain_from(request)
    inv = _get_invoice_or_404(d.tenant_id, id)
    b = read_json(request)
    # 仅 DRAFT/OCR_DONE 可改；BOUND/CHECKED/VOID → 40901（契约 PUT /invoices/{id}）
    if inv.status not in ("DRAFT", "OCR_DONE"):
        raise ApiError(409, CODE_CONFLICT, "当前状态不允许修改发票")
    invoice_type = b.get("invoiceType")
    if invoice_type is not None and invoice_type not in ("GENERAL", "SPECIAL", "ELECTRONIC", "ITINERARY"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    total = None
    if b.get("totalAmount") is not None:
        total = _money(b["totalAmount"])
        if total is None or total <= 0:
            raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    issue_date = None
    if b.get("issueDate") is not None:
        issue_date = _parse_date(b["issueDate"])
        if issue_date is None:
            raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    with transaction.atomic():
        # 部分更新：仅提供的字段被覆盖（对齐 Task 5 update_travel_standard 风格）
        if b.get("number") is not None:
            inv.number = b["number"]
        if b.get("invoiceCode") is not None:
            inv.invoice_code = b["invoiceCode"]
        if invoice_type is not None:
            inv.invoice_type = invoice_type
        if b.get("sellerName") is not None:
            inv.seller_name = b["sellerName"]
        if b.get("sellerTaxId") is not None:
            inv.seller_tax_id = b["sellerTaxId"]
        if b.get("buyerName") is not None:
            inv.buyer_name = b["buyerName"]
        if b.get("buyerTaxId") is not None:
            inv.buyer_tax_id = b["buyerTaxId"]
        if b.get("amountExclTax") is not None:
            inv.amount_excl_tax = _money(b["amountExclTax"]) or Decimal("0")
        if b.get("taxAmount") is not None:
            inv.tax_amount = _money(b["taxAmount"]) or Decimal("0")
        if total is not None:
            inv.total_amount = total
        if issue_date is not None:
            inv.issue_date = issue_date
        if b.get("remark") is not None:
            inv.remark = b["remark"]
        # number/total/issue_date 变更后重算标记（exclude_id=self，自身不计）
        inv.is_duplicated = _invoice_duplicated(
            d.tenant_id, inv.number, inv.total_amount, inv.issue_date, exclude_id=inv.id)
        inv.save()
    return ok(request, to_api_invoice(inv))


def bind_invoice(request: HttpRequest, id: int):
    d = domain_from(request)
    b = read_json(request)
    expense_id = b.get("expenseId")
    if not expense_id:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    with transaction.atomic():
        inv = FInvoice.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
        if inv is None:
            raise ApiError(404, CODE_NOT_FOUND, "发票不存在")
        e = FExpense.objects.filter(id=expense_id, tenant_id=d.tenant_id, deleted=0).first()
        if e is None:
            raise ApiError(404, CODE_NOT_FOUND, "报销单不存在")
        if e.status == "PAID":
            raise ApiError(409, CODE_CONFLICT, "报销单已支付，不可绑定发票")
        if inv.status == "BOUND":
            if inv.expense_id == e.id:
                # 幂等：重复绑定同一报销单 → 直接返回现状
                return ok(request, to_api_invoice(inv))
            raise ApiError(409, CODE_CONFLICT, "发票已绑定报销单，不可重复绑定")
        if inv.status in ("VOID",):
            raise ApiError(409, CODE_CONFLICT, "已作废发票不可绑定")
        # 事务内：invoice_ids 追加（幂等）、expense_id 落值、status=BOUND
        ids = list(e.invoice_ids or [])
        if inv.id not in ids:
            ids.append(inv.id)
        e.invoice_ids = ids
        e.save(update_fields=["invoice_ids", "updated_at"])
        inv.expense_id = e.id
        inv.status = "BOUND"
        inv.save(update_fields=["expense_id", "status", "updated_at"])
    return ok(request, to_api_invoice(inv))


def void_invoice(request: HttpRequest, id: int):
    d = domain_from(request)
    with transaction.atomic():
        inv = FInvoice.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
        if inv is None:
            raise ApiError(404, CODE_NOT_FOUND, "发票不存在")
        # BOUND（已绑定报销单）→ 40901；其余状态置 VOID（终态，作废不回收号码）
        if inv.status == "BOUND":
            raise ApiError(409, CODE_CONFLICT, "已绑定报销单的发票不可作废")
        if inv.status != "VOID":
            inv.status = "VOID"
            inv.save(update_fields=["status", "updated_at"])
    return ok(request, to_api_invoice(inv))


# ---------------------------------------------------------------------------
# 发票 OCR 三级回落（A1/F-08，Task 7）
# ---------------------------------------------------------------------------
OCR_DONE_FLOOR = Decimal("0.85")  # 置信度 ≥0.85 → OCR_DONE（契约规定）


def _normalize_ocr_fields(raw: dict) -> dict:
    """LLM/规则产出 → 契约字段（camelCase、金额两位小数字符串）。只采纳白名单键。"""
    from core.invoice_ocr import FIELD_WEIGHTS

    allowed = set(FIELD_WEIGHTS) | {"ocrConfidence"}
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        if k not in allowed or v in (None, ""):
            continue
        s = str(v).strip()
        if k in ("amountExclTax", "taxAmount", "totalAmount"):
            try:
                s = str(Decimal(s.replace(",", "")).quantize(Decimal("0.01")))
            except Exception:
                continue
        elif k == "issueDate" and s:
            d = _parse_date(s)
            if d is None:
                continue
            s = d.isoformat()
        out[k] = s
    return out


def _llm_invoice_fields(text: str) -> tuple[dict, list[str]]:
    """OCR 一级回落：LLM 抽取。返回 (fields, reasons)。未配置/失败 → 空字段+原因。"""
    from django.conf import settings

    reasons: list[str] = []
    if not settings.LLM_BASE_URL:
        return {}, ["ocr-engine-unavailable"] if not text else []
    system = ('你是发票 OCR 信息抽取助手。只输出一个 JSON 对象，'
              '格式 {"invoiceType":"GENERAL|SPECIAL|ELECTRONIC|ITINERARY",'
              '"number":"...","invoiceCode":"...","sellerName":"...","sellerTaxId":"...",'
              '"buyerName":"...","buyerTaxId":"...","amountExclTax":"0.00",'
              '"taxAmount":"0.00","totalAmount":"0.00","issueDate":"YYYY-MM-DD"}，'
              '金额为两位小数字符串，未识别的键输出 null，不要输出其它文字。')
    try:
        from core.llm import chat_json

        raw = chat_json(system, text or "")
        return _normalize_ocr_fields(raw), []
    except Exception as exc:
        return {}, [f"llm-failed：{exc}"]


def invoice_ocr(request: HttpRequest):
    """POST /invoices/ocr：LLM → 规则 → 降级 三级回落（HTTP 200 恒定，AI 产出仅建议）。

    - 双不可用（无 LLM 且无 text）→ 降级 DRAFT 骨架，reasons=["ocr-engine-unavailable"]；
    - 解析成功 conf≥0.85 → OCR_DONE，字段落库；否则 DRAFT；
    - is_duplicated 同手工新建规则（标记不拦截）。
    """
    d = domain_from(request)
    b = read_json(request)
    text = (b.get("text") or "").strip()
    file_url = (b.get("fileUrl") or "").strip()
    # fileUrl/text 均缺省也降级应答（契约 HTTP 200 恒定；test_contract_full_coverage 以 {} 打本端点）

    with transaction.atomic():
        inv = FInvoice(tenant_id=d.tenant_id, creator_id=d.user_id, status="DRAFT")
        reasons: list[str] = []
        warnings: list[str] = []
        fields: dict[str, str] = {}
        confidence = None

        llm_fields, llm_reasons = _llm_invoice_fields(text)
        reasons.extend(llm_reasons)
        if llm_fields:
            fields = llm_fields
            # LLM 路径无独立自洽告警源，置 TBD 由规则回落补齐，这里直接沿用 LLM 结果
            confidence = 0.8
        else:
            from core.invoice_ocr import parse_invoice_text

            fields, conf_f, warnings = parse_invoice_text(text)
            confidence = conf_f

        has_fields = bool(fields)
        if has_fields and confidence >= OCR_DONE_FLOOR:
            inv.status = "OCR_DONE"
        inv.number = fields.get("number") or ""
        inv.invoice_code = fields.get("invoiceCode") or ""
        it = fields.get("invoiceType")
        if it in ("GENERAL", "SPECIAL", "ELECTRONIC", "ITINERARY"):
            inv.invoice_type = it
        inv.seller_name = fields.get("sellerName") or ""
        inv.seller_tax_id = fields.get("sellerTaxId") or ""
        inv.buyer_name = fields.get("buyerName") or ""
        inv.buyer_tax_id = fields.get("buyerTaxId") or ""

        def _dec_field(key: str) -> Decimal:
            try:
                return Decimal(fields[key])
            except Exception:
                return Decimal("0")

        inv.amount_excl_tax = _dec_field("amountExclTax")
        inv.tax_amount = _dec_field("taxAmount")
        inv.total_amount = _dec_field("totalAmount")
        if fields.get("issueDate"):
            inv.issue_date = _parse_date(fields["issueDate"])
        # 模型无 file_url 列，契约 Invoice 亦无 fileUrl 字段 —— 仅留存审计于 ocr_raw_json
        inv.ocr_raw_json = {"fields": fields, "warnings": warnings, "reasons": reasons,
                            "fileUrl": file_url or None}
        if confidence is not None and confidence > 0:
            inv.ocr_confidence = Decimal(str(confidence)).quantize(Decimal("0.0001"))
        if not has_fields:
            inv.remark = (inv.remark or "OCR 未能识别发票内容，请人工补录")
        inv.save()
        inv.code = code_of("INV", inv.id)
        inv.save(update_fields=["code", "updated_at"])
        # is_duplicated 同手工新建规则（Task 6 语义）：标记不拦截
        inv.is_duplicated = _invoice_duplicated(
            d.tenant_id, inv.number, inv.total_amount, inv.issue_date, exclude_id=inv.id)
        if inv.is_duplicated:
            inv.save(update_fields=["is_duplicated", "updated_at"])

    resp = to_api_invoice(inv)
    # 契约 InvoiceOcrResponse = Invoice + ocrWarnings；降级原因经 reasons 持久化在
    # ocr_raw_json（模型内），不进响应体（契约无 ocrRawJson 字段）。
    # ocrWarnings = 引擎侧原因（llm-failed/ocr-engine-unavailable）+ text 存在时的解析告警；
    # 无 text 时「ocr-text-empty」与引擎原因重复，噪音过滤。
    resp["ocrWarnings"] = reasons + (warnings if text else [])
    return ok(request, resp)


# ---------------------------------------------------------------------------
# 借款全生命周期（F-13 / Task 9 / 契约 /loans :1094-1341）
# ---------------------------------------------------------------------------

# 借款审批链基准步骤（契约 /approve :1209）：金额 <100000 → [R-MANAGER, R-FINANCE]；
# ≥100000 或租户开启两步审批（core.approval.twostep_enabled）→ 前插 R-LEADER。
_LOAN_LEADER_THRESHOLD = Decimal("100000.00")


def _loan_steps(amount: Decimal) -> list[str]:
    steps = ["R-MANAGER", "R-FINANCE"]
    if amount >= _LOAN_LEADER_THRESHOLD or approval.twostep_enabled():
        steps.insert(0, "R-LEADER")
    return steps


def _get_loan_or_404(tenant_id: int, loan_id: int) -> FLoan:
    loan = FLoan.objects.filter(id=loan_id, tenant_id=tenant_id, deleted=0).first()
    if loan is None:
        raise ApiError(404, CODE_NOT_FOUND, "借款单不存在")
    return loan


def _loan_approvals(tenant_id: int, loan_id: int) -> list[dict]:
    """审批流水：SysApprovalLog(biz_type=LOAN) 仅 APPROVE/REJECT/RETURN 动作
    （SUBMIT 是提交事件不是审批动作，对齐报销 FExpenseApproval 语义）。
    SysApprovalLog 无现成 mapper（to_api_approval 仅收 FExpenseApproval，且恰 3 文件
    约束不改 mappings.py），在此按其字段自建 dict：键对齐 to_api_approval 范式，
    expense_id 处放 loan_id（借款流水归属借款单）。"""
    out: list[dict] = []
    for l in approval.list_logs(tenant_id, "LOAN", loan_id):
        if l.action not in ("APPROVE", "REJECT", "RETURN"):
            continue
        out.append({
            "id": l.id, "expense_id": loan_id, "step_order": l.step,
            "approver_user_id": l.actor_id, "role": l.actor_role,
            "action": l.action, "comment": l.comment,
            "status": l.action, "acted_at": fmt_ts(l.acted_at),
        })
    return out


def create_loan(request: HttpRequest):
    """创建借款（契约 :1094）：必填 projectId、amount>0，创建即 DRAFT 并取号。

    legal_entity_id 派生依据（Task 3 裁定）：FLoan.legal_entity_id NOT NULL 无 default
    （apps/funding/models.py:357），而契约 LoanCreateRequest 无 legalEntityId 字段（不改契约），
    故从关联项目 EProject.legal_entity_id（apps/project/models.py:23，default=1）派生；
    项目缺失/无值时落 default=1（对齐 import_bank_flow 的 legal_entity_id 先例 api.py:456）。
    """
    d = domain_from(request)
    b = read_json(request)
    project_id = b.get("project_id") or b.get("projectId")
    amount = _money(b.get("amount"))
    if not project_id or amount is None or amount <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误（projectId、amount>0 必填）")
    project = EProject.objects.filter(id=project_id, tenant_id=d.tenant_id, deleted=0).first()
    loan = FLoan.objects.create(
        tenant_id=d.tenant_id,
        creator_id=d.user_id,
        project_id=project_id,
        legal_entity_id=project.legal_entity_id if project else 1,
        applicant_user_id=d.user_id,
        amount=_d2(amount),
        reason=b.get("reason"),
        budget_line_id=b.get("budget_line_id") or b.get("budgetLineId"),
    )
    loan.code = code_of("LOAN", loan.id)
    loan.save(update_fields=["code", "updated_at"])
    return ok(request, to_api_loan(loan))


def list_loans(request: HttpRequest):
    """分页查询借款单（契约 :1118）：page/size/status/projectId 过滤。"""
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FLoan.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("projectId"):
        qs = qs.filter(project_id=request.GET["projectId"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_loan(l) for l in rows], "total": total, "page": page, "size": size})


def get_loan(request: HttpRequest, id: int):
    """借款单详情（契约 :1153）：含审批流水（SysApprovalLog biz_type=LOAN）。"""
    d = domain_from(request)
    loan = _get_loan_or_404(d.tenant_id, id)
    m = to_api_loan(loan)
    m["approvals"] = _loan_approvals(d.tenant_id, loan.id)
    return ok(request, m)


def submit_loan(request: HttpRequest, id: int):
    """提交借款（契约 :1176）：仅 DRAFT；预算制冻结 amount_frozen（40902）；
    置 SUBMITTED + frozen_at=now；通知审批链首步。仿 submit_expense:544-592 事务链。"""
    d = domain_from(request)
    with transaction.atomic():
        loan = FLoan.objects.filter(
            id=id, tenant_id=d.tenant_id, deleted=0, status="DRAFT",
        ).select_for_update().first()
        if loan is None:
            raise ApiError(409, CODE_CONFLICT, "仅 DRAFT 状态可提交")
        if loan.budget_line_id:
            # 预算制：锁定预算行并冻结（包干制跳过，语义与 submit_expense 一致）
            line = FBudgetLine.objects.select_for_update().filter(
                id=loan.budget_line_id, deleted=0).first()
            if line is None:
                raise ApiError(404, CODE_NOT_FOUND, "预算行不存在")
            if line.remaining < loan.amount:
                raise ApiError(409, CODE_CONFLICT_REF, "预算行可支余额不足，冻结失败")
            line.amount_frozen = _d2(line.amount_frozen + loan.amount)
            line.save(update_fields=["amount_frozen", "updated_at"])
            loan.frozen_at = dj_tz.now()
        loan.status = "SUBMITTED"
        loan.submitted_at = dj_tz.now()
        loan.modifier_id = d.user_id
        loan.save()
        # 提交事件落审批流水（step=0 / action=SUBMIT；流水仅展示 APPROVE/REJECT/RETURN）
        approval.log(d.tenant_id, "LOAN", loan.id, 0, d.user_id, "", "SUBMIT")
    steps = _loan_steps(loan.amount)
    _notify_role(d.tenant_id, steps[0], "LOAN_APPROVAL",
                 f"待审批：借款单 {loan.code or loan.id}",
                 f"金额 {num2(loan.amount)} 元，请及时审批", f"loan/{loan.id}")
    loan.refresh_from_db()
    return ok(request, to_api_loan(loan))


def approve_loan(request: HttpRequest, id: int):
    """借款审批（契约 :1204）：action 小写枚举 approve/reject/return（区别于报销大写）。
    steps 由金额/两步开关内存推导，进度=SysApprovalLog 已 APPROVE 条数；逐 step 校验角色
    （R-ADMIN 可代审，对齐 _approve_one）；reject/return 释放冻结；走完 → APPROVED。
    借款资金结转发生在 pay（区别于报销 approve 末步即转实扣）。"""
    d = domain_from(request)
    b = read_json(request)
    raw = b.get("action")
    if raw not in ("approve", "reject", "return"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 仅支持 approve/reject/return")
    action = raw.upper()
    loan = _get_loan_or_404(d.tenant_id, id)
    if loan.status != "SUBMITTED":
        raise ApiError(409, CODE_CONFLICT, "单据不在审批中状态")
    steps = _loan_steps(loan.amount)
    done = sum(1 for l in approval.list_logs(d.tenant_id, "LOAN", id)
               if l.action == "APPROVE")
    step_order = done + 1
    if step_order > len(steps):
        raise ApiError(409, CODE_CONFLICT, "单据不在审批中状态")
    want = steps[done]
    if want not in set(d.roles) and "R-ADMIN" not in set(d.roles):
        raise ApiError(403, CODE_FORBIDDEN, f"当前步骤需要 {want} 角色")
    final = step_order == len(steps)
    new_status = "SUBMITTED"
    if action == "APPROVE":
        if final:
            new_status = "APPROVED"
    elif action == "REJECT":
        new_status = "REJECTED"
    else:  # RETURN
        new_status = "RETURNED"
    releases = action in ("REJECT", "RETURN")
    with transaction.atomic():
        if releases and loan.budget_line_id:
            FBudgetLine.objects.filter(id=loan.budget_line_id, deleted=0).update(
                amount_frozen=F("amount_frozen") - loan.amount,
                amount_released=F("amount_released") + loan.amount,
                updated_at=dj_tz.now())
        updates = {"status": new_status, "modifier_id": d.user_id,
                   "updated_at": dj_tz.now()}
        if releases:
            updates["frozen_at"] = None
        FLoan.objects.filter(id=loan.id).update(**updates)
        approval.log(d.tenant_id, "LOAN", loan.id, step_order, d.user_id, want,
                     action, b.get("comment"))
    if final and new_status == "APPROVED":
        _notify_role(d.tenant_id, "R-FINANCE", "LOAN_APPROVAL",
                     f"待放款：借款单 {loan.code or loan.id}",
                     f"金额 {num2(loan.amount)} 元，审批已通过", f"loan/{loan.id}")
    loan.refresh_from_db()
    return ok(request, to_api_loan(loan))


def pay_loan(request: HttpRequest, id: int):
    """放款（契约 :1243）：仅 APPROVED → PAID；frozen→used 结转；paid_at=now。
    Preflight Ruling 8：Casbin 已放行 R-MANAGER+R-FINANCE 的 POST /loans/*，
    代码层必须收紧为仅 R-FINANCE（R-ADMIN 不代行放款，资金动作无代审）。"""
    d = domain_from(request)
    if not approval.has_role(d.roles, "R-FINANCE"):
        raise ApiError(403, CODE_FORBIDDEN, "仅 R-FINANCE 可执行放款")
    with transaction.atomic():
        loan = FLoan.objects.filter(
            id=id, tenant_id=d.tenant_id, deleted=0, status="APPROVED",
        ).select_for_update().first()
        if loan is None:
            raise ApiError(409, CODE_CONFLICT, "仅 APPROVED 状态可放款")
        if loan.budget_line_id:
            FBudgetLine.objects.filter(id=loan.budget_line_id, deleted=0).update(
                amount_frozen=F("amount_frozen") - loan.amount,
                amount_used=F("amount_used") + loan.amount,
                updated_at=dj_tz.now())
        FLoan.objects.filter(id=loan.id).update(
            status="PAID", paid_at=dj_tz.now(), modifier_id=d.user_id,
            updated_at=dj_tz.now())
        approval.log(d.tenant_id, "LOAN", loan.id, 0, d.user_id, "R-FINANCE", "PAY")
    loan.refresh_from_db()
    return ok(request, to_api_loan(loan))


def write_off_loan(request: HttpRequest, id: int):
    """冲销（契约 :1269）：仅 PAID 可冲销；expense 须 APPROVED 且 related_loan_id=本单
    （违者 40901）；冲销额=报销单金额，本次不得超过 remainingForWriteoff
    （=amount−write_off_amount−refunded_amount，冲销/退款共享，超额 → 40902）；
    remainingForWriteoff 归零（补齐）→ CLOSED，覆盖纯冲销/纯退款/混合流。
    防双计：SysApprovalLog 记
    WRITE_OFF(expense/{id})，重复报销单 40901（无台账表的保守实现，Task 12 可升级）。"""
    d = domain_from(request)
    b = read_json(request)
    expense_id = b.get("expense_id") or b.get("expenseId")
    if not expense_id:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误（expenseId 必填）")
    with transaction.atomic():
        loan = FLoan.objects.filter(
            id=id, tenant_id=d.tenant_id, deleted=0, status="PAID",
        ).select_for_update().first()
        if loan is None:
            raise ApiError(409, CODE_CONFLICT, "仅 PAID 状态可冲销")
        exp = FExpense.objects.filter(
            id=expense_id, tenant_id=d.tenant_id, deleted=0).first()
        if exp is None:
            raise ApiError(404, CODE_NOT_FOUND, "报销单不存在")
        if exp.status != "APPROVED" or exp.related_loan_id != loan.id:
            raise ApiError(409, CODE_CONFLICT, "报销单须 APPROVED 且关联本借款")
        if any(l.action == "WRITE_OFF" and l.comment == f"expense/{exp.id}"
               for l in approval.list_logs(d.tenant_id, "LOAN", loan.id)):
            raise ApiError(409, CODE_CONFLICT, "该报销单已冲销过本借款")
        if exp.amount > loan.remaining_for_writeoff:
            raise ApiError(409, CODE_CONFLICT_REF, "冲销金额累计超出借款余额")
        FLoan.objects.filter(id=loan.id).update(
            write_off_amount=F("write_off_amount") + exp.amount,
            modifier_id=d.user_id, updated_at=dj_tz.now())
        approval.log(d.tenant_id, "LOAN", loan.id, 0, d.user_id, "R-FINANCE",
                     "WRITE_OFF", f"expense/{exp.id}")
        loan.refresh_from_db()
        if loan.remaining_for_writeoff == 0:
            FLoan.objects.filter(id=loan.id).update(
                status="CLOSED", updated_at=dj_tz.now())
    loan.refresh_from_db()
    return ok(request, to_api_loan(loan))


def refund_loan(request: HttpRequest, id: int):
    """退款（契约 :1307）：仅 PAID 可退款；body.amount ≤ remainingForWriteoff
    （超出 40901，契约明示区别于冲销的 40902）；remainingForWriteoff
    （=amount−write_off_amount−refunded_amount，冲销/退款共享）归零（补齐）
    → CLOSED，覆盖纯冲销/纯退款/混合流。"""
    d = domain_from(request)
    b = read_json(request)
    amount = _money(b.get("amount"))
    if amount is None or amount <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误（amount 须为正数金额）")
    with transaction.atomic():
        loan = FLoan.objects.filter(
            id=id, tenant_id=d.tenant_id, deleted=0, status="PAID",
        ).select_for_update().first()
        if loan is None:
            raise ApiError(409, CODE_CONFLICT, "仅 PAID 状态可退款")
        if amount > loan.remaining_for_writeoff:
            raise ApiError(409, CODE_CONFLICT, "退款金额超出可退余额")
        FLoan.objects.filter(id=loan.id).update(
            refunded_amount=F("refunded_amount") + amount,
            modifier_id=d.user_id, updated_at=dj_tz.now())
        approval.log(d.tenant_id, "LOAN", loan.id, 0, d.user_id, "R-FINANCE",
                     "REFUND", f"amount/{_d2(amount)}")
        loan.refresh_from_db()
        if loan.remaining_for_writeoff == 0:
            FLoan.objects.filter(id=loan.id).update(
                status="CLOSED", updated_at=dj_tz.now())
    loan.refresh_from_db()
    return ok(request, to_api_loan(loan))


# ---------------------------------------------------------------------------
# 凭证同步（Task 3 / F-11，契约 :1642-1697）：push 下发 + 财务回调回写
# ---------------------------------------------------------------------------
def _to_api_voucher_sync(v: FVoucherSync) -> dict:
    """契约 VoucherSync schema 键（camelCase，无 code 键——schema 未定义不外发）。"""
    return {
        "id": v.id, "expenseId": v.expense_id,
        "financeSystem": v.finance_system,
        "voucherNo": v.voucher_no, "syncStatus": v.sync_status,
        "retryCount": v.retry_count, "errorMsg": v.error_msg,
        "syncAt": fmt_ts(v.sync_at),
    }


def _voucher_sync_of(tenant_id: int, expense_id: int) -> "FVoucherSync | None":
    """按 (tenant, expense) 取有效凭证同步行（应用层 1:1 约束；Task 5 复用查 voucher_sync_id）。"""
    return FVoucherSync.objects.filter(
        tenant_id=tenant_id, expense_id=expense_id, deleted=0).first()


def push_voucher(request: HttpRequest):
    """下发/重推凭证至财务系统（契约 /vouchers/sync）。

    幂等：已有非 MANUAL 记录 → 返回既有行；MANUAL 亦返回既有行（人工介入态不自动重推）。
    M2 前不做真实外部调用：落 payload 即视为受理（status=SYNCING）。
    """
    d = domain_from(request)
    b = read_json(request)
    expense_id = b.get("expenseId")
    if not expense_id:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误（expenseId 必填）")
    finance_system = b.get("financeSystem") or "YONYOU"
    with transaction.atomic():
        exp = FExpense.objects.filter(
            id=expense_id, tenant_id=d.tenant_id, deleted=0).first()
        if exp is None:
            raise ApiError(404, CODE_NOT_FOUND, "报销单不存在")
        existing = _voucher_sync_of(d.tenant_id, expense_id)
        if existing is not None:
            return ok(request, _to_api_voucher_sync(existing))
        vs = FVoucherSync.objects.create(
            tenant_id=d.tenant_id, creator_id=d.user_id,
            expense_id=expense_id, finance_system=finance_system,
            status="SYNCING", sync_status="SYNCING",  # 受理即同步中；schema enum 未列 SYNCING 为契约缺口（CONCERN）
            payload_json={
                "expenseId": exp.id,
                "expenseCode": exp.code,
                "financeSystem": finance_system,
                "amount": num2(exp.amount),
            },
        )
        vs.code = code_of("VCH", vs.id)
        vs.save(update_fields=["code"])
    return ok(request, _to_api_voucher_sync(vs))


def voucher_callback(request: HttpRequest):
    """财务系统凭证同步回调（契约 /vouchers/sync-callback）。

    幂等：记录已 SUCCESS → 200 返回既有状态摘要，不重复翻转。
    SUCCESS → sync_status=SUCCESS、voucher_no 回填、sync_at=now、callback_json 落回执；
      同事务 expense.status: PAID→VOUCHER_SYNCED（其余状态不动）。
    FAILED → sync_status=FAILED、retry_count+1、error_msg=detail 摘要；
      第 4 次失败（retry_count 将超 3）→ status=MANUAL；报销状态不动。
    """
    d = domain_from(request)
    b = read_json(request)
    expense_id = b.get("expenseId")
    result = b.get("result")
    if not expense_id or result not in ("SUCCESS", "FAILED"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误（expenseId/result 必填）")
    with transaction.atomic():
        vs = FVoucherSync.objects.filter(
            tenant_id=d.tenant_id, expense_id=expense_id, deleted=0,
        ).select_for_update().first()
        if vs is None:
            raise ApiError(404, CODE_NOT_FOUND, "凭证同步记录不存在")
        if vs.sync_status == "SUCCESS":
            return ok(request, _to_api_voucher_sync(vs))  # 幂等：不重复翻转
        if result == "SUCCESS":
            vs.sync_status = "SUCCESS"
            vs.status = "SUCCESS"
            vs.voucher_no = b.get("voucherNo")
            vs.sync_at = dj_tz.now()
            vs.callback_json = {"result": result, "voucherNo": b.get("voucherNo"),
                                "detail": b.get("detail")}
            vs.modifier_id = d.user_id
            vs.save()
            # 报销回写：仅 PAID → VOUCHER_SYNCED，其余状态不动（models.py:135 状态集）
            FExpense.objects.filter(
                id=vs.expense_id, tenant_id=d.tenant_id, deleted=0,
                status="PAID").update(status="VOUCHER_SYNCED", updated_at=dj_tz.now())
        else:  # FAILED
            vs.sync_status = "FAILED"
            vs.retry_count = vs.retry_count + 1
            detail = b.get("detail")
            if isinstance(detail, dict):
                err_text = detail.get("msg") or json.dumps(detail, ensure_ascii=False)
            else:
                err_text = str(detail) if detail else "财务系统回调失败"
            vs.error_msg = str(err_text)[:500]
            if vs.retry_count > 3:
                vs.status = "MANUAL"
            vs.modifier_id = d.user_id
            vs.save()
    vs.refresh_from_db()
    return ok(request, _to_api_voucher_sync(vs))


# ---------------------------------------------------------------------------
# 全成本核算 计算/查询（Task 5 / F-20）+ 平行记账查询（A4 / F-21 查询面）
# ---------------------------------------------------------------------------
def _to_api_cost_pool(cp: FCostPool) -> dict:
    """契约 CostPool schema 键（camelCase，含 Task 5 新增 status）。"""
    return {
        "id": cp.id, "code": cp.code,
        "projectId": cp.project_id, "period": cp.period,
        "directCost": num2(cp.direct_cost),
        "indirectAlloc": list(cp.indirect_alloc_json or []),
        "fullCost": num2(cp.full_cost),
        "status": cp.status,
        "basisRuleId": cp.basis_rule_id, "policyPackId": cp.policy_pack_id,
    }


def _to_api_accounting_entry(tenant_id: int, ae: FAccountingEntry) -> dict:
    """契约 AccountingEntry schema 键（camelCase）；EXPENSE 行回查 voucherSyncId。"""
    voucher_sync_id = ae.voucher_sync_id
    if voucher_sync_id is None and ae.source_txn_type == "EXPENSE":
        vs = _voucher_sync_of(tenant_id, ae.source_txn_id)
        voucher_sync_id = vs.id if vs is not None else None
    return {
        "id": ae.id, "code": ae.code,
        "sourceTxnId": ae.source_txn_id, "sourceTxnType": ae.source_txn_type,
        "projectId": ae.project_id, "period": ae.period,
        "finEntry": ae.fin_entry_json, "budEntry": ae.bud_entry_json,
        "postedFinance": ae.posted_finance, "postedBudget": ae.posted_budget,
        "reconcileStatus": ae.reconcile_status,
        "voucherSyncId": voucher_sync_id, "policyPackId": ae.policy_pack_id,
    }


def page_accounting_entries(request: HttpRequest):
    """契约 GET /accounting-entries：分录分页（sourceTxnType/reconcileStatus/projectId 过滤）。"""
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FAccountingEntry.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("sourceTxnType"):
        qs = qs.filter(source_txn_type=request.GET["sourceTxnType"])
    if request.GET.get("reconcileStatus"):
        qs = qs.filter(reconcile_status=request.GET["reconcileStatus"])
    if request.GET.get("projectId"):
        qs = qs.filter(project_id=request.GET["projectId"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [
        _to_api_accounting_entry(d.tenant_id, ae) for ae in rows
    ], "total": total, "page": page, "size": size})


def get_accounting_entry(request: HttpRequest, id: int):
    """契约 GET /accounting-entries/{id}：单条分录（租户隔离，40401 兜底）。"""
    d = domain_from(request)
    ae = FAccountingEntry.objects.filter(
        id=id, tenant_id=d.tenant_id, deleted=0).first()
    if ae is None:
        raise ApiError(404, CODE_NOT_FOUND, "分录不存在")
    return ok(request, _to_api_accounting_entry(d.tenant_id, ae))


def page_cost_pools(request: HttpRequest):
    """契约 GET /cost-pools：成本池分页（projectId/period/status 过滤）。"""
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = FCostPool.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("projectId"):
        qs = qs.filter(project_id=request.GET["projectId"])
    if request.GET.get("period"):
        qs = qs.filter(period=request.GET["period"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + limit]
    return ok(request, {"list": [
        _to_api_cost_pool(cp) for cp in rows
    ], "total": total, "page": page, "size": size})


def calculate_cost_pool(request: HttpRequest):
    """契约 POST /cost-pools/calculate：全成本核算（F-20）。

    直接费用 = Σ报销(PAID/VOUCHER_SYNCED) + Σ外拨(APPROVED=实付语义)；
    间接分摊 = 单条管理费行（来源 f_indirect_fee，M1 固定规则，basis 可复算）；
    全成本 = 直接 + Σ间接。LOCKED 行拒绝复算（40901）；
    幂等键 (tenant, project, period, deleted=0)：复算 = 更新同一行。
    """
    d = domain_from(request)
    b = read_json(request)
    project_id = b.get("projectId")
    period = b.get("period")
    if not project_id or not isinstance(project_id, int) or project_id <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    if not period or not isinstance(period, str) or not re.fullmatch(r"\d{6}", period):
        raise ApiError(400, CODE_BAD_REQUEST, "period 须为 YYYYMM")
    p = EProject.objects.filter(
        id=project_id, tenant_id=d.tenant_id, deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    existing = FCostPool.objects.filter(
        tenant_id=d.tenant_id, project_id=project_id,
        period=period, deleted=0).first()
    if existing is not None and existing.status == "LOCKED":
        raise ApiError(409, CODE_CONFLICT, "LOCKED 成本池禁止复算")
    outward_sum = FOutward.objects.filter(
        tenant_id=d.tenant_id, project_id=project_id,
        status="APPROVED", deleted=0,
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    direct = _d2(
        _sum_expense(d.tenant_id, project_id, ("PAID", "VOUCHER_SYNCED"))
        + outward_sum
    )
    indirect_alloc: list[dict] = []
    fee = FIndirectFee.objects.filter(
        tenant_id=d.tenant_id, project_id=project_id,
        period=period, deleted=0).first()
    if fee is not None:
        indirect_alloc.append({
            "type": "管理费", "basis": f"indirect_fee:{fee.id}",
            "amount": num2(fee.indirect_amount),
        })
    indirect_total = sum(
        (Decimal(x["amount"]) for x in indirect_alloc), Decimal("0"))
    full_cost = _d2(direct + indirect_total)
    cp, created = FCostPool.objects.update_or_create(
        tenant_id=d.tenant_id, project_id=project_id,
        period=period, deleted=0,
        defaults={
            "creator_id": existing.creator_id if existing is not None else d.user_id,
            "legal_entity_id": p.legal_entity_id or 1,
            "direct_cost": direct, "indirect_alloc_json": indirect_alloc,
            "full_cost": full_cost, "status": "CALCULATED",
            "basis_rule_id": None, "policy_pack_id": None,
            "modifier_id": d.user_id,
        })
    if created:
        cp.code = code_of("CPL", cp.id)
        cp.save(update_fields=["code", "updated_at"])
    return ok(request, _to_api_cost_pool(cp))


def get_cost_pool(request: HttpRequest, project_id: int):
    """契约 GET /cost-pools/{projectId}：单项目全成本明细（period 必填）。"""
    d = domain_from(request)
    period = request.GET.get("period")
    if not period:
        raise ApiError(400, CODE_BAD_REQUEST, "period 必填")
    cp = FCostPool.objects.filter(
        tenant_id=d.tenant_id, project_id=project_id,
        period=period, deleted=0).first()
    if cp is None:
        raise ApiError(404, CODE_NOT_FOUND, "成本池不存在")
    return ok(request, _to_api_cost_pool(cp))


# ---------------------------------------------------------------------------
# 决算单 create/get/approve（Task 6 / F-13 / A7）：创建即落快照
# ---------------------------------------------------------------------------
def _settlement_totals(tenant_id: int, project_id: int) -> tuple[Decimal, Decimal, Decimal]:
    """决算快照口径：income=Σ CLAIMED 到账；expense=Σ (APPROVED/PAID/VOUCHER_SYNCED)
    报销（与 funding_execution 口径一致，FOutward 不计入）；remaining=income−expense。
    快照只在 create 时计算落库，读取不复算。"""
    income = _sum_claimed_income(tenant_id, project_id)
    expense = _sum_expense(tenant_id, project_id, ("APPROVED", "PAID", "VOUCHER_SYNCED"))
    return income, expense, _d2(income - expense)


def _to_api_settlement(s: FSettlement) -> dict:
    """契约 Settlement schema 键（camelCase，Money=string）。"""
    return {
        "id": s.id, "code": s.code,
        "projectId": s.project_id, "closingDate": (
            s.closing_date.isoformat() if s.closing_date else None),
        "incomeTotal": num2(s.income_total),
        "expenseTotal": num2(s.expense_total),
        "remaining": num2(s.remaining),
        "treatment": s.treatment, "auditReportUrl": s.audit_report_url,
        "status": s.status,
    }


def create_settlement(request: HttpRequest):
    """契约 POST /settlements：创建决算单（F-13）。

    落地即 AUDITING（契约无 SUBMIT 端点）；幂等键 (tenant, project, deleted=0)：
    DRAFT/SUBMITTED/AUDITING/REJECTED → update_or_create 重算快照覆盖（REJECTED 重开，
    Review Focus #4）；APPROVED 终态拒绝复算（40901）。code SET 前缀仅新建时回填。
    """
    d = domain_from(request)
    b = read_json(request)
    project_id = b.get("projectId")
    closing_date = _parse_date(b.get("closingDate"))
    if closing_date is None:
        raise ApiError(400, CODE_BAD_REQUEST, "closingDate 须为 YYYY-MM-DD")
    p = EProject.objects.filter(
        id=project_id, tenant_id=d.tenant_id, deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    treatment = b.get("treatment") or "结转"
    if treatment not in ("结转", "收回", "留用"):
        raise ApiError(400, CODE_BAD_REQUEST, "treatment 仅 结转|收回|留用")
    score_detail = b.get("scoreDetail")
    if score_detail is not None and not isinstance(score_detail, dict):
        raise ApiError(400, CODE_BAD_REQUEST, "scoreDetail 须为对象")
    existing = FSettlement.objects.filter(
        tenant_id=d.tenant_id, project_id=project_id, deleted=0).first()
    if existing is not None and existing.status == "APPROVED":
        raise ApiError(409, CODE_CONFLICT, "决算已 APPROVED，禁止重算")
    income, expense, remaining = _settlement_totals(d.tenant_id, project_id)
    snap = {
        "creator_id": existing.creator_id if existing is not None else d.user_id,
        "legal_entity_id": p.legal_entity_id or 1,
        "closing_date": closing_date,
        "income_total": income, "expense_total": expense, "remaining": remaining,
        "treatment": treatment, "status": "AUDITING", "modifier_id": d.user_id,
    }
    if score_detail is not None:
        snap["score_detail"] = score_detail
    else:
        snap["score_detail"] = {"disbursementTotal": num2(FOutward.objects.filter(
            tenant_id=d.tenant_id, project_id=project_id,
            status="APPROVED", deleted=0,
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0"))}
    with transaction.atomic():
        if existing is not None:
            row = FSettlement.objects.select_for_update().filter(
                id=existing.id, tenant_id=d.tenant_id, deleted=0).first()
            for k, v in snap.items():
                setattr(row, k, v)
            row.save()
        else:
            row = FSettlement.objects.create(**snap, project_id=project_id,
                                             tenant_id=d.tenant_id)
        if row.code is None:
            row.code = code_of("SET", row.id)
            row.save(update_fields=["code", "updated_at"])
    approval.log(d.tenant_id, "SETTLEMENT", row.id, 0, d.user_id, "R-FINANCE",
                 "SUBMIT", None)
    return ok(request, _to_api_settlement(row))


def get_settlement(request: HttpRequest, project_id: int):
    """契约 GET /settlements/{projectId}：读快照（tenant 隔离，40401 兜底，不复算）。"""
    d = domain_from(request)
    s = FSettlement.objects.filter(
        id__isnull=False, tenant_id=d.tenant_id, project_id=project_id,
        deleted=0).order_by("-id").first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "决算单不存在")
    return ok(request, _to_api_settlement(s))


def approve_settlement(request: HttpRequest, settlement_id: int):
    """契约 POST /settlements/{settlementId}/approve：审批（A7 两级审批面）。

    仅 AUDITING 可操作（否则 40901）；APPROVE→APPROVED（treatment 必填校验沿用
    create 枚举）；REJECT→REJECTED；scoreDetail 可选落 JSONB；终态重放 40901。
    """
    d = domain_from(request)
    b = read_json(request)
    action = b.get("action")
    if action not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 仅 APPROVE|REJECT")
    with transaction.atomic():
        s = FSettlement.objects.select_for_update().filter(
            id=settlement_id, tenant_id=d.tenant_id, deleted=0).first()
        if s is None:
            raise ApiError(404, CODE_NOT_FOUND, "决算单不存在")
        if s.status != "AUDITING":
            raise ApiError(409, CODE_CONFLICT, "仅 AUDITING 可审批")
        treatment = b.get("treatment")
        if treatment is not None and treatment not in ("结转", "收回", "留用"):
            raise ApiError(400, CODE_BAD_REQUEST, "treatment 仅 结转|收回|留用")
        score_detail = b.get("scoreDetail")
        if score_detail is not None and not isinstance(score_detail, dict):
            raise ApiError(400, CODE_BAD_REQUEST, "scoreDetail 须为对象")
        if action == "APPROVE":
            if treatment:
                s.treatment = treatment
            s.status = "APPROVED"
        else:
            s.status = "REJECTED"
        if score_detail is not None:
            s.score_detail = score_detail
        s.approved_by = d.user_id
        s.approved_at = dj_tz.now()
        s.modifier_id = d.user_id
        s.save()
        approval.log(d.tenant_id, "SETTLEMENT", s.id, 1, d.user_id, "R-FINANCE",
                     action, b.get("comment"))
        return ok(request, _to_api_settlement(s))
