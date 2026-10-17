"""采购与合同域 G API（对齐 design/09-采购与合同管理-G.openapi.yaml，纯契约实现）。

链路：采购申请（G-02 预算冻结联动 F 剩余额，40910 拦截）→ G-03 方式判定引擎（确定性决策表，
人不越权）→ 招标/比价（废标回退 CHALLENGE）→ 定标 → 订单 → 合同状态机（DRAFT→REVIEW 四方意见→
TO_SIGN→ACTIVE；供应商黑名单/未入库/资质过期硬拦截 40913）→ 付款计划（Σ≤合同额 40911）→
付款执行回调（冻结→实扣迁移）→ AI 解析/风险（确定性降级）→ 到货验收转资产（幂等 40916）。
"""
from __future__ import annotations

import time

from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.procure.models import (
    GBid,
    GContract,
    GContractPayment,
    GOrder,
    GOutsource,
    GRequisition,
    GSupplier,
)
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
    read_json_soft,
)
from apps.output.api import page_args, _parse_date  # 共用分页/日期解析

# G-03 确定性决策表（阈值可按租户制度包配置，此处为默认 DSL）
WAY_PUBLIC = 4_000_000
WAY_INVITE = 1_000_000
WAY_INQUIRY = 300_000

# 新错误码（本域登记）
CODE_BUDGET_FREEZE_FAIL = 40910  # 超预算冻结失败
CODE_PAYMENT_EXCEED = 40911  # 付款累计超合同额
CODE_BLACKLIST = 40913  # 供应商黑名单硬拦截
CODE_DUPLICATE_ASSET = 40916  # 重复转资产


def _now():
    return dj_tz.now()


def _parse_dt(s):
    if not s:
        return None
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None
    return dj_tz.make_aware(dt) if dj_tz.is_naive(dt) else dt


def _gen_code(prefix: str, tenant_id: int, model=None, year: int | None = None) -> str:
    if model is None:  # 按前缀映射表模型（旧调用兼容）
        model = {"REQ": GRequisition, "BID": GBid, "ORD": GOrder,
                 "CON": GContract, "OSC": GContract}.get(prefix, GRequisition)
    y = year or _now().year
    seq = model.objects.filter(tenant_id=tenant_id, code__startswith=f"{prefix}-{y}-").count() + 1
    return f"{prefix}-{y}-{seq:04d}"


def _get_req_or_404(rid: int) -> GRequisition:
    r = GRequisition.objects.filter(id=rid, deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "采购申请不存在")
    return r


def _get_contract_or_404(cid: int) -> GContract:
    c = GContract.objects.filter(id=cid, deleted=0).first()
    if c is None:
        raise ApiError(404, CODE_NOT_FOUND, "合同不存在")
    return c


def _dec(v):
    if v is None:
        return None
    from decimal import Decimal
    try:
        return Decimal(str(v))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 供应商 G-04/G-09（黑名单/资质硬拦截闸门）
# ---------------------------------------------------------------------------


def _check_supplier_usable(supplier: GSupplier | None):
    """未入库/黑名单/资质过期 → 40913 硬拦截（不可绕过，历史只读）。"""
    if supplier is None:
        raise ApiError(403, CODE_BLACKLIST, "相对方未指定入库供应商")
    if supplier.blacklist:
        raise ApiError(403, CODE_BLACKLIST, f"供应商 {supplier.name} 在黑名单，硬拦截")
    if supplier.status != "IN_LIBRARY":
        raise ApiError(403, CODE_BLACKLIST, f"供应商 {supplier.name} 非在库状态（{supplier.status}）")
    if supplier.qualification_expire_date and supplier.qualification_expire_date < dj_tz.localdate():
        raise ApiError(403, CODE_BLACKLIST, f"供应商 {supplier.name} 资质过期，禁止新合同")


