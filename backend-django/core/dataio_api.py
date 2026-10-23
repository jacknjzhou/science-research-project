"""dataio 端点（对齐 Go dataio handler 5 条路由）。

GET  /dataio/template?module=      xlsx 模板（表头+示例行+校验说明）
POST /dataio/import?module=        multipart 上传 xlsx → 逐行导入 → sys_import_log
GET  /dataio/imports               导入日志分页（module/from/to 过滤）
POST /dataio/imports/{id}/undo     按 snapshot 撤销（业务引用中 → 40902）
POST /dataio/export                选择性字段导出 xlsx 文件流
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from django.http import HttpRequest, HttpResponse
from django.utils import timezone as dj_tz

from apps.notify.models import SysImportLog
from core import dataio
from core.auth.deps import domain_from
from core.httpx import ApiError, CODE_BAD_REQUEST, CODE_CONFLICT, CODE_NOT_FOUND, ok, read_json


def _parse_ts(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.replace("Z", "+0000"), fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _xlsx_response(content: bytes, filename: str) -> HttpResponse:
    r = HttpResponse(content, content_type=dataio.XLSX_MIME)
    r["Content-Disposition"] = f"attachment; filename={filename}"
    return r


def template(request: HttpRequest):
    d = domain_from(request)
    spec = dataio.spec_or_400(request.GET.get("module", ""))
    return _xlsx_response(dataio.build_template(spec), f"{spec.module.replace('.', '_')}_template.xlsx")


def import_rows(request: HttpRequest):
    d = domain_from(request)
    spec = dataio.spec_or_400(request.GET.get("module", ""))
    f = request.FILES.get("file")
    if f is None:
        raise ApiError(400, CODE_BAD_REQUEST, "multipart 字段 file 必填")
    rows = dataio.read_body_rows(f)
    res = spec.import_fn(d.tenant_id, d.user_id, rows)
    imported, skipped, errs, snapshot = res[:4]
    # 第 5 元组元素可选：模块附加摘要（如 asset.inventory 的盘盈/盘亏比对结果）
    summary = dict(res[4]) if len(res) > 4 and isinstance(res[4], dict) else {}
    SysImportLog.objects.create(
        tenant_id=d.tenant_id, user_id=d.user_id, biz_type=spec.module,
        filename=f.name,
        total_rows=len(rows), ok_rows=imported, fail_rows=len(errs),
        snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    return ok(request, {"rowCount": len(rows), "successCount": imported,
                        "failCount": len(errs), "skipped": skipped, "errors": errs,
                        **summary})


def list_imports(request: HttpRequest):
    d = domain_from(request)
    try:
        page = max(int(request.GET.get("page", "1") or "1"), 1)
        size = min(max(int(request.GET.get("size", "20") or "20"), 1), 200)
    except ValueError:
        page, size = 1, 20
    qs = SysImportLog.objects.filter(tenant_id=d.tenant_id)
    if request.GET.get("module"):
        qs = qs.filter(biz_type=request.GET["module"])
    f, t = _parse_ts(request.GET.get("from")), _parse_ts(request.GET.get("to"))
    if f:
        qs = qs.filter(created_at__gte=f)
    if t:
        qs = qs.filter(created_at__lte=t)
    total = qs.count()
    rows = qs.order_by("-id")[ (page - 1) * size : page * size ]
    return ok(request, {
        "list": [{
            "id": l.id, "module": l.biz_type, "filename": l.filename,
            "row_count": l.total_rows, "success_count": l.ok_rows, "fail_count": l.fail_rows,
            "operator_id": l.user_id, "undone": l.undone,
            "created_at": f"{dj_tz.localtime(l.created_at):%Y-%m-%d %H:%M:%S}",
        } for l in rows],
        "total": total, "page": page, "size": size,
    })


def undo_import(request: HttpRequest, id: int):
    d = domain_from(request)
    log = SysImportLog.objects.filter(id=id, tenant_id=d.tenant_id).first()
    if log is None:
        raise ApiError(404, CODE_NOT_FOUND, "导入日志不存在")
    if log.undone:
        raise ApiError(409, CODE_CONFLICT, "批次已撤销")
    try:
        snapshot = json.loads(log.snapshot) if log.snapshot else []
    except Exception:
        snapshot = []
    if not snapshot:
        raise ApiError(409, CODE_CONFLICT, "无可撤销快照")
    if log.biz_type not in dataio.SPECS:
        raise ApiError(400, CODE_BAD_REQUEST, "该模块暂不支持撤销")
    spec = dataio.SPECS[log.biz_type]
    if spec.claimed_fn(d.tenant_id, snapshot) > 0:
        raise ApiError(409, CODE_CONFLICT, "批次内已有认领入账行，禁止撤销")
    deleted = spec.undo_fn(d.tenant_id, snapshot)
    log.undone = True
    log.save(update_fields=["undone"])
    return ok(request, {"undone": deleted})


def export(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    spec = dataio.spec_or_400(body.get("module") or "")
    columns = body.get("columns") or body.get("fields") or []
    if not isinstance(columns, list):
        raise ApiError(400, CODE_BAD_REQUEST, "columns 须为数组")
    filters = body.get("filters") or {}
    kw = filters.get("kw") or body.get("kw")
    claim_status = filters.get("claim_status") or body.get("claim_status")
    rows = spec.export_fn(d.tenant_id, kw, claim_status)
    content = dataio.build_export(spec, rows, [str(c) for c in columns])
    filename = f"{spec.module.replace('.', '_')}_export_{dj_tz.now():%Y%m%d%H%M%S}.xlsx"
    return _xlsx_response(content, filename)
