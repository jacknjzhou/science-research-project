"""科研绩效域 M API（对齐 Go modules/performance：handler + records + calculate + portrait）。

方案：CRUD + activate（同维度旧 active→SUPERSEDED，本方案→ACTIVE，一个事务）
因子：upsert/update/delete
计算：scoring_rule 四法（COUNT/BY_LEVEL/BY_AMOUNT/LADDER）+ 跨域真聚合
记录：CALCULATED→CONFIRMED→APPROVED→PAID（confirm/appeal/approve/void）
发放：DRAFT/APPROVING→APPROVED→PAID / REJECTED（pay 联动记录→PAID）
画像：/portrait/{userId} 项目/经费/成果/考核真聚合
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.performance.models import MPayout, MRecord, MRecordItem, MScheme, MSchemeFactor
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
    ok,
    read_json,
    read_json_soft,
)

MANAGER_ROLES = {"R-ADMIN", "R-MANAGER", "R-LEADER"}
PAYOUT_ROLES = {"R-ADMIN", "R-MANAGER", "R-LEADER", "R-FINANCE"}

RE_YEAR = re.compile(r"^(\d{4})$")
RE_QUARTER = re.compile(r"^(\d{4})\s*[Qq]([1-4])$")
RE_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = max(int(request.GET.get("page", "1") or "1"), 1)
        size = min(max(int(request.GET.get("size", "20") or "20"), 1), 200)
    except ValueError:
        page, size = 1, 20
    return page, size, size, (page - 1) * size


def _is_manager(d) -> bool:
    return any(r in MANAGER_ROLES for r in d.roles)


def _can_payout(d) -> bool:
    return any(r in PAYOUT_ROLES for r in d.roles)


def _round2(f: float) -> float:
    return float(Decimal(str(f)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _period_range(period: str) -> tuple[date | None, date | None]:
    """YEAR="2026" / QUARTER="2026Q3" / MONTH="2026-03" → [from,to] 闭区间。"""
    p = period.strip()
    if m := RE_QUARTER.match(p):
        y, q = int(m.group(1)), int(m.group(2))
        start = date(y, (q - 1) * 3 + 1, 1)
        nxt = date(y + (3 * q) // 12, ((3 * q) % 12) + 1, 1)
    elif m := RE_MONTH.match(p):
        y, mo = int(m.group(1)), int(m.group(2))
        start = date(y, mo, 1)
        nxt = date(y + (mo // 12), (mo % 12) + 1, 1)
    elif m := RE_YEAR.match(p):
        y = int(m.group(1))
        start, nxt = date(y, 1, 1), date(y + 1, 1, 1)
    else:
        return None, None
    return start, nxt


def _scheme_or_404(request: HttpRequest, scheme_id: int) -> MScheme:
    s = MScheme.objects.filter(id=scheme_id, tenant_id=domain_from(request).tenant_id,
                               deleted=0).first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "方案不存在")
    return s


def _record_or_404(request: HttpRequest, record_id: int) -> MRecord:
    r = MRecord.objects.filter(id=record_id, tenant_id=domain_from(request).tenant_id,
                               deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return r


# ---------------------------------------------------------------------------
# mapper
# ---------------------------------------------------------------------------

def to_api_scheme(s: MScheme, factors: list | None = None) -> dict:
    out = {
        "id": s.id, "code": s.code, "name": s.name, "period_type": s.period_type,
        "scope_dept_id": s.scope_dept_id, "scope_staff_type": s.scope_staff_type,
        "effective_period": s.effective_period, "version": s.version,
        "active": s.active, "status": s.status,
        "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
    }
    if factors is not None:
        out["factors"] = [to_api_factor(f) for f in factors]
    return out


def to_api_factor(f: MSchemeFactor) -> dict:
    return {
        "id": f.id, "scheme_id": f.scheme_id, "factor_code": f.factor_code,
        "factor_name": f.factor_name, "weight": f"{f.weight:.2f}",
        "scoring_rule": f.scoring_rule or {},
        "max_score": (f"{f.max_score:.2f}" if f.max_score is not None else None),
        "data_source": f.data_source, "clause_ref": f.clause_ref, "sort_no": f.sort_no,
    }


def to_api_record(r: MRecord, items: list | None = None) -> dict:
    out = {
        "id": r.id, "scheme_id": r.scheme_id, "scheme_name": None,
        "staff_user_id": r.staff_user_id, "staff_name": None, "period": r.period,
        "dept_id": r.dept_id, "total_score": f"{r.total_score:.2f}",
        "rank": r.rank, "status": r.status, "calc_batch": r.calc_batch,
        "calc_at": (r.calc_at.isoformat() if r.calc_at else None),
        "confirmed_at": (r.confirmed_at.isoformat() if r.confirmed_at else None),
        "approve_at": (r.approve_at.isoformat() if r.approve_at else None),
    }
    if items is not None:
        out["items"] = [to_api_record_item(i) for i in items]
    return out


def to_api_record_item(i: MRecordItem) -> dict:
    return {
        "id": i.id, "record_id": i.record_id, "factor_code": i.factor_code,
        "factor_name": None, "metric_value": f"{i.metric_value:.4f}",
        "raw_score": f"{i.raw_score:.2f}", "weighted_score": f"{i.weighted_score:.2f}",
        "evidence": i.evidence or [],
    }


def to_api_payout(p: MPayout) -> dict:
    return {
        "id": p.id, "code": p.code, "record_id": p.record_id,
        "payee_user_id": p.payee_user_id, "payee_name": None,
        "amount": f"{p.amount:.2f}", "period": p.period, "pay_channel": p.pay_channel,
        "status": p.status,
        "approved_at": (p.approved_at.isoformat() if p.approved_at else None),
        "paid_at": (p.paid_at.isoformat() if p.paid_at else None),
        "voucher_code": p.voucher_code,
    }


# ---------------------------------------------------------------------------
# 方案 / 因子
# ---------------------------------------------------------------------------

def list_schemes(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = MScheme.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if v := request.GET.get("period_type"):
        qs = qs.filter(period_type=v)
    if v := request.GET.get("effective_period"):
        qs = qs.filter(effective_period=v)
    if v := request.GET.get("scope_dept_id"):
        try:
            qs = qs.filter(scope_dept_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("keyword"):
        qs = qs.filter(name__icontains=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_scheme(s) for s in rows],
                        "total": total, "page": page, "size": size})


def get_scheme(request: HttpRequest, id: int):
    s = _scheme_or_404(request, id)
    factors = list(MSchemeFactor.objects.filter(scheme_id=id).order_by("sort_no", "id"))
    return ok(request, to_api_scheme(s, factors))


def create_scheme(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("name") or not b.get("period_type") or not b.get("effective_period"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    s = MScheme.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        security_level=b.get("security_level") or "INTERNAL",
        legal_entity_id=b.get("legal_entity_id"), policy_pack_id=b.get("policy_pack_id"),
        name=b["name"], period_type=b["period_type"],
        scope_dept_id=b.get("scope_dept_id"), scope_staff_type=b.get("scope_staff_type"),
        effective_period=b["effective_period"], remark=b.get("remark"))
    s.code = f"PERF-{s.created_at.year}-{s.id:06d}"
    s.save(update_fields=["code"])
    return ok(request, to_api_scheme(s))


def update_scheme(request: HttpRequest, id: int):
    d = domain_from(request)
    s = _scheme_or_404(request, id)
    if s.status != "DRAFT":
        raise ApiError(409, CODE_CONFLICT, "方案不存在或状态不可编辑（仅 DRAFT）")
    b = read_json(request)
    if b.get("name"):
        s.name = b["name"]
    if b.get("period_type"):
        s.period_type = b["period_type"]
    if b.get("scope_dept_id") is not None:
        s.scope_dept_id = b["scope_dept_id"]
    if b.get("scope_staff_type") is not None:
        s.scope_staff_type = b["scope_staff_type"]
    if b.get("effective_period"):
        s.effective_period = b["effective_period"]
    if b.get("remark") is not None:
        s.remark = b["remark"]
    s.modifier_id = d.user_id
    s.save()
    return ok(request, to_api_scheme(s))


def delete_scheme(request: HttpRequest, id: int):
    d = domain_from(request)
    s = _scheme_or_404(request, id)
    s.deleted = 1
    s.modifier_id = d.user_id
    s.save(update_fields=["deleted", "modifier_id", "updated_at"])
    return ok(request, {"id": id, "deleted": True})


def activate_scheme(request: HttpRequest, id: int):
    """同维度旧 active → SUPERSEDED，本方案 → ACTIVE（一个事务内两步）。"""
    d = domain_from(request)
    s = _scheme_or_404(request, id)
    with transaction.atomic():
        sup = MScheme.objects.filter(
            tenant_id=d.tenant_id, deleted=0, active=True,
            period_type=s.period_type, effective_period=s.effective_period,
            scope_dept_id=s.scope_dept_id).exclude(id=id)
        if s.scope_staff_type:
            sup = sup.filter(scope_staff_type=s.scope_staff_type)
        else:
            sup = sup.filter(Q(scope_staff_type__isnull=True) | Q(scope_staff_type=""))
        sup.update(status="SUPERSEDED", active=False, updated_at=dj_tz.now())
        s.status = "ACTIVE"
        s.active = True
        s.modifier_id = d.user_id
        s.save()
    return ok(request, to_api_scheme(s))


def list_factors(request: HttpRequest, id: int):
    _scheme_or_404(request, id)
    rows = list(MSchemeFactor.objects.filter(scheme_id=id).order_by("sort_no", "id"))
    return ok(request, {"list": [to_api_factor(f) for f in rows]})


def upsert_factor(request: HttpRequest, id: int):
    d = domain_from(request)
    _scheme_or_404(request, id)
    b = read_json(request)
    if not b.get("factor_code") or not b.get("scoring_rule") or not b.get("data_source"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    f, _ = MSchemeFactor.objects.update_or_create(
        scheme_id=id, tenant_id=d.tenant_id, factor_code=b["factor_code"],
        defaults={
            "factor_name": b.get("factor_name"),
            "weight": Decimal(str(b.get("weight") or 0)),
            "scoring_rule": b["scoring_rule"],
            "max_score": (Decimal(str(b["max_score"])) if b.get("max_score") else None),
            "data_source": b["data_source"], "clause_ref": b.get("clause_ref"),
            "sort_no": b.get("sort_no") or 0, "creator_id": d.user_id,
        })
    return ok(request, to_api_factor(f))


def update_factor(request: HttpRequest, id: int, factor_id: int):
    _scheme_or_404(request, id)
    f = MSchemeFactor.objects.filter(id=factor_id, scheme_id=id).first()
    if f is None:
        raise ApiError(404, CODE_NOT_FOUND, "因子不存在")
    b = read_json(request)
    if b.get("factor_name"):
        f.factor_name = b["factor_name"]
    if b.get("weight") is not None:
        f.weight = Decimal(str(b["weight"]))
    if b.get("scoring_rule") is not None:
        f.scoring_rule = b["scoring_rule"]
    if b.get("max_score") is not None:
        f.max_score = (Decimal(str(b["max_score"])) if b["max_score"] else None)
    if b.get("data_source"):
        f.data_source = b["data_source"]
    if b.get("clause_ref") is not None:
        f.clause_ref = b["clause_ref"]
    if b.get("sort_no") is not None:
        f.sort_no = b["sort_no"]
    f.save()
    return ok(request, to_api_factor(f))


def delete_factor(request: HttpRequest, id: int, factor_id: int):
    _scheme_or_404(request, id)
    n, _ = MSchemeFactor.objects.filter(id=factor_id, scheme_id=id).delete()
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "因子不存在")
    return ok(request, {"factor_id": factor_id, "deleted": True})


# ---------------------------------------------------------------------------
# 计算（calculate.go 忠实移植）
# ---------------------------------------------------------------------------

def _score_factor(rule: dict, weight: float, max_score: float,
                  agg: dict) -> tuple[float, float, float, list]:
    """返回 (metric, raw, weighted, evidence)。"""
    method = str(rule.get("method") or "").upper().strip()
    unit = float(rule.get("unit") or 0) or 1.0
    evidence = agg.get("evidence") or []
    if method == "COUNT":
        metric = float(agg["total"])
        raw = metric * unit
    elif method == "BY_LEVEL":
        metric = float(agg["total"])
        level_map = rule.get("levelMap") or {}
        raw = sum(float(cnt) * float(level_map.get(k, 0)) for k, cnt in agg["by_type"].items())
    elif method == "BY_AMOUNT":
        metric = float(agg["amount"])
        raw = metric * unit
    elif method == "LADDER":
        metric = float(agg["amount"]) or float(agg["total"])
        raw = 0.0
        for t in rule.get("ladder") or []:
            if float(t.get("min", 0)) <= metric <= float(t.get("max", 0)):
                raw = float(t.get("score", 0))
                break
    else:  # MANUAL / 未知 → 不自动计分
        metric, raw = 0.0, 0.0
    if max_score > 0 and raw > max_score:
        raw = max_score
    weighted = raw * weight / 100.0
    return metric, raw, weighted, evidence


def _agg_outputs(tenant_id: int, staff_id: int, f, t) -> dict:
    from apps.output.models import ROutput
    qs = ROutput.objects.filter(
        tenant_id=tenant_id, deleted=0,
        status__in=("CLAIMED", "ASSIGNED_TO_PROJECT", "COUNTED_FOR_PERFORMANCE"))
    if f:
        qs = qs.filter(publish_date__gte=f)
    if t:
        qs = qs.filter(publish_date__lte=t)
    rows = [o for o in qs
            if any(isinstance(a, dict) and a.get("user_id") == staff_id for a in (o.authors or []))]
    by_type: dict[str, int] = {}
    for o in rows:
        by_type[o.output_type] = by_type.get(o.output_type, 0) + 1
    return {"by_type": by_type, "total": len(rows), "amount": 0.0, "evidence": [
        {"output_id": o.id, "output_type": o.output_type, "title": o.title} for o in rows]}


def _agg_projects(tenant_id: int, staff_id: int, f, t) -> dict:
    from apps.project.models import EProject
    qs = EProject.objects.filter(tenant_id=tenant_id, deleted=0)
    if f:
        qs = qs.filter(start_date__gte=f)
    if t:
        qs = qs.filter(start_date__lte=t)
    # member_ids 为 JSONB 数组：sqlite/PG 兼容走 Python 侧过滤（contains 不可用，见 Phase 1 教训）
    rows = [p for p in qs
            if p.pi_user_id == staff_id
            or any(int(m) == staff_id for m in (p.member_ids or [])
                   if isinstance(m, (int, str)) and str(m).isdigit())]
    by_type: dict[str, int] = {}
    total = 0
    amount = 0.0
    evidence = []
    for p in rows:
        total += 1
        by_type[p.project_type or ""] = by_type.get(p.project_type or "", 0) + 1
        amount += float(p.total_budget or 0)
        evidence.append({"project_id": p.id, "project_type": p.project_type,
                         "total_budget": float(p.total_budget or 0)})
    return {"by_type": by_type, "total": total, "amount": amount, "evidence": evidence}


def _agg_income(tenant_id: int, staff_id: int, f, t) -> dict:
    from apps.funding.models import FIncome
    qs = FIncome.objects.filter(tenant_id=tenant_id, claim_status="CLAIMED",
                                claimed_by=staff_id)
    if f:
        qs = qs.filter(receipt_date__gte=f)
    if t:
        qs = qs.filter(receipt_date__lte=t)
    total = qs.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    return {"by_type": {}, "total": 0, "amount": float(total), "evidence": [
        {"income_id": i.id, "amount": float(i.amount)} for i in qs]}


def _agg_deals(tenant_id: int, staff_id: int, f, t) -> dict:
    """T_DEAL 为 Phase 4 域：表未建时静默空聚合（对齐 Go 查询失败静默语义取空）。"""
    try:
        from django.db import connection
        if connection.introspection.table_names():
            tables = connection.introspection.table_names()
            if "t_deal" not in tables and "T_DEAL" not in tables:
                return {"by_type": {}, "total": 0, "amount": 0.0, "evidence": []}
        from apps.transfer.models import TDeal  # Phase 4 落地后启用
        qs = TDeal.objects.filter(tenant_id=tenant_id)
        if f:
            qs = qs.filter(signed_at__gte=f)
        if t:
            qs = qs.filter(signed_at__lte=t)
        total = qs.aggregate(s=Sum("contract_amount"))["s"] or Decimal("0")
        return {"by_type": {}, "total": 0, "amount": float(total), "evidence": []}
    except Exception:
        return {"by_type": {}, "total": 0, "amount": 0.0, "evidence": []}


def _compute_staff(request: HttpRequest, scheme: MScheme, factors: list,
                   staff_id: int, dept_id, period: str, f, t, batch: str) -> bool:
    """对单个 staff 聚合→算分→upsert record→重建 items。返回是否新增。"""
    d = domain_from(request)
    existed = MRecord.objects.filter(
        tenant_id=d.tenant_id, deleted=0, scheme_id=scheme.id,
        staff_user_id=staff_id, period=period).exists()
    need = {f_.data_source for f_ in factors}
    aggs = {}
    if "R_OUTPUT" in need:
        aggs["R_OUTPUT"] = _agg_outputs(d.tenant_id, staff_id, f, t)
    if "E_PROJECT" in need:
        aggs["E_PROJECT"] = _agg_projects(d.tenant_id, staff_id, f, t)
    if "F_INCOME" in need:
        aggs["F_INCOME"] = _agg_income(d.tenant_id, staff_id, f, t)
    if "T_DEAL" in need:
        aggs["T_DEAL"] = _agg_deals(d.tenant_id, staff_id, f, t)

    total = 0.0
    item_rows = []
    for fac in factors:
        agg = aggs.get(fac.data_source, {"by_type": {}, "total": 0, "amount": 0.0, "evidence": []})
        metric, raw, weighted, ev = _score_factor(
            fac.scoring_rule or {}, float(fac.weight or 0),
            float(fac.max_score) if fac.max_score is not None else 0.0, agg)
        total += weighted
        item_rows.append({"code": fac.factor_code, "metric": metric, "raw": raw,
                          "wgt": weighted, "ev": ev})

    detail = {
        "period": period, "calc_batch": batch, "scheme_id": scheme.id,
        "total": _round2(total),
        "factors": [{"factor_code": it["code"], "metric": it["metric"],
                     "raw_score": _round2(it["raw"]),
                     "weighted_score": _round2(it["wgt"])} for it in item_rows],
    }
    rec = MRecord.objects.filter(
        tenant_id=d.tenant_id, deleted=0, scheme_id=scheme.id,
        staff_user_id=staff_id, period=period).first()
    if rec is None:
        rec = MRecord(tenant_id=d.tenant_id, creator_id=d.user_id,
                      scheme_id=scheme.id, staff_user_id=staff_id, period=period)
    rec.dept_id = dept_id
    rec.total_score = Decimal(str(_round2(total)))
    rec.calc_detail = detail
    rec.calc_batch = batch
    rec.calc_at = dj_tz.now()
    rec.save()
    MRecordItem.objects.filter(record_id=rec.id).delete()
    for it in item_rows:
        MRecordItem.objects.create(
            record_id=rec.id, tenant_id=d.tenant_id, factor_code=it["code"],
            metric_value=Decimal(str(round(it["metric"], 4))),
            raw_score=Decimal(str(_round2(it["raw"]))),
            weighted_score=Decimal(str(_round2(it["wgt"]))),
            evidence=it["ev"])
    return not existed


def calculate_performance(request: HttpRequest, id: int):
    d = domain_from(request)
    scheme = _scheme_or_404(request, id)
    b = read_json(request)
    if not b.get("period"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    factors = list(MSchemeFactor.objects.filter(scheme_id=id))
    if not factors:
        raise ApiError(400, CODE_BAD_REQUEST, "方案未配置因子，无法计算")
    f, t = _period_range(b["period"])

    staff: list[int] = b.get("staff_ids") or []
    staff_dept: dict[int, int | None] = {}
    if not staff:
        from apps.project.models import EProject
        qs = EProject.objects.filter(tenant_id=d.tenant_id, deleted=0)
        if b.get("dept_ids"):
            qs = qs.filter(department_id__in=b["dept_ids"])
        for p in qs:
            if p.pi_user_id not in staff_dept:
                staff.append(p.pi_user_id)
                staff_dept[p.pi_user_id] = p.department_id

    batch = request.headers.get("Idempotency-Key") or f"BATCH-{b['period']}-{int(time.time())}"
    inserted = 0
    updated = 0
    for sid in staff:
        is_new = _compute_staff(request, scheme, factors, sid, staff_dept.get(sid),
                                b["period"], f, t, batch)
        if is_new:
            inserted += 1
        else:
            updated += 1
    return ok(request, {"calc_batch": batch, "period": b["period"],
                        "computed": len(staff), "inserted": inserted, "updated": updated})


# ---------------------------------------------------------------------------
# 记录 / 发放
# ---------------------------------------------------------------------------

def list_records(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = MRecord.objects.filter(tenant_id=d.tenant_id, deleted=0)
    staff = request.GET.get("staff_user_id")
    if not _is_manager(d):
        staff = str(d.user_id)
    if staff:
        try:
            qs = qs.filter(staff_user_id=int(staff))
        except ValueError:
            pass
    if v := request.GET.get("scheme_id"):
        try:
            qs = qs.filter(scheme_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("period"):
        qs = qs.filter(period=v)
    if v := request.GET.get("dept_id"):
        try:
            qs = qs.filter(dept_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("keyword"):
        qs = qs.filter(code__icontains=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_record(r) for r in rows],
                        "total": total, "page": page, "size": size})


def _read_record_for_abac(request: HttpRequest, record_id: int, mgr_only: bool) -> MRecord:
    d = domain_from(request)
    rec = _record_or_404(request, record_id)
    if mgr_only:
        if not _is_manager(d):
            raise ApiError(403, CODE_FORBIDDEN, "无权限：需管理角色")
        return rec
    if not _is_manager(d) and rec.staff_user_id != d.user_id:
        raise ApiError(403, CODE_FORBIDDEN, "越权：只能访问本人记录")
    return rec


def get_record(request: HttpRequest, id: int):
    return ok(request, to_api_record(_read_record_for_abac(request, id, False)))


def get_record_detail(request: HttpRequest, id: int):
    rec = _read_record_for_abac(request, id, False)
    items = list(MRecordItem.objects.filter(record_id=rec.id).order_by("id"))
    return ok(request, to_api_record(rec, items))


def confirm_record(request: HttpRequest, id: int):
    d = domain_from(request)
    rec = _read_record_for_abac(request, id, False)
    if rec.status != "CALCULATED":
        raise ApiError(409, CODE_CONFLICT, "非法状态迁移（仅 CALCULATED 可确认）")
    rec.status = "CONFIRMED"
    rec.confirmed_by = d.user_id
    rec.confirmed_at = dj_tz.now()
    rec.save()
    return ok(request, to_api_record(rec))


def appeal_record(request: HttpRequest, id: int):
    d = domain_from(request)
    rec = _read_record_for_abac(request, id, False)
    b = read_json(request)
    if not b.get("reason"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    if rec.status not in ("CALCULATED", "CONFIRMED"):
        raise ApiError(409, CODE_CONFLICT, "非法状态迁移（仅 CALCULATED/CONFIRMED 可申诉）")
    rec.appeal_reason = b["reason"]
    rec.modifier_id = d.user_id
    rec.save(update_fields=["appeal_reason", "modifier_id", "updated_at"])
    return ok(request, to_api_record(rec))


def approve_record(request: HttpRequest, id: int):
    d = domain_from(request)
    rec = _read_record_for_abac(request, id, True)
    if rec.status != "CONFIRMED":
        raise ApiError(409, CODE_CONFLICT, "非法状态迁移（仅 CONFIRMED 可审批）")
    rec.status = "APPROVED"
    rec.approve_by = d.user_id
    rec.approve_at = dj_tz.now()
    rec.save()
    return ok(request, to_api_record(rec))


def void_record(request: HttpRequest, id: int):
    d = domain_from(request)
    rec = _read_record_for_abac(request, id, True)
    b = read_json_soft(request)
    if rec.status == "PAID":
        raise ApiError(409, CODE_CONFLICT, "非法状态迁移（已发放记录不可作废）")
    rec.status = "VOIDED"
    rec.void_reason = (b or {}).get("void_reason") or (b or {}).get("reason")
    rec.modifier_id = d.user_id
    rec.save()
    return ok(request, to_api_record(rec))


def list_payouts(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = MPayout.objects.filter(tenant_id=d.tenant_id, deleted=0)
    payee = request.GET.get("payee_user_id")
    if not _can_payout(d):
        payee = str(d.user_id)
    if payee:
        try:
            qs = qs.filter(payee_user_id=int(payee))
        except ValueError:
            pass
    if v := request.GET.get("period"):
        qs = qs.filter(period=v)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_payout(p) for p in rows],
                        "total": total, "page": page, "size": size})


def get_payout(request: HttpRequest, id: int):
    d = domain_from(request)
    p = MPayout.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "发放单不存在")
    if not _can_payout(d) and p.payee_user_id != d.user_id:
        raise ApiError(403, CODE_FORBIDDEN, "越权：只能访问本人发放单")
    return ok(request, to_api_payout(p))


def create_payout(request: HttpRequest):
    d = domain_from(request)
    if not _can_payout(d):
        raise ApiError(403, CODE_FORBIDDEN, "无权限：需发放权限角色")
    b = read_json(request)
    if not b.get("record_id") or not b.get("amount"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    rec = _record_or_404(request, b["record_id"])
    if rec.status != "APPROVED":
        raise ApiError(409, CODE_CONFLICT, "仅 APPROVED 记录可发起发放")
    p = MPayout.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id, record_id=rec.id,
        payee_user_id=rec.staff_user_id, amount=Decimal(str(b["amount"])),
        period=rec.period, pay_channel=b.get("pay_channel"),
        security_level="INTERNAL")
    return ok(request, to_api_payout(p))


def _payout_or_404(request: HttpRequest, payout_id: int) -> MPayout:
    p = MPayout.objects.filter(id=payout_id, tenant_id=domain_from(request).tenant_id,
                               deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "发放单不存在")
    return p


def approve_payout(request: HttpRequest, id: int):
    d = domain_from(request)
    if not _can_payout(d):
        raise ApiError(403, CODE_FORBIDDEN, "无权限")
    p = _payout_or_404(request, id)
    if p.status not in ("DRAFT", "APPROVING"):
        raise ApiError(409, CODE_CONFLICT, "非法状态迁移（仅 DRAFT/APPROVING 可审批）")
    p.status = "APPROVED"
    p.approved_at = dj_tz.now()
    p.modifier_id = d.user_id
    p.save()
    return ok(request, to_api_payout(p))


def pay_payout(request: HttpRequest, id: int):
    d = domain_from(request)
    if not _can_payout(d):
        raise ApiError(403, CODE_FORBIDDEN, "无权限")
    p = _payout_or_404(request, id)
    b = read_json_soft(request)
    if p.status != "APPROVED":
        raise ApiError(409, CODE_CONFLICT, "非法状态迁移（仅 APPROVED 可发放）")
    p.status = "PAID"
    p.paid_at = dj_tz.now()
    p.voucher_code = (b or {}).get("voucher_code")
    p.modifier_id = d.user_id
    p.save()
    MRecord.objects.filter(id=p.record_id, tenant_id=d.tenant_id).exclude(
        status="PAID").update(status="PAID", updated_at=dj_tz.now())  # 联动尽力而为
    return ok(request, to_api_payout(p))


def reject_payout(request: HttpRequest, id: int):
    d = domain_from(request)
    if not _can_payout(d):
        raise ApiError(403, CODE_FORBIDDEN, "无权限")
    p = _payout_or_404(request, id)
    b = read_json_soft(request)
    if p.status not in ("DRAFT", "APPROVING"):
        raise ApiError(409, CODE_CONFLICT, "非法状态迁移（仅 DRAFT/APPROVING 可驳回）")
    p.status = "REJECTED"
    p.reject_reason = (b or {}).get("reason")
    p.modifier_id = d.user_id
    p.save()
    return ok(request, to_api_payout(p))


def my_performance(request: HttpRequest):
    d = domain_from(request)
    qs = MRecord.objects.filter(tenant_id=d.tenant_id, deleted=0, staff_user_id=d.user_id)
    if v := request.GET.get("period"):
        qs = qs.filter(period=v)
    out = []
    for r in qs.order_by("-id"):
        items = list(MRecordItem.objects.filter(record_id=r.id).order_by("id"))
        out.append(to_api_record(r, items))
    return ok(request, {"list": out})


def perf_ranking(request: HttpRequest):
    d = domain_from(request)
    if not _is_manager(d):
        raise ApiError(403, CODE_FORBIDDEN, "无权限：排行仅管理角色可见")
    scheme_id = request.GET.get("scheme_id")
    period = request.GET.get("period")
    if not scheme_id or not period:
        raise ApiError(400, CODE_BAD_REQUEST, "缺少 scheme_id / period")
    top = 20
    if v := request.GET.get("top"):
        try:
            top = min(max(int(v), 1), 500)
        except ValueError:
            top = 20
    qs = (MRecord.objects.filter(tenant_id=d.tenant_id, deleted=0,
                                 scheme_id=int(scheme_id), period=period)
          .exclude(status="VOIDED").order_by("-total_score")[:top])
    out = [{"rank": i + 1, "staff_user_id": r.staff_user_id, "staff_name": None,
            "dept_id": r.dept_id, "total_score": f"{r.total_score:.2f}"}
           for i, r in enumerate(qs)]
    return ok(request, {"list": out})


# ---------------------------------------------------------------------------
# PI 画像（portrait.go：真聚合，无 mock 回退）
# ---------------------------------------------------------------------------

def portrait(request: HttpRequest, user_id: int):
    d = domain_from(request)
    if user_id <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "userId 非法")
    from apps.funding.models import FBudget, FBudgetLine
    from apps.output.models import ROutput
    from apps.project.models import EProject

    projs_qs = EProject.objects.filter(tenant_id=d.tenant_id, deleted=0)
    projs = [p for p in projs_qs
             if p.pi_user_id == user_id
             or any(int(m) == user_id for m in (p.member_ids or [])
                    if isinstance(m, (int, str)) and str(m).isdigit())]
    project_count = len(projs)
    budget_total = sum(float(p.total_budget or 0) for p in projs)
    proj_ids = [p.id for p in projs]
    budget_ids = list(FBudget.objects.filter(
        tenant_id=d.tenant_id, deleted=0, project_id__in=proj_ids).values_list("id", flat=True))
    used_total = float(FBudgetLine.objects.filter(budget_id__in=budget_ids, deleted=0)
                       .aggregate(s=Sum("amount_used"))["s"] or 0)
    exec_rate = 0.0
    if budget_total > 0:
        exec_rate = _round2(used_total / budget_total)
    output_count = sum(1 for o in ROutput.objects.filter(tenant_id=d.tenant_id, deleted=0)
                       if any(isinstance(a, dict) and a.get("user_id") == user_id
                              for a in (o.authors or [])))
    latest = (MRecord.objects.filter(tenant_id=d.tenant_id, deleted=0,
                                     staff_user_id=user_id)
              .exclude(status="VOIDED").order_by("-calc_at", "-id").first())
    latest_score = f"{latest.total_score:.2f}" if latest else "0.00"
    return ok(request, {
        "userId": user_id,
        "projects": {"count": project_count, "budgetTotal": f"{budget_total:.2f}",
                     "usedTotal": f"{used_total:.2f}", "execRate": exec_rate},
        "outputs": {"count": output_count},
        "assessment": {"latestScore": latest_score},
    })
