"""T13 Excel 导入导出底座（对齐 Go modules/dataio 全部语义）。

模块注册表模式：新模块实现 ModuleSpec 即可挂入（funding.income 首个全链路落地）。
- 模板：表头 + 示例行 + 「校验说明」sheet（openpyxl 对齐 excelize 行为）
- 导入：xlsx 逐行解析 → 幂等键去重跳过 → 行级错误清单 → sys_import_log snapshot
- 撤销：snapshot 内业务行未被引用才允许（引用中 → 40902 拒绝整体撤销）
- 导出：选择性字段（columns/fields）与顺序，缺省全字段
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from django.http import HttpRequest
from django.utils import timezone as dj_tz
from openpyxl import Workbook, load_workbook

from apps.funding.models import FIncome
from apps.notify.models import SysImportLog
from core.auth.deps import domain_from
from core.httpx import ApiError, CODE_BAD_REQUEST, CODE_CONFLICT, CODE_NOT_FOUND, ok

MOD_INCOME = "funding.income"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class ModuleSpec:
    module: str
    headers: list[str]
    sample: list[str]
    hints: list[str]
    export_fields: list[str]
    export_labels: dict[str, str]
    # rows → (imported, skipped, errors, snapshot_keys)
    import_fn: Callable[[int, int, list[list[str]]], tuple[int, int, list[dict], list[str]]]
    # snapshot_keys → 被业务引用的行数（>0 禁止撤销）
    claimed_fn: Callable[[int, list[str]], int] = field(default=lambda t, k: 0)
    # snapshot_keys → 撤销（返回删除行数）
    undo_fn: Callable[[int, list[str]], int] = field(default=lambda t, k: 0)
    # (kw, claim_status) → 导出行记录 dict（key=export_fields）
    export_fn: Callable[[int, str | None, str | None], list[dict]] = field(
        default=lambda t, kw, cs: []
    )


def _parse_amount(s: str):
    s = (s or "").strip()
    if not s:
        return None, False
    try:
        return Decimal(s).quantize(Decimal("0.01")), True
    except InvalidOperation:
        return None, False


def _parse_date(s: str):
    from datetime import date, datetime

    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    if isinstance(s, date):
        return s
    return None


# ---------------------------------------------------------------------------
# funding.income：收款导入（幂等：bank_flow_no 同租户唯一，重复行跳过）
# ---------------------------------------------------------------------------
def _income_import(tenant_id: int, user_id: int, rows: list[list[str]]):
    imported = skipped = 0
    errs: list[dict] = []
    snapshot: list[str] = []
    for i, row in enumerate(rows):
        line_no = i + 2  # xlsx 行号（含表头）
        if len(row) < 6:
            errs.append({"row": line_no, "error": "列数不足 6"})
            continue
        flow_no = (row[5] or "").strip()
        if not flow_no:
            errs.append({"row": line_no, "error": "银行流水号必填"})
            continue
        amt, ok_amt = _parse_amount(row[2])
        if not ok_amt:
            errs.append({"row": line_no, "error": f"金额非法：{row[2]}"})
            continue
        if FIncome.objects.filter(tenant_id=tenant_id, bank_flow_no=flow_no, deleted=0).exists():
            skipped += 1
            continue
        FIncome.objects.create(
            tenant_id=tenant_id, creator_id=user_id, legal_entity_id=1,
            receipt_no=(row[0] or "").strip() or None,
            receipt_date=_parse_date(row[1]),
            amount=amt,
            payer_name=(row[3] or "").strip() or None,
            purpose_text=(row[4] or "").strip() or None,
            bank_flow_no=flow_no,
        )
        imported += 1
        snapshot.append(flow_no)
    return imported, skipped, errs, snapshot


def _income_claimed(tenant_id: int, flow_nos: list[str]) -> int:
    return FIncome.objects.filter(
        tenant_id=tenant_id, bank_flow_no__in=flow_nos, claim_status="CLAIMED", deleted=0
    ).count()


def _income_undo(tenant_id: int, flow_nos: list[str]) -> int:
    return FIncome.objects.filter(
        tenant_id=tenant_id, bank_flow_no__in=flow_nos, deleted=0
    ).update(deleted=1, updated_at=dj_tz.now())


INCOME_EXPORT_FIELDS = [
    "id", "code", "receipt_no", "receipt_date", "amount",
    "payer_name", "purpose_text", "bank_flow_no", "claim_status", "created_at",
]
INCOME_EXPORT_LABEL = {
    "id": "ID", "code": "到款编号", "receipt_no": "收款编号", "receipt_date": "收款日期",
    "amount": "金额", "payer_name": "付款单位", "purpose_text": "摘要",
    "bank_flow_no": "银行流水号", "claim_status": "认领状态", "created_at": "创建时间",
}


def _income_export(tenant_id: int, kw: str | None, claim_status: str | None) -> list[dict]:
    qs = FIncome.objects.filter(tenant_id=tenant_id, deleted=0)
    if kw:
        from django.db.models import Q
        qs = qs.filter(Q(payer_name__icontains=kw) | Q(purpose_text__icontains=kw) | Q(bank_flow_no__icontains=kw))
    if claim_status:
        qs = qs.filter(claim_status=claim_status)
    out = []
    for e in qs.order_by("-id")[:10000]:
        out.append({
            "id": str(e.id), "code": e.code or "",
            "receipt_no": e.receipt_no or "",
            "receipt_date": f"{e.receipt_date:%Y-%m-%d}" if e.receipt_date else "",
            "amount": f"{e.amount:.2f}", "payer_name": e.payer_name or "",
            "purpose_text": e.purpose_text or "", "bank_flow_no": e.bank_flow_no or "",
            "claim_status": e.claim_status,
            "created_at": f"{dj_tz.localtime(e.created_at):%Y-%m-%d %H:%M:%S}",
        })
    return out


SPECS: dict[str, ModuleSpec] = {
    MOD_INCOME: ModuleSpec(
        module=MOD_INCOME,
        headers=["收款编号", "收款日期", "金额", "付款单位", "摘要", "银行流水号"],
        sample=["", "2026-01-15", "50000.00", "示例科技有限公司", "纵向课题 2026 年度拨款", "BK2026011500001"],
        hints=[
            "收款日期格式 YYYY-MM-DD；金额两位小数",
            "银行流水号必填且同租户唯一（重复行自动跳过，幂等）",
            "导入成功后可在「导入日志」中整体撤销（未认领状态下）",
        ],
        export_fields=INCOME_EXPORT_FIELDS,
        export_labels=INCOME_EXPORT_LABEL,
        import_fn=_income_import,
        claimed_fn=_income_claimed,
        undo_fn=_income_undo,
        export_fn=_income_export,
    ),
}


def spec_or_400(module: str) -> ModuleSpec:
    spec = SPECS.get(module or "")
    if spec is None:
        raise ApiError(400, CODE_BAD_REQUEST, "未知模块，支持：" + " | ".join(SPECS))
    return spec


# ---------------------------------------------------------------------------
# xlsx 工具（openpyxl）
# ---------------------------------------------------------------------------
def build_template(spec: ModuleSpec) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"
    ws.append(spec.headers)
    ws.append(spec.sample)
    hints = wb.create_sheet("校验说明")
    for h in spec.hints:
        hints.append([h])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_body_rows(file_obj) -> list[list[str]]:
    """首 sheet 除表头外的非空行（单元格统一转字符串）。"""
    try:
        wb = load_workbook(file_obj, read_only=True, data_only=True)
    except Exception:
        raise ApiError(400, CODE_BAD_REQUEST, "仅支持 xlsx 格式") from None
    ws = wb.worksheets[0]
    body: list[list[str]] = []
    for idx, row in enumerate(ws.iter_rows(values_only=True)):
        if idx == 0:
            continue
        cells = ["" if v is None else (v if isinstance(v, str) else str(v)) for v in row]
        if any(c.strip() for c in cells):
            body.append(cells)
    wb.close()
    if not body:
        raise ApiError(400, CODE_BAD_REQUEST, "无数据行")
    return body


def build_export(spec: ModuleSpec, rows: list[dict], columns: list[str]) -> bytes:
    valid = set(spec.export_fields)
    cols = [c for c in columns if c in valid] or list(spec.export_fields)
    wb = Workbook()
    ws = wb.active
    ws.title = "导出结果"
    ws.append([spec.export_labels.get(c, c) for c in cols])
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
