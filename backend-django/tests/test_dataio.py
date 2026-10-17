"""T13 dataio Excel 导入导出底座测试（对齐 Go dataio handler_test 语义）。"""
import io

import pytest
from django.test import Client
from openpyxl import Workbook, load_workbook

from apps.funding.models import FIncome
from tests.conftest import bearer


def _c():
    return Client()


def _xlsx(rows: list[list[str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"
    ws.append(["收款编号", "收款日期", "金额", "付款单位", "摘要", "银行流水号"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(c, rows: list[list[str]]):
    return c.post(
        "/api/v1/dataio/import?module=funding.income",
        data={"file": ("income.xlsx", io.BytesIO(_xlsx(rows)),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        format="multipart",
        **bearer(1, ["R-ADMIN"]),
    )


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------
def test_template_download(seed_auth):
    c = _c()
    r = c.get("/api/v1/dataio/template?module=funding.income", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.active.title == "导入模板"
    assert wb.active.cell(1, 1).value == "收款编号"
    assert wb.active.cell(2, 3).value == "50000.00"
    assert wb["校验说明"].cell(1, 1).value.startswith("收款日期格式")


def test_template_unknown_module_400(seed_auth):
    c = _c()
    r = c.get("/api/v1/dataio/template?module=nope", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 400
    assert "未知模块" in r.json()["message"]


# ---------------------------------------------------------------------------
# 导入：幂等跳过 + 行级错误 + 日志
# ---------------------------------------------------------------------------
def test_import_rows_idempotent_and_errors(seed_auth):
    c = _c()
    rows = [
        ["SK-1", "2026-01-15", "50000.00", "甲公司", "纵向拨款", "BK001"],
        ["SK-2", "bad-date", "abc", "乙公司", "格式坏行", "BK002"],  # 金额非法
        ["SK-X", "", "", "", "仅缺流水号", ""],  # 银行流水号必填
        ["SK-3", "2026-01-16", "100.50", "丙公司", "重复流水", "BK001"],  # 幂等跳过
    ]
    r = _upload(c, rows)
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["rowCount"] == 4
    assert body["successCount"] == 1
    assert body["failCount"] == 2
    assert body["skipped"] == 1
    err_rows = {e["row"]: e["error"] for e in body["errors"]}
    assert 3 in err_rows and "金额非法" in err_rows[3]
    assert 4 in err_rows and "银行流水号必填" in err_rows[4]

    # 全空行不算数据行
    r = _upload(c, [["", "", "", "", "", ""]])
    assert r.status_code == 400
    assert r.json()["message"] == "无数据行"

    # 导入日志
    r = c.get("/api/v1/dataio/imports?module=funding.income", **bearer(1, ["R-ADMIN"]))
    logs = r.json()["data"]["list"]
    assert logs[0]["module"] == "funding.income"
    assert logs[0]["success_count"] == 1
    assert logs[0]["fail_count"] == 2

    inc = FIncome.objects.get(bank_flow_no="BK001", deleted=0)
    assert str(inc.amount) == "50000.00"
    assert inc.claim_status == "UNCLAIMED"


# ---------------------------------------------------------------------------
# 撤销：引用守卫 + 快照回滚
# ---------------------------------------------------------------------------
def test_undo_with_claim_guard(seed_auth):
    c = _c()
    r = _upload(c, [
        ["SK-1", "2026-01-15", "100.00", "甲", "x", "BK-U1"],
        ["SK-2", "2026-01-16", "200.00", "乙", "y", "BK-U2"],
    ])
    assert r.json()["data"]["successCount"] == 2

    r = c.get("/api/v1/dataio/imports", **bearer(1, ["R-ADMIN"]))
    log_id = r.json()["data"]["list"][0]["id"]

    # 认领其中一行后 → 撤销被拒
    FIncome.objects.filter(bank_flow_no="BK-U1").update(claim_status="CLAIMED")
    r = c.post(f"/api/v1/dataio/imports/{log_id}/undo", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409
    assert "认领" in r.json()["message"]

    # 取消认领 → 撤销成功，两行软删
    FIncome.objects.filter(bank_flow_no="BK-U1").update(claim_status="UNCLAIMED")
    r = c.post(f"/api/v1/dataio/imports/{log_id}/undo", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 200
    assert r.json()["data"]["undone"] == 2
    assert FIncome.objects.filter(bank_flow_no__in=["BK-U1", "BK-U2"], deleted=0).count() == 0

    # 重复撤销 → 409
    r = c.post(f"/api/v1/dataio/imports/{log_id}/undo", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 409


def test_undo_unknown_log_404(seed_auth):
    c = _c()
    r = c.post("/api/v1/dataio/imports/9999/undo", **bearer(1, ["R-ADMIN"]))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 导出：选择性字段 + 文件流
# ---------------------------------------------------------------------------
def test_export_selective_columns(seed_auth):
    FIncome.objects.create(
        tenant_id=1, creator_id=1, receipt_no="SK-E1", receipt_date="2026-01-15",
        amount=1000.50, payer_name="丁公司", bank_flow_no="BK-E1",
    )
    c = _c()
    r = c.post(
        "/api/v1/dataio/export",
        data={"module": "funding.income", "columns": ["bank_flow_no", "amount"]},
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    assert r.status_code == 200
    assert r["Content-Disposition"].startswith("attachment")
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb.active
    assert ws.cell(1, 1).value == "银行流水号"  # 列按请求顺序
    assert ws.cell(1, 2).value == "金额"
    assert ws.cell(2, 1).value == "BK-E1"
    assert ws.cell(2, 2).value == "1000.50"

    # kw 过滤
    r = c.post(
        "/api/v1/dataio/export",
        data={"module": "funding.income", "filters": {"kw": "丁公司"}},
        content_type="application/json",
        **bearer(1, ["R-ADMIN"]),
    )
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.active.max_row == 2  # 表头 + 1 行
