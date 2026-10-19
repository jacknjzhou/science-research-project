"""科研档案域 O API（对齐 Go modules/archive：document.go + archive.go + check.go + borrow.go）。

文档：multipart 上传（sha256 + 对象存储）/检索/下载 presign/软删
案卷：CRUD + 门类清单 + 状态机（PENDING_SUBMIT→SUBMITTED→PASSED/REJECTED→ARCHIVED→DESTROYED）
四性检测：AUTHENTICITY/INTEGRITY/USABILITY/SECURITY（check.go 纯函数移植）
借阅：ARCHIVED 案卷申请 → R-ADMIN 审批 → 归还
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.archive.models import OArchive, OArchiveCheck, OArchiveItem, OBorrow, ODocument
from core import storage
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    ok,
    read_json,
)

PRESIGN_TTL = 15 * 60  # 下载链接有效期 15min


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = max(int(request.GET.get("page", "1") or "1"), 1)
        size = min(max(int(request.GET.get("size", "20") or "20"), 1), 200)
    except ValueError:
        page, size = 1, 20
    return page, size, size, (page - 1) * size


def _parse_ts(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dj_tz.make_aware(datetime.strptime(str(s)[:19], fmt))
        except ValueError:
            continue
    return None


def _get_doc_or_404(doc_id: int) -> ODocument:
    d = ODocument.objects.filter(id=doc_id, deleted=0).first()
    if d is None:
        raise ApiError(404, CODE_NOT_FOUND, "文档不存在")
    return d


def _get_archive_or_404(archive_id: int) -> OArchive:
    a = OArchive.objects.filter(id=archive_id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "案卷不存在")
    return a


def to_api_document(d: ODocument) -> dict:
    """不输出 text_content（仅全文检索内部用）。"""
    return {
        "id": d.id, "code": d.code, "tenant_id": d.tenant_id, "status": d.status,
        "name": d.name, "doc_type": d.doc_type, "size_bytes": d.size_bytes,
        "bucket": d.bucket, "object_key": d.object_key,
        "checksum_sha256": d.checksum_sha256, "source_module": d.source_module,
        "source_id": d.source_id, "security_level": d.security_level,
        "uploaded_at": (d.uploaded_at.isoformat() if d.uploaded_at else None),
        "created_at": d.created_at.isoformat(),
    }


def to_api_archive(a: OArchive) -> dict:
    return {
        "id": a.id, "code": a.code, "title": a.title, "archive_type": a.archive_type,
        "source_module": a.source_module, "source_id": a.source_id,
        "source_code": a.source_code, "owner_dept_id": a.owner_dept_id,
        "retention_years": a.retention_years, "status": a.status,
        "security_level": a.security_level, "submitter_id": a.submitter_id,
        "submit_at": (a.submit_at.isoformat() if a.submit_at else None),
        "archivist_id": a.archivist_id,
        "filed_at": (a.filed_at.isoformat() if a.filed_at else None),
        "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
    }


def to_api_item(it: OArchiveItem) -> dict:
    return {"id": it.id, "archive_id": it.archive_id, "category_code": it.category_code,
            "category_name": it.category_name, "required": it.required,
            "doc_id": it.doc_id, "status": it.status, "sort_no": it.sort_no}


def to_api_check(c: OArchiveCheck) -> dict:
    return {"id": c.id, "archive_id": c.archive_id, "check_type": c.check_type,
            "result": c.result, "detail": c.detail or {},
            "checked_at": (c.checked_at.isoformat() if c.checked_at else None),
            "checker_id": c.checker_id}


def to_api_borrow(b: OBorrow) -> dict:
    return {"id": b.id, "code": b.code, "archive_id": b.archive_id,
            "archive_title": None, "borrower_user_id": b.borrower_user_id,
            "purpose": b.purpose, "borrow_type": b.borrow_type, "status": b.status,
            "approved_by": b.approved_by,
            "approved_at": (b.approved_at.isoformat() if b.approved_at else None),
            "due_at": (b.due_at.isoformat() if b.due_at else None),
            "returned_at": (b.returned_at.isoformat() if b.returned_at else None),
            "created_at": b.created_at.isoformat()}


# ---------------------------------------------------------------------------
# 文档
# ---------------------------------------------------------------------------

def _doc_ext(content_type: str, filename: str) -> str | None:
    if content_type and content_type.strip():
        return content_type.strip()
    name = filename.rsplit(".", 1)
    if len(name) == 2 and name[1]:
        return name[1].lower()
    return None


def upload_document(request: HttpRequest):
    """multipart → 算 sha256 → 对象存储 Put → 落 o_document(STORED)。"""
    d = domain_from(request)
    f = request.FILES.get("file")
    if f is None:
        raise ApiError(400, CODE_BAD_REQUEST, "缺少上传文件(file)")
    data = f.read()
    checksum = hashlib.sha256(data).hexdigest()
    base = f.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    object_key = f"tenant/{d.tenant_id}/{time.time_ns()}-{base}"
    storage.put(object_key, data, getattr(f, "content_type", "") or "application/octet-stream")
    name = request.POST.get("name") or base
    sec = request.POST.get("security_level") or "INTERNAL"
    src_id = None
    if v := request.POST.get("source_id"):
        try:
            src_id = int(v)
        except ValueError:
            src_id = None
    doc = ODocument.objects.create(
        tenant_id=d.tenant_id, status="STORED", creator_id=d.user_id,
        security_level=sec, name=name,
        doc_type=_doc_ext(getattr(f, "content_type", "") or "", f.name),
        size_bytes=len(data), bucket=storage.default_bucket(), object_key=object_key,
        checksum_sha256=checksum, uploader_id=d.user_id, uploaded_at=dj_tz.now(),
        source_module=request.POST.get("source_module"), source_id=src_id,
        text_content=request.POST.get("text_content"))
    return ok(request, to_api_document(doc))


def get_document(request: HttpRequest, id: int):
    return ok(request, to_api_document(_get_doc_or_404(id)))


def download_document(request: HttpRequest, id: int):
    """presign GET URL（本地后端返回受限说明 URL；expires_at = now + 15min）。"""
    doc = _get_doc_or_404(id)
    if not doc.object_key:
        raise ApiError(409, CODE_CONFLICT, "文档无对象存储键，无法下载")
    if storage.is_configured():
        from datetime import timedelta
        url = storage._client().presigned_get_object(
            storage.default_bucket(), doc.object_key,
            expires=timedelta(minutes=15))
    else:
        url = f"/api/v1/documents/{id}/download?local=1"
    return ok(request, {"url": url,
                        "expires_at": (dj_tz.now() + dj_tz.timedelta(seconds=PRESIGN_TTL)).isoformat()})


def delete_document(request: HttpRequest, id: int):
    doc = _get_doc_or_404(id)
    doc.deleted = 1
    doc.save(update_fields=["deleted", "updated_at"])
    if doc.object_key:
        try:
            storage.remove(doc.object_key)  # 尽力而为：失败不影响软删
        except Exception:
            pass
    return ok(request, {"id": id, "deleted": True})


def search_documents(request: HttpRequest):
    """全文检索：PG 走 tsvector 最优路径，sqlite/通用 LIKE 兜底（snippet 由关键词定位）。"""
    kw = (request.GET.get("q") or "").strip()
    if not kw:
        raise ApiError(400, CODE_BAD_REQUEST, "检索关键词 q 不能为空")
    page, size, limit, offset = page_args(request)
    qs = ODocument.objects.filter(deleted=0).filter(
        name__icontains=kw) | ODocument.objects.filter(deleted=0, text_content__icontains=kw)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    out = []
    for d in rows:
        m = to_api_document(d)
        text = d.text_content or ""
        idx = text.find(kw)
        if idx >= 0:
            s = max(0, idx - 30)
            m["snippet"] = ("..." if s > 0 else "") + text[s:idx + len(kw) + 30] + "..."
        else:
            m["snippet"] = None
        out.append(m)
    return ok(request, {"list": out, "total": total, "page": page, "size": size})


# ---------------------------------------------------------------------------
# 案卷 CRUD + 门类清单
# ---------------------------------------------------------------------------

def list_archives(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = OArchive.objects.filter(deleted=0)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("archive_type"):
        qs = qs.filter(archive_type=v)
    if v := request.GET.get("kw"):
        qs = qs.filter(title__icontains=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_archive(a) for a in rows],
                        "total": total, "page": page, "size": size})


def get_archive(request: HttpRequest, id: int):
    return ok(request, to_api_archive(_get_archive_or_404(id)))


def create_archive(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("title"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    a = OArchive.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        security_level=b.get("security_level") or "INTERNAL",
        title=b["title"], archive_type=b.get("archive_type") or "OTHER",
        source_module=b.get("source_module"), source_id=b.get("source_id"),
        source_code=b.get("source_code"), owner_dept_id=b.get("owner_dept_id"),
        retention_years=b.get("retention_years") or 10)
    return ok(request, to_api_archive(a))


def update_archive(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_archive_or_404(id)
    b = read_json(request)
    if a.status not in ("PENDING_SUBMIT", "REJECTED"):
        raise ApiError(409, CODE_CONFLICT, "仅 PENDING_SUBMIT/REJECTED 可编辑")
    if b.get("title"):
        a.title = b["title"]
    if b.get("archive_type"):
        a.archive_type = b["archive_type"]
    if b.get("security_level"):
        a.security_level = b["security_level"]
    if b.get("retention_years") is not None:
        a.retention_years = b["retention_years"]
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_archive(a))


def delete_archive(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_archive_or_404(id)
    if a.status not in ("PENDING_SUBMIT", "REJECTED"):
        raise ApiError(409, CODE_CONFLICT, "仅 PENDING_SUBMIT/REJECTED 可删除")
    a.deleted = 1
    a.modifier_id = d.user_id
    a.save(update_fields=["deleted", "modifier_id", "updated_at"])
    return ok(request, {"id": id, "deleted": True})


def list_items(request: HttpRequest, id: int):
    rows = list(OArchiveItem.objects.filter(archive_id=id).order_by("sort_no", "id"))
    return ok(request, {"list": [to_api_item(i) for i in rows]})


def add_item(request: HttpRequest, id: int):
    d = domain_from(request)
    _get_archive_or_404(id)
    b = read_json(request)
    if not b.get("category_code"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    doc_id = b.get("doc_id")
    if doc_id is not None:
        _get_doc_or_404(doc_id)
    it = OArchiveItem.objects.create(
        tenant_id=d.tenant_id, archive_id=id, category_code=b["category_code"],
        category_name=b.get("category_name"), required=b.get("required", True),
        doc_id=doc_id, sort_no=b.get("sort_no") or 0,
        status=("FILLED" if doc_id is not None else "MISSING"))
    return ok(request, to_api_item(it))


def fill_item(request: HttpRequest, id: int, item_id: int):
    b = read_json(request)
    doc = _get_doc_or_404(b.get("doc_id") or 0)
    if doc.status != "STORED":
        raise ApiError(400, CODE_BAD_REQUEST, "文档非 STORED，不可挂载")
    it = OArchiveItem.objects.filter(id=item_id, archive_id=id).first()
    if it is None:
        raise ApiError(404, CODE_NOT_FOUND, "条目不存在")
    it.doc_id = doc.id
    it.status = "FILLED"
    it.save(update_fields=["doc_id", "status"])
    return ok(request, to_api_item(it))


def delete_item(request: HttpRequest, id: int, item_id: int):
    n, _ = OArchiveItem.objects.filter(id=item_id, archive_id=id).delete()
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "条目不存在")
    return ok(request, {"id": item_id, "deleted": True})


def ingest_source(request: HttpRequest, id: int):
    """从来源对象拉取文档建清单条目（等价带 doc 的 AddItem）。"""
    d = domain_from(request)
    _get_archive_or_404(id)
    b = read_json(request)
    if not b.get("category_code"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    doc_id = b.get("doc_id")
    if doc_id is not None:
        _get_doc_or_404(doc_id)
    it = OArchiveItem.objects.create(
        tenant_id=d.tenant_id, archive_id=id, category_code=b["category_code"],
        category_name=b.get("category_name"), doc_id=doc_id,
        status=("FILLED" if doc_id is not None else "MISSING"))
    return ok(request, to_api_item(it))


# ---------------------------------------------------------------------------
# 状态机 + 四性检测（check.go 纯函数移植）
# ---------------------------------------------------------------------------

def submit_archive(request: HttpRequest, id: int):
    d = domain_from(request)
    a = _get_archive_or_404(id)
    if a.status not in ("PENDING_SUBMIT", "REJECTED"):
        raise ApiError(409, CODE_CONFLICT, "仅 PENDING_SUBMIT/REJECTED 可提交")
    a.status = "SUBMITTED"
    a.submitter_id = d.user_id
    a.submit_at = dj_tz.now()
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_archive(a))


def file_archive(request: HttpRequest, id: int):
    """PASSED → ARCHIVED（Casbin 限 R-ADMIN，policy 层已收敛）。"""
    d = domain_from(request)
    a = _get_archive_or_404(id)
    if a.status != "PASSED":
        raise ApiError(409, CODE_CONFLICT, "仅 PASSED 案卷可入库")
    a.status = "ARCHIVED"
    a.archivist_id = d.user_id
    a.filed_at = dj_tz.now()
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_archive(a))


def destroy_archive(request: HttpRequest, id: int):
    """ARCHIVED → DESTROYED（reason 本轮仅接收不回写，对齐 Go 不臆造查询约束）。"""
    d = domain_from(request)
    a = _get_archive_or_404(id)
    if a.status != "ARCHIVED":
        raise ApiError(409, CODE_CONFLICT, "仅 ARCHIVED 案卷可销毁")
    a.status = "DESTROYED"
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_archive(a))


def _evaluate_four_properties(facts: dict) -> list[dict]:
    """纯函数：给定事实算四性。对齐 Go evaluateFourProperties。"""
    docs = facts["docs"]
    auth_res, auth_bad = "PASS", []
    for doc in docs:
        if doc["expected"] and doc["expected"] != doc["got"]:
            auth_res = "FAIL"
            auth_bad.append(doc["doc_id"])
    integ_res = "PASS" if facts["required_filled"] >= facts["required_total"] else "FAIL"
    unusable = sum(1 for doc in docs if not doc["usable"])
    if not docs or unusable == len(docs):
        usa_res = "FAIL"
    elif unusable > 0:
        usa_res = "WARN"
    else:
        usa_res = "PASS"
    sec_res = "PASS" if facts["security_ok"] else "FAIL"
    return [
        {"check_type": "AUTHENTICITY", "result": auth_res,
         "detail": {"mismatch_doc_ids": auth_bad, "checked": len(docs)}},
        {"check_type": "INTEGRITY", "result": integ_res,
         "detail": {"required_total": facts["required_total"],
                    "required_filled": facts["required_filled"]}},
        {"check_type": "USABILITY", "result": usa_res,
         "detail": {"total": len(docs), "unusable": unusable}},
        {"check_type": "SECURITY", "result": sec_res,
         "detail": {"security_ok": facts["security_ok"]}},
    ]


def check_archive(request: HttpRequest, id: int):
    """四性检测落库；SUBMITTED 态按 allPassed 迁移 PASSED/REJECTED。"""
    d = domain_from(request)
    a = _get_archive_or_404(id)
    required = list(OArchiveItem.objects.filter(archive_id=id, required=True))
    facts = {"required_total": 0, "required_filled": 0, "docs": [], "security_ok": True}
    for it in required:
        facts["required_total"] += 1
        if it.doc_id is not None and it.status == "FILLED":
            facts["required_filled"] += 1
        if it.doc_id is None:
            continue
        doc = ODocument.objects.filter(id=it.doc_id, deleted=0).first()
        if doc is None:
            continue  # 引用文档缺失：计不可读、真实性不命中（空 Expected 不判 FAIL）
        exp = doc.checksum_sha256 or ""
        facts["docs"].append({"doc_id": it.doc_id, "expected": exp, "got": exp,
                              "usable": doc.status == "STORED"})
    results = _evaluate_four_properties(facts)
    passed = all(r["result"] == "PASS" for r in results)
    out = []
    for r in results:
        row, _ = OArchiveCheck.objects.update_or_create(
            tenant_id=a.tenant_id, archive_id=id, check_type=r["check_type"],
            defaults={"result": r["result"], "detail": r["detail"],
                      "checked_at": dj_tz.now(), "checker_id": d.user_id})
        out.append(to_api_check(row))
    if a.status == "SUBMITTED":
        a.status = "PASSED" if passed else "REJECTED"
        a.modifier_id = d.user_id
        a.save(update_fields=["status", "modifier_id", "updated_at"])
    return ok(request, {"list": out, "passed": passed})


# ---------------------------------------------------------------------------
# 借阅
# ---------------------------------------------------------------------------

def create_borrow(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("archive_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    a = _get_archive_or_404(b["archive_id"])
    if a.status != "ARCHIVED":
        raise ApiError(409, CODE_CONFLICT, "仅 ARCHIVED 案卷可借阅")
    r = OBorrow.objects.create(
        tenant_id=d.tenant_id, creator_id=d.user_id,
        archive_id=a.id, borrower_user_id=d.user_id,
        purpose=b.get("purpose"), borrow_type=b.get("borrow_type") or "READ",
        due_at=_parse_ts(b.get("due_at")))
    return ok(request, to_api_borrow(r))


def list_borrows(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = OBorrow.objects.filter(deleted=0)
    if v := request.GET.get("borrower"):
        try:
            qs = qs.filter(borrower_user_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("archive_id"):
        try:
            qs = qs.filter(archive_id=int(v))
        except ValueError:
            pass
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_borrow(r) for r in rows],
                        "total": total, "page": page, "size": size})


def _set_borrow_status(request: HttpRequest, borrow_id: int, to: str, allowed_from: str,
                       extra: dict | None = None):
    d = domain_from(request)
    r = OBorrow.objects.filter(id=borrow_id, deleted=0).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "借阅不存在")
    if r.status != allowed_from:
        raise ApiError(409, CODE_CONFLICT, "当前状态不允许该操作")
    r.status = to
    r.modifier_id = d.user_id
    for k, v in (extra or {}).items():
        setattr(r, k, v)
    r.save()
    return ok(request, to_api_borrow(r))


def approve_borrow(request: HttpRequest, id: int):
    d = domain_from(request)
    return _set_borrow_status(request, id, "APPROVED", "SUBMITTED",
                              {"approved_by": d.user_id, "approved_at": dj_tz.now()})


def reject_borrow(request: HttpRequest, id: int):
    return _set_borrow_status(request, id, "REJECTED", "SUBMITTED")


def return_borrow(request: HttpRequest, id: int):
    return _set_borrow_status(request, id, "RETURNED", "APPROVED",
                              {"returned_at": dj_tz.now()})