def list_suppliers(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = GSupplier.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    for k in ("status", "type", "grade"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    if v := request.GET.get("blacklist"):
        qs = qs.filter(blacklist=v in ("true", "1"))
    if kw := request.GET.get("keyword"):
        qs = qs.filter(Q(name__icontains=kw))
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [{
        "id": s.id, "code": s.code, "name": s.name, "credit_code": s.credit_code,
        "type": s.type, "status": s.status, "grade": s.grade, "blacklist": s.blacklist,
        "qualification_json": s.qualification_json or [],
        "qualification_expire_date": f"{s.qualification_expire_date:%Y-%m-%d}" if s.qualification_expire_date else None,
    } for s in rows], "total": total, "page": page, "size": size})


# ---------------------------------------------------------------------------
# 采购申请 G-01/G-02/G-03
# ---------------------------------------------------------------------------

WAY_RULES = [
    (WAY_PUBLIC, "公开招标", 1),
    (WAY_INVITE, "邀请招标", 2),
    (WAY_INQUIRY, "询价", 3),
]


def _decide_way(est_amount, category: str) -> tuple[str, int | None]:
    """G-03 判定引擎：金额决策表（人不越权）；外协走外协分包合同流。"""
    if category == "外协":
        return "单一来源", 9  # 外协分包（rule 9，G-09）
    amt = float(est_amount or 0)
    if amt >= WAY_PUBLIC:
        return "公开招标", 1
    if amt >= WAY_INVITE:
        return "邀请招标", 2
    if amt >= WAY_INQUIRY:
        return "询价", 3
    return "自行采购", 4


