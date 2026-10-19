"""成果域 R API（对齐 Go modules/output：handler.go + governance.go + writeback.go）。

台账：/output 多条件筛选、/output/mine、/output/pending-claim、详情
认领：/output/claim|reject|mark-not-mine 批量（1-100，batch_id B+unixnano base36）
关联：PUT /output/{id}/projects 全量替换 + CLAIMED→ASSIGNED_TO_PROJECT
治理：期刊源库/级别/挂接/解析、转载、推送池导入/忽略、专利阶段/年费、代理机构
单一写者：conclude_output_eval（N 域回写唯一入口）
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest

from apps.output.mappings import num2, num_float, to_api_output
from apps.output.models import (
    RAgency,
    RClaimRecord,
    RJournalLevel,
    RJournalLevelSource,
    RJournalSource,
    ROutput,
    ROutputProject,
    RPaperReprint,
    RPatentFee,
    RPushItem,
)
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    ok,
    read_json,
)

# 12 output_type 枚举（R-20 扩充）
OUTPUT_TYPES = {
    "PAPER", "PATENT", "SOFTWARE", "STANDARD", "AWARD", "BOOK", "DATASET",
    "CONFERENCE", "NEW_VARIETY", "LAYOUT", "APPRAISAL", "HONOR",
}
SOURCE_ENUM = {"CNKI", "WOS", "SCOPUS", "WANFANG", "CNIPA", "CROSSREF", "ALTMETRIC", "MANUAL", "FETCH"}
STAGE_ORDER = {"PRE_APPLY": 0, "APPLIED": 1, "PUBLISHED": 2, "GRANTED": 3, "TRANSFERRED": 4}


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = max(int(request.GET.get("page", "1") or "1"), 1)
        size = min(max(int(request.GET.get("size", "20") or "20"), 1), 200)
    except ValueError:
        page, size = 1, 20
    return page, size, size, (page - 1) * size


def norm_title_hash(title: str) -> str:
    """规范化标题哈希：sha256(lower(trim(title)))，去重主键候选。"""
    return hashlib.sha256(title.lower().strip().encode("utf-8")).hexdigest()


def new_batch_id() -> str:
    return "B" + _to_base36(time.time_ns())


def _to_base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(s)[:19], fmt).date()
        except ValueError:
            continue
    return None


def _get_output_or_404(output_id: int) -> ROutput:
    o = ROutput.objects.filter(id=output_id, deleted=0).first()
    if o is None:
        raise ApiError(404, CODE_NOT_FOUND, "成果不存在")
    return o


# ---------------------------------------------------------------------------
# 读端点
# ---------------------------------------------------------------------------

def list_outputs(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = ROutput.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("output_type"):
        qs = qs.filter(output_type=v)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("claim_status"):
        qs = qs.filter(claim_status=v)
    if v := request.GET.get("source"):
        qs = qs.filter(source=v)
    kw = request.GET.get("keyword") or request.GET.get("kw")
    if kw:
        qs = qs.filter(Q(title__icontains=kw) | Q(title_en__icontains=kw))
    if v := request.GET.get("year"):
        try:
            qs = qs.filter(publish_date__year=int(v))
        except ValueError:
            pass
    if v := request.GET.get("department_id"):
        try:
            qs = qs.filter(department_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("project_id"):
        # project_ids JSONB 数组包含：sqlite/PG 兼容走 Python 侧过滤
        try:
            pid = int(v)
        except ValueError:
            pid = None
        if pid is not None:
            all_rows = [o for o in qs.order_by("-id") if pid in (o.project_ids or [])]
            total = len(all_rows)
            return ok(request, {"list": [to_api_output(o) for o in all_rows[offset:offset + limit]],
                                "total": total, "page": page, "size": size})
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_output(o) for o in rows],
                        "total": total, "page": page, "size": size})


def list_my_outputs(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = ROutput.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if v := request.GET.get("output_type"):
        qs = qs.filter(output_type=v)
    if v := request.GET.get("year"):
        try:
            qs = qs.filter(publish_date__year=int(v))
        except ValueError:
            pass
    rows = [o for o in qs.order_by("-id") if any(
        isinstance(a, dict) and a.get("user_id") == d.user_id for a in (o.authors or []))]
    total = len(rows)
    return ok(request, {"list": [to_api_output(o) for o in rows[offset:offset + limit]],
                        "total": total, "page": page, "size": size})


def list_pending_claim(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = ROutput.objects.filter(tenant_id=d.tenant_id, deleted=0, status="PENDING_CLAIM")
    min_c = request.GET.get("min_confidence")
    if min_c:
        try:
            qs = qs.filter(match_confidence__gte=float(min_c))
        except ValueError:
            pass
    total = qs.count()
    rows = list(qs.order_by("-match_confidence", "-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_output(o) for o in rows],
                        "total": total, "page": page, "size": size})


def get_output(request: HttpRequest, id: int):
    return ok(request, to_api_output(_get_output_or_404(id)))


# ---------------------------------------------------------------------------
# 写端点
# ---------------------------------------------------------------------------

def create_output(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("output_type") or not b.get("title"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    if b["output_type"] not in OUTPUT_TYPES:
        raise ApiError(400, CODE_BAD_REQUEST, "output_type 非法")
    src = b.get("source") or "MANUAL"
    if src not in SOURCE_ENUM:
        raise ApiError(400, CODE_BAD_REQUEST, "source 非法")
    o = ROutput.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        status="MANUAL_DRAFT", claim_status="UNCLAIMED", is_claimed=False,
        output_type=b["output_type"], title=b["title"],
        title_en=b.get("title_en"), abstract=b.get("abstract"),
        publish_date=_parse_date(b.get("publish_date")),
        authors=b.get("authors") or [], external_author_names=[],
        affiliations=b.get("affiliations") or [], project_ids=[],
        language=b.get("language"), source=src,
        title_hash=norm_title_hash(b["title"]),
        legal_entity_id=d.legal_entity_id or 1,
        security_level=b.get("security_level") or "INTERNAL",
        remark=b.get("remark"),
    )
    return ok(request, to_api_output(o))


def _claim_tokens(action: str) -> tuple[str, str, bool]:
    """(claim_status, status, is_claimed)。"""
    if action == "CLAIM":
        return "CLAIMED", "CLAIMED", True
    if action == "REJECT":
        return "REJECTED", "REJECTED", False
    if action == "MARK_NOT_MINE":
        return "NOT_MINE", "PENDING_CLAIM", False
    return "PENDING", "PENDING_CLAIM", False


def _process_claim(request: HttpRequest, action: str):
    d = domain_from(request)
    b = read_json(request)
    items = b.get("items")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise ApiError(400, CODE_BAD_REQUEST, "批量项数非法（1-100）")
    batch_id = new_batch_id()
    claim_status, status, is_claimed = _claim_tokens(action)
    results = []
    for it in items:
        oid = (it or {}).get("output_id")
        o = ROutput.objects.filter(id=oid, deleted=0).first() if oid else None
        if o is None:
            results.append({"output_id": oid, "success": False, "message": "成果不存在或状态冲突"})
            continue
        o.claim_status = claim_status
        o.status = status
        o.is_claimed = is_claimed
        o.save(update_fields=["claim_status", "status", "is_claimed", "updated_at"])
        RClaimRecord.objects.create(
            tenant_id=d.tenant_id, creator_id=d.user_id, output_id=o.id,
            user_id=d.user_id, action=action, reason=b.get("reason"),
            edited_fields=it.get("edited_fields"), batch_id=batch_id,
        )
        results.append({"output_id": o.id, "success": True, "new_status": status, "message": "ok"})
    return ok(request, {"batch_id": batch_id, "results": results})


def claim_outputs(request: HttpRequest):
    return _process_claim(request, "CLAIM")


def reject_outputs(request: HttpRequest):
    return _process_claim(request, "REJECT")


def mark_not_mine(request: HttpRequest):
    return _process_claim(request, "MARK_NOT_MINE")


def link_projects(request: HttpRequest, id: int):
    """PUT /output/{id}/projects：全量替换关联集合 + CLAIMED→ASSIGNED_TO_PROJECT。"""
    d = domain_from(request)
    o = _get_output_or_404(id)
    b = read_json(request)
    pids = b.get("project_ids")
    if not isinstance(pids, list):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    cp = b.get("contribution_pct")
    with transaction.atomic():
        ROutputProject.objects.filter(output_id=o.id).update(status="REVOKED", deleted=1)
        for pid in pids:
            ROutputProject.objects.create(
                tenant_id=d.tenant_id, creator_id=d.user_id,
                output_id=o.id, project_id=pid,
                relation_type=b.get("relation_type") or "CONTRIBUTION",
                contribution_pct=cp,
            )
        o.status = "ASSIGNED_TO_PROJECT"
        o.save(update_fields=["status", "updated_at"])
    return ok(request, {"linked": len(pids)})


# ---------------------------------------------------------------------------
# 单一写者（N 域结论回写唯一入口；签名权威勿漂移）
# ---------------------------------------------------------------------------

def conclude_output_eval(output_id: int, passed: bool) -> None:
    """ConcludeOutputEval：pass→ASSIGNED_TO_PROJECT+is_claimed=true；fail→REJECTED。"""
    o = ROutput.objects.filter(id=output_id, deleted=0).first()
    if o is None:
        return
    if passed:
        o.status = "ASSIGNED_TO_PROJECT"
        o.is_claimed = True
    else:
        o.status = "REJECTED"
    o.save(update_fields=["status", "is_claimed", "updated_at"])


# ---------------------------------------------------------------------------
# P5 治理：T16 期刊 / T17 网推 / T18 专利
# ---------------------------------------------------------------------------

def create_journal_source(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    s = RJournalSource.objects.create(
        tenant_id=d.tenant_id, name=b["name"], issn=b.get("issn"),
        year_from=b.get("year_from"), year_to=b.get("year_to"))
    return ok(request, {"id": s.id, "name": s.name, "issn": s.issn,
                        "year_from": s.year_from, "year_to": s.year_to})


def list_journal_sources(request: HttpRequest):
    d = domain_from(request)
    qs = RJournalSource.objects.filter(tenant_id=d.tenant_id, deleted=0)
    y = request.GET.get("year")
    if y:
        try:
            qs = qs.filter(Q(year_from__lte=int(y)) | Q(year_from__isnull=True),
                           Q(year_to__gte=int(y)) | Q(year_to__isnull=True))
        except ValueError:
            pass
    rows = list(qs.order_by("id"))
    return ok(request, {"list": [{"id": s.id, "name": s.name, "issn": s.issn,
                                  "year_from": s.year_from, "year_to": s.year_to} for s in rows],
                        "total": len(rows)})


def create_journal_level(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("code") or not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    l = RJournalLevel.objects.create(
        tenant_id=d.tenant_id, code=b["code"], name=b["name"],
        paper_type=b.get("paper_type"), indexed=b.get("indexed", True))
    return ok(request, {"id": l.id, "code": l.code, "name": l.name,
                        "paper_type": l.paper_type, "indexed": l.indexed})


def list_journal_levels(request: HttpRequest):
    d = domain_from(request)
    rows = list(RJournalLevel.objects.filter(tenant_id=d.tenant_id, deleted=0).order_by("id"))
    return ok(request, {"list": [{"id": l.id, "code": l.code, "name": l.name,
                                  "paper_type": l.paper_type, "indexed": l.indexed} for l in rows],
                        "total": len(rows)})


def attach_level_source(request: HttpRequest, id: int):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("source_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    lv = RJournalLevel.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if lv is None:
        raise ApiError(404, CODE_NOT_FOUND, "刊物级别不存在")
    RJournalLevelSource.objects.create(
        tenant_id=d.tenant_id, level_id=id, source_id=b["source_id"],
        year_from=b.get("year_from"), year_to=b.get("year_to"))
    return ok(request, {"level_id": id, "source_id": b["source_id"]})


def resolve_journal_level(request: HttpRequest):
    """GET /journal-levels/resolve?name=&year= —— 未命中 200+null。"""
    d = domain_from(request)
    name = request.GET.get("name", "")
    year = request.GET.get("year")
    qs = RJournalLevelSource.objects.filter(tenant_id=d.tenant_id)
    if year:
        try:
            qs = qs.filter(Q(year_from__lte=int(year)) | Q(year_from__isnull=True),
                           Q(year_to__gte=int(year)) | Q(year_to__isnull=True))
        except ValueError:
            pass
    lv_ids = list(qs.values_list("level_id", flat=True))
    lv = RJournalLevel.objects.filter(id__in=lv_ids, deleted=0).filter(name=name).first()
    if lv is None:
        return ok(request, None)
    return ok(request, {"level_code": lv.code, "level_name": lv.name})


def create_reprint(request: HttpRequest, id: int):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    _get_output_or_404(id)
    rp = RPaperReprint.objects.create(
        tenant_id=d.tenant_id, output_id=id, name=b["name"], type=b.get("type"),
        reprint_date=_parse_date(b.get("reprint_date")), remark=b.get("remark"))
    return ok(request, {"id": rp.id, "output_id": rp.output_id, "name": rp.name,
                        "type": rp.type, "reprint_date": (f"{rp.reprint_date:%Y-%m-%d}" if rp.reprint_date else None)})


def list_reprints(request: HttpRequest, id: int):
    rows = list(RPaperReprint.objects.filter(output_id=id, deleted=0).order_by("id"))
    out = [{"id": rp.id, "name": rp.name, "type": rp.type,
            "reprint_date": (f"{rp.reprint_date:%Y-%m-%d}" if rp.reprint_date else None),
            "remark": rp.remark} for rp in rows]
    return ok(request, {"list": out, "total": len(out)})


def list_push_items(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = RPushItem.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("type"):
        qs = qs.filter(type=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    out = [{"id": it.id, "type": it.type, "source_db": it.source_db, "title": it.title,
            "authors": it.authors or [], "year": it.year, "raw_doi": it.raw_doi,
            "status": it.status, "pushed_at": it.pushed_at.isoformat() if it.pushed_at else ""} for it in rows]
    return ok(request, {"list": out, "total": total, "page": page, "size": size})


def import_push_item(request: HttpRequest, id: int):
    """查重：title_hash 精确命中 → 40905+existing_id；相似标题 → need_force；导入 R_OUTPUT。"""
    d = domain_from(request)
    it = RPushItem.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if it is None:
        raise ApiError(404, CODE_NOT_FOUND, "推送项不存在")
    if it.status == "IGNORED":
        raise ApiError(409, CODE_CONFLICT, "已忽略项不可导入")
    if it.status == "IMPORTED":
        raise ApiError(409, CODE_CONFLICT, "已导入")
    force = request.GET.get("force") == "true"
    # 1) 精确重复：dedup_key == title_hash 命中已有成果 → 40905
    ex = ROutput.objects.filter(tenant_id=d.tenant_id, deleted=0, title_hash=it.dedup_key).first()
    if ex is not None:
        raise ApiError(409, 40905, "精确重复成果已存在",
                       data={"existing_id": ex.id, "existing_title": ex.title})
    # 2) 相似标题（LIKE 前缀模拟 pg_trgm 相似度；Django/PG 均可用）
    similar = list(ROutput.objects.filter(
        tenant_id=d.tenant_id, deleted=0,
        title__icontains=it.title[:4])[:5])
    if similar and not force:
        return ok(request, {"similar": [{"id": s.id, "title": s.title, "status": s.status} for s in similar],
                            "need_force": True})
    # 3) 导入为 R_OUTPUT（AUTO_FETCHED；源库标记入 source）
    o = ROutput.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        status="PENDING_CLAIM", claim_status="UNCLAIMED",
        output_type=it.type, title=it.title, source=it.source_db,
        publish_date=(datetime(it.year, 1, 1).date() if it.year else None),
        title_hash=norm_title_hash(it.title), legal_entity_id=d.legal_entity_id or 1,
    )
    it.status = "IMPORTED"
    it.output_id = o.id
    it.save(update_fields=["status", "output_id"])
    return ok(request, {"output_id": o.id, "status": "IMPORTED"})


def ignore_push_item(request: HttpRequest, id: int):
    d = domain_from(request)
    it = RPushItem.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if it is None:
        raise ApiError(404, CODE_NOT_FOUND, "推送项不存在")
    it.status = "IGNORED"
    it.save(update_fields=["status"])
    return ok(request, {"ignored": True})


def set_patent_stage(request: HttpRequest, id: int):
    """仅允许按序 +1 或原地幂等。"""
    _get_output_or_404(id)
    b = read_json(request)
    stage = b.get("stage")
    if stage not in STAGE_ORDER:
        raise ApiError(400, CODE_BAD_REQUEST, "stage 非法")
    o = ROutput.objects.get(id=id)
    cur = STAGE_ORDER.get(o.stage, 0)
    if STAGE_ORDER[stage] != cur and STAGE_ORDER[stage] != cur + 1:
        raise ApiError(409, CODE_CONFLICT, f"阶段只能按序流转（当前 {o.stage}）")
    o.stage = stage
    o.save(update_fields=["stage", "updated_at"])
    return ok(request, {"id": id, "stage": stage})


def create_patent_fee(request: HttpRequest, id: int):
    d = domain_from(request)
    _get_output_or_404(id)
    b = read_json(request)
    if not b.get("year") or not b.get("amount"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    f = RPatentFee.objects.create(
        tenant_id=d.tenant_id, patent_id=id, year=b["year"],
        amount=num2(b["amount"]), paid_at=_parse_date(b.get("paid_at")),
        status=b.get("status") or "UNPAID")
    return ok(request, {"id": f.id, "patent_id": f.patent_id, "year": f.year,
                        "amount": num2(f.amount),
                        "paid_at": (f"{f.paid_at:%Y-%m-%d}" if f.paid_at else None),
                        "status": f.status})


def list_patent_fees(request: HttpRequest, id: int):
    rows = list(RPatentFee.objects.filter(patent_id=id).order_by("id"))
    out = [{"id": f.id, "year": f.year, "amount": num2(f.amount),
            "paid_at": (f"{f.paid_at:%Y-%m-%d}" if f.paid_at else None),
            "status": f.status} for f in rows]
    return ok(request, {"list": out, "total": len(out)})


def create_agency(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "参数错误")
    a = RAgency.objects.create(tenant_id=d.tenant_id, name=b["name"], contact=b.get("contact"))
    return ok(request, {"id": a.id, "name": a.name, "contact": a.contact})


def list_agencies(request: HttpRequest):
    d = domain_from(request)
    rows = list(RAgency.objects.filter(tenant_id=d.tenant_id, deleted=0).order_by("id"))
    return ok(request, {"list": [{"id": a.id, "name": a.name, "contact": a.contact} for a in rows],
                        "total": len(rows)})
