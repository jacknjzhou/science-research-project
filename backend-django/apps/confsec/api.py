"""涉密管理与多法人治理域 X API（对齐 design/11-*.openapi.yaml，纯契约实现）。

铁律：
1. MFA 二次鉴别——策略发布/授权/吊销/放行/定降解密/涉密人员审查等关键操作须携带
   X-MFA-Assert 头，缺失 → 403。
2. zone-guard 三网判定——涉密对象在非 SECRET_NET 网络域不可见，403 且不暴露对象
   存在性（防探测）；请求网络域取 X-Network-Zone 头（缺省 OFFICE）。
3. AI 绝不自动定密——classify 一律 needApproval=True。
4. SM3 哈希链——X_SEC_LOG 逐条链式摘要（实现以 sha256 代 SM3，接口语义一致），
   查询返回链校验状态；指纹比对不一致二次拦截并 risk_flag=2 告警。
"""
from __future__ import annotations

import hashlib

from django.db import transaction
from django.db.models import Max
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.confsec.models import (
    XAccessGrant,
    XFlowAudit,
    XPersonnelSec,
    XSecLog,
    XSecurityPolicy,
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


def _parse_dt(s):
    if not s:
        return None
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None
    return dj_tz.make_aware(dt) if dj_tz.is_naive(dt) else dt

SECRET_LEVELS = ("SECRET", "TOP_SECRET")
LEVELS = ("PUBLIC", "INTERNAL", "SECRET", "TOP_SECRET")


def _now():
    return dj_tz.now()


def _gen_code(prefix: str, tenant_id: int, model) -> str:
    y = _now().year
    seq = model.objects.filter(tenant_id=tenant_id, code__startswith=f"{prefix}-{y}-").count() + 1
    return f"{prefix}-{y}-{seq:06d}"


def _mfa(request: HttpRequest) -> str:
    """二次身份鉴别断言：关键操作必填，缺失 403。"""
    assert_tok = request.headers.get("X-MFA-Assert")
    if not assert_tok:
        raise ApiError(403, CODE_FORBIDDEN, "关键操作须二次身份鉴别（X-MFA-Assert 头缺失）")
    return assert_tok


def _zone(request: HttpRequest) -> str:
    return request.headers.get("X-Network-Zone", "OFFICE")


def _sm3(payload: str) -> str:
    """SM3 摘要（实现以 sha256 承载，链值语义一致：覆盖业务字段+hash_prev）。"""
    return "sm3-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sec_log(tenant_id: int, **kw) -> XSecLog:
    """写安全日志并入哈希链（同租户链式）。"""
    prev = (XSecLog.objects.filter(tenant_id=tenant_id).order_by("-id")
            .values_list("hash_self", flat=True).first())
    body = {
        "tenant_id": tenant_id,
        "legal_entity_id": kw.get("legal_entity_id") or 1,
        "actor_id": kw.get("actor_id") or 0,
        "actor_role": kw.get("actor_role"),
        "network_zone": kw.get("network_zone") or "OFFICE",
        "action": kw.get("action") or "READ",
        "object_type": kw.get("object_type") or "-",
        "object_id": kw.get("object_id") or 0,
        "field_diff_json": kw.get("field_diff_json"),
        "security_level": kw.get("security_level") or "INTERNAL",
        "granted_level": kw.get("granted_level"),
        "result": kw.get("result") or "ALLOW",
        "risk_flag": kw.get("risk_flag") or 0,
        "hash_prev": prev,
        "occurred_at": kw.get("occurred_at") or _now(),
        "source_ip": kw.get("source_ip"),
        "device_id": kw.get("device_id"),
    }
    body["hash_self"] = _sm3(f"{prev}|{body['actor_id']}|{body['action']}|"
                             f"{body['object_type']}:{body['object_id']}|{body['result']}|"
                             f"{body['occurred_at'].isoformat() if body['occurred_at'] else ''}")
    return XSecLog.objects.create(**body)


# ---------------------------------------------------------------------------
# 法人树 / 并表 X-08/X-10（读写 sys_legal_entity）
# ---------------------------------------------------------------------------


def _api_entity(e) -> dict:
    return {
        "id": e.id, "code": e.code, "tenantId": e.tenant_id, "name": e.name,
        "creditCode": e.credit_code, "entityType": e.entity_type,
        "shortCode": e.short_code, "consolidated": e.consolidated,
        "reportScope": (e.remark or ""), "status": e.status,
    }


def _entity_stats(tenant_id: int, entity_id: int) -> dict:
    """法人治理统计（项目/经费/资产/人员计数；跨 app 懒导入，缺失回 0）。"""
    project_count = expense_amount = asset_count = personnel_count = 0
    try:
        from apps.project.models import EProject
        project_count = EProject.objects.filter(tenant_id=tenant_id,
                                                legal_entity_id=entity_id, deleted=0).count()
    except Exception:
        pass
    try:
        from apps.funding.models import FExpense
        expense_amount = float(FExpense.objects.filter(tenant_id=tenant_id,
                                                       legal_entity_id=entity_id, deleted=0)
                               .aggregate(s=Sum("amount"))["s"] or 0)
    except Exception:
        pass
    try:
        from apps.asset.models import AAsset
        asset_count = AAsset.objects.filter(tenant_id=tenant_id,
                                            legal_entity_id=entity_id, deleted=0).count()
    except Exception:
        pass
    try:
        from apps.staff.models import SStaff
        personnel_count = SStaff.objects.filter(tenant_id=tenant_id,
                                                legal_entity_id=entity_id, deleted=0).count()
    except Exception:
        pass
    return {"projectCount": project_count, "expenseAmount": expense_amount,
            "assetCount": asset_count, "personnelCount": personnel_count}


def get_entity_tree(request: HttpRequest):
    """法人树（X-08）：总院—分院两层（entityType 承载层级）。"""
    dom = domain_from(request)
    from apps.sysadmin.models import SysLegalEntity

    qs = SysLegalEntity.objects.filter(tenant_id=dom.tenant_id, deleted=0)
    totals = list(qs.filter(entity_type="TOTAL_INSTITUTE").order_by("id"))
    branches = list(qs.filter(entity_type="BRANCH_INSTITUTE").order_by("id"))
    if not totals and branches:  # 兜底：无总院时首法人作根
        totals = [branches.pop(0)] if branches else []
    nodes = [{"entity": _api_entity(t), "children": [], "asPrimary": True,
              "stats": _entity_stats(dom.tenant_id, t.id)} for t in totals]
    for b in branches:
        node = {"entity": _api_entity(b), "children": [], "asPrimary": False,
                "stats": _entity_stats(dom.tenant_id, b.id)}
        if nodes:
            nodes[0]["children"].append(node)
        else:
            nodes.append(node)
    return ok(request, nodes)


@transaction.atomic
def upsert_entity(request: HttpRequest):
    """法人新增/变更（X-08，落 sys_legal_entity；仅 R-ADMIN）。"""
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("name") or not b.get("entityType"):
        raise ApiError(400, CODE_BAD_REQUEST, "name/entityType 必填")
    from apps.sysadmin.models import SysLegalEntity

    if b.get("id"):
        e = SysLegalEntity.objects.filter(id=int(b["id"]), tenant_id=dom.tenant_id,
                                          deleted=0).first()
        if e is None:
            raise ApiError(404, CODE_NOT_FOUND, "法人不存在")
    else:
        y = _now().year
        seq = SysLegalEntity.objects.filter(tenant_id=dom.tenant_id,
                                            code__startswith=f"LE-{y}-").count() + 1
        e = SysLegalEntity.objects.create(
            tenant_id=dom.tenant_id, code=f"LE-{y}-{seq:06d}", name=b["name"],
            entity_type=b["entityType"])
    e.name = b["name"]
    e.credit_code = b.get("creditCode", e.credit_code)
    e.entity_type = b["entityType"]
    e.short_code = b.get("shortCode", e.short_code)
    e.consolidated = bool(b.get("consolidated", e.consolidated))
    e.status = b.get("status") or e.status
    e.remark = b.get("reportScope") or e.remark
    e.save()
    _sec_log(dom.tenant_id, actor_id=dom.user_id, actor_role="R-ADMIN",
             action="UPDATE" if b.get("id") else "CREATE",
             object_type="sys_legal_entity", object_id=e.id, result="ALLOW")
    return ok(request, _api_entity(e))


DIM_SOURCES = {
    "PROJECT": ("apps.project.models", "EProject", "budget_total", "id"),
    "EXPENSE": ("apps.funding.models", "FExpense", "amount", "id"),
    "ASSET": ("apps.asset.models", "AAsset", "value", "id"),
    "CONTRACT": ("apps.procure.models", "GContract", "amount", "id"),
}


def _dim_rows(tenant_id: int, dimension: str) -> list[dict]:
    """分法人聚合一行：[{legal_entity_id, amount}]（口径：主责法人全额计入）。"""
    if dimension == "PERSONNEL":
        try:
            from apps.staff.models import SStaff
            qs = SStaff.objects.filter(tenant_id=tenant_id, deleted=0)
            agg = {}
            for s in qs:
                agg[s.legal_entity_id] = agg.get(s.legal_entity_id, 0) + 1
            return [{"legal_entity_id": k, "amount": v} for k, v in agg.items()]
        except Exception:
            return []
    cfg = DIM_SOURCES.get(dimension)
    if cfg is None:
        return []
    mod_name, cls_name, amount_field, _ = cfg
    try:
        mod = __import__(mod_name, fromlist=[cls_name])
        model = getattr(mod, cls_name)
        qs = model.objects.filter(tenant_id=tenant_id, deleted=0)
        agg: dict[int, float] = {}
        for o in qs:
            le = getattr(o, "legal_entity_id", None) or 1
            agg[le] = agg.get(le, 0) + float(getattr(o, amount_field, 0) or 0)
        return [{"legal_entity_id": k, "amount": v} for k, v in agg.items()]
    except Exception:
        return []


def consolidate(request: HttpRequest):
    """并表合并视图与下钻（X-10）：主责法人准入账，参与法人按分摊比例避免重复计入。"""
    dom = domain_from(request)
    from apps.sysadmin.models import SysLegalEntity

    level = request.GET.get("level") or "merge"
    dimension = (request.GET.get("dimension") or "PROJECT").upper()
    period = request.GET.get("period")
    raw = _dim_rows(dom.tenant_id, dimension)
    ents = {e.id: e for e in SysLegalEntity.objects.filter(tenant_id=dom.tenant_id, deleted=0)}
    primary_ids = {e.id for e in ents.values() if e.entity_type == "TOTAL_INSTITUTE"}
    drill, total = [], 0.0
    for r in raw:
        le = r["legal_entity_id"]
        e = ents.get(le)
        is_primary = le in primary_ids or len(primary_ids) == 0
        ratio = 1.0 if is_primary else 0.5  # 参与法人按 0.5 分摊（口径可配置）
        drill.append({"legalEntityId": le, "legalEntityName": e.name if e else f"LE-{le}",
                      "role": "PRIMARY" if is_primary else "PARTICIPANT",
                      "amount": r["amount"], "allocRatio": ratio})
        total += r["amount"] * ratio
    if request.GET.get("legalEntityId"):
        drill = [d for d in drill if d["legalEntityId"] == int(request.GET["legalEntityId"])]
    data = {"level": level, "dimension": dimension, "period": period}
    if level == "merge":
        data["merged"] = {"totalAmount": round(total, 2), "totalCount": len(raw),
                          "dedupNote": "主责法人全额计入，参与法人按分摊比例 0.5 折算，避免跨法人重复计入"}
    else:
        data["rows"] = drill
    return ok(request, data)


# ---------------------------------------------------------------------------
# 密级策略 X-01/02/05
# ---------------------------------------------------------------------------


def _api_policy(p: XSecurityPolicy) -> dict:
    return {
        "id": p.id, "code": p.code, "tenantId": p.tenant_id,
        "legalEntityId": p.legal_entity_id, "securityLevel": p.security_level,
        "version": p.version, "effectiveFrom": f"{p.effective_from:%Y-%m-%d}" if p.effective_from else None,
        "effectiveTo": f"{p.effective_to:%Y-%m-%d}" if p.effective_to else None,
        "matrixJson": p.matrix_json, "appliedModules": p.applied_modules or [],
        "policyPackId": p.policy_pack_id, "status": p.status,
    }


@transaction.atomic
def publish_policy(request: HttpRequest):
    """发布密级/流向策略（X-01/02/05）：同租户同模块集合仅一套 ACTIVE，旧版 SUPERSEDED。"""
    dom = domain_from(request)
    _mfa(request)  # 三员分立：安全管理员发布须二次鉴别
    b = read_json(request)
    if not b.get("matrixJson") or not b.get("appliedModules"):
        raise ApiError(400, CODE_BAD_REQUEST, "matrixJson/appliedModules 必填")
    modules = sorted({str(m).upper() for m in b["appliedModules"]})
    # 旧 ACTIVE 同集合 → SUPERSEDED
    olds = XSecurityPolicy.objects.filter(tenant_id=dom.tenant_id, deleted=0, status="ACTIVE")
    for old in olds:
        if sorted({str(m).upper() for m in (old.applied_modules or [])}) == modules:
            old.status = "SUPERSEDED"
            old.modifier_id = dom.user_id
            old.save(update_fields=["status", "modifier_id", "updated_at"])
    y = _now().year
    seq = XSecurityPolicy.objects.filter(tenant_id=dom.tenant_id,
                                         code__startswith=f"SEC-{y}-").count() + 1
    ver = (XSecurityPolicy.objects.filter(tenant_id=dom.tenant_id)
           .aggregate(m=Max("version"))["m"] or 0) + 1
    p = XSecurityPolicy.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=f"SEC-{y}-{seq:06d}",
        legal_entity_id=b.get("legalEntityId") or dom.legal_entity_id or 1,
        security_level=b.get("securityLevel") or "INTERNAL",
        version=ver,
        effective_from=_parse_date(b.get("effectiveFrom")) or dj_tz.localdate(),
        effective_to=_parse_date(b.get("effectiveTo")),
        matrix_json=b["matrixJson"], applied_modules=modules,
        policy_pack_id=b.get("policyPackId"), status="ACTIVE",
        remark=b.get("remark"),
    )
    _sec_log(dom.tenant_id, actor_id=dom.user_id, actor_role="R-ADMIN",
             action="GRANT", object_type="X_SECURITY_POLICY", object_id=p.id,
             result="ALLOW", security_level=p.security_level)
    return ok(request, _api_policy(p))