@transaction.atomic
def create_requisition(request: HttpRequest):
    """创建申请（G-01，契约无独立提交端点 → 创建即提交）+ 预算冻结（G-02，40910）
    + G-03 方式判定，落库 WAY_DECIDED。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("project_id", "category", "item_name", "est_amount", "budget_subject_code"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    est = _dec(b["est_amount"])
    r = GRequisition.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("REQ", dom.tenant_id),
        project_id=int(b["project_id"]), applicant_id=int(b.get("applicant_id") or dom.user_id),
        category=b["category"], item_name=b["item_name"], spec=b.get("spec"),
        est_amount=est,
        budget_subject_code=b["budget_subject_code"],
        legal_entity_id=b.get("legal_entity_id") or dom.legal_entity_id or 1,
        security_level=b.get("security_level") or "INTERNAL",
        remark=b.get("remark"),
    )
    line_id = _freeze_budget(r.tenant_id, r.budget_subject_code, est)
    r.frozen_amount = est
    way, rule_id = _decide_way(est, r.category)
    r.purchase_way = way
    r.way_basis_rule_id = rule_id
    r.policy_pack_id = 1  # 默认制度包快照（可复算）
    r.status = "WAY_DECIDED"
    r.remark = "; ".join(filter(None, [r.remark, f"冻结 budget_line={line_id}"]))
    r.save()
    return ok(request, {**_api_requisition(r),
                        "clause_ref": f"RULE-{rule_id}" if rule_id else None,
                        "policy_pack_id": r.policy_pack_id})


def _freeze_budget(tenant_id: int, subject_code: str, amount) -> int:
    """对科目剩余可支额度发起冻结；不足 → 40910（含剩余额度提示）。"""
    from apps.funding.models import FBudgetLine, FSubject
    sub = FSubject.objects.filter(tenant_id=tenant_id, code=subject_code, deleted=0).first()
    if sub is None:
        raise ApiError(400, CODE_BAD_REQUEST, f"经费科目 {subject_code} 不存在")
    lines = list(FBudgetLine.objects.filter(tenant_id=tenant_id, subject_id=sub.id,
                                            deleted=0, status="ACTIVE"))
    total_remaining = sum(l.remaining for l in lines)
    if total_remaining < amount:
        raise ApiError(409, CODE_BUDGET_FREEZE_FAIL,
                       f"科目剩余可支额度不足（剩余 {total_remaining}，申请 {amount}）",
                       data={"subject_code": subject_code, "remaining": str(total_remaining)})
    # 冻结到第一行有足够剩余的 budget_line（不允许负余额）
    for line in lines:
        if line.remaining >= amount:
            line.amount_frozen = line.amount_frozen + amount
            line.save(update_fields=["amount_frozen", "updated_at"])
            return line.id
    raise ApiError(409, CODE_BUDGET_FREEZE_FAIL, "冻结失败：无可拆分行")


def _api_requisition(r: GRequisition) -> dict:
    return {
        "id": r.id, "code": r.code, "status": r.status,
        "project_id": r.project_id, "applicant_id": r.applicant_id,
        "category": r.category, "item_name": r.item_name, "spec": r.spec,
        "est_amount": float(r.est_amount), "budget_subject_code": r.budget_subject_code,
        "frozen_amount": float(r.frozen_amount), "purchase_way": r.purchase_way,
        "way_basis_rule_id": r.way_basis_rule_id,
        "legal_entity_id": r.legal_entity_id, "security_level": r.security_level,
        "created_at": r.created_at.isoformat(), "remark": r.remark,
    }


def list_requisitions(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = GRequisition.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    for k in ("status", "category", "purchase_way"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    if v := request.GET.get("project_id"):
        try:
            qs = qs.filter(project_id=int(v))
        except ValueError:
            pass
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [_api_requisition(r) for r in rows],
                        "total": total, "page": page, "size": size})


def get_way(request: HttpRequest, id: int):
    """GET 方式判定结果（G-03）：返回已判定的采购方式与依据规则；未判定则即时计算预览。"""
    r = _get_req_or_404(id)
    way, rule_id = _decide_way(r.est_amount, r.category)
    if r.purchase_way:
        way, rule_id = r.purchase_way, r.way_basis_rule_id
    return ok(request, {"requisition_id": r.id, "status": r.status,
                        "purchase_way": way, "way_basis_rule_id": rule_id,
                        "clause_ref": f"RULE-{rule_id}" if rule_id else None,
                        "frozen_amount": float(r.frozen_amount)})


@transaction.atomic
def decide_way(request: HttpRequest, id: int):
    """提交并触发 G-02 冻结 + G-03 方式判定（DRAFT→SUBMITTED→WAY_DECIDED）。"""
    dom = domain_from(request)
    r = _get_req_or_404(id)
    if r.status not in ("DRAFT",):
        raise ApiError(409, CODE_CONFLICT, f"提交状态机冲突：当前 {r.status}")
    line_id = _freeze_budget(r.tenant_id, r.budget_subject_code, r.est_amount)
    r.frozen_amount = r.est_amount
    way, rule_id = _decide_way(r.est_amount, r.category)
    r.purchase_way = way
    r.way_basis_rule_id = rule_id
    r.policy_pack_id = 1  # 默认制度包快照（可复算）
    r.status = "WAY_DECIDED"
    r.modifier_id = dom.user_id
    r.remark = "; ".join(filter(None, [r.remark, f"冻结 budget_line={line_id}"]))
    r.save()
    return ok(request, {**_api_requisition(r),
                        "clause_ref": f"RULE-{rule_id}",
                        "policy_pack_id": r.policy_pack_id})


# ---------------------------------------------------------------------------
# 招标 G-05
# ---------------------------------------------------------------------------


@transaction.atomic
def create_bid(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("requisition_id") or b.get("method") not in (
            "公开招标", "邀请招标", "竞争性谈判", "单一来源", "询价", "自行采购"):
        raise ApiError(400, CODE_BAD_REQUEST, "requisition_id 与 method 必填")
    r = _get_req_or_404(int(b["requisition_id"]))
    if r.status != "WAY_DECIDED":
        raise ApiError(409, CODE_CONFLICT, f"发标状态机冲突：当前 {r.status}")
    # 邀请招标/询价候选供应商校验（黑名单/未入库硬拦截）
    for sid in (b.get("invited_supplier_ids") or []):
        s = GSupplier.objects.filter(id=int(sid), deleted=0).first()
        _check_supplier_usable(s)
    bid = GBid.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("BID", dom.tenant_id),
        requisition=r, method=b["method"],
        publish_at=_parse_dt(b.get("publish_at")) or _now(),
        bid_open_at=_parse_dt(b.get("bid_open_at")),
        invited_supplier_ids=b.get("invited_supplier_ids") or [],
        bids_json=b.get("bids_json") or [],
    )
    r.status = "BIDDING"
    r.save(update_fields=["status", "updated_at"])
    return ok(request, {"id": bid.id, "code": bid.code, "status": bid.status,
                        "requisition_id": r.id, "method": bid.method})


@transaction.atomic
def award_bid(request: HttpRequest, id: int):
    """定标（G-05）：PUBLICIZING→AWARDED；废标（winner 空）回退释放冻结。"""
    dom = domain_from(request)
    bid = GBid.objects.filter(id=id, deleted=0).first()
    if bid is None:
        raise ApiError(404, CODE_NOT_FOUND, "招标不存在")
    if bid.status != "PUBLICIZING":
        raise ApiError(409, CODE_CONFLICT, f"定标状态机冲突：当前 {bid.status}")
    b = read_json(request)
    voided = bool(b.get("voided"))
    winner = b.get("winner_supplier_id")
    if not voided and not winner:
        raise ApiError(400, CODE_BAD_REQUEST, "winner_supplier_id 必填（废标则 voided=true）")
    if winner and not voided:
        s = GSupplier.objects.filter(id=int(winner), deleted=0).first()
        _check_supplier_usable(s)
        bid.winner_supplier_id = int(winner)
        bid.status = "AWARDED"
        bid.remark = "; ".join(filter(None, [bid.remark,
                                             b.get("winner_reason"),
                                             f"saving={b['saving_amount']}" if b.get("saving_amount") else None]))
    else:
        # 废标/弃标：回退申请 + 释放冻结（G-02 释放时机，业务码 40912 语义）
        bid.status = "CHALLENGE"
        bid.remark = "; ".join(filter(None, [bid.remark, f"voided:{b.get('void_reason') or '未填原因'}"]))
        r = bid.requisition
        if r.frozen_amount and r.frozen_amount > 0:
            from apps.funding.models import FBudgetLine, FSubject
            sub = FSubject.objects.filter(tenant_id=r.tenant_id, code=r.budget_subject_code,
                                          deleted=0).first()
            if sub is not None:
                line = FBudgetLine.objects.filter(id=int((r.remark or "").split("budget_line=")[-1].split(";")[0] or 0),
                                                  deleted=0).first()
                if line is None:
                    line = FBudgetLine.objects.filter(tenant_id=r.tenant_id, subject_id=sub.id,
                                                      deleted=0).first()
                if line is not None:
                    line.amount_frozen = line.amount_frozen - r.frozen_amount
                    line.save(update_fields=["amount_frozen", "updated_at"])
            r.frozen_amount = 0
            r.status = "SUBMITTED"
            r.save()
    bid.award_at = _now()
    bid.modifier_id = dom.user_id
    bid.save()
    return ok(request, {"id": bid.id, "status": bid.status,
                        "winner_supplier_id": bid.winner_supplier_id})


# ---------------------------------------------------------------------------
# 订单 G-12/G-17
# ---------------------------------------------------------------------------


def list_orders(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = GOrder.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    for k in ("status", "delivery_status"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    if v := request.GET.get("requisition_id"):
        try:
            qs = qs.filter(requisition_id=int(v))
        except ValueError:
            pass
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [{
        "id": o.id, "code": o.code, "status": o.status,
        "requisition_id": o.requisition_id, "contract_id": o.contract_id,
        "supplier_id": o.supplier_id, "order_amount": float(o.order_amount),
        "order_date": f"{o.order_date:%Y-%m-%d}" if o.order_date else None,
        "delivery_status": o.delivery_status,
        "accepted_at": o.accepted_at.isoformat() if o.accepted_at else None,
        "converted_asset": o.converted_asset,
    } for o in rows], "total": total, "page": page, "size": size})


@transaction.atomic
def create_order_from_bid(request: HttpRequest):
    """下单（定标后）：AWARDED 招标 → 订单 DRAFT；申请 → ORDERED。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("bid_id", "supplier_id", "order_amount"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, "bid_id/supplier_id/order_amount 必填")
    bid = GBid.objects.filter(id=int(b["bid_id"]), deleted=0).first()
    if bid is None or bid.status != "AWARDED":
        raise ApiError(409, CODE_CONFLICT, "仅 AWARDED 招标可下单")
    s = GSupplier.objects.filter(id=int(b["supplier_id"]), deleted=0).first()
    _check_supplier_usable(s)
    o = GOrder.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("ORD", dom.tenant_id),
        requisition=bid.requisition, supplier=s,
        order_amount=_dec(b["order_amount"]),
        order_date=_parse_date(b.get("order_date")) or dj_tz.localdate(),
        expect_delivery_date=_parse_date(b.get("expect_delivery_date")),
    )
    bid.requisition.status = "ORDERED"
    bid.requisition.save(update_fields=["status", "updated_at"])
    return ok(request, {"id": o.id, "code": o.code, "status": o.status,
                        "requisition_id": o.requisition_id, "supplier_id": o.supplier_id})


