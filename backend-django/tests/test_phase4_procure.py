"""Phase 4 G/A 域测试（纯契约域）。

G：采购申请（创建即冻结+方式判定 40910）→ 发标（黑名单 40913）→ 定标/废标回退 →
合同评审四方会签 → 签署 → 付款计划（40911）→ 付款回调（冻结→实扣）→ 到货转资产（40916）。
A：建卡（要素缺失 PENDING_RECEIPT）→ 领用/归还/调拨（涉密保密审查 403）→
耗材 FIFO/效期冻结/危化双锁 → 折旧幂等 → 凭证回调 → 处置（残值复核）→ 盘点盘盈亏。
"""
import json
from decimal import Decimal

from django.test import Client

from apps.asset.models import AAsset, AConsumable, ADepreciation, AStockTxn
from apps.funding.models import FBudgetLine, FSubject
from apps.procure.models import GBid, GContract, GOrder, GRequisition, GSupplier
from tests.conftest import bearer

MG = ["R-MANAGER"]
ST = ["R-STAFF"]
FIN = ["R-FINANCE"]


def _c():
    return Client()


def _j(r):
    return r.json()


def _post(c, url, body, user=2, roles=MG):
    return c.post(url, data=json.dumps(body), content_type="application/json",
                  **bearer(user, roles))


def _put(c, url, body, user=2, roles=MG):
    return c.put(url, data=json.dumps(body), content_type="application/json",
                 **bearer(user, roles))


def _budget(remaining="10000"):
    sub = FSubject.objects.create(tenant_id=1, creator_id=1, name="设备费",
                                  category="DIRECT", code="S-ASSET")
    FBudgetLine.objects.create(tenant_id=1, creator_id=1, budget_id=1,
                               subject_id=sub.id, amount_planned=Decimal(remaining))
    return sub


def _req(c, est="5000", category="设备", subject="S-ASSET", user=2, roles=ST):
    return _post(c, "/api/v1/procurement/requisitions", {
        "project_id": 5, "category": category, "item_name": "测试采购物",
        "est_amount": est, "budget_subject_code": subject,
    }, user=user, roles=roles)


def _supplier(**kw):
    base = dict(tenant_id=1, creator_id=1, name="合格供应商", status="IN_LIBRARY",
                qualification_expire_date="2030-12-31")
    base.update(kw)
    return GSupplier.objects.create(**base)


def _order(supplier=None, delivery_status="ACCEPTED", category="设备", est="50000"):
    sup = supplier or _supplier()
    sub = _budget()
    r = GRequisition.objects.create(
        tenant_id=1, creator_id=1, code="REQ-2026-9001", project_id=5,
        applicant_id=2, category=category, item_name="测试物", est_amount=Decimal(est),
        budget_subject_code=sub.code, status="ORDERED")
    return GOrder.objects.create(
        tenant_id=1, creator_id=1, code="ORD-2026-9001", requisition=r, supplier=sup,
        order_amount=Decimal(est), delivery_status=delivery_status)


# ===========================================================================
# G-01/G-02/G-03：申请（创建即冻结）+ 方式判定 + 超预算 40910
# ===========================================================================


def test_requisition_way_and_budget_freeze(seed_auth):
    c = _c()
    _budget("10000000")
    # 150 万 → 邀请招标 rule 2；冻结后剩余额下降
    r = _req(c, est="1500000")
    d = _j(r)["data"]
    assert d["status"] == "WAY_DECIDED"
    assert d["purchase_way"] == "邀请招标"
    assert d["way_basis_rule_id"] == 2
    assert d["frozen_amount"] == 1500000
    # GET 方式判定：可复算
    r = c.get(f"/api/v1/procurement/requisitions/{d['id']}/way", **bearer(2, ST))
    assert _j(r)["data"]["purchase_way"] == "邀请招标"
    # 5000 → 自行采购 rule 4
    r = _req(c, est="5000")
    assert _j(r)["data"]["purchase_way"] == "自行采购"
    # 超预算 → 40910
    r = _req(c, est="9999999")
    body = _j(r)
    assert body["code"] == 40910


def test_requisition_way_tiers(seed_auth):
    c = _c()
    _budget("10000000")
    r = _req(c, est="5000000")
    assert _j(r)["data"]["purchase_way"] == "公开招标"
    r = _req(c, est="500000")
    assert _j(r)["data"]["purchase_way"] == "询价"
    # 外协 → 单一来源 rule 9
    r = _req(c, est="50000", category="外协")
    assert _j(r)["data"]["purchase_way"] == "单一来源"


# ===========================================================================
# G-05：发标（黑名单硬拦截 40913）→ 定标 / 废标回退释放冻结
# ===========================================================================


