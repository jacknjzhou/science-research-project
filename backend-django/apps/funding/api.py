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
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.funding.mappings import (
    code_of,
    num2,
    num4,
    to_api_approval,
    to_api_budget,
    to_api_carryover,
    to_api_expense,
    to_api_income,
    to_api_line,
    to_api_outward,
    to_api_subject,
    to_api_warn_config,
)
from apps.funding.models import (
    FBudget,
    FBudgetLine,
    FCarryover,
    FExpense,
    FExpenseApproval,
    FIncome,
    FIndirectFee,
    FOutward,
    FSubject,
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