# ---------------------------------------------------------------------------
# 合同 G-07/G-08/G-10/G-11/G-13/G-14
# ---------------------------------------------------------------------------


def list_contracts(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = GContract.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    for k in ("status", "contract_type"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    if v := request.GET.get("project_id"):
        try:
            qs = qs.filter(project_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("supplier_id"):
        try:
            qs = qs.filter(supplier_id=int(v))
        except ValueError:
            pass
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    paid = {p.contract_id: p.paid_sum for p in GContractPayment.objects.filter(
        tenant_id=domain_from(request).tenant_id, deleted=0)
        .values("contract_id").annotate(paid_sum=Sum("plan_amount"))}
    return ok(request, {"list": [_api_contract(c, paid.get(c.id, 0)) for c in rows],
                        "total": total, "page": page, "size": size})


def _api_contract(c: GContract, paid_sum=0) -> dict:
    return {
        "id": c.id, "code": c.code, "status": c.status,
        "requisition_id": c.requisition_id, "contract_type": c.contract_type,
        "project_id": c.project_id, "supplier_id": c.supplier_id,
        "party_a": c.party_a, "party_b": c.party_b,
        "amount": float(c.amount), "currency": c.currency,
        "paid_sum": float(paid_sum),
        "sign_date": f"{c.sign_date:%Y-%m-%d}" if c.sign_date else None,
        "start_date": f"{c.start_date:%Y-%m-%d}" if c.start_date else None,
        "end_date": f"{c.end_date:%Y-%m-%d}" if c.end_date else None,
        "sign_method": c.sign_method, "outsource": c.outsource,
        "security_level": c.security_level, "legal_entity_id": c.legal_entity_id,
        "created_at": c.created_at.isoformat(), "remark": c.remark,
    }


@transaction.atomic
def create_contract(request: HttpRequest):
    """合同创建（G-07/G-10）：相对方硬拦截 + 外协分流（OSC 前缀 + G_OUTSOURCE 台账）。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("contract_type", "party_b", "amount"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    supplier = None
    if b.get("supplier_id"):
        supplier = GSupplier.objects.filter(id=int(b["supplier_id"]), deleted=0).first()
        _check_supplier_usable(supplier)
    is_outsource = b["contract_type"] == "外协分包"
    c = GContract.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("OSC" if is_outsource else "CON", dom.tenant_id),
        requisition_id=b.get("requisition_id"),
        contract_type=b["contract_type"], project_id=b.get("project_id"),
        supplier=supplier, party_a=b.get("party_a"), party_b=b["party_b"],
        amount=_dec(b["amount"]), currency=b.get("currency") or "CNY",
        pay_terms_json=b.get("pay_terms_json"),
        deliverables_json=b.get("deliverables_json"),
        start_date=_parse_date(b.get("start_date")),
        end_date=_parse_date(b.get("end_date")),
        outsource=is_outsource,
        legal_entity_id=b.get("legal_entity_id") or dom.legal_entity_id or 1,
        security_level=b.get("security_level") or "INTERNAL",
        remark=b.get("remark"),
    )
    if is_outsource and supplier is not None:
        GOutsource.objects.create(
            tenant_id=dom.tenant_id, creator_id=dom.user_id, contract=c,
            outsource_unit=supplier, outsource_amount=_dec(b["amount"]),
            payout_subject_code=b.get("payout_subject_code"),
        )
    return ok(request, _api_contract(c))


REVIEW_ROLES = ("tech", "legal", "finance", "security")


@transaction.atomic
def review_contract(request: HttpRequest, id: int):
    """合同评审（G-07/G-08）：技术/法务/财务/密级四方意见；任一驳回回 DRAFT。"""
    dom = domain_from(request)
    c = _get_contract_or_404(id)
    if c.status not in ("DRAFT", "REVIEW", "AMENDING"):
        raise ApiError(409, CODE_CONFLICT, f"评审状态机冲突：当前 {c.status}")
    b = read_json(request)
    opinions = c.ai_parse_json and c.ai_parse_json.get("review_opinions") or {}
    if not isinstance(opinions, dict):
        opinions = {}
    role = b.get("role")
    if role not in REVIEW_ROLES:
        raise ApiError(400, CODE_BAD_REQUEST, "role 必须为 tech/legal/finance/security")
    opinions[role] = {"result": b.get("result"), "comment": b.get("comment"),
                      "by": dom.user_id, "at": _now().isoformat()}
    c.ai_parse_json = {**(c.ai_parse_json or {}), "review_opinions": opinions}
    c.status = "REVIEW"
    if b.get("result") == "REJECT":
        c.status = "DRAFT"
    elif all(r in opinions and opinions[r].get("result") == "APPROVE" for r in REVIEW_ROLES):
        c.status = "TO_SIGN"
    c.modifier_id = dom.user_id
    c.save()
    return ok(request, {**_api_contract(c), "review_opinions": opinions})


@transaction.atomic
def sign_contract(request: HttpRequest, id: int):
    """签署（G-11）：TO_SIGN→ACTIVE；CA 不可用降级纸质（sign_method=纸质+scan_url）。"""
    dom = domain_from(request)
    c = _get_contract_or_404(id)
    if c.status != "TO_SIGN":
        raise ApiError(409, CODE_CONFLICT, f"签署状态机冲突：当前 {c.status}")
    b = read_json_soft(request)
    c.sign_method = b.get("sign_method") or "电子签"
    if c.sign_method == "纸质" and not b.get("scan_url"):
        raise ApiError(400, CODE_BAD_REQUEST, "纸质签署须补传扫描件 scan_url")
    if b.get("scan_url"):
        c.ai_parse_json = {**(c.ai_parse_json or {}), "scan_url": b["scan_url"]}
    c.status = "ACTIVE"
    c.sign_date = _parse_date(b.get("sign_date")) or dj_tz.localdate()
    c.modifier_id = dom.user_id
    c.save()
    return ok(request, _api_contract(c))


@transaction.atomic
def ai_parse_contract(request: HttpRequest, id: int):
    """G-13 AI 解析：确定性降级（逐字段来源+置信度，人工确认后落字段）。"""
    c = _get_contract_or_404(id)
    result = {
        "fields": {
            "party_a": {"value": c.party_a, "source": "MANUAL", "confidence": 1.0},
            "party_b": {"value": c.party_b, "source": "MANUAL", "confidence": 1.0},
            "amount": {"value": float(c.amount), "source": "MANUAL", "confidence": 1.0},
        },
        "degraded": True,
        "note": "LLM 解析未启用（svc-ai 增强后回吐置信度），人工确认后落字段",
    }
    c.ai_parse_json = {**(c.ai_parse_json or {}), "parse": result}
    c.save(update_fields=["ai_parse_json", "updated_at"])
    return ok(request, result)


@transaction.atomic
def ai_risk_contract(request: HttpRequest, id: int):
    """G-14 AI 风险：规则引擎硬约束（条款红线）+ LLM 建议（降级空）。"""
    c = _get_contract_or_404(id)
    risks = []
    # 规则引擎：无付款条款 / 无交付物清单 → 高风险提示（硬约束可拦截项）
    if not c.pay_terms_json:
        risks.append({"clause": "付款条款", "risk_type": "MISSING", "level": "HIGH",
                      "suggestion": "补充付款阶段与比例", "rule_hit": "RULE-G-PAY-01", "llm": False})
    if not c.deliverables_json:
        risks.append({"clause": "交付物清单", "risk_type": "MISSING", "level": "MED",
                      "suggestion": "明确交付物与验收标准", "rule_hit": "RULE-G-DEL-01", "llm": False})
    c.ai_risk_json = risks
    c.save(update_fields=["ai_risk_json", "updated_at"])
    return ok(request, {"list": risks})


def trace_contract(request: HttpRequest, id: int):
    """G-12 合同追溯链（联动 E-17）：申请→招标→订单→合同→付款 全链节点。"""
    c = _get_contract_or_404(id)
    nodes = [{"step": "CONTRACT", "id": c.id, "code": c.code, "status": c.status,
              "at": c.created_at.isoformat()}]
    if c.requisition_id:
        r = GRequisition.objects.filter(id=c.requisition_id).first()
        if r:
            nodes.insert(0, {"step": "REQUISITION", "id": r.id, "code": r.code,
                             "status": r.status, "at": r.created_at.isoformat()})
            bids = GBid.objects.filter(requisition_id=r.id, deleted=0)
            for bid in bids:
                nodes.insert(1, {"step": "BID", "id": bid.id, "code": bid.code,
                                 "status": bid.status, "at": bid.created_at.isoformat()})
            orders = GOrder.objects.filter(requisition_id=r.id, deleted=0)
            for o in orders:
                nodes.append({"step": "ORDER", "id": o.id, "code": o.code,
                              "status": o.status, "at": o.created_at.isoformat()})
    payments = GContractPayment.objects.filter(contract=c, deleted=0).order_by("id")
    for p in payments:
        nodes.append({"step": "PAYMENT", "id": p.id, "code": p.code, "phase": p.phase,
                      "status": p.status, "plan_amount": float(p.plan_amount),
                      "paid_amount": float(p.paid_amount)})
    return ok(request, {"contract_id": c.id, "chain": nodes})


# ---------------------------------------------------------------------------
# 付款计划与执行 G-08
# ---------------------------------------------------------------------------


@transaction.atomic
def create_payment_plan(request: HttpRequest, id: int):
    """付款计划（G-08）：Σ plan_amount ≤ 合同额硬拦截（40911）。"""
    dom = domain_from(request)
    c = _get_contract_or_404(id)
    b = read_json(request)
    items = b.get("plans") or ([b] if b.get("plan_amount") else [])
    if not items:
        raise ApiError(400, CODE_BAD_REQUEST, "plans 或 plan_amount 必填")
    planned_total = GContractPayment.objects.filter(contract=c, deleted=0).exclude(
        status="CANCELLED").aggregate(s=Sum("plan_amount"))["s"] or 0
    new_total = planned_total + sum(float(i.get("plan_amount") or 0) for i in items)
    if new_total > float(c.amount):
        raise ApiError(409, CODE_PAYMENT_EXCEED,
                       f"付款计划累计 {new_total} 超合同额 {c.amount}",
                       data={"contract_amount": float(c.amount), "planned_total": float(new_total)})
    out = []
    for i in items:
        p = GContractPayment.objects.create(
            tenant_id=dom.tenant_id, creator_id=dom.user_id, contract=c,
            code=f"{c.code}-P{GContractPayment.objects.filter(contract=c).count() + 1}",
            phase=i.get("phase") or "验收", plan_amount=_dec(i["plan_amount"]),
            plan_date=_parse_date(i.get("plan_date")),
        )
        out.append({"id": p.id, "phase": p.phase, "plan_amount": float(p.plan_amount),
                    "status": p.status})
    return ok(request, {"list": out, "planned_total": float(new_total)})


# ---------------------------------------------------------------------------
# 付款执行回调 /finance/expense（G-08 →F）：冻结→实扣原子迁移 + paid_amount 回填。
# ---------------------------------------------------------------------------


@transaction.atomic
def payment_callback(request: HttpRequest):
    """/finance/expense（G-08）：F 模块付款回调，expense_id 幂等去重，累计实付≤合同额。"""
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("payment_id") or not b.get("expense_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "payment_id/expense_id 必填")
    p = GContractPayment.objects.filter(id=int(b["payment_id"]), deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "付款计划不存在")
    if p.expense_id and int(p.expense_id) == int(b["expense_id"]) and p.status in ("PAID", "VOUCHER_SYNCED"):
        return ok(request, {"id": p.id, "status": p.status, "paid_amount": float(p.paid_amount),
                            "idempotent": True})  # 幂等以 expense_id 去重
    if p.status in ("PAID", "VOUCHER_SYNCED"):
        raise ApiError(409, CODE_CONFLICT, f"付款已执行（{p.status}）")
    amount = _dec(b.get("paid_amount") or b.get("amount") or p.plan_amount)
    c = p.contract
    paid_total = GContractPayment.objects.filter(contract=c, deleted=0).aggregate(
        s=Sum("paid_amount"))["s"] or 0
    if paid_total + amount > c.amount:
        raise ApiError(409, CODE_PAYMENT_EXCEED, "累计实付超合同额")
    # 冻结→实扣：合同关联申请冻结转实扣（有 requisition 且冻结未释放）
    r = c.requisition
    if r is not None and r.frozen_amount and r.frozen_amount > 0:
        from apps.funding.models import FBudgetLine, FSubject
        sub = FSubject.objects.filter(tenant_id=r.tenant_id, code=r.budget_subject_code,
                                      deleted=0).first()
        if sub is not None:
            for line in FBudgetLine.objects.filter(tenant_id=r.tenant_id, subject_id=sub.id,
                                                   deleted=0, status="ACTIVE"):
                frozen_here = min(line.amount_frozen, r.frozen_amount)
                if frozen_here > 0:
                    line.amount_frozen = line.amount_frozen - frozen_here
                    line.amount_used = line.amount_used + frozen_here
                    line.save(update_fields=["amount_frozen", "amount_used", "updated_at"])
                    r.frozen_amount = r.frozen_amount - frozen_here
                    break
        r.save(update_fields=["frozen_amount", "updated_at"])
    p.status = "PAID"
    p.paid_amount = amount
    p.paid_at = _parse_dt(b.get("pay_date")) or _now()
    p.expense_id = int(b["expense_id"])
    p.modifier_id = dom.user_id
    if b.get("voucher_status"):
        p.remark = "; ".join(filter(None, [p.remark, f"voucher_status={b['voucher_status']}"]))
    p.save()
    return ok(request, {"id": p.id, "status": p.status, "paid_amount": float(p.paid_amount),
                        "paid_at": p.paid_at.isoformat()})