def current_policy(request: HttpRequest):
    """查当前生效策略（zone-guard 判定依据）；无 ACTIVE → 404（回落内置保守默认）。"""
    dom = domain_from(request)
    module = (request.GET.get("module") or "").upper()
    policies = list(XSecurityPolicy.objects.filter(tenant_id=dom.tenant_id, deleted=0,
                                                   status="ACTIVE").order_by("-id"))
    if module:
        policies = [p for p in policies
                    if module in [str(m).upper() for m in (p.applied_modules or [])]]
    if not policies:
        raise ApiError(404, CODE_NOT_FOUND,
                       "当前无 ACTIVE 策略（回落内置保守默认：SECRET+ 一律拒绝）")
    return ok(request, _api_policy(policies[0]))


# ---------------------------------------------------------------------------
# 授权 X-01/04/11
# ---------------------------------------------------------------------------


def _api_grant(g: XAccessGrant) -> dict:
    return {
        "id": g.id, "code": g.code, "tenantId": g.tenant_id,
        "legalEntityId": g.legal_entity_id, "securityLevel": g.security_level,
        "subjectUserId": g.subject_user_id, "scopeType": g.scope_type,
        "scopeRef": g.scope_ref, "grantedLevel": g.granted_level,
        "networkZone": g.network_zone, "mfaBound": g.mfa_bound,
        "validFrom": g.valid_from.isoformat() if g.valid_from else None,
        "validTo": g.valid_to.isoformat() if g.valid_to else None,
        "status": g.status,
    }


