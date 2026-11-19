"""G 域供应商门户（M2-c / C4）：询价可见与在线应价、合同进度脱敏只读。

隔离口径：供应商侧身份来自"令牌用户 → 所属机构 → 绑定的 GSupplier"，
一切读写都限定在该供应商被邀请/被签约的数据内；跨机构一律 404。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest

from apps.procure.api import _my_supplier
from apps.procure.models import GBid, GContract, GContractPayment, GRequisition
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


def _money_strict(v) -> Decimal | None:
    """金额口径：最多两位小数，多余精度=无效（禁静默进位）。"""
    if v is None:
        return None
    try:
        raw = Decimal(str(v))
        q = raw.quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return None
    return None if q != raw else q


def _num2(v) -> str:
    return f"{Decimal(str(v or 0)):.2f}"


def _my_bid_or_404(d, bid_id: int) -> tuple[GBid, Any]:
    """我（我的供应商）被邀请的询价；未邀请/跨租户一律 404。"""
    s = _my_supplier(d)
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "询价不存在")
    b = GBid.objects.filter(id=bid_id, tenant_id=d.tenant_id, deleted=0).first()
    if b is None or s.id not in [int(x) for x in (b.invited_supplier_ids or [])]:
        raise ApiError(404, CODE_NOT_FOUND, "询价不存在")
    return b, s


def list_supplier_inquiries(request: HttpRequest):
    """我被邀请的询价（脱敏：不含需求明细金额/内部预算）。"""
    d = domain_from(request)
    s = _my_supplier(d)
    if s is None:
        return ok(request, {"list": [], "total": 0})

    # invited_supplier_ids 是 JSON 数组：sqlite 不支持 JSON contains 查询，
    # 与 E 域看板 same 手法——Python 端过滤（单租户询价数量有限）。
    candidates = GBid.objects.filter(tenant_id=d.tenant_id, deleted=0).order_by("-id")[:500]
    bids = [
        b for b in candidates
        if s.id in [int(x) for x in (b.invited_supplier_ids or [])]
    ][:100]
    req_ids = [b.requisition_id for b in bids]
    reqs = {
        r.id: r
        for r in GRequisition.objects.filter(
            tenant_id=d.tenant_id, id__in=req_ids, deleted=0
        )
    }
    rows = []
    for b in bids:
        r = reqs.get(b.requisition_id)
        mine = [x for x in (b.bids_json or []) if int(x.get("supplierId", 0) or 0) == s.id]
        rows.append(
            {
                "id": b.id,
                "code": b.code,
                "method": b.method,
                "status": b.status,
                "title": (r.item_name if r else None),
                "category": (r.category if r else None),
                "open_at": b.bid_open_at.isoformat() if b.bid_open_at else None,
                "quoted": bool(mine),
                "my_amount": mine[-1]["totalAmount"] if mine else None,
            }
        )
    return ok(request, {"list": rows, "total": len(rows)})


def quote_inquiry(request: HttpRequest, id: int):
    """在线应价：同供应商重报即覆盖；已定标不可再报。"""
    d = domain_from(request)
    body = read_json(request)
    amount = _money_strict(body.get("totalAmount"))
    if amount is None or amount <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "报价金额无效")
    remark = (body.get("remark") or "").strip()[:512] or None

    s = _my_supplier(d)
    if s is None:
        raise ApiError(403, CODE_FORBIDDEN, "当前机构未绑定供应商")
    with transaction.atomic():
        b = (
            GBid.objects.select_for_update()
            .filter(id=id, tenant_id=d.tenant_id, deleted=0)
            .first()
        )
        if b is None or s.id not in [int(x) for x in (b.invited_supplier_ids or [])]:
            raise ApiError(404, CODE_NOT_FOUND, "询价不存在")
        if b.status != "PUBLICIZING":
            raise ApiError(409, CODE_CONFLICT, "询价已定标，不可再应价")

        entries = [x for x in (b.bids_json or [])]
        entries = [x for x in entries if int(x.get("supplierId", 0) or 0) != s.id]
        entries.append(
            {
                "supplierId": s.id,
                "supplierName": s.name,
                "totalAmount": _num2(amount),
                "remark": remark,
            }
        )
        b.bids_json = entries
        b.modifier_id = d.user_id
        b.save(update_fields=["bids_json", "modifier_id", "updated_at"])

    return ok(request, {"id": b.id, "totalAmount": _num2(amount), "quoted": True})


# ---------------------------------------------------------------- 合同进度（脱敏）

_CONTRACT_MASK_KEYS = (
    "id", "code", "name", "amount", "signed_at", "end_date", "status",
    "pay_phase_count", "paid_amount", "paid_ratio",
)


def _api_contract_for_supplier(c: GContract, paid: Decimal, phases: int) -> dict:
    """对外脱敏视图：只暴露白名单键（不含 party_a/备注/AI 风险/需求单号）。"""
    amount = c.amount or Decimal("0")
    ratio = "0.00" if amount == 0 else f"{(paid / amount):.2f}"
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "amount": _num2(amount),
        "signed_at": c.sign_date.isoformat() if getattr(c, "sign_date", None) else None,
        "end_date": c.end_date.isoformat() if getattr(c, "end_date", None) else None,
        "status": c.status,
        "pay_phase_count": phases,
        "paid_amount": _num2(paid),
        "paid_ratio": ratio,
    }


def list_supplier_contracts(request: HttpRequest):
    """我机构绑定的合同执行进度（脱敏只读）。"""
    d = domain_from(request)
    s = _my_supplier(d)
    if s is None:
        return ok(request, {"list": [], "total": 0})

    contracts = list(
        GContract.objects.filter(tenant_id=d.tenant_id, supplier_id=s.id, deleted=0)
        .order_by("-id")[:100]
    )
    rows = []
    for c in contracts:
        agg = GContractPayment.objects.filter(
            tenant_id=d.tenant_id, contract_id=c.id, deleted=0
        ).aggregate(paid=Sum("paid_amount"), n=Sum("id"))
        paid = agg["paid"] or Decimal("0")
        phases = GContractPayment.objects.filter(
            tenant_id=d.tenant_id, contract_id=c.id, deleted=0
        ).count()
        rows.append(_api_contract_for_supplier(c, paid, phases))
    return ok(request, {"list": rows, "total": len(rows)})