def test_bid_blacklist_and_award(seed_auth):
    c = _c()
    _budget("10000000")
    r = _req(c, est="1500000")
    req_id = _j(r)["data"]["id"]
    bad = _supplier(name="黑名单供应商", blacklist=True)
    ok_sup = _supplier(name="二号供应商")
    # 邀请名单含黑名单 → 40913
    r = _post(c, "/api/v1/procurement/bids", {
        "requisition_id": req_id, "method": "邀请招标",
        "invited_supplier_ids": [bad.id]})
    assert _j(r)["code"] == 40913
    # 正常发标
    r = _post(c, "/api/v1/procurement/bids", {
        "requisition_id": req_id, "method": "邀请招标",
        "invited_supplier_ids": [ok_sup.id]})
    bid = _j(r)["data"]
    assert bid["status"] == "PUBLICIZING"
    # 黑名单中标 → 40913
    r = _post(c, f"/api/v1/procurement/bids/{bid['id']}/award",
              {"winner_supplier_id": bad.id})
    assert _j(r)["code"] == 40913
    # 正常定标
    r = _post(c, f"/api/v1/procurement/bids/{bid['id']}/award", {
        "winner_supplier_id": ok_sup.id, "winner_reason": "综合评分最高"})
    assert _j(r)["data"]["status"] == "AWARDED"


def test_bid_void_releases_budget(seed_auth):
    c = _c()
    sub = _budget("10000000")
    r = _req(c, est="1500000")
    req_id = _j(r)["data"]["id"]
    r = _post(c, "/api/v1/procurement/bids",
              {"requisition_id": req_id, "method": "邀请招标"})
    bid_id = _j(r)["data"]["id"]
    line = FBudgetLine.objects.get(subject_id=sub.id)
    frozen_before = line.amount_frozen
    assert frozen_before > 0
    # 废标 → CHALLENGE + 释放冻结
    r = _post(c, f"/api/v1/procurement/bids/{bid_id}/award", {
        "voided": True, "void_reason": "不足三家有效投标"})
    assert _j(r)["data"]["status"] == "CHALLENGE"
    line.refresh_from_db()
    assert line.amount_frozen == frozen_before - Decimal("1500000")
    req = GRequisition.objects.get(id=req_id)
    assert req.status == "SUBMITTED" and req.frozen_amount == 0


# ===========================================================================
# G-07/G-08/G-11：合同评审四方会签 → 签署 → 付款计划 40911 → 付款回调冻结→实扣
# ===========================================================================


def _active_contract(c, supplier=None, amount="50000", requisition_id=None):
    sup = supplier or _supplier()
    r = _post(c, "/api/v1/contract", {
        "contract_type": "采购", "party_b": sup.name, "supplier_id": sup.id,
        "amount": amount, "project_id": 5, "requisition_id": requisition_id,
        "pay_terms_json": [{"phase": "验收", "ratio": 1.0}],
        "deliverables_json": ["设备一台"]})
    assert _j(r)["code"] == 0, _j(r)
    return _j(r)["data"]["id"]


def test_contract_review_sign_payment(seed_auth):
    c = _c()
    sub = _budget("100000")
    r = _req(c, est="50000")
    req_id = _j(r)["data"]["id"]
    cid = _active_contract(c, requisition_id=req_id)
    # 四方会签：任一驳回回 DRAFT
    r = _put(c, f"/api/v1/contract/{cid}/review",
             {"role": "tech", "result": "REJECT", "comment": "参数不符"})
    assert _j(r)["data"]["status"] == "DRAFT"
    for role in ("tech", "legal", "finance", "security"):
        r = _put(c, f"/api/v1/contract/{cid}/review",
                 {"role": role, "result": "APPROVE", "comment": "同意"})
    assert _j(r)["data"]["status"] == "TO_SIGN"
    # 签署 → ACTIVE
    r = _post(c, f"/api/v1/contract/{cid}/sign", {"sign_method": "电子签"})
    assert _j(r)["data"]["status"] == "ACTIVE"
    # 付款计划累计超合同额 → 40911
    r = _post(c, f"/api/v1/contract/{cid}/payment-plan", {
        "plans": [{"phase": "验收", "plan_amount": "60000"}]})
    assert _j(r)["code"] == 40911
    r = _post(c, f"/api/v1/contract/{cid}/payment-plan", {
        "plans": [{"phase": "验收", "plan_amount": "50000"}]})
    pid = _j(r)["data"]["list"][0]["id"]
    # 付款回调：冻结→实扣迁移
    line = FBudgetLine.objects.get(subject_id=sub.id)
    assert line.amount_frozen == Decimal("50000") and line.amount_used == 0
    r = _post(c, "/api/v1/finance/expense", {
        "payment_id": pid, "expense_id": 901, "paid_amount": "50000",
        "voucher_status": "SUCCESS"}, user=3, roles=FIN)
    assert _j(r)["code"] == 0, _j(r)
    assert _j(r)["data"]["status"] == "PAID"
    line.refresh_from_db()
    assert line.amount_frozen == 0 and line.amount_used == Decimal("50000")
    # 幂等：同 expense_id 重放返回原结果
    r = _post(c, "/api/v1/finance/expense", {
        "payment_id": pid, "expense_id": 901, "paid_amount": "50000"},
        user=3, roles=FIN)
    assert _j(r)["data"].get("idempotent") is True


