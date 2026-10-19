"""资产与耗材域 A API（对齐 design/10-资产与耗材管理-A.openapi.yaml，纯契约实现）。

链路：建卡（要素缺失置 PENDING_RECEIPT，禁止折旧）/ 到货转卡（G-17+A-03 合并端点，
幂等 40916）/ 台账 / 全周期档案 / 领用归还调拨 / 耗材出入库（FIFO+效期冻结+危化双人
双锁）/ 按月折旧（(asset_id,period) 唯一幂等）/ 凭证回调 / 处置（残值异常转财务复核）/
盘点（盘盈盘亏）/ 追溯 / AI 补全（确定性降级）。
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.asset.models import (
    AAsset,
    AConsumable,
    ADepreciation,
    ADisposal,
    AStockTxn,
)
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
from apps.output.api import page_args, _parse_date  # 共用分页/日期解析
from core.reqschema import validate_body
from apps.asset.schemas import AssetIn, FromReceiptIn, DepreciationRunIn, VoucherCallbackIn, InventoryIn, IssueIn, TransferIn, DisposalIn, StockInIn, StockOutIn

# G-17 与本域共用：重复转资产幂等拦截（错误码已在 G 域登记）
CODE_DUPLICATE_ASSET = 40916

SECRET_LEVELS = ("SECRET", "TOP_SECRET")

TXN_STAGE = {
    "REQUISITION": "ISSUE",
    "RETURN": "ISSUE",
    "STOCK_IN": "ISSUE",
    "STOCK_OUT": "ISSUE",
    "COUNT_GAIN": "INVENTORY",
    "COUNT_LOSS": "INVENTORY",
}


def _now():
    return dj_tz.now()


def _dec(v):
    if v is None:
        return None
    from decimal import Decimal

    try:
        return Decimal(str(v))
    except Exception:
        return None


def _f(v):
    return float(v) if v is not None else 0.0


def _gen_code(prefix: str, tenant_id: int, model, digits: int = 6) -> str:
    y = _now().year
    seq = model.objects.filter(tenant_id=tenant_id, code__startswith=f"{prefix}-{y}-").count() + 1
    return f"{prefix}-{y}-{seq:0{digits}d}"


def _get_asset_or_404(aid: int) -> AAsset:
    a = AAsset.objects.filter(id=aid, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "资产不存在")
    return a


def _asset_complete(a: AAsset) -> bool:
    """要素完整 = 原值>0 且有责任人；完整方可折旧/使用。"""
    return _f(a.value) > 0 and a.custodian_id is not None


def _api_asset(a: AAsset) -> dict:
    return {
        "id": a.id, "code": a.code, "tenantId": a.tenant_id,
        "legalEntityId": a.legal_entity_id, "securityLevel": a.security_level,
        "policyPackId": a.policy_pack_id, "assetType": a.asset_type,
        "categoryCode": a.category_code, "name": a.name, "brand": a.brand,
        "model": a.model, "serialNo": a.serial_no, "value": _f(a.value),
        "purchaseDate": f"{a.purchase_date:%Y-%m-%d}" if a.purchase_date else None,
        "inDate": f"{a.in_date:%Y-%m-%d}" if a.in_date else None,
        "deprMethod": a.depr_method, "deprYears": a.depr_years,
        "deprAccum": _f(a.depr_accum), "netValue": _f(a.net_value),
        "custodianId": a.custodian_id, "deptId": a.dept_id, "location": a.location,
        "sourceType": a.source_type, "sourceRef": a.source_ref, "projectId": a.project_id,
        "usageRate": _f(a.usage_rate) if a.usage_rate is not None else None,
        "shareFlag": a.share_flag, "openFlag": a.open_flag, "status": a.status,
        "createdAt": a.created_at.isoformat(), "updatedAt": a.updated_at.isoformat(),
        "remark": a.remark,
    }


def _api_txn(t: AStockTxn) -> dict:
    return {
        "id": t.id, "code": t.code, "type": t.type, "status": t.status,
        "refAssetId": t.ref_asset_id, "refSku": t.ref_sku, "refBatchNo": t.ref_batch_no,
        "qty": _f(t.qty), "amount": _f(t.amount) if t.amount is not None else None,
        "projectId": t.project_id, "operatorId": t.operator_id,
        "doubleConfirmBy": t.double_confirm_by,
        "relatedExpenseId": t.related_expense_id,
        "txnTime": t.txn_time.isoformat() if t.txn_time else None,
        "balanceAfter": _f(t.balance_after) if t.balance_after is not None else None,
        "fifoExempt": t.fifo_exempt,
    }


# ---------------------------------------------------------------------------
# 建卡 A-02 / 到货转卡 A-03（G-17 合并端点）
# ---------------------------------------------------------------------------


def _new_asset(dom, b: dict) -> AAsset:
    """按请求体建卡；value>0 且有责任人 → IN_USE（要素完整），否则 PENDING_RECEIPT。"""
    value = _dec(b.get("value")) or 0
    a = AAsset.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("AST", dom.tenant_id, AAsset),
        legal_entity_id=b.get("legalEntityId") or b.get("legal_entity_id") or dom.legal_entity_id or 1,
        security_level=b.get("securityLevel") or b.get("security_level") or "INTERNAL",
        policy_pack_id=b.get("policyPackId"),
        asset_type=b.get("assetType") or "FIXED",
        category_code=b.get("categoryCode") or "UNCATEGORIZED",
        name=b.get("name") or f"资产{b.get('serialNo') or ''}",
        brand=b.get("brand"), model=b.get("model"), serial_no=b.get("serialNo") or b.get("serial_no"),
        value=value,
        purchase_date=_parse_date(b.get("purchaseDate") or b.get("purchase_date")),
        in_date=_parse_date(b.get("inDate") or b.get("in_date")) or dj_tz.localdate(),
        depr_method=b.get("deprMethod") or "STRAIGHT_LINE",
        depr_years=b.get("deprYears"),
        custodian_id=b.get("custodianId") or b.get("custodian_id"),
        dept_id=b.get("deptId") or b.get("dept_id"),
        location=b.get("location"),
        source_type=b.get("sourceType") or "PURCHASE",
        source_ref=b.get("sourceRef") or b.get("source_ref"),
        project_id=b.get("projectId") or b.get("project_id"),
        share_flag=bool(b.get("shareFlag")),
        open_flag=bool(b.get("openFlag")),
        remark=b.get("remark"),
    )
    a.net_value = a.value
    if _asset_complete(a):
        a.status = "IN_USE"
    else:
        a.status = "PENDING_RECEIPT"
        missing = [k for k, v in (("value", _f(a.value) > 0), ("custodianId", a.custodian_id)) if not v]
        a.remark = "; ".join(filter(None, [a.remark, f"missing:{','.join(missing)}"]))
    a.save()
    return a


@validate_body(AssetIn)
@transaction.atomic
def create_asset(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("assetType") or not b.get("categoryCode") or not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "assetType/categoryCode/name 必填")
    a = _new_asset(dom, b)
    return ok(request, _api_asset(a))


@validate_body(FromReceiptIn)
@transaction.atomic
def create_from_receipt(request: HttpRequest):
    """A-03 承接 G-17（合并端点）：ACCEPTED 订单 → 资产/耗材登记，1:1 幂等（40916）。"""
    dom = domain_from(request)
    b = read_json(request)
    order_id = b.get("orderId") or b.get("order_id")
    if not order_id:
        raise ApiError(400, CODE_BAD_REQUEST, "orderId 必填")
    from apps.procure.models import GOrder

    o = GOrder.objects.filter(id=int(order_id), deleted=0).first()
    if o is None:
        raise ApiError(404, CODE_NOT_FOUND, "订单不存在")
    if o.converted_asset:
        raise ApiError(409, CODE_DUPLICATE_ASSET, "该订单已转资产/耗材（幂等拦截）",
                       data={"converted_target_id": o.converted_target_id})
    if o.delivery_status != "ACCEPTED":
        raise ApiError(409, CODE_CONFLICT, f"仅验收通过（ACCEPTED）可转资产，当前 {o.delivery_status}")
    req = o.requisition
    target = (b.get("target") or "").upper() or (
        "CONSUMABLE" if req and req.category in ("试剂耗材", "耗材") else "ASSET")
    if target == "CONSUMABLE":
        batch_info = b.get("batch_info") or {}
        rec = AConsumable.objects.create(
            tenant_id=dom.tenant_id, creator_id=dom.user_id,
            code=_gen_code("KC", dom.tenant_id, AConsumable, 4),
            sku=batch_info.get("sku") or f"SKU-{o.id}",
            name=req.item_name if req else f"订单{o.id}耗材",
            category="REAGENT" if req and req.category == "试剂耗材" else "CONSUMABLE",
            stock_qty=batch_info.get("qty") or 1,
            unit=batch_info.get("unit") or "批",
            batch_no=batch_info.get("batch_no"),
            expire_date=_parse_date(batch_info.get("expire_date")),
            safe_stock=batch_info.get("safe_stock"),
            location=b.get("location"),
            custodian_id=b.get("custodianId") or b.get("custodian_id"),
            legal_entity_id=b.get("legalEntityId") or dom.legal_entity_id or 1,
        )
        target_id, table = rec.id, "A_CONSUMABLE"
    else:
        serial = (b.get("serial_nos") or [None])[0]
        a = _new_asset(dom, {
            "name": req.item_name if req else f"订单{o.id}设备",
            "value": o.order_amount,
            "serialNo": serial,
            "sourceRef": o.id,
            "sourceType": "PURCHASE",
            "projectId": req.project_id if req else b.get("projectId"),
            "custodianId": b.get("custodianId") or b.get("custodian_id"),
            "deptId": b.get("deptId") or b.get("dept_id"),
            "location": b.get("location"),
            "legalEntityId": b.get("legalEntityId") or o.legal_entity_id,
        })
        target_id, table = a.id, "A_ASSET"
    o.converted_asset = True
    o.converted_target_id = target_id
    o.save(update_fields=["converted_asset", "converted_target_id", "updated_at"])
    return ok(request, {"target_table": table, "target_id": target_id, "order_id": o.id})


# ---------------------------------------------------------------------------
# 台账 / 全周期档案 / 追溯
# ---------------------------------------------------------------------------


def ledger(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = AAsset.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    for k in ("status", "asset_type", "category_code"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    for k in ("deptId", "custodianId", "projectId"):
        if v := request.GET.get(k):
            try:
                qs = qs.filter(**{k: int(v)})
            except ValueError:
                pass
    # 涉密隔离：非涉密会话过滤 SECRET 及以上明细
    dom = domain_from(request)
    if dom.security_level not in SECRET_LEVELS:
        qs = qs.exclude(security_level__in=SECRET_LEVELS)
    if kw := request.GET.get("keyword"):
        qs = qs.filter(Q(name__icontains=kw) | Q(model__icontains=kw) | Q(serial_no__icontains=kw))
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [_api_asset(a) for a in rows],
                        "total": total, "page": page, "size": size})


def _txn_event(t: AStockTxn) -> dict:
    return {"stage": TXN_STAGE.get(t.type, "ISSUE"), "refType": "A_STOCK_TXN",
            "refId": t.id, "actorId": t.operator_id,
            "at": t.txn_time.isoformat() if t.txn_time else None,
            "detail": {"type": t.type, "qty": _f(t.qty)}}


def lifecycle(request: HttpRequest, id: int):
    a = _get_asset_or_404(id)
    events = [{"stage": "REGISTER", "refType": "A_ASSET", "refId": a.id,
               "actorId": a.creator_id, "at": a.created_at.isoformat(),
               "detail": {"code": a.code, "sourceType": a.source_type}}]
    for t in AStockTxn.objects.filter(ref_asset_id=a.id, deleted=0).order_by("id"):
        events.append(_txn_event(t))
    deprs = list(ADepreciation.objects.filter(asset_id=a.id, deleted=0).order_by("period"))
    for d in deprs:
        events.append({"stage": "DEPRECIATION", "refType": "A_DEPRECIATION", "refId": d.id,
                       "actorId": d.creator_id, "at": d.created_at.isoformat(),
                       "detail": {"period": d.period, "deprAmount": _f(d.depr_amount)}})
    disposals = list(ADisposal.objects.filter(asset_id=a.id, deleted=0).order_by("id"))
    for dp in disposals:
        events.append({"stage": "DISPOSAL", "refType": "A_DISPOSAL", "refId": dp.id,
                       "actorId": dp.creator_id, "at": dp.created_at.isoformat(),
                       "detail": {"method": dp.method, "status": dp.status}})
    return ok(request, {"asset": _api_asset(a), "events": events,
                        "depreciations": [_api_depr(d) for d in deprs],
                        "disposals": [_api_disposal(dp) for dp in disposals]})


def trace(request: HttpRequest, id: int):
    """端到端追溯（→E-17）：申报→招标→订单→资产 链节点。"""
    a = _get_asset_or_404(id)
    nodes = [{"nodeSeq": 1, "objectType": "A_ASSET", "objectId": a.id, "bizCode": a.code,
              "action": "REGISTER", "occurredAt": a.created_at.isoformat()}]
    seq = 1
    if a.source_ref:
        from apps.procure.models import GOrder

        o = GOrder.objects.filter(id=a.source_ref, deleted=0).first()
        if o is not None:
            seq += 1
            nodes.append({"nodeSeq": seq, "objectType": "G_ORDER", "objectId": o.id,
                          "bizCode": o.code, "action": "PURCHASE",
                          "occurredAt": o.created_at.isoformat()})
            req = o.requisition
            if req is not None:
                seq += 1
                nodes.insert(0, {"nodeSeq": 0, "objectType": "G_REQUISITION", "objectId": req.id,
                                 "bizCode": req.code, "action": "REQUISITION",
                                 "occurredAt": req.created_at.isoformat()})
    nodes = [{**n, "nodeSeq": i + 1} for i, n in enumerate(nodes)]
    return ok(request, {"traceId": f"ASSET-{a.code}", "nodes": nodes})


# ---------------------------------------------------------------------------
# 领用 / 归还 / 调拨 A-05
# ---------------------------------------------------------------------------


def _asset_txn(dom, a: AAsset, typ: str, b: dict, operator_id: int, status="ISSUED") -> AStockTxn:
    return AStockTxn.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("TXN", dom.tenant_id, AStockTxn, 6),
        type=typ, status=status, ref_asset_id=a.id,
        qty=1, balance_after=1,
        project_id=b.get("projectId") or a.project_id,
        operator_id=operator_id,
        related_expense_id=b.get("relatedExpenseId"),
        remark=b.get("remark"),
    )


@validate_body(IssueIn)
@transaction.atomic
def issue_asset(request: HttpRequest, id: int):
    dom = domain_from(request)
    a = _get_asset_or_404(id)
    if a.status not in ("IN_USE", "IDLE"):
        raise ApiError(409, CODE_CONFLICT, f"领用状态机冲突：当前 {a.status}（待验收确认不可领用）")
    b = read_json(request)
    if not b.get("projectId"):
        raise ApiError(400, CODE_BAD_REQUEST, "projectId 必填")
    if b.get("custodianId"):
        a.custodian_id = int(b["custodianId"])
    if b.get("deptId"):
        a.dept_id = int(b["deptId"])
    if b.get("location"):
        a.location = b["location"]
    a.project_id = int(b["projectId"])
    if b.get("usageRate") is not None:
        a.usage_rate = _dec(b["usageRate"])
    a.status = "IN_USE"
    a.modifier_id = dom.user_id
    a.save()
    t = _asset_txn(dom, a, "REQUISITION", b, dom.user_id)
    return ok(request, _api_txn(t))


@transaction.atomic
def return_asset(request: HttpRequest, id: int):
    dom = domain_from(request)
    a = _get_asset_or_404(id)
    if a.status != "IN_USE":
        raise ApiError(409, CODE_CONFLICT, f"归还状态机冲突：当前 {a.status}")
    b = read_json_soft(request)
    a.status = "IDLE"
    a.custodian_id = None
    if b.get("location"):
        a.location = b["location"]
    if b.get("deptId"):
        a.dept_id = int(b["deptId"])
    a.modifier_id = dom.user_id
    a.save()
    t = _asset_txn(dom, a, "RETURN", b, dom.user_id, status="ISSUED")
    return ok(request, _api_txn(t))


@validate_body(TransferIn)
@transaction.atomic
def transfer_asset(request: HttpRequest, id: int):
    """调拨：涉密资产须保密审查单（联动 11），否则 403；调拨落地置 IN_USE。"""
    dom = domain_from(request)
    a = _get_asset_or_404(id)
    if a.status in ("PENDING_DISPOSE", "DISPOSED"):
        raise ApiError(409, CODE_CONFLICT, f"调拨状态机冲突：当前 {a.status}")
    b = read_json(request)
    if not b.get("toLegalEntityId") or not b.get("toDeptId"):
        raise ApiError(400, CODE_BAD_REQUEST, "toLegalEntityId/toDeptId 必填")
    if a.security_level in SECRET_LEVELS and not b.get("secrecyReviewId"):
        raise ApiError(403, CODE_FORBIDDEN, "涉密资产调拨须保密审查单 secrecyReviewId")
    a.status = "TRANSFERRING"
    a.save(update_fields=["status", "updated_at"])
    a.legal_entity_id = int(b["toLegalEntityId"])
    a.dept_id = int(b["toDeptId"])
    if b.get("toCustodianId"):
        a.custodian_id = int(b["toCustodianId"])
    if b.get("toLocation"):
        a.location = b["toLocation"]
    a.status = "IN_USE"  # 落地确认（本域无独立确认端点，一步完成并留痕）
    a.remark = "; ".join(filter(None, [a.remark, f"transfer->LE{a.legal_entity_id}/DEPT{a.dept_id}"]))
    a.modifier_id = dom.user_id
    a.save()
    return ok(request, _api_asset(a))


# ---------------------------------------------------------------------------
# 耗材库存 A-07/A-08
# ---------------------------------------------------------------------------


def _consumable_status(rec: AConsumable) -> str:
    today = dj_tz.localdate()
    if rec.expire_date and rec.expire_date < today:
        return "EXPIRED"
    if rec.safe_stock is not None and rec.stock_qty <= rec.safe_stock:
        return "LOW_STOCK"
    if rec.expire_date and (rec.expire_date - today).days <= 30:
        return "NEAR_EXPIRY"
    return "IN_STOCK"


def _api_consumable(c: AConsumable) -> dict:
    return {
        "id": c.id, "code": c.code, "sku": c.sku, "name": c.name, "category": c.category,
        "qty": _f(c.stock_qty), "unit": c.unit, "batchNo": c.batch_no,
        "safeStock": _f(c.safe_stock) if c.safe_stock is not None else None,
        "status": _consumable_status(c), "storedStatus": c.status,
        "expireDate": f"{c.expire_date:%Y-%m-%d}" if c.expire_date else None,
        "isHazard": c.is_hazard, "hazardLevel": c.hazard_level, "msdsUrl": c.msds_url,
        "location": c.location, "legalEntityId": c.legal_entity_id,
        "securityLevel": c.security_level,
    }


def list_consumables(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = AConsumable.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("category"):
        qs = qs.filter(category=v)
    if v := request.GET.get("is_hazard"):
        qs = qs.filter(is_hazard=v in ("true", "1"))
    if kw := request.GET.get("keyword"):
        qs = qs.filter(Q(name__icontains=kw) | Q(sku__icontains=kw) | Q(location__icontains=kw))
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [_api_consumable(c) for c in rows],
                        "total": total, "page": page, "size": size})


def _sku_balance(tenant_id: int, sku: str):
    return AConsumable.objects.filter(tenant_id=tenant_id, sku=sku, deleted=0).aggregate(
        s=Sum("stock_qty"))["s"] or 0


@validate_body(StockInIn)
@transaction.atomic
def stock_in(request: HttpRequest, sku: str):
    """入库（A-07）：批次记录（同租户同批次同 SKU 唯一，累加），危化须绑定 MSDS。"""
    dom = domain_from(request)
    b = read_json(request)
    qty = _dec(b.get("qty"))
    if qty is None or qty <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "qty 必填且 > 0")
    is_hazard = bool(b.get("isHazard"))
    if is_hazard and not b.get("msdsUrl"):
        raise ApiError(400, CODE_BAD_REQUEST, "危化品入库须绑定 MSDS（msdsUrl）")
    batch_no = b.get("batchNo") or _now().strftime("B%Y%m%d%H%M%S")
    rec = AConsumable.objects.filter(tenant_id=dom.tenant_id, sku=sku,
                                     batch_no=batch_no, deleted=0).first()
    if rec is None:
        rec = AConsumable.objects.create(
            tenant_id=dom.tenant_id, creator_id=dom.user_id,
            code=_gen_code("KC", dom.tenant_id, AConsumable, 4),
            sku=sku, name=b.get("name") or sku,
            category=b.get("category") or "CONSUMABLE",
            is_hazard=is_hazard, hazard_level=b.get("hazardLevel"),
            msds_url=b.get("msdsUrl"), stock_qty=qty,
            unit=b.get("unit"), batch_no=batch_no,
            produce_date=_parse_date(b.get("produceDate")),
            expire_date=_parse_date(b.get("expireDate")),
            safe_stock=_dec(b.get("safeStock")),
            location=b.get("location"),
            custodian_id=b.get("custodianId") or dom.user_id,
            legal_entity_id=b.get("legalEntityId") or dom.legal_entity_id or 1,
            security_level=b.get("securityLevel") or "INTERNAL",
        )
    else:
        rec.stock_qty = rec.stock_qty + qty
        rec.modifier_id = dom.user_id
        rec.save(update_fields=["stock_qty", "modifier_id", "updated_at"])
    balance = _sku_balance(dom.tenant_id, sku)
    t = AStockTxn.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("TXN", dom.tenant_id, AStockTxn, 6),
        type="STOCK_IN", status="ISSUED", ref_sku=sku, ref_batch_no=batch_no,
        qty=qty, amount=_dec(b.get("amount")), operator_id=dom.user_id,
        balance_after=balance, remark=b.get("remark"),
    )
    return ok(request, _api_txn(t))


@validate_body(StockOutIn)
@transaction.atomic
def stock_out(request: HttpRequest, sku: str):
    """出库领用（A-07/A-08）：FIFO+效期冻结+危化双人双锁+豁免留痕。"""
    dom = domain_from(request)
    b = read_json(request)
    qty = _dec(b.get("qty"))
    for k in ("projectId", "operatorId"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    if qty is None or qty <= 0:
        raise ApiError(400, CODE_BAD_REQUEST, "qty 必填且 > 0")
    batches = list(AConsumable.objects.filter(tenant_id=dom.tenant_id, sku=sku, deleted=0,
                                              stock_qty__gt=0)
                   .order_by(F("expire_date").asc(nulls_last=True), "id"))
    today = dj_tz.localdate()
    live = [c for c in batches if not (c.expire_date and c.expire_date < today)]
    if not live:
        raise ApiError(403, CODE_FORBIDDEN, "该 SKU 无可领用批次（过期批次冻结，走危废/报废）")
    if b.get("batchNo"):
        rec = next((c for c in batches if c.batch_no == b["batchNo"]), None)
        if rec is None:
            raise ApiError(404, CODE_NOT_FOUND, f"批次 {b['batchNo']} 不存在")
        if rec not in live:
            raise ApiError(403, CODE_FORBIDDEN, f"批次 {rec.batch_no} 已过期冻结，不可领用（走危废/报废）")
        fifo_first = live[0]
        violated = rec.id != fifo_first.id
        if violated and not b.get("fifoExempt"):
            raise ApiError(409, CODE_CONFLICT,
                           f"违反 FIFO（最早到期批次 {fifo_first.batch_no}），须 fifoExempt 授权豁免")
        if b.get("fifoExempt") and not b.get("fifoExemptApproverId"):
            raise ApiError(400, CODE_BAD_REQUEST, "FIFO 豁免须 fifoExemptApproverId 授权人")
    else:
        rec = live[0]
    if rec.is_hazard and not b.get("doubleConfirmBy"):
        raise ApiError(403, CODE_FORBIDDEN, "危化品出库须双人双锁：doubleConfirmBy 必填")
    if rec.stock_qty < qty:
        raise ApiError(409, CODE_CONFLICT,
                       f"库存不足：批次余 {rec.stock_qty}，申请 {qty}")
    rec.stock_qty = rec.stock_qty - qty
    rec.modifier_id = dom.user_id
    rec.save(update_fields=["stock_qty", "modifier_id", "updated_at"])
    balance = _sku_balance(dom.tenant_id, sku)
    status = "ISSUED"
    t = AStockTxn.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("TXN", dom.tenant_id, AStockTxn, 6),
        type="STOCK_OUT", status=status, ref_sku=sku, ref_batch_no=rec.batch_no,
        qty=qty, project_id=int(b["projectId"]), operator_id=int(b["operatorId"]),
        double_confirm_by=b.get("doubleConfirmBy"),
        related_expense_id=b.get("relatedExpenseId"),
        balance_after=balance,
        fifo_exempt=bool(b.get("fifoExempt")),
        remark=b.get("usage"),
    )
    return ok(request, _api_txn(t))


# ---------------------------------------------------------------------------
# 折旧 A-09/A-12 / 凭证回调 F-11
# ---------------------------------------------------------------------------


def _api_depr(d: ADepreciation) -> dict:
    return {
        "id": d.id, "code": d.code, "policyPackId": d.policy_pack_id,
        "assetId": d.asset_id, "period": d.period, "deprAmount": _f(d.depr_amount),
        "allocProjectIds": d.alloc_project_ids or [], "voucherId": d.voucher_id,
        "posted": d.posted, "status": d.status,
    }


@validate_body(DepreciationRunIn)
@transaction.atomic
def run_depreciation(request: HttpRequest):
    """按月折旧（A-09）：仅 IN_USE 且要素完整；(asset_id,period) 唯一幂等。"""
    dom = domain_from(request)
    b = read_json(request)
    import re

    period = b.get("period")
    if not period or not re.fullmatch(r"\d{4}-\d{2}", str(period)):
        raise ApiError(400, CODE_BAD_REQUEST, "period 必填且格式 YYYY-MM")
    qs = AAsset.objects.filter(tenant_id=dom.tenant_id, deleted=0, status="IN_USE")
    if b.get("legalEntityId"):
        qs = qs.filter(legal_entity_id=int(b["legalEntityId"]))
    if b.get("assetIds"):
        qs = qs.filter(id__in=[int(i) for i in b["assetIds"]])
    records, processed, skipped, total_amt, alloc_count = [], 0, 0, 0.0, 0
    for a in qs:
        remaining = _f(a.value) - _f(a.depr_accum)
        if (a.depr_method == "NONE" or not a.depr_years or a.depr_years <= 0
                or _f(a.value) <= 0 or a.custodian_id is None or remaining <= 0):
            skipped += 1
            continue
        amount = round(min(_f(a.value) / (a.depr_years * 12), remaining), 2)
        if ADepreciation.objects.filter(asset_id=a, period=period, deleted=0).exists():
            skipped += 1  # 幂等：同月已计提
            continue
        alloc = ([{"projectId": a.project_id, "ratio": 1.0, "amount": amount}]
                 if a.project_id else [])
        d = ADepreciation.objects.create(
            tenant_id=a.tenant_id, creator_id=dom.user_id,
            code=_gen_code("DEP", a.tenant_id, ADepreciation, 6),
            legal_entity_id=a.legal_entity_id, security_level=a.security_level,
            policy_pack_id=a.policy_pack_id or b.get("policyPackId"),
            asset=a, period=period, depr_amount=_dec(amount),
            alloc_project_ids=alloc, status="CALCULATED",
        )
        a.depr_accum = a.depr_accum + _dec(amount)
        a.net_value = a.value - a.depr_accum
        a.save(update_fields=["depr_accum", "net_value", "updated_at"])
        records.append(d)
        processed += 1
        total_amt += amount
        alloc_count += len(alloc)
    return ok(request, {"period": period, "processedCount": processed,
                        "skippedCount": skipped, "totalDeprAmount": round(total_amt, 2),
                        "allocationCount": alloc_count,
                        "records": [_api_depr(d) for d in records]})


@validate_body(VoucherCallbackIn)
@transaction.atomic
def voucher_callback(request: HttpRequest):
    """折旧凭证回调（F-11）：回写 voucher_id/posted/status。"""
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("period") or not b.get("items"):
        raise ApiError(400, CODE_BAD_REQUEST, "period/items 必填")
    updated = 0
    for item in b["items"]:
        if not item.get("depreciationId") or not item.get("voucherId"):
            continue
        d = ADepreciation.objects.filter(id=int(item["depreciationId"]), deleted=0).first()
        if d is None:
            continue
        d.voucher_id = int(item["voucherId"])
        posted = 1 if item.get("posted", True) else 0
        d.posted = posted
        d.status = "POSTED" if posted else "DRAFT"
        d.modifier_id = dom.user_id
        d.save(update_fields=["voucher_id", "posted", "status", "modifier_id", "updated_at"])
        updated += 1
    return ok(request, {"period": b["period"], "updated": updated})


# ---------------------------------------------------------------------------
# 处置 A-10 / 盘点 A-11
# ---------------------------------------------------------------------------


def _api_disposal(dp: ADisposal) -> dict:
    return {
        "id": dp.id, "code": dp.code, "assetId": dp.asset_id, "method": dp.method,
        "appraisal": dp.appraisal, "residualValue": _f(dp.residual_value)
        if dp.residual_value is not None else None,
        "approvalChain": dp.approval_chain or [],
        "relatedVoucher": dp.related_voucher, "archiveRef": dp.archive_ref,
        "status": dp.status,
    }


@validate_body(DisposalIn)
@transaction.atomic
def create_disposal(request: HttpRequest, id: int):
    """处置发起（A-10）：残值>原值或为负 → finance_review 标记转财务复核。"""
    dom = domain_from(request)
    a = _get_asset_or_404(id)
    if a.status in ("PENDING_DISPOSE", "DISPOSED"):
        raise ApiError(409, CODE_CONFLICT, f"处置状态机冲突：当前 {a.status}")
    b = read_json(request)
    method = b.get("method")
    if method not in ("SCRAP", "SELL", "TRANSFER", "DESTROY"):
        raise ApiError(400, CODE_BAD_REQUEST, "method 必须为 SCRAP/SELL/TRANSFER/DESTROY")
    residual = _dec(b.get("residualValue"))
    finance_review = residual is not None and (residual < 0 or residual > a.value)
    dp = ADisposal.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("DSP", dom.tenant_id, ADisposal),
        legal_entity_id=a.legal_entity_id, security_level=a.security_level,
        asset=a, method=method, appraisal=b.get("appraisal"),
        residual_value=residual, approval_chain=b.get("approvalChain") or [],
        archive_ref=b.get("archiveRef"), remark=b.get("remark"),
        status="APPRAISED" if b.get("appraisal") else "APPLIED",
    )
    a.status = "PENDING_DISPOSE"
    a.modifier_id = dom.user_id
    a.save(update_fields=["status", "modifier_id", "updated_at"])
    return ok(request, {**_api_disposal(dp), "financeReview": finance_review})


@validate_body(InventoryIn)
@transaction.atomic
def submit_inventory(request: HttpRequest):
    """盘点（A-11）：财务账 vs 资产卡 vs 实物三方比对 → 盘盈/盘亏/账实不符。"""
    dom = domain_from(request)
    b = read_json(request)
    items = b.get("items")
    if items is None:
        raise ApiError(400, CODE_BAD_REQUEST, "items 必填")
    collected_serials = {str(i.get("serialNo") or "") for i in items if i.get("serialNo")}
    matched, differences = 0, []
    qs = AAsset.objects.filter(tenant_id=dom.tenant_id, deleted=0).exclude(
        status__in=("DISPOSED", "PENDING_DISPOSE"))
    if b.get("deptId"):
        qs = qs.filter(dept_id=int(b["deptId"]))
    if b.get("legalEntityId"):
        qs = qs.filter(legal_entity_id=int(b["legalEntityId"]))
    for i in items:
        sn = i.get("serialNo")
        if not sn:
            continue
        a = qs.filter(serial_no=sn).first()
        if a is not None:
            matched += 1
            if i.get("location") and a.location and i["location"] != a.location:
                differences.append({
                    "diffType": "BOOK_MISMATCH", "serialNo": sn, "assetId": a.id,
                    "bookValue": _f(a.net_value), "physicalValue": _f(a.net_value),
                    "reason": f"存放地不符：账 {a.location} / 实物 {i['location']}",
                    "needApproval": True,
                })
        else:
            differences.append({
                "diffType": "COUNT_GAIN", "serialNo": sn, "assetId": None,
                "bookValue": None, "physicalValue": _f(i.get("qty")) if i.get("qty") else None,
                "reason": "实物在册但账上无卡（盘盈）", "needApproval": True,
            })
            AStockTxn.objects.create(
                tenant_id=dom.tenant_id, creator_id=dom.user_id,
                code=_gen_code("TXN", dom.tenant_id, AStockTxn, 6),
                type="COUNT_GAIN", ref_sku=sn, qty=_dec(i.get("qty")) or 1,
                operator_id=b.get("collectedBy") or dom.user_id,
                balance_after=_dec(i.get("qty")) or 1,
            )
    for a in qs:
        if a.serial_no and a.serial_no not in collected_serials:
            differences.append({
                "diffType": "COUNT_LOSS", "serialNo": a.serial_no, "assetId": a.id,
                "bookValue": _f(a.net_value), "physicalValue": None,
                "reason": "账上有卡但实物未采集到（盘亏）", "needApproval": True,
            })
            AStockTxn.objects.create(
                tenant_id=dom.tenant_id, creator_id=dom.user_id,
                code=_gen_code("TXN", dom.tenant_id, AStockTxn, 6),
                type="COUNT_LOSS", ref_asset_id=a.id, qty=1,
                operator_id=b.get("collectedBy") or dom.user_id, balance_after=0,
            )
    gain = sum(1 for d in differences if d["diffType"] == "COUNT_GAIN")
    loss = sum(1 for d in differences if d["diffType"] == "COUNT_LOSS")
    return ok(request, {"matchedCount": matched, "gainCount": gain, "lossCount": loss,
                        "differences": differences})


# ---------------------------------------------------------------------------
# AI 补全 A-15（确定性降级）
# ---------------------------------------------------------------------------


@transaction.atomic
def ai_fill(request: HttpRequest, id: int):
    """A-15：读取发票/合同预填建议（降级：从既有卡与 G-13 解析结果回填建议）。"""
    a = _get_asset_or_404(id)
    read_json_soft(request)
    suggestions = {k: v for k, v in {
        "brand": a.brand, "model": a.model, "serialNo": a.serial_no,
        "value": _f(a.value) if _f(a.value) > 0 else None,
        "purchaseDate": f"{a.purchase_date:%Y-%m-%d}" if a.purchase_date else None,
        "categoryCode": a.category_code,
    }.items() if v is not None}
    confidence = {k: 0.6 for k in suggestions}  # 降级置信度 <0.85 标黄
    needs = [k for k in ("value", "serialNo") if k not in suggestions or confidence.get(k, 0) < 0.85]
    return ok(request, {"suggestions": suggestions, "confidence": confidence,
                        "needsManualConfirm": needs, "modelVersion": "degraded-rules-v1",
                        "degraded": True})