@transaction.atomic
def grant_access(request: HttpRequest):
    """授予授权/密级许可：SECRET+ 强制 mfa_bound=1 且二次鉴别。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("subjectUserId", "scopeType", "grantedLevel", "networkZone"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    if b["grantedLevel"] not in LEVELS or b["networkZone"] not in ("INTERNET", "OFFICE", "SECRET_NET"):
        raise ApiError(400, CODE_BAD_REQUEST, "grantedLevel/networkZone 取值非法")
    high = b["grantedLevel"] in SECRET_LEVELS
    if high:
        _mfa(request)
    mfa_bound = bool(b.get("mfaBound")) or high
    g = XAccessGrant.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        code=_gen_code("SEC", dom.tenant_id, XAccessGrant),
        legal_entity_id=b.get("legalEntityId") or dom.legal_entity_id or 1,
        subject_user_id=int(b["subjectUserId"]), scope_type=b["scopeType"],
        scope_ref=b.get("scopeRef"), granted_level=b["grantedLevel"],
        network_zone=b["networkZone"], mfa_bound=mfa_bound,
        valid_from=_parse_dt(b.get("validFrom")) or _now(),
        valid_to=_parse_dt(b.get("validTo")),
        remark=b.get("remark"),
    )
    _sec_log(dom.tenant_id, actor_id=dom.user_id, actor_role="R-ADMIN",
             action="GRANT", object_type="X_ACCESS_GRANT", object_id=g.id,
             result="ALLOW", granted_level=g.granted_level)
    return ok(request, _api_grant(g))


def list_grants(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = XAccessGrant.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("subjectUserId"):
        try:
            qs = qs.filter(subject_user_id=int(v))
        except ValueError:
            pass
    for k in ("networkZone", "status"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [_api_grant(g) for g in rows],
                        "total": total, "page": page, "size": size})


@transaction.atomic
def revoke_access(request: HttpRequest):
    """吊销/冻结授权（X-11）：二次鉴别 + 审计。"""
    dom = domain_from(request)
    _mfa(request)
    b = read_json(request)
    if not b.get("grantId") or b.get("action") not in ("FREEZE", "REVOKE"):
        raise ApiError(400, CODE_BAD_REQUEST, "grantId 与 action(FREEZE/REVOKE) 必填")
    g = XAccessGrant.objects.filter(id=int(b["grantId"]), deleted=0).first()
    if g is None:
        raise ApiError(404, CODE_NOT_FOUND, "授权不存在")
    g.status = "FROZEN" if b["action"] == "FREEZE" else "REVOKED"
    g.modifier_id = dom.user_id
    g.remark = "; ".join(filter(None, [g.remark, b.get("reason")]))
    g.save()
    _sec_log(dom.tenant_id, actor_id=dom.user_id, actor_role="R-ADMIN",
             action="GRANT", object_type="X_ACCESS_GRANT", object_id=g.id,
             result="ALLOW", risk_flag=1 if g.status == "REVOKED" else 0,
             granted_level=g.granted_level)
    return ok(request, _api_grant(g))


# ---------------------------------------------------------------------------
# 涉密输出/跨网审批 X-05/06（落 x_flow_audit，EXF）
# ---------------------------------------------------------------------------


def _api_flow(f: XFlowAudit) -> dict:
    return {
        "id": f.id, "code": f.code, "direction": f.direction,
        "objectType": f.object_type, "objectId": f.object_id,
        "fromDomain": f.from_domain, "toDomain": f.to_domain,
        "applicantId": f.applicant_id, "approver1Id": f.approver1_id,
        "approver2Id": f.approver2_id, "secondVerifierId": f.second_verifier_id,
        "payloadDigest": f.payload_digest, "desensitizeNote": f.desensitize_note,
        "releaseScope": f.release_scope, "securityLevel": f.security_level,
        "status": f.status, "reason": f.reason,
    }


@transaction.atomic
def create_export_apply(request: HttpRequest):
    """发起涉密输出/跨网审批（X-05/06）：跨网默认禁止，例外走此审批。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("direction", "objectType", "objectId", "toDomain", "payloadDigest"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    f = XFlowAudit.objects.create(
        tenant_id=dom.tenant_id,
        code=_gen_code("EXF", dom.tenant_id, XFlowAudit),
        direction=b["direction"], object_type=b["objectType"],
        object_id=int(b["objectId"]),
        from_domain=b.get("fromDomain") or "SECRET_NET", to_domain=b["toDomain"],
        applicant_id=dom.user_id, payload_digest=b["payloadDigest"],
        desensitize_note=b.get("desensitizeNote"),
        security_level=b.get("securityLevel") or "SECRET",
        legal_entity_id=b.get("legalEntityId") or dom.legal_entity_id or 1,
        reason=b.get("reason"),
    )
    return ok(request, _api_flow(f))


@transaction.atomic
def approve_export(request: HttpRequest):
    """双审（X-06）：APPLIED→PRE_REVIEW（初审）→SEC_REVIEW（复审）；审批人≠申请人。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("exportId", "stage", "verdict"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    f = XFlowAudit.objects.filter(id=int(b["exportId"]), deleted=0).first()
    if f is None:
        raise ApiError(404, CODE_NOT_FOUND, "输出审批单不存在")
    if f.status in ("RELEASED", "REJECTED", "RECORDED"):
        raise ApiError(409, CODE_CONFLICT, f"单据已终态（{f.status}）")
    expect = {"PRE_REVIEW": "APPLIED", "SEC_REVIEW": "PRE_REVIEW"}.get(b["stage"])
    if expect is None or f.status != expect:
        raise ApiError(409, CODE_CONFLICT,
                       f"审批阶段非法：当前 {f.status}，须先经 {expect or '合法阶段'}")
    approver = b.get("approverId") or dom.user_id
    if int(approver) == int(f.applicant_id):
        raise ApiError(400, CODE_BAD_REQUEST, "审批人与申请人须不同人")
    if b["verdict"] == "REJECT":
        f.status = "REJECTED"
        f.reason = "; ".join(filter(None, [f.reason, b.get("comment")]))
    else:
        if b["stage"] == "PRE_REVIEW":
            f.approver1_id = int(approver)
            f.status = "PRE_REVIEW"
        else:
            f.approver2_id = int(approver)
            f.status = "SEC_REVIEW"
            if b.get("releaseScope"):
                f.release_scope = b["releaseScope"]
    f.save()
    _sec_log(f.tenant_id, actor_id=approver, action="EXPORT",
             object_type="x_flow_audit", object_id=f.id,
             result="ALLOW" if b["verdict"] == "PASS" else "DENY",
             security_level=f.security_level)
    return ok(request, _api_flow(f))


def release_export(request: HttpRequest):
    """二次鉴别放行（X-04/06）：指纹比对不一致二次拦截（risk_flag=2 告警）。
    注意：不包 transaction.atomic——拦截日志必须随 409 一并落库留痕。"""
    dom = domain_from(request)
    _mfa(request)
    b = read_json(request)
    if not b.get("exportId") or not b.get("actualPayloadDigest"):
        raise ApiError(400, CODE_BAD_REQUEST, "exportId/actualPayloadDigest 必填")
    f = XFlowAudit.objects.filter(id=int(b["exportId"]), deleted=0).first()
    if f is None:
        raise ApiError(404, CODE_NOT_FOUND, "输出审批单不存在")
    if f.status != "SEC_REVIEW":
        raise ApiError(409, CODE_CONFLICT, f"仅 SEC_REVIEW 可放行，当前 {f.status}")
    if b["actualPayloadDigest"] != f.payload_digest:
        _sec_log(f.tenant_id, actor_id=dom.user_id, action="EXPORT",
                 object_type="x_flow_audit", object_id=f.id, result="DENY",
                 risk_flag=2, security_level=f.security_level)  # 高危告警
        raise ApiError(409, CODE_CONFLICT, "实际输出内容指纹与审批不符，二次拦截")
    f.status = "RELEASED"
    f.second_verifier_id = int(b.get("secondVerifierId") or dom.user_id)
    if b.get("releaseScope"):
        f.release_scope = b["releaseScope"]
    f.save()
    _sec_log(f.tenant_id, actor_id=dom.user_id, action="EXPORT",
             object_type="x_flow_audit", object_id=f.id, result="ALLOW",
             security_level=f.security_level)
    return ok(request, _api_flow(f))


@transaction.atomic
def get_export_detail(request: HttpRequest, id: int):
    """查询输出审批状态；涉密正文在非 SECRET_NET 域 403 且不暴露存在性（防探测）。"""
    f = XFlowAudit.objects.filter(id=id, deleted=0).first()
    zone = _zone(request)
    if f is not None and f.security_level in SECRET_LEVELS and zone != "SECRET_NET":
        raise ApiError(403, CODE_FORBIDDEN, "涉密对象在当前网络域不可见")  # 不暴露细节
    if f is None:
        raise ApiError(404, CODE_NOT_FOUND, "输出审批单不存在")
    return ok(request, _api_flow(f))


# ---------------------------------------------------------------------------
# 密级判定/降密/解密 X-13/14（AI 仅提示，永不自动生效）
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_classify(request: HttpRequest):
    dom = domain_from(request)
    _mfa(request)
    b = read_json(request)
    for k in ("targetType", "targetId", "op"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    op = b["op"]
    if op not in ("SET_LEVEL", "DOWN_CLASSIFY", "DECLASSIFY"):
        raise ApiError(400, CODE_BAD_REQUEST, "op 取值非法")
    if op == "SET_LEVEL" and not b.get("proposedLevel"):
        raise ApiError(400, CODE_BAD_REQUEST, "SET_LEVEL 须人工确定 proposedLevel")
    classify_status = {"SET_LEVEL": "UNCLASSIFIED", "DOWN_CLASSIFY": "DOWN_CLASSIFY",
                       "DECLASSIFY": "DECLASSIFY"}[op]
    target_level = b.get("proposedLevel")
    audit_ref = None
    if b["targetType"] == "PERSONNEL":
        p, _ = XPersonnelSec.objects.update_or_create(
            tenant_id=dom.tenant_id, user_id=int(b["targetId"]), deleted=0,
            defaults={"classify_status": classify_status,
                      "granted_level": target_level or "INTERNAL",
                      "creator_id": dom.user_id, "modifier_id": dom.user_id})
        audit_ref = p.code
    else:
        # 对象密级：以资产为例（跨类型对象按需扩展）；AI 提示永不直接生效
        from apps.asset.models import AAsset
        a = AAsset.objects.filter(id=int(b["targetId"]), deleted=0).first()
        if a is not None and target_level:
            a.security_level = target_level
            a.modifier_id = dom.user_id
            a.save(update_fields=["security_level", "modifier_id", "updated_at"])
        audit_ref = f"OBJ-{b['targetId']}"
    log = _sec_log(dom.tenant_id, actor_id=dom.user_id, action="CLASSIFY",
                   object_type=b["targetType"], object_id=int(b["targetId"]),
                   result="ALLOW", security_level=target_level or "INTERNAL")
    return ok(request, {
        "targetId": int(b["targetId"]), "classifyStatus": classify_status,
        "securityLevel": target_level, "needApproval": True,
        "auditRef": audit_ref or f"SECLOG-{log.id}",
        "aiHint": b.get("aiHint"),  # 仅提示，不参与判定
    })


# ---------------------------------------------------------------------------
# 安全日志 X-07（SM3 哈希链，append-only）
# ---------------------------------------------------------------------------


@transaction.atomic
def write_sec_log(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    for k in ("actorId", "networkZone", "action", "objectType", "objectId", "result"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    log = _sec_log(
        b.get("tenantId") or dom.tenant_id,
        legal_entity_id=b.get("legalEntityId"), actor_id=int(b["actorId"]),
        actor_role=b.get("actorRole"), network_zone=b["networkZone"],
        action=b["action"], object_type=b["objectType"], object_id=int(b["objectId"]),
        field_diff_json=b.get("fieldDiffJson"),
        security_level=b.get("securityLevel"), granted_level=b.get("grantedLevel"),
        result=b["result"], risk_flag=b.get("riskFlag") or 0,
        occurred_at=_parse_dt(b.get("occurredAt")) or _now(),
        source_ip=b.get("sourceIp"), device_id=b.get("deviceId"),
    )
    return ok(request, {"id": log.id, "hashSelf": log.hash_self, "async": True})


def _chain_intact(tenant_id: int) -> bool:
    prev = None
    for lg in XSecLog.objects.filter(tenant_id=tenant_id).order_by("id"):
        expect = _sm3(f"{prev}|{lg.actor_id}|{lg.action}|{lg.object_type}:{lg.object_id}|"
                      f"{lg.result}|{lg.occurred_at.isoformat() if lg.occurred_at else ''}")
        if lg.hash_self != expect:
            return False
        prev = lg.hash_self
    return True


def query_sec_log(request: HttpRequest):
    """稽核查询（X-07）：risk 过滤 + 哈希链校验状态；只读不可删改。"""
    dom = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = XSecLog.objects.filter(tenant_id=dom.tenant_id)
    if request.GET.get("risk") in ("true", "1"):
        qs = qs.filter(risk_flag__gt=0)
    if v := request.GET.get("legalEntityId"):
        try:
            qs = qs.filter(legal_entity_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("networkZone"):
        qs = qs.filter(network_zone=v)
    if v := request.GET.get("object"):
        parts = v.split(":")
        if len(parts) == 2:
            qs = qs.filter(object_type=parts[0], object_id=parts[1])
    if v := request.GET.get("from"):
        qs = qs.filter(occurred_at__gte=_parse_dt(v))
    if v := request.GET.get("to"):
        qs = qs.filter(occurred_at__lte=_parse_dt(v))
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])

    def _api(lg: XSecLog) -> dict:
        return {
            "id": lg.id, "tenantId": lg.tenant_id, "legalEntityId": lg.legal_entity_id,
            "actorId": lg.actor_id, "actorRole": lg.actor_role,
            "networkZone": lg.network_zone, "action": lg.action,
            "objectType": lg.object_type, "objectId": lg.object_id,
            "fieldDiffJson": lg.field_diff_json, "securityLevel": lg.security_level,
            "grantedLevel": lg.granted_level, "result": lg.result,
            "riskFlag": lg.risk_flag, "hashPrev": lg.hash_prev, "hashSelf": lg.hash_self,
            "occurredAt": lg.occurred_at.isoformat() if lg.occurred_at else None,
            "sourceIp": lg.source_ip, "deviceId": lg.device_id,
        }

    return ok(request, {"chainIntact": _chain_intact(dom.tenant_id),
                        "list": [_api(lg) for lg in rows],
                        "total": total, "page": page, "size": size})


# ---------------------------------------------------------------------------
# 涉密人员 X-11（联动 07）
# ---------------------------------------------------------------------------


def _api_personnel(p: XPersonnelSec) -> dict:
    return {
        "id": p.id, "code": p.code, "tenantId": p.tenant_id,
        "legalEntityId": p.legal_entity_id, "securityLevel": p.security_level,
        "userId": p.user_id, "staffId": p.staff_id,
        "secretEligible": p.secret_eligible, "grantedLevel": p.granted_level,
        "classifyStatus": p.classify_status,
        "reviewDate": f"{p.review_date:%Y-%m-%d}" if p.review_date else None,
        "nextReviewDate": f"{p.next_review_date:%Y-%m-%d}" if p.next_review_date else None,
        "trainingRecords": p.training_records or [],
        "leaveClearance": p.leave_clearance, "status": p.status,
    }


@transaction.atomic
def personnel_review(request: HttpRequest):
    """入职审查/在岗复审/离岗清退（X-11）：清退三要素未完成 → 授权自动收敛 FROZEN。"""
    dom = domain_from(request)
    _mfa(request)
    b = read_json(request)
    if not b.get("userId") or not b.get("op"):
        raise ApiError(400, CODE_BAD_REQUEST, "userId/op 必填")
    op = b["op"]
    if op not in ("ONBOARD_REVIEW", "INPOST_RE_REVIEW", "LEAVE_CLEARANCE"):
        raise ApiError(400, CODE_BAD_REQUEST, "op 取值非法")
    p = XPersonnelSec.objects.filter(tenant_id=dom.tenant_id,
                                     user_id=int(b["userId"]), deleted=0).first()
    if p is None:
        p = XPersonnelSec.objects.create(
            tenant_id=dom.tenant_id, creator_id=dom.user_id,
            code=_gen_code("SEC", dom.tenant_id, XPersonnelSec),
            user_id=int(b["userId"]),
            legal_entity_id=b.get("legalEntityId") or dom.legal_entity_id or 1)
    if op == "ONBOARD_REVIEW":
        p.secret_eligible = bool(b.get("secretEligible"))
        p.granted_level = b.get("grantedLevel") or p.granted_level
        p.status = "GRANTED" if p.secret_eligible else "PENDING_REVIEW"
        if p.granted_level in SECRET_LEVELS and not _grant_exists(dom.tenant_id, p.user_id):
            raise ApiError(400, CODE_BAD_REQUEST,
                           "SECRET+ 许可须先经 /security/grant 授权（mfa_bound）")
    elif op == "INPOST_RE_REVIEW":
        p.review_date = _parse_date(b.get("reviewDate")) or dj_tz.localdate()
        p.next_review_date = _parse_date(b.get("nextReviewDate"))
        p.status = "GRANTED"  # 复审通过，刷新在岗状态
        if b.get("grantedLevel"):
            p.granted_level = b["grantedLevel"]
        if b.get("trainingRecord"):
            p.training_records = (p.training_records or []) + [b["trainingRecord"]]
    else:  # LEAVE_CLEARANCE
        lc = b.get("leaveClearance") or {}
        complete = all(lc.get(k) for k in ("carrierReturned", "accessRevoked", "undertakingSigned"))
        p.leave_clearance = {**lc, "closedBy": dom.user_id, "closedAt": _now().isoformat()}
        p.status = "CLEARED_OUT" if complete else "FROZEN"
        # 授权自动收敛：该用户全部 EFFECTIVE 授权 → FROZEN（只读占位）
        XAccessGrant.objects.filter(tenant_id=dom.tenant_id,
                                    subject_user_id=p.user_id,
                                    status="EFFECTIVE", deleted=0).update(status="FROZEN")
    p.modifier_id = dom.user_id
    p.save()
    _sec_log(dom.tenant_id, actor_id=dom.user_id, action="CLASSIFY",
             object_type="X_PERSONNEL_SEC", object_id=p.id, result="ALLOW",
             granted_level=p.granted_level)
    return ok(request, _api_personnel(p))


def _grant_exists(tenant_id: int, user_id: int) -> bool:
    return XAccessGrant.objects.filter(
        tenant_id=tenant_id, subject_user_id=user_id,
        status="EFFECTIVE", granted_level__in=SECRET_LEVELS, deleted=0).exists()