# ===========================================================================
# G-17 / A-03：到货转资产（幂等 40916）
# ===========================================================================


def test_from_receipt_convert_and_idempotent(seed_auth):
    c = _c()
    o = _order()
    r = _post(c, "/api/v1/asset/from-receipt", {"orderId": o.id})
    assert _j(r)["code"] == 0, _j(r)
    d = _j(r)["data"]
    assert d["target_table"] == "A_ASSET"
    a = AAsset.objects.get(id=d["target_id"])
    # 有金额无责任人 → 要素缺失 PENDING_RECEIPT
    assert a.status == "PENDING_RECEIPT"
    assert a.value == Decimal("50000")
    # 非 ACCEPTED 订单 → 409
    o2 = _order(delivery_status="DELIVERED")
    r = _post(c, "/api/v1/asset/from-receipt", {"order_id": o2.id})
    assert _j(r)["code"] == 40901
    # 重复转资产 → 40916
    r = _post(c, "/api/v1/asset/from-receipt", {"orderId": o.id})
    assert _j(r)["code"] == 40916
    # 试剂耗材订单 → A_CONSUMABLE
    o3 = _order(category="试剂耗材")
    r = _post(c, "/api/v1/asset/from-receipt", {"orderId": o3.id, "target": "CONSUMABLE"})
    assert _j(r)["data"]["target_table"] == "A_CONSUMABLE"


# ===========================================================================
# A-02/A-05：建卡 → 领用/归还/调拨（涉密保密审查 403）
# ===========================================================================


def _full_asset(c, **kw):
    body = {"assetType": "FIXED", "categoryCode": "CAT-01", "name": "高速离心机",
            "serialNo": kw.pop("serialNo", "SN-A001"), "value": "120000",
            "custodianId": 2, "deptId": 3, "location": "实验楼 301",
            "deprMethod": "STRAIGHT_LINE", "deprYears": 10, "projectId": 5}
    body.update(kw)
    r = _post(c, "/api/v1/asset", body)
    assert _j(r)["code"] == 0, _j(r)
    return _j(r)["data"]


def test_asset_create_issue_return_transfer(seed_auth):
    c = _c()
    d = _full_asset(c)
    assert d["code"].startswith("AST-")
    assert d["status"] == "IN_USE" and d["netValue"] == 120000
    # 领用：换责任人/项目，生成 REQUISITION 流水
    r = _post(c, f"/api/v1/asset/{d['id']}/issue", {
        "projectId": 7, "custodianId": 3, "location": "实验楼 502", "usageRate": 0.8})
    t = _j(r)["data"]
    assert t["type"] == "REQUISITION" and t["balanceAfter"] == 1
    a = AAsset.objects.get(id=d["id"])
    assert a.custodian_id == 3 and a.project_id == 7 and a.usage_rate == Decimal("0.8000")
    # 归还 → IDLE
    r = _post(c, f"/api/v1/asset/{d['id']}/return", {"location": "库房"})
    assert _j(r)["data"]["type"] == "RETURN"
    a.refresh_from_db()
    assert a.status == "IDLE" and a.custodian_id is None
    # 再领用后调拨
    _post(c, f"/api/v1/asset/{d['id']}/issue", {"projectId": 7})
    r = _post(c, f"/api/v1/asset/{d['id']}/transfer", {
        "toLegalEntityId": 2, "toDeptId": 9, "toCustodianId": 4, "toLocation": "分院"})
    assert _j(r)["data"]["legalEntityId"] == 2
    a.refresh_from_db()
    assert a.status == "IN_USE" and a.dept_id == 9
    # 涉密资产调拨无保密审查单 → 403
    sec = _full_asset(c, serialNo="SN-SEC1", securityLevel="SECRET")
    r = _post(c, f"/api/v1/asset/{sec['id']}/transfer",
              {"toLegalEntityId": 2, "toDeptId": 9})
    assert _j(r)["code"] == 40301
    r = _post(c, f"/api/v1/asset/{sec['id']}/transfer", {
        "toLegalEntityId": 2, "toDeptId": 9, "secrecyReviewId": 77})
    assert _j(r)["code"] == 0


