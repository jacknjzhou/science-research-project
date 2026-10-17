"""成果转化域 T API（对齐 design/05-科技成果转化-T.openapi.yaml，无 Go 参考纯契约实现）。

链路：披露→评估分派→交易状态机（PRD §6.2）→合同起草→多级审批（T-08 金额门槛）→
电子签→公示（独立异议状态机，异议未结阻断执行）→到账登记→分配规则/明细→发放到人→年报。
AI 三端点（T-17/T-18/T-19）确定性降级实现，LLM 可用时走 core/llm。
公开通道：GET /publicity/{dealId}、POST /publicity/{dealId}/objection（security: []）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.transform.mappings import (
    num2,
    num_float,
    to_api_annual,
    to_api_chain,
    to_api_contract,
    to_api_deal,
    to_api_disclosure,
    to_api_dist_record,
    to_api_income,
    to_api_partner,
    to_api_publicity,
    to_api_rule,
    to_api_valuation,
)
from apps.transform.models import (
    TAnnualReport,
    TApprovalChain,
    TContract,
    TDeal,
    TDisclosure,
    TDistributionRecord,
    TDistributionRule,
    TEnterpartner,
    TIncome,
    TPublicity,
    TValuation,
)
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_DIST_PCT_SUM,
    CODE_NOT_FOUND,
    CODE_TEAM_PCT_LOW,
    ok,
    read_json,
    read_json_soft,
)

DEAL_TYPES = {"转让", "独占许可", "排他许可", "普通许可", "作价投资", "合作实施"}
PAYMENT_METHODS = {"一次性", "分期", "入门费+销售提成"}
APPLY_TO_MAP = {"转让": "转让", "独占许可": "许可", "排他许可": "许可", "普通许可": "许可", "作价投资": "作价", "合作实施": "许可"}
# T-08 规则引擎：金额 ≥100 万追加院所级，≥500 万达理事会（>500 万需 BOARD）
CHAIN_LEVELS = ["LEGAL", "FINANCE", "INSTITUTE", "COMPETENT_DEPT", "BOARD"]
BOARD_THRESHOLD = 5_000_000
INSTITUTE_THRESHOLD = 1_000_000

from apps.output.api import page_args, _parse_date  # noqa: E402  共用分页/日期解析


def _now():
    return dj_tz.now()


def _dec(v):
    if v is None:
        return None
    try:
        from decimal import Decimal

        return Decimal(str(v))
    except Exception:
        return None


def _get_disclosure_or_404(did: int) -> TDisclosure:
    d = TDisclosure.objects.filter(id=did, deleted=0).first()
    if d is None:
        raise ApiError(404, CODE_NOT_FOUND, "披露不存在")
    return d


def _get_deal_or_404(did: int) -> TDeal:
    d = TDeal.objects.filter(id=did, deleted=0).first()
    if d is None:
        raise ApiError(404, CODE_NOT_FOUND, "交易不存在")
    return d


def _get_income_or_404(iid: int) -> TIncome:
    r = TIncome.objects.filter(id=iid, deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "到账记录不存在")
    return r


def _gen_deal_code(tenant_id: int) -> str:
    year = _now().year
    seq = TDeal.objects.filter(tenant_id=tenant_id, code__startswith=f"DEAL-{year}-").count() + 1
    return f"DEAL-{year}-{seq:04d}"


def _guard(deal: TDeal, allowed: set[str], action: str):
    if deal.status not in allowed:
        raise ApiError(409, CODE_CONFLICT, f"{action} 状态机冲突：当前 {deal.status}")


# ---------------------------------------------------------------------------
# 披露 T-01
# ---------------------------------------------------------------------------


def list_disclosure(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = TDisclosure.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("output_id"):
        try:
            qs = qs.filter(output_id=int(v))
        except ValueError:
            pass
    if request.GET.get("mine") in ("true", "1"):
        qs = qs.filter(disclosed_by=domain_from(request).user_id)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_disclosure(r) for r in rows],
                        "total": total, "page": page, "size": size})


@transaction.atomic
def create_disclosure(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("output_id") or not b.get("disclosure_date"):
        raise ApiError(400, CODE_BAD_REQUEST, "output_id 与 disclosure_date 必填")
    d = TDisclosure.objects.create(
        tenant_id=dom.tenant_id,
        creator_id=dom.user_id,
        output_id=int(b["output_id"]),
        project_id=b.get("project_id") or None,
        disclosed_by=int(b.get("disclosed_by") or dom.user_id),
        department_id=b.get("department_id") or None,
        disclosure_date=_parse_date(b["disclosure_date"]),
        tech_summary=b.get("tech_summary"),
        application_scenarios=b.get("application_scenarios") or [],
        maturity_level=b.get("maturity_level"),
        is_core_tech=bool(b.get("is_core_tech", False)),
        target_partners=b.get("target_partners") or [],
        expected_value=_dec(b.get("expected_value")),
        legal_entity_id=dom.legal_entity_id or 1,
        security_level=b.get("security_level") or "INTERNAL",
        remark=b.get("remark"),
    )
    return ok(request, to_api_disclosure(d))


@transaction.atomic
def submit_disclosure(request: HttpRequest, id: int):
    dom = domain_from(request)
    d = _get_disclosure_or_404(id)
    if d.status != "DRAFT":
        raise ApiError(409, CODE_CONFLICT, f"提交状态机冲突：当前 {d.status}")
    d.status = "SUBMITTED"
    d.submitted_at = _now()
    d.modifier_id = dom.user_id
    d.save(update_fields=["status", "submitted_at", "modifier_id", "updated_at"])
    return ok(request, to_api_disclosure(d))


# ---------------------------------------------------------------------------
# 评估 T-03/T-04
# ---------------------------------------------------------------------------


@transaction.atomic
def assign_valuation(request: HttpRequest, id: int):
    dom = domain_from(request)
    d = _get_disclosure_or_404(id)
    b = read_json(request)
    vtype = b.get("valuator_type")
    if vtype not in ("INTERNAL", "EXTERNAL"):
        raise ApiError(400, CODE_BAD_REQUEST, "valuator_type 必须为 INTERNAL/EXTERNAL")
    if vtype == "EXTERNAL" and not b.get("valuator_org"):
        raise ApiError(400, CODE_BAD_REQUEST, "外评必须指定评估机构 valuator_org")
    if d.status not in ("SUBMITTED", "UNDER_EVAL"):
        raise ApiError(409, CODE_CONFLICT, f"评估分派状态机冲突：当前 {d.status}")
    v = TValuation.objects.create(
        tenant_id=dom.tenant_id,
        creator_id=dom.user_id,
        disclosure=d,
        valuator_type=vtype,
        valuator_name=b.get("valuator_name"),
        valuator_org=b.get("valuator_org"),
        method=b.get("method"),
    )
    d.status = "UNDER_EVAL"
    d.modifier_id = dom.user_id
    d.save(update_fields=["status", "modifier_id", "updated_at"])
    return ok(request, to_api_valuation(v))


@transaction.atomic
def upload_external_report(request: HttpRequest, id: int):
    dom = domain_from(request)
    v = TValuation.objects.filter(id=id, deleted=0).first()
    if v is None:
        raise ApiError(404, CODE_NOT_FOUND, "评估记录不存在")
    b = read_json(request)
    if b.get("valuation_amount") is None:
        raise ApiError(400, CODE_BAD_REQUEST, "valuation_amount 必填")
    v.valuation_amount = _dec(b["valuation_amount"])
    v.currency = b.get("currency") or "CNY"
    v.report_url = b.get("report_url")
    v.valuation_date = _parse_date(b.get("valuation_date"))
    v.valid_until = _parse_date(b.get("valid_until"))
    v.status = "REPORT_UPLOADED"
    v.modifier_id = dom.user_id
    v.save()
    return ok(request, to_api_valuation(v))


# ---------------------------------------------------------------------------
# 交易 T-02/T-05/T-07
# ---------------------------------------------------------------------------


def list_deals(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = TDeal.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("deal_type"):
        qs = qs.filter(deal_type=v)
    if v := request.GET.get("output_id"):
        try:
            qs = qs.filter(output_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("enterpartner_id"):
        try:
            qs = qs.filter(enterpartner_id=int(v))
        except ValueError:
            pass
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_deal(r) for r in rows],
                        "total": total, "page": page, "size": size})


def _apply_negotiation(deal: TDeal, b: dict, dom) -> None:
    """谈判条款字段校验 + 落库（createDeal/negotiation 共用）。"""
    if b.get("deal_type") not in DEAL_TYPES:
        raise ApiError(400, CODE_BAD_REQUEST, "deal_type 非法")
    if b.get("payment_method") not in PAYMENT_METHODS:
        raise ApiError(400, CODE_BAD_REQUEST, "payment_method 非法")
    if b.get("contract_amount") is None:
        raise ApiError(400, CODE_BAD_REQUEST, "contract_amount 必填")
    if b.get("deal_type") == "作价投资":
        if b.get("equity_ratio") is None or b.get("exit_arrangement") is None:
            raise ApiError(400, CODE_BAD_REQUEST, "作价投资必须携 equity_ratio 与 exit_arrangement")
        deal.equity_ratio = _dec(b["equity_ratio"])
        deal.equity_value = _dec(b.get("equity_value"))
        deal.exit_arrangement = b.get("exit_arrangement")
    if b.get("payment_method") == "入门费+销售提成" and b.get("royalty_rate") is None:
        raise ApiError(400, CODE_BAD_REQUEST, "入门费+销售提成模式必须携 royalty_rate")
    deal.deal_type = b["deal_type"]
    deal.payment_method = b["payment_method"]
    deal.contract_amount = _dec(b["contract_amount"])
    deal.enterpartner_id = b.get("enterpartner_id") or None
    deal.partner_name = b.get("partner_name")
    deal.partner_credit_code = b.get("partner_credit_code")
    deal.initial_fee = _dec(b.get("initial_fee"))
    deal.royalty_rate = _dec(b.get("royalty_rate"))
    deal.term_start = _parse_date(b.get("term_start"))
    deal.term_end = _parse_date(b.get("term_end"))
    # 工商核验快照：命中企业库异常 → 签约前标红（PRD §11）
    if deal.enterpartner_id:
        ep = TEnterpartner.objects.filter(id=deal.enterpartner_id, deleted=0).first()
        if ep is not None:
            deal.partner_check_abnormal = ep.check_abnormal
            deal.partner_checked_at = ep.last_checked_at


@transaction.atomic
def create_deal(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("disclosure_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "disclosure_id 必填")
    d = _get_disclosure_or_404(int(b["disclosure_id"]))
    deal = TDeal(
        tenant_id=dom.tenant_id,
        creator_id=dom.user_id,
        code=_gen_deal_code(dom.tenant_id),
        disclosure=d,
        output_id=d.output_id,
        project_id=d.project_id,
        legal_entity_id=dom.legal_entity_id or d.legal_entity_id,
        security_level=d.security_level,
        status="DRAFT",
    )
    _apply_negotiation(deal, b, dom)
    deal.save()
    # 披露进入 DEALING（有交易在谈）
    if d.status in ("SUBMITTED", "UNDER_EVAL"):
        d.status = "DEALING"
        d.save(update_fields=["status", "updated_at"])
    return ok(request, to_api_deal(deal))


def get_deal(request: HttpRequest, id: int):
    deal = _get_deal_or_404(id)
    data = to_api_deal(deal)
    chain = TApprovalChain.objects.filter(deal=deal, deleted=0).order_by("step_order")
    data["approval_chain"] = [to_api_chain(c) for c in chain]
    return ok(request, data)


@transaction.atomic
def save_negotiation(request: HttpRequest, id: int):
    dom = domain_from(request)
    deal = _get_deal_or_404(id)
    _guard(deal, {"DRAFT", "VALUATED", "NEGOTIATING"}, "谈判")
    b = read_json(request)
    _apply_negotiation(deal, b, dom)
    deal.status = "NEGOTIATING"
    deal.modifier_id = dom.user_id
    deal.save()
    return ok(request, to_api_deal(deal))


@transaction.atomic
def publish_deal(request: HttpRequest, id: int):
    """T-05 挂牌发布（推送国家技术转移平台）；VALUATED/NEGOTIATING 均可挂牌。"""
    dom = domain_from(request)
    deal = _get_deal_or_404(id)
    _guard(deal, {"VALUATED", "NEGOTIATING"}, "挂牌发布")
    deal.modifier_id = dom.user_id
    deal.save(update_fields=["modifier_id", "updated_at"])
    return ok(request, to_api_deal(deal))


# ---------------------------------------------------------------------------
# 合作企业库 T-06
# ---------------------------------------------------------------------------


@transaction.atomic
def register_partner(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("company_name"):
        raise ApiError(400, CODE_BAD_REQUEST, "company_name 必填")
    if cc := b.get("credit_code"):
        dup = TEnterpartner.objects.filter(
            tenant_id=dom.tenant_id, credit_code=cc, deleted=0
        ).exclude(company_name=b["company_name"]).first()
        if dup is not None:
            raise ApiError(409, CODE_CONFLICT, "统一社会信用代码已登记", data={"existing_id": dup.id})
    # 工商真实性核验：外部 API 未接入 → 确定性记录核验时间，异常标记以 business_check_json 为准
    check_json = b.get("business_check_json")
    ep = TEnterpartner.objects.create(
        tenant_id=dom.tenant_id,
        creator_id=dom.user_id,
        company_name=b["company_name"],
        credit_code=cc,
        industry=b.get("industry"),
        register_status=b.get("register_status"),
        business_check_json=check_json,
        check_abnormal=bool((check_json or {}).get("abnormal", False)),
        last_checked_at=_now(),
        tech_needs=b.get("tech_needs") or [],
        contact=b.get("contact"),
        past_deals=b.get("past_deals") or [],
        evaluation_score=_dec(b.get("evaluation_score")),
    )
    return ok(request, to_api_partner(ep))


def list_partners(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = TEnterpartner.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("industry"):
        qs = qs.filter(industry=v)
    if v := request.GET.get("check_abnormal"):
        qs = qs.filter(check_abnormal=v in ("true", "1"))
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_partner(r) for r in rows],
                        "total": total, "page": page, "size": size})


# ---------------------------------------------------------------------------
# 合同 T-08/T-10 + 多级审批 T-09
# ---------------------------------------------------------------------------


def _contract_hash(deal_id: int, version: int, body: dict) -> str:
    raw = json.dumps({"deal_id": deal_id, "version": version, "body": body},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@transaction.atomic
def draft_contract(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("deal_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "deal_id 必填")
    deal = _get_deal_or_404(int(b["deal_id"]))
    _guard(deal, {"NEGOTIATING", "DRAFT_CONTRACT"}, "合同起草")
    if TContract.objects.filter(deal=deal, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "一交易一有效合同")
    prev = None
    version = 1
    immutable = _contract_hash(deal.id, version, b)
    c = TContract.objects.create(
        tenant_id=dom.tenant_id,
        creator_id=dom.user_id,
        deal=deal,
        template_code=b.get("template_code"),
        contract_file_url=b.get("contract_file_url"),
        redline_file_url=b.get("redline_file_url"),
        version=version,
        immutable_hash=immutable,
        prev_hash=prev,
    )
    deal.status = "DRAFT_CONTRACT"
    deal.modifier_id = dom.user_id
    deal.save(update_fields=["status", "modifier_id", "updated_at"])
    return ok(request, to_api_contract(c))


def get_contract(request: HttpRequest, id: int):
    c = TContract.objects.filter(id=id, deleted=0).first()
    if c is None:
        raise ApiError(404, CODE_NOT_FOUND, "合同不存在")
    return ok(request, to_api_contract(c))


def _build_chain(deal: TDeal, dom) -> None:
    """T-08 规则引擎：按金额阈值生成审批链并快照门槛（可复算）。"""
    amount = deal.contract_amount or 0
    if amount >= BOARD_THRESHOLD:
        levels = CHAIN_LEVELS
    elif amount >= INSTITUTE_THRESHOLD:
        levels = ["LEGAL", "FINANCE", "INSTITUTE"]
    else:
        levels = ["LEGAL", "FINANCE"]
    deal.approval_required_level = levels[-1]
    deal.save(update_fields=["approval_required_level", "updated_at"])
    thresholds = {"LEGAL": None, "FINANCE": None, "INSTITUTE": INSTITUTE_THRESHOLD,
                  "COMPETENT_DEPT": None, "BOARD": BOARD_THRESHOLD}
    for i, role in enumerate(levels, start=1):
        TApprovalChain.objects.create(
            tenant_id=deal.tenant_id, creator_id=dom.user_id, deal=deal,
            step_order=i, approver_role=role, amount_threshold=thresholds.get(role),
            policy_pack_id=deal.policy_pack_id,
        )


@transaction.atomic
def approve_deal(request: HttpRequest, id: int):
    dom = domain_from(request)
    deal = _get_deal_or_404(id)
    b = read_json(request)
    action = b.get("action")
    if action not in ("APPROVE", "REJECT", "RETURN"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 必须为 APPROVE/REJECT/RETURN")
    chain = list(TApprovalChain.objects.filter(deal=deal, deleted=0).order_by("step_order"))
    if not chain:
        _guard(deal, {"DRAFT_CONTRACT"}, "审批启动")
        deal.status = "UNDER_APPROVAL"
        deal.save(update_fields=["status", "updated_at"])
        _build_chain(deal, dom)
        chain = list(TApprovalChain.objects.filter(deal=deal, deleted=0).order_by("step_order"))
    else:
        _guard(deal, {"UNDER_APPROVAL", "DRAFT_CONTRACT"}, "审批")
        if deal.status == "DRAFT_CONTRACT":
            deal.status = "UNDER_APPROVAL"
            deal.save(update_fields=["status", "updated_at"])
    pending = [c for c in chain if c.status == "PENDING"]
    if not pending:
        raise ApiError(409, CODE_CONFLICT, "审批链已完结")
    step = pending[0]
    if b.get("step_order"):
        target = TApprovalChain.objects.filter(deal=deal, step_order=int(b["step_order"]), deleted=0).first()
        if target is None:
            raise ApiError(404, CODE_NOT_FOUND, "审批步序不存在")
        if target.status != "PENDING":
            raise ApiError(409, CODE_CONFLICT, "该步序已审批")
        step = target
    step.action = action
    step.comment = b.get("comment")
    step.approver_id = dom.user_id
    step.acted_at = _now()
    if action == "APPROVE":
        step.status = "APPROVED"
        step.save()
        if not TApprovalChain.objects.filter(deal=deal, status="PENDING", deleted=0).exists():
            deal.status = "APPROVED"
            contract = TContract.objects.filter(deal=deal, deleted=0).first()
            if contract is not None:
                contract.status = "TO_SIGN"
                contract.save(update_fields=["status", "updated_at"])
            deal.save(update_fields=["status", "updated_at"])
    elif action == "REJECT":
        step.status = "REJECTED"
        step.save()
        deal.status = "DRAFT_CONTRACT"  # 契约：REJECT 回 DRAFT_CONTRACT
        deal.save(update_fields=["status", "updated_at"])
    else:  # RETURN
        step.status = "RETURNED"
        step.save()
    return ok(request, {"deal": to_api_deal(deal), "step": to_api_chain(step)})


@transaction.atomic
def sign_deal(request: HttpRequest, id: int):
    dom = domain_from(request)
    deal = _get_deal_or_404(id)
    _guard(deal, {"APPROVED"}, "电子签")
    b = read_json(request)
    contract = TContract.objects.filter(deal=deal, deleted=0).first()
    if contract is None:
        raise ApiError(409, CODE_CONFLICT, "无有效合同")
    signed_at = b.get("signed_at")
    dt = _now()
    if signed_at:
        try:
            dt = datetime.fromisoformat(str(signed_at))
        except ValueError:
            pass
    deal.status = "SIGNED"
    deal.signed_at = dt
    deal.modifier_id = dom.user_id
    deal.save()
    contract.status = "SIGNED"
    contract.signed_at = dt
    contract.seal_records = b.get("seal_records") or contract.seal_records or []
    contract.save()
    return ok(request, to_api_deal(deal))


# ---------------------------------------------------------------------------
# 公示与异议 T-14（公开通道）
# ---------------------------------------------------------------------------


def get_publicity(request: HttpRequest, dealId: int):
    p = TPublicity.objects.filter(deal_id=dealId, deleted=0).order_by("-id").first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "公示不存在")
    return ok(request, to_api_publicity(p))


@transaction.atomic
def publish_publicity(request: HttpRequest, dealId: int):
    dom = domain_from(request)
    deal = _get_deal_or_404(dealId)
    _guard(deal, {"SIGNED"}, "公示发布")
    b = read_json(request)
    raw_days = b.get("duration_days")
    duration = 15 if raw_days is None else int(raw_days)
    if duration < 0:
        raise ApiError(400, CODE_BAD_REQUEST, "duration_days 非法")
    start = _now()
    end = start + timedelta(days=duration)
    summary = b.get("summary_json") or {}
    snap = hashlib.sha256(json.dumps(summary, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    p = TPublicity.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, deal=deal,
        publish_start_at=start, publish_end_at=end, duration_days=duration,
        url=f"/public/transform/deal/{deal.id}", summary_json=summary,
        public_snapshot_hash=snap,
    )
    deal.status = "PUBLICIZED"
    deal.modifier_id = dom.user_id
    deal.save(update_fields=["status", "modifier_id", "updated_at"])
    return ok(request, to_api_publicity(p))


@transaction.atomic
def submit_objection(request: HttpRequest, dealId: int):
    """公开通道：不登录可提交异议（PRD §11），置 objection_open 阻断执行。"""
    p = TPublicity.objects.filter(deal_id=dealId, deleted=0).order_by("-id").first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "公示不存在")
    b = read_json(request)
    if not b.get("content"):
        raise ApiError(400, CODE_BAD_REQUEST, "content 必填")
    objections = p.objections or []
    oid = f"OBJ{p.id}-{len(objections) + 1}"
    objections.append({
        "objection_id": oid,
        "submitter": b.get("submitter"),
        "contact": b.get("contact"),
        "content": b["content"],
        "submitted_at": _now().isoformat(),
        "handle_status": "OPEN",
        "handle_result": None,
        "handled_at": None,
    })
    p.objections = objections
    p.objection_open = True
    p.status = "OBJECTION_PENDING"
    p.save()
    return ok(request, {"objection_id": oid})


@transaction.atomic
def handle_objection(request: HttpRequest, dealId: int):
    dom = domain_from(request)
    p = TPublicity.objects.filter(deal_id=dealId, deleted=0).order_by("-id").first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "公示不存在")
    b = read_json(request)
    oid = b.get("objection_id")
    hs = b.get("handle_status")
    if not oid or hs not in ("PROCESSING", "SUSTAINED", "DISMISSED"):
        raise ApiError(400, CODE_BAD_REQUEST, "objection_id 与 handle_status 必填（PROCESSING/SUSTAINED/DISMISSED）")
    objections = p.objections or []
    target = next((o for o in objections if o.get("objection_id") == oid), None)
    if target is None:
        raise ApiError(404, CODE_NOT_FOUND, "异议不存在")
    target["handle_status"] = hs
    target["handle_result"] = b.get("handle_result")
    target["handled_at"] = _now().isoformat()
    p.objections = objections
    deal = p.deal
    if hs == "SUSTAINED":
        p.status = "TERMINATED"
        p.save()
        deal.status = "TERMINATED"
        deal.terminated_reason = "OBJECTION_SUSTAINED"
        deal.modifier_id = dom.user_id
        deal.save(update_fields=["status", "terminated_reason", "modifier_id", "updated_at"])
    elif hs == "DISMISSED":
        # objection_open 语义 = 存在未结异议（PRD §11）；全部处置完毕才解除阻断
        p.objection_open = any(
            o.get("handle_status") in ("OPEN", "PROCESSING") for o in objections
        )
        # 公示期满且异议已结 → 公示完成、交易进执行（异议未结阻断执行，PRD §11）
        if p.objection_open is False and _now() >= p.publish_end_at:
            p.status = "COMPLETED"
            if deal.status == "PUBLICIZED":
                deal.status = "EXECUTING"
                deal.save(update_fields=["status", "updated_at"])
        p.save()
    else:
        p.save()
    return ok(request, to_api_publicity(p))


# ---------------------------------------------------------------------------
# 到账 T-11
# ---------------------------------------------------------------------------


@transaction.atomic
def register_income(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("deal_id") or not b.get("received_date") or b.get("amount") is None:
        raise ApiError(400, CODE_BAD_REQUEST, "deal_id/received_date/amount 必填")
    deal = _get_deal_or_404(int(b["deal_id"]))
    if deal.status not in ("SIGNED", "PUBLICIZED", "EXECUTING", "INCOME_RECEIVED", "DISTRIBUTED"):
        raise ApiError(409, CODE_CONFLICT, f"到账登记状态机冲突：当前 {deal.status}")
    if bfn := b.get("bank_flow_no"):
        if TIncome.objects.filter(tenant_id=dom.tenant_id, bank_flow_no=bfn, deleted=0).exists():
            raise ApiError(409, CODE_CONFLICT, "银行流水号已登记")
    royalty_calc = None
    if b.get("sales_amount") is not None and deal.royalty_rate is not None:
        royalty_calc = float(b["sales_amount"]) * float(deal.royalty_rate)
    inc = TIncome.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, deal=deal,
        finance_receipt_id=b.get("finance_receipt_id"),
        received_date=_parse_date(b["received_date"]),
        amount=_dec(b["amount"]),
        currency=b.get("currency") or "CNY",
        receipt_no=b.get("receipt_no"),
        bank_flow_no=bfn,
        payment_phase=b.get("payment_phase"),
        sales_amount=_dec(b.get("sales_amount")),
        royalty_calc_amount=_dec(royalty_calc),
        voucher_url=b.get("voucher_url"),
    )
    if deal.status in ("SIGNED", "PUBLICIZED", "EXECUTING"):
        deal.status = "INCOME_RECEIVED"
        deal.save(update_fields=["status", "updated_at"])
    return ok(request, to_api_income(inc))


@transaction.atomic
def match_income(request: HttpRequest, id: int):
    dom = domain_from(request)
    inc = _get_income_or_404(id)
    b = read_json_soft(request)
    if b.get("finance_receipt_id"):
        inc.finance_receipt_id = int(b["finance_receipt_id"])
    if inc.status == "PENDING":
        inc.status = "MATCHED"
    inc.modifier_id = dom.user_id
    inc.save()
    return ok(request, to_api_income(inc))


# ---------------------------------------------------------------------------
# 分配规则与明细 T-12/T-13
# ---------------------------------------------------------------------------


@transaction.atomic
def save_distribution_rule(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    for k in ("rule_name", "applies_to", "team_pct", "institute_pct", "individual_pct", "min_team_pct", "effective_from"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    team, inst, ind = float(b["team_pct"]), float(b["institute_pct"]), float(b["individual_pct"])
    if abs(team + inst + ind - 1) > 1e-4:
        raise ApiError(400, CODE_DIST_PCT_SUM, "分配三方比例之和≠1")
    if team < float(b["min_team_pct"]):
        raise ApiError(409, CODE_TEAM_PCT_LOW, "团队比例低于 min_team_pct，拦截")
    rule = TDistributionRule.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        rule_name=b["rule_name"], applies_to=b["applies_to"],
        team_pct=_dec(team), institute_pct=_dec(inst), individual_pct=_dec(ind),
        min_team_pct=_dec(b["min_team_pct"]),
        policy_ref=b.get("policy_ref"), policy_pack_id=b.get("policy_pack_id"),
        effective_from=_parse_date(b["effective_from"]),
        effective_to=_parse_date(b.get("effective_to")),
        active=bool(b.get("active", True)),
    )
    return ok(request, to_api_rule(rule))


def _hit_rule(deal: TDeal, on_date) -> TDistributionRule | None:
    applies = APPLY_TO_MAP.get(deal.deal_type)
    if applies is None:
        return None
    rules = TDistributionRule.objects.filter(
        tenant_id=deal.tenant_id, applies_to=applies, active=True, deleted=0,
        effective_from__lte=on_date,
    ).order_by("-effective_from")
    for r in rules:
        if r.effective_to is None or on_date <= r.effective_to:
            return r
    return None


@transaction.atomic
def generate_distribution(request: HttpRequest, id: int):
    dom = domain_from(request)
    inc = _get_income_or_404(id)
    if TDistributionRecord.objects.filter(income=inc, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "一期到账一分配明细")
    deal = inc.deal
    b = read_json_soft(request)
    rule = None
    if b.get("rule_id"):
        rule = TDistributionRule.objects.filter(id=int(b["rule_id"]), deleted=0).first()
        if rule is None:
            raise ApiError(404, CODE_NOT_FOUND, "分配规则不存在")
    else:
        rule = _hit_rule(deal, inc.received_date)
    if rule is None:
        raise ApiError(409, CODE_CONFLICT, "无生效分配规则")
    total = float(inc.amount or 0)
    breakdown_in = b.get("breakdown") or []
    if breakdown_in:
        bp_sum = sum(float(i.get("pct", 0)) for i in breakdown_in)
        if abs(bp_sum - 1) > 1e-4:
            raise ApiError(400, CODE_DIST_PCT_SUM, "breakdown 比例之和≠1")
        breakdown = [{"user_id": int(i["user_id"]), "pct": float(i["pct"]),
                      "amount": round(total * float(i["pct"]), 2), "basis": i.get("basis")} for i in breakdown_in]
    else:
        breakdown = []
    rec = TDistributionRecord.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, income=inc, deal=deal, rule=rule,
        status="GENERATED",
        total_amount=_dec(total),
        team_amount=_dec(round(total * float(rule.team_pct), 2)),
        institute_amount=_dec(round(total * float(rule.institute_pct), 2)),
        individual_amount=_dec(round(total * float(rule.individual_pct), 2)),
        breakdown=breakdown, policy_pack_id=rule.policy_pack_id,
    )
    inc.allocated = True
    inc.status = "ALLOCATED"
    inc.save(update_fields=["allocated", "status", "updated_at"])
    if deal.status in ("EXECUTING", "INCOME_RECEIVED"):
        deal.status = "DISTRIBUTED"
        deal.save(update_fields=["status", "updated_at"])
    return ok(request, to_api_dist_record(rec))


@transaction.atomic
def issue_distribution(request: HttpRequest, id: int):
    dom = domain_from(request)
    rec = TDistributionRecord.objects.filter(id=id, deleted=0).first()
    if rec is None:
        raise ApiError(404, CODE_NOT_FOUND, "分配明细不存在")
    b = read_json(request)
    action = b.get("action") or "ISSUE"
    if action not in ("ISSUE", "HOLD", "RESUME"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 必须为 ISSUE/HOLD/RESUME")
    if action == "HOLD":
        reason = b.get("held_reason") or "OTHER"
        rec.held_reason = reason
        rec.dispute_note = b.get("note")
        rec.status = "DISPUTED" if reason == "DISPUTE" else "HELD"
        rec.save()
        return ok(request, to_api_dist_record(rec))
    if action == "RESUME":
        if rec.status not in ("DISPUTED", "HELD"):
            raise ApiError(409, CODE_CONFLICT, f"恢复发放状态机冲突：当前 {rec.status}")
        rec.status = "PUBLISHED"
        rec.save()
        return ok(request, to_api_dist_record(rec))
    # ISSUE：DISPUTED/HELD 需带仲裁结论或说明
    if rec.status in ("DISPUTED", "HELD") and not b.get("note"):
        raise ApiError(400, CODE_BAD_REQUEST, "争议/暂缓发放需携仲裁结论 note")
    if rec.status not in ("GENERATED", "PUBLISHED", "CONFIRMED", "DISPUTED", "HELD"):
        raise ApiError(409, CODE_CONFLICT, f"发放状态机冲突：当前 {rec.status}")
    rec.status = "ISSUED"
    rec.issued_at = _now()
    rec.save()
    return ok(request, to_api_dist_record(rec))


def list_my_distribution(request: HttpRequest):
    """员工仅见 breakdown 中与自己相关条目（detail §7）。"""
    page, size, limit, offset = page_args(request)
    uid = domain_from(request).user_id
    rows = [r for r in TDistributionRecord.objects.filter(
        tenant_id=domain_from(request).tenant_id, deleted=0).order_by("-id")
        if any(int(i.get("user_id", -1)) == uid for i in (r.breakdown or []))]
    out = []
    for r in rows[offset:offset + limit]:
        data = to_api_dist_record(r)
        data["breakdown"] = [i for i in (r.breakdown or []) if int(i.get("user_id", -1)) == uid]
        out.append(data)
    return ok(request, {"list": out, "total": len(rows), "page": page, "size": size})


# ---------------------------------------------------------------------------
# 年度报告 T-15
# ---------------------------------------------------------------------------


@transaction.atomic
def generate_annual_report(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("report_year"):
        raise ApiError(400, CODE_BAD_REQUEST, "report_year 必填")
    year = int(b["report_year"])
    le_id = b.get("legal_entity_id") or dom.legal_entity_id or 1
    deals = TDeal.objects.filter(tenant_id=dom.tenant_id, deleted=0,
                                 signed_at__year=year, legal_entity_id=le_id)
    top = list(deals.order_by("-contract_amount")[:5])
    incomes = TIncome.objects.filter(tenant_id=dom.tenant_id, deleted=0,
                                     received_date__year=year, deal__legal_entity_id=le_id)
    issued = TDistributionRecord.objects.filter(tenant_id=dom.tenant_id, deleted=0,
                                                issued_at__year=year)
    team = issued.aggregate(s=Sum("team_amount"))["s"] or 0
    inst = issued.aggregate(s=Sum("institute_amount"))["s"] or 0
    ind = issued.aggregate(s=Sum("individual_amount"))["s"] or 0
    report, _ = TAnnualReport.objects.update_or_create(
        tenant_id=dom.tenant_id, report_year=year, legal_entity_id=le_id, deleted=0,
        defaults={
            "creator_id": dom.user_id,
            "total_deals": deals.count(),
            "total_contract_amount": deals.aggregate(s=Sum("contract_amount"))["s"] or 0,
            "total_income": incomes.aggregate(s=Sum("amount"))["s"] or 0,
            "total_distributed": team + inst + ind,
            "top_deals": [{"deal_id": d.id, "code": d.code, "amount": num_float(d.contract_amount),
                           "type": d.deal_type} for d in top],
            "distribution_summary": {"team": num2(team), "institute": num2(inst), "individual": num2(ind)},
            "report_file_url": f"/reports/transform/{year}-{le_id}.{(b.get('format') or 'PDF').lower()}",
            "generated_at": _now(),
            "status": "GENERATED",
            "modifier_id": dom.user_id,
        },
    )
    return ok(request, to_api_annual(report))


# ---------------------------------------------------------------------------
# AI 三端点 T-17/T-18/T-19（确定性降级；LLM 可用时增强）
# ---------------------------------------------------------------------------


def ai_opportunity(request: HttpRequest):
    """T-17：企业技术需求 × 评估分匹配（向量/GNN 由 svc-ai 增强，此处确定性排序）。"""
    b = read_json(request)
    top_n = int(b.get("top_n") or 10)
    industry = b.get("filter_industry")
    qs = TEnterpartner.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0,
                                      status__in=["ACTIVE", "PENDING"])
    if industry:
        qs = qs.filter(industry=industry)
    rows = sorted(qs, key=lambda r: float(r.evaluation_score or 0), reverse=True)[:top_n]
    out = []
    for r in rows:
        out.append({
            "enterpartner_id": r.id,
            "company_name": r.company_name,
            "match_score": num_float(r.evaluation_score) or 0.0,
            "confidence": 0.5,
            "reason": "企业技术需求与成果标签匹配（确定性排序，LLM 增强未启用）",
            "suggestion": "建议先接触企业技术需求对接人",
        })
    return ok(request, {"list": out})


@transaction.atomic
def ai_contract_risk(request: HttpRequest, id: int):
    """T-18：已审查结果直接回放；未审查且 LLM 未配置 → 空清单降级（不阻塞业务）。"""
    c = TContract.objects.filter(id=id, deleted=0).first()
    if c is None:
        raise ApiError(404, CODE_NOT_FOUND, "合同不存在")
    if c.ai_risk_report is not None:
        return ok(request, {"list": c.ai_risk_report})
    try:
        from core.llm import chat_json
        result = chat_json(
            system="你是合同风险审查助手，逐条输出 {clause,severity,issue,suggestion,ref_article,confidence}。",
            user=json.dumps({
                "contract_no": c.contract_no, "template": c.template_code,
                "deal_type": c.deal.deal_type, "amount": num_float(c.deal.contract_amount),
            }, ensure_ascii=False),
        )
        items = result if isinstance(result, list) else result.get("list", [])
    except Exception:
        items = []
    c.ai_risk_report = items
    c.save(update_fields=["ai_risk_report", "updated_at"])
    return ok(request, {"list": items})


def ai_pricing(request: HttpRequest, id: int):
    """T-19：可比交易库分位数定价区间（确定性），仅供参考。"""
    deal = _get_deal_or_404(id)
    comps = list(TDeal.objects.filter(
        tenant_id=deal.tenant_id, deleted=0, deal_type=deal.deal_type,
        status__in=["SIGNED", "EXECUTING", "INCOME_RECEIVED", "DISTRIBUTED", "CLOSED"],
    ).exclude(id=deal.id).order_by("contract_amount"))
    amounts = sorted(float(d.contract_amount or 0) for d in comps)
    if amounts:
        low = amounts[max(0, len(amounts) // 4)]
        high = amounts[min(len(amounts) - 1, 3 * len(amounts) // 4)]
        confidence = min(0.9, 0.4 + 0.1 * len(amounts))
    else:
        low, high, confidence = 0.0, 0.0, 0.0
    return ok(request, {
        "price_low": round(low, 2),
        "price_high": round(high, 2),
        "currency": "CNY",
        "confidence": confidence,
        "basis": f"同类型（{deal.deal_type}）已成交交易 {len(amounts)} 笔分位数区间（确定性计算）",
        "comparables": [{"deal_code": d.code, "amount": num_float(d.contract_amount),
                         "year": d.signed_at.year if d.signed_at else d.created_at.year} for d in comps[:5]],
        "disclaimer": "最终定价以评估机构报告与谈判为准",
    })