def test_asset_ledger_and_lifecycle(seed_auth):
    c = _c()
    d = _full_asset(c, serialNo="SN-L1")
    _post(c, f"/api/v1/asset/{d['id']}/issue", {"projectId": 7})
    r = c.get("/api/v1/asset/ledger", {"keyword": "离心机"}, **bearer(2, ST))
    assert _j(r)["data"]["total"] >= 1
    r = c.get(f"/api/v1/asset/{d['id']}/lifecycle", **bearer(2, ST))
    lc = _j(r)["data"]
    stages = [e["stage"] for e in lc["events"]]
    assert "REGISTER" in stages and "ISSUE" in stages
    # 追溯链（source_ref=None → 单节点）
    r = c.get(f"/api/v1/asset/{d['id']}/trace", **bearer(2, ST))
    assert _j(r)["data"]["nodes"][0]["objectType"] == "A_ASSET"
    # 涉密资产对 INTERNAL 会话不可见（台账过滤）
    _full_asset(c, serialNo="SN-SEC2", securityLevel="SECRET")
    r = c.get("/api/v1/asset/ledger", **bearer(2, ST))
    serials = [x["serialNo"] for x in _j(r)["data"]["list"]]
    assert "SN-SEC2" not in serials


# ===========================================================================
# A-07/A-08：耗材 FIFO / 效期冻结 / 危化双锁 / 豁免留痕
# ===========================================================================


def _in(c, sku, batch, expire, qty="10", **kw):
    body = {"batchNo": batch, "expireDate": expire, "qty": qty,
            "name": "测试试剂", "category": "REAGENT", "unit": "瓶"}
    body.update(kw)
    return _post(c, f"/api/v1/consumable/{sku}/stock-in", body)


def test_consumable_fifo_and_expiry_and_hazard(seed_auth):
    c = _c()
    # 普通试剂：两批次，B-Near 先到期
    r = _in(c, "SKU-1", "B-Near", "2027-01-01")
    assert _j(r)["data"]["type"] == "STOCK_IN"
    _in(c, "SKU-1", "B-Far", "2028-06-01")
    # 危化入库缺 MSDS → 40001
    r = _in(c, "SKU-H", "B-H1", "2027-06-01", isHazard=True)
    assert _j(r)["code"] == 40001
    r = _in(c, "SKU-H", "B-H1", "2027-06-01", isHazard=True,
            hazardLevel="管制", msdsUrl="http://x/msds.pdf")
    assert _j(r)["code"] == 0
    # FIFO：缺省选最早到期 B-Near
    r = _post(c, "/api/v1/consumable/SKU-1/stock-out", {
        "qty": "3", "projectId": 5, "operatorId": 2, "usage": "实验"})
    t = _j(r)["data"]
    assert t["refBatchNo"] == "B-Near" and t["balanceAfter"] == 17
    # 违反 FIFO 且未豁免 → 40901
    r = _post(c, "/api/v1/consumable/SKU-1/stock-out", {
        "qty": "1", "projectId": 5, "operatorId": 2, "batchNo": "B-Far"})
    assert _j(r)["code"] == 40901
    # 豁免缺授权人 → 40001；带授权人 → 放行并留痕
    r = _post(c, "/api/v1/consumable/SKU-1/stock-out", {
        "qty": "1", "projectId": 5, "operatorId": 2, "batchNo": "B-Far",
        "fifoExempt": True})
    assert _j(r)["code"] == 40001
    r = _post(c, "/api/v1/consumable/SKU-1/stock-out", {
        "qty": "1", "projectId": 5, "operatorId": 2, "batchNo": "B-Far",
        "fifoExempt": True, "fifoExemptApproverId": 1})
    t = _j(r)["data"]
    assert t["fifoExempt"] is True and t["refBatchNo"] == "B-Far"
    # 危化出库缺第二确认人 → 40301
    r = _post(c, "/api/v1/consumable/SKU-H/stock-out", {
        "qty": "1", "projectId": 5, "operatorId": 2})
    assert _j(r)["code"] == 40301
    r = _post(c, "/api/v1/consumable/SKU-H/stock-out", {
        "qty": "1", "projectId": 5, "operatorId": 2, "doubleConfirmBy": 3})
    assert _j(r)["data"]["doubleConfirmBy"] == 3
    # 过期批次冻结 → 40301
    _in(c, "SKU-E", "B-Old", "2020-01-01")
    r = _post(c, "/api/v1/consumable/SKU-E/stock-out", {
        "qty": "1", "projectId": 5, "operatorId": 2})
    assert _j(r)["code"] == 40301
    r = _post(c, "/api/v1/consumable/SKU-E/stock-out", {
        "qty": "1", "projectId": 5, "operatorId": 2, "batchNo": "B-Old"})
    assert _j(r)["code"] == 40301
    # 库存不足 → 40901
    r = _post(c, "/api/v1/consumable/SKU-1/stock-out", {
        "qty": "999", "projectId": 5, "operatorId": 2})
    assert _j(r)["code"] == 40901


# ===========================================================================
# A-09/A-12：折旧幂等 + 凭证回调 F-11
# ===========================================================================


def test_depreciation_run_idempotent_and_voucher(seed_auth):
    c = _c()
    d = _full_asset(c, serialNo="SN-D1")  # 120000 / 10 年 → 1000/月
    aid = d["id"]
    # 缺 period → 40001
    r = _post(c, "/api/v1/asset/depreciation/run", {})
    assert _j(r)["code"] == 40001
    r = _post(c, "/api/v1/asset/depreciation/run", {"period": "2026-09"})
    res = _j(r)["data"]
    assert res["processedCount"] == 1 and res["totalDeprAmount"] == 1000
    rec = res["records"][0]
    assert rec["deprAmount"] == 1000 and rec["allocProjectIds"][0]["projectId"] == 5
    a = AAsset.objects.get(id=aid)
    assert a.depr_accum == Decimal("1000") and a.net_value == Decimal("119000")
    # 同月重跑 → 幂等 skip
    r = _post(c, "/api/v1/asset/depreciation/run", {"period": "2026-09"})
    assert _j(r)["data"]["processedCount"] == 0
    assert _j(r)["data"]["skippedCount"] >= 1
    # PENDING_RECEIPT/不计提资产被排除
    _full_asset(c, serialNo="SN-D2", value="0")  # 要素缺失
    r = _post(c, "/api/v1/asset/depreciation/run", {"period": "2026-10"})
    assert all(rr["assetId"] != AAsset.objects.get(serial_no="SN-D2").id
               for rr in _j(r)["data"]["records"])
    # 凭证回调 → POSTED
    dep_id = rec["id"]
    r = _post(c, "/api/v1/finance/voucher", {
        "period": "2026-09",
        "items": [{"depreciationId": dep_id, "voucherId": 555, "posted": True}]},
        user=3, roles=FIN)
    assert _j(r)["data"]["updated"] == 1
    dd = ADepreciation.objects.get(id=dep_id)
    assert dd.posted == 1 and dd.status == "POSTED" and dd.voucher_id == 555


# ===========================================================================
# A-10/A-11：处置（残值复核）+ 盘点盘盈亏
# ===========================================================================


def test_disposal_and_inventory(seed_auth):
    c = _c()
    d = _full_asset(c, serialNo="SN-P1")
    d2 = _full_asset(c, serialNo="SN-P2")
    # 残值 > 原值 → financeReview
    r = _post(c, f"/api/v1/asset/{d['id']}/disposal", {
        "method": "SCRAP", "residualValue": "999999",
        "appraisal": {"conclusion": "已无使用价值"}})
    dp = _j(r)["data"]
    assert dp["financeReview"] is True and dp["code"].startswith("DSP-")
    assert AAsset.objects.get(id=d["id"]).status == "PENDING_DISPOSE"
    # 重复处置 → 40901
    r = _post(c, f"/api/v1/asset/{d['id']}/disposal", {"method": "SELL"})
    assert _j(r)["code"] == 40901
    # 盘点：SN-P2 已采集 → matched；SN-X 盘盈；SN-P3 盘亏（有卡未采集）
    _full_asset(c, serialNo="SN-P3")
    r = _post(c, "/api/v1/asset/inventory", {
        "deptId": 3, "collectedBy": 2,
        "items": [{"serialNo": "SN-P2", "location": "实验楼 301"},
                  {"serialNo": "SN-X", "qty": 1}]})
    inv = _j(r)["data"]
    assert inv["matchedCount"] == 1 and inv["gainCount"] == 1 and inv["lossCount"] == 1
    types = {x["diffType"] for x in inv["differences"]}
    assert types == {"COUNT_GAIN", "COUNT_LOSS"}
    assert all(x["needApproval"] for x in inv["differences"])
    # 盘盈亏落流水
    assert AStockTxn.objects.filter(type__in=("COUNT_GAIN", "COUNT_LOSS")).count() == 2
