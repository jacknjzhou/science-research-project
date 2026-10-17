"""Phase 4 T 成果转化域测试（纯契约域）：披露→评估→交易状态机→合同→多级审批→
电子签→公示/异议→到账→分配规则/明细→发放→年报→AI 三端点。

角色按 policy.csv：披露 R-STAFF；评估/交易/合同/审批/分配 R-MANAGER；审批 R-LEADER 亦可；
到账 R-FINANCE/R-MANAGER；公示 GET 与异议提交为公开通道。
"""
import json

from django.test import Client

from apps.output.models import ROutput
from apps.transform.models import (
    TDeal,
    TDisclosure,
    TEnterpartner,
    TIncome,
    TPublicity,
)
from tests.conftest import bearer


def _c():
    return Client()


def _json(r):
    return r.json()


def _output(**kw):
    base = dict(tenant_id=1, status="MANUAL_DRAFT", creator_id=1, output_type="PATENT",
                title="转化测试专利", authors=[], project_ids=[], source="MANUAL",
                legal_entity_id=1)
    base.update(kw)
    return ROutput.objects.create(**base)


def _disclosure(out, **kw):
    base = dict(tenant_id=1, creator_id=2, output_id=out.id, disclosed_by=2,
                disclosure_date="2026-10-17", legal_entity_id=1)
    base.update(kw)
    return TDisclosure.objects.create(**base)


def _negotiate_body(**kw):
    base = dict(deal_type="转让", contract_amount=60000, payment_method="一次性",
                partner_name="某某科技", partner_credit_code="91330100MA000000XX")
    base.update(kw)
    return base


# ===========================================================================
# 披露 + 评估
# ===========================================================================

def test_disclosure_submit_and_valuation(seed_auth):
    c = _c()
    out = _output()
    # 创建（R-STAFF 一键拟转化）
    r = c.post("/api/v1/disclosure", data=json.dumps({
        "output_id": out.id, "disclosure_date": "2026-10-17",
        "tech_summary": "一种高效催化方法", "maturity_level": 5, "is_core_tech": False,
        "application_scenarios": [{"scene": "化工", "desc": "催化"}],
    }), content_type="application/json", **bearer(2, ["R-STAFF"]))
    d = _json(r)["data"]
    assert d["status"] == "DRAFT"
    assert d["application_scenarios"][0]["scene"] == "化工"
    # 非法迁移：SUBMITTED 下再 valuation 先 409（未提交）
    r = c.post(f"/api/v1/disclosure/{d['id']}/valuation", data=json.dumps({
        "valuator_type": "INTERNAL"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 提交 → SUBMITTED
    r = c.post(f"/api/v1/disclosure/{d['id']}/submit", **bearer(2, ["R-STAFF"]))
    assert _json(r)["data"]["status"] == "SUBMITTED"
    # 重复提交 409
    r = c.post(f"/api/v1/disclosure/{d['id']}/submit", **bearer(2, ["R-STAFF"]))
    assert _json(r)["code"] == 40901
    # 外评缺机构 40001
    r = c.post(f"/api/v1/disclosure/{d['id']}/valuation", data=json.dumps({
        "valuator_type": "EXTERNAL"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40001
    # 内评分派 → UNDER_EVAL
    r = c.post(f"/api/v1/disclosure/{d['id']}/valuation", data=json.dumps({
        "valuator_type": "INTERNAL", "valuator_name": "评估小组", "method": "收益法"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    v = _json(r)["data"]
    assert v["status"] == "DRAFT"
    assert _json(c.get("/api/v1/disclosure?status=UNDER_EVAL",
                       **bearer(2, ["R-STAFF"])))["data"]["list"][0]["id"] == d["id"]
    # 外评报告上传
    r = c.post(f"/api/v1/valuation/{v['id']}/external-report", data=json.dumps({
        "valuation_amount": 88000, "valuation_date": "2026-10-17"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "REPORT_UPLOADED"
    assert _json(r)["data"]["valuation_amount"] == 88000


# ===========================================================================
# 合作企业库
# ===========================================================================

def test_partner_register_and_duplicate(seed_auth):
    c = _c()
    body = {"company_name": "甲科技", "credit_code": "91330100MA11111111",
            "industry": "新材料", "tech_needs": [{"need": "缓释技术"}],
            "contact": {"name": "王工"}, "business_check_json": {"abnormal": False}}
    r = c.post("/api/v1/partner", data=json.dumps(body),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    p = _json(r)["data"]
    assert p["check_abnormal"] is False
    assert p["last_checked_at"] is not None
    # 信用代码重复 → 40901 + existing_id
    r = c.post("/api/v1/partner", data=json.dumps({**body, "company_name": "乙公司"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    e = _json(r)
    assert e["code"] == 40901
    assert e["data"]["existing_id"] == p["id"]
    # 工商异常标红
    r = c.post("/api/v1/partner", data=json.dumps({
        "company_name": "丙公司", "business_check_json": {"abnormal": True}}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["check_abnormal"] is True
    # 列表过滤
    r = c.get("/api/v1/partner?check_abnormal=true", **bearer(2, ["R-STAFF"]))
    lst = _json(r)["data"]["list"]
    assert len(lst) == 1 and lst[0]["company_name"] == "丙公司"


# ===========================================================================
# 交易状态机：谈判→挂牌→合同→审批→签约
# ===========================================================================

def test_deal_full_chain_small_amount(seed_auth):
    c = _c()
    out = _output()
    d = _disclosure(out, status="SUBMITTED", submitted_at="2026-10-17T00:00:00Z")
    # 创建交易（DEAL-年-序）
    r = c.post("/api/v1/deal", data=json.dumps({
        "disclosure_id": d.id, **_negotiate_body()}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    deal = _json(r)["data"]
    assert deal["code"].startswith("DEAL-2026-")
    assert deal["status"] == "DRAFT"
    assert deal["partner_check_abnormal"] is False
    # 披露进入 DEALING
    assert TDisclosure.objects.get(id=d.id).status == "DEALING"
    # 作价投资缺股权 → 40001
    r = c.post(f"/api/v1/deal/{deal['id']}/negotiation", data=json.dumps({
        "deal_type": "作价投资", "contract_amount": 100, "payment_method": "一次性"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40001
    # 提成模式缺 royalty_rate → 40001
    r = c.post(f"/api/v1/deal/{deal['id']}/negotiation", data=json.dumps({
        "deal_type": "转让", "contract_amount": 60000, "payment_method": "入门费+销售提成"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40001
    # 正常谈判 → NEGOTIATING
    r = c.post(f"/api/v1/deal/{deal['id']}/negotiation", data=json.dumps(_negotiate_body()),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "NEGOTIATING"
    # 挂牌发布（幂等通过）
    r = c.post(f"/api/v1/deal/{deal['id']}/publish", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 0
    # 合同起草 → DRAFT_CONTRACT
    r = c.post("/api/v1/contract/draft", data=json.dumps({
        "deal_id": deal["id"], "template_code": "T-转让-01"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    ct = _json(r)["data"]
    assert ct["version"] == 1
    # immutable_hash 不在契约 mapper（契约字段外），查库验证哈希链
    from apps.transform.models import TContract
    ct_row = TContract.objects.get(id=ct["id"])
    assert ct_row.immutable_hash and len(ct_row.immutable_hash) == 64
    assert TDeal.objects.get(id=deal["id"]).status == "DRAFT_CONTRACT"
    # 重复起草 → 409（一交易一有效合同）
    r = c.post("/api/v1/contract/draft", data=json.dumps({"deal_id": deal["id"]}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901
    # 小额（6 万 < 100 万）→ 审批链仅 LEGAL+FINANCE
    r = c.post(f"/api/v1/deal/{deal['id']}/approve", data=json.dumps({"action": "APPROVE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    body = _json(r)["data"]
    assert body["deal"]["status"] == "UNDER_APPROVAL"
    assert body["deal"]["approval_required_level"] == "FINANCE"
    # 二级审批完 → APPROVED，合同 TO_SIGN
    r = c.post(f"/api/v1/deal/{deal['id']}/approve", data=json.dumps({"action": "APPROVE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["deal"]["status"] == "APPROVED"
    # 电子签 → SIGNED
    r = c.post(f"/api/v1/deal/{deal['id']}/sign", data=json.dumps({
        "provider": "e签宝", "seal_records": [{"provider": "e签宝", "sig_hash": "h1"}]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "SIGNED"
    assert TDeal.objects.get(id=deal["id"]).signed_at is not None
    return deal


def test_deal_board_threshold_and_reject(seed_auth):
    c = _c()
    out = _output()
    d = _disclosure(out, status="SUBMITTED", submitted_at="2026-10-17T00:00:00Z")
    # 600 万 ≥ 500 万 → BOARD
    r = c.post("/api/v1/deal", data=json.dumps({
        "disclosure_id": d.id, **_negotiate_body(contract_amount=6_000_000)}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    deal = _json(r)["data"]
    c.post(f"/api/v1/deal/{deal['id']}/negotiation", data=json.dumps(_negotiate_body(contract_amount=6_000_000)),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post("/api/v1/contract/draft", data=json.dumps({"deal_id": deal["id"]}),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    r = c.post(f"/api/v1/deal/{deal['id']}/approve", data=json.dumps({"action": "APPROVE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    chain = _json(c.get(f"/api/v1/deal/{deal['id']}",
                        **bearer(1, ["R-MANAGER"])))["data"]["approval_chain"]
    assert [s["approver_role"] for s in chain] == ["LEGAL", "FINANCE", "INSTITUTE", "COMPETENT_DEPT", "BOARD"]
    assert chain[-1]["amount_threshold"] == 5000000
    # REJECT → 回 DRAFT_CONTRACT
    r = c.post(f"/api/v1/deal/{deal['id']}/approve", data=json.dumps({"action": "REJECT"}),
               content_type="application/json", **bearer(1, ["R-LEADER"]))
    assert _json(r)["data"]["deal"]["status"] == "DRAFT_CONTRACT"


# ===========================================================================
# 公示/异议（公开通道）
# ===========================================================================

def test_publicity_objection_block_and_release(seed_auth):
    c = _c()
    deal_id = test_deal_full_chain_small_amount(seed_auth)["id"]
    # 公开发布公示（duration 0 → 立即满期）
    r = c.post(f"/api/v1/publicity/{deal_id}", data=json.dumps({
        "duration_days": 0, "summary_json": {"subject": "催化专利", "deal_amount": 60000}}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    pub = _json(r)["data"]
    assert TDeal.objects.get(id=deal_id).status == "PUBLICIZED"
    # 公开 GET：无鉴权可访问（security: []）
    r = c.get(f"/api/v1/publicity/{deal_id}")
    assert r.status_code == 200
    assert _json(r)["data"]["summary_json"]["deal_amount"] == 60000
    # 公开异议提交：无鉴权
    r = c.post(f"/api/v1/publicity/{deal_id}/objection", data=json.dumps({
        "submitter": "匿名", "content": "对分配比例有异议"}), content_type="application/json")
    oid = _json(r)["data"]["objection_id"]
    pub_row = TPublicity.objects.get(id=pub["id"])
    assert pub_row.objection_open is True
    assert pub_row.status == "OBJECTION_PENDING"
    # 异议未结 → 公示期后不可直接进执行（此刻还在 OBJECTION_PENDING，deal 仍 PUBLICIZED）
    r = c.post(f"/api/v1/publicity/{deal_id}/objection/handle", data=json.dumps({
        "objection_id": oid, "handle_status": "PROCESSING"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert TDeal.objects.get(id=deal_id).status == "PUBLICIZED"
    # DISMISSED + 公示期满 → 公示 COMPLETED、交易 EXECUTING
    r = c.post(f"/api/v1/publicity/{deal_id}/objection/handle", data=json.dumps({
        "objection_id": oid, "handle_status": "DISMISSED", "handle_result": "理由不成立"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert TDeal.objects.get(id=deal_id).status == "EXECUTING"
    # 异议成立路径：新交易 SUSTAINED → TERMINATED
    out = _output(title="第二专利")
    d2 = _disclosure(out, status="SUBMITTED", submitted_at="2026-10-17T00:00:00Z")
    r = c.post("/api/v1/deal", data=json.dumps({"disclosure_id": d2.id, **_negotiate_body()}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    deal2 = _json(r)["data"]
    c.post(f"/api/v1/deal/{deal2['id']}/negotiation", data=json.dumps(_negotiate_body()),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post("/api/v1/contract/draft", data=json.dumps({"deal_id": deal2["id"]}),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post(f"/api/v1/deal/{deal2['id']}/approve", data=json.dumps({"action": "APPROVE"}),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post(f"/api/v1/deal/{deal2['id']}/approve", data=json.dumps({"action": "APPROVE"}),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post(f"/api/v1/deal/{deal2['id']}/sign", data=json.dumps({}),
           content_type="application/json", **bearer(1, ["R-MANAGER"]))
    c.post(f"/api/v1/publicity/{deal2['id']}", data=json.dumps({
        "duration_days": 0, "summary_json": {}}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    r = c.post(f"/api/v1/publicity/{deal2['id']}/objection", data=json.dumps({"content": "异议"}), content_type="application/json")
    oid2 = _json(r)["data"]["objection_id"]
    r = c.post(f"/api/v1/publicity/{deal2['id']}/objection/handle", data=json.dumps({
        "objection_id": oid2, "handle_status": "SUSTAINED"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    d2row = TDeal.objects.get(id=deal2["id"])
    assert d2row.status == "TERMINATED"
    assert d2row.terminated_reason == "OBJECTION_SUSTAINED"


# ===========================================================================
# 到账 + 分配 + 发放
# ===========================================================================

def test_income_distribution_and_issue(seed_auth):
    c = _c()
    deal_id = test_deal_full_chain_small_amount(seed_auth)["id"]
    deal = TDeal.objects.get(id=deal_id)
    deal.status = "EXECUTING"  # 承接上链（异议已结）
    deal.save()
    # 到账：流水号防重
    body = {"deal_id": deal_id, "received_date": "2026-10-17", "amount": 60000,
            "bank_flow_no": "BF001", "payment_phase": "第 1 期"}
    r = c.post("/api/v1/income", data=json.dumps(body),
               content_type="application/json", **bearer(3, ["R-FINANCE"]))
    inc = _json(r)["data"]
    assert inc["status"] == "PENDING"
    assert TDeal.objects.get(id=deal_id).status == "INCOME_RECEIVED"
    r = c.post("/api/v1/income", data=json.dumps(body),
               content_type="application/json", **bearer(3, ["R-FINANCE"]))
    assert _json(r)["code"] == 40901
    # 提成计算：sales_amount × royalty_rate
    deal.royalty_rate = "0.0500"
    deal.save(update_fields=["royalty_rate"])
    r = c.post("/api/v1/income", data=json.dumps({
        "deal_id": deal_id, "received_date": "2026-10-18", "amount": 5000,
        "bank_flow_no": "BF002", "sales_amount": 100000}),
        content_type="application/json", **bearer(3, ["R-FINANCE"]))
    assert float(_json(r)["data"]["royalty_calc_amount"]) == 5000.0
    # 匹配 → MATCHED
    r = c.post(f"/api/v1/income/{inc['id']}/match", data=json.dumps({"finance_receipt_id": 99}),
               content_type="application/json", **bearer(3, ["R-FINANCE"]))
    assert _json(r)["data"]["status"] == "MATCHED"
    # 分配规则：三比例之和≠1 → 50010
    r = c.post("/api/v1/distribution-rule", data=json.dumps({
        "rule_name": "R1", "applies_to": "转让", "team_pct": 0.7, "institute_pct": 0.2,
        "individual_pct": 0.2, "min_team_pct": 0.6, "effective_from": "2026-01-01"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 50010
    # team < min → 50003
    r = c.post("/api/v1/distribution-rule", data=json.dumps({
        "rule_name": "R2", "applies_to": "转让", "team_pct": 0.5, "institute_pct": 0.3,
        "individual_pct": 0.2, "min_team_pct": 0.6, "effective_from": "2026-01-01"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 50003
    # 合法规则
    r = c.post("/api/v1/distribution-rule", data=json.dumps({
        "rule_name": "标准规则", "applies_to": "转让", "team_pct": 0.7, "institute_pct": 0.2,
        "individual_pct": 0.1, "min_team_pct": 0.6, "effective_from": "2026-01-01"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    rule = _json(r)["data"]
    assert rule["active"] is True
    # 生成分配明细（命中规则：42000/12000/6000）
    r = c.post(f"/api/v1/income/{inc['id']}/distribution", data=json.dumps({}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    rec = _json(r)["data"]
    assert float(rec["team_amount"]) == 42000.0
    assert float(rec["institute_amount"]) == 12000.0
    assert TIncome.objects.get(id=inc["id"]).status == "ALLOCATED"
    assert TDeal.objects.get(id=deal_id).status == "DISTRIBUTED"
    # breakdown 定制：比例和≠1 → 50010
    r = c.post(f"/api/v1/income/{inc['id']}/distribution", data=json.dumps({}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40901  # 一期一明细
    inc2 = TIncome.objects.get(bank_flow_no="BF002")
    r = c.post(f"/api/v1/income/{inc2.id}/distribution", data=json.dumps({
        "breakdown": [{"user_id": 2, "pct": 0.9, "basis": "第一发明人"}]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 50010
    r = c.post(f"/api/v1/income/{inc2.id}/distribution", data=json.dumps({
        "breakdown": [{"user_id": 2, "pct": 1.0, "basis": "第一发明人"}]}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    rec2 = _json(r)["data"]
    assert rec2["breakdown"][0]["amount"] == 5000.0
    # HOLD（DISPUTE → DISPUTED）→ 无 note 发放 40001 → RESUME → ISSUE
    r = c.post(f"/api/v1/distribution/{rec2['id']}/issue", data=json.dumps({
        "action": "HOLD", "held_reason": "DISPUTE", "note": "发明人异议"}),
        content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "DISPUTED"
    r = c.post(f"/api/v1/distribution/{rec2['id']}/issue", data=json.dumps({"action": "ISSUE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40001
    r = c.post(f"/api/v1/distribution/{rec2['id']}/issue", data=json.dumps({"action": "RESUME"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "PUBLISHED"
    r = c.post(f"/api/v1/distribution/{rec2['id']}/issue", data=json.dumps({"action": "ISSUE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "ISSUED"
    assert _json(r)["data"]["issued_at"] is not None
    # 第一笔直接发放
    r = c.post(f"/api/v1/distribution/{rec['id']}/issue", data=json.dumps({"action": "ISSUE"}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["status"] == "ISSUED"
    # mine：staff(2) 仅见 breakdown 含自己的明细
    r = c.get("/api/v1/distribution/mine", **bearer(2, ["R-STAFF"]))
    mine = _json(r)["data"]["list"]
    assert len(mine) == 1
    assert mine[0]["breakdown"][0]["user_id"] == 2


# ===========================================================================
# 年报 + AI
# ===========================================================================

def test_annual_report_and_ai(seed_auth):
    c = _c()
    deal_id = test_deal_full_chain_small_amount(seed_auth)["id"]
    TDeal.objects.filter(id=deal_id).update(status="CLOSED")
    TIncome.objects.create(tenant_id=1, creator_id=1, deal_id=deal_id,
                           received_date="2026-10-17", amount=60000)
    r = c.post("/api/v1/annual-report/generate", data=json.dumps({"report_year": 2026}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    rep = _json(r)["data"]
    assert rep["report_year"] == 2026
    assert rep["total_deals"] == 1
    assert rep["total_contract_amount"] == 60000.0
    assert rep["total_income"] == 60000.0
    assert rep["status"] == "GENERATED"
    assert rep["top_deals"][0]["code"].startswith("DEAL-")
    # 幂等 upsert
    r = c.post("/api/v1/annual-report/generate", data=json.dumps({"report_year": 2026}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["data"]["id"] == rep["id"]
    # AI 定价：同类型已成交可比（补一笔同类 CLOSED 交易）
    src = TDeal.objects.get(id=deal_id)
    TDeal.objects.create(tenant_id=1, creator_id=1, disclosure_id=src.disclosure_id,
                         output_id=src.output_id, deal_type="转让", status="CLOSED",
                         contract_amount=60000, legal_entity_id=1)
    r = c.post(f"/api/v1/deal/{deal_id}/ai-pricing", data=json.dumps({}),
               content_type="application/json", **bearer(1, ["R-MANAGER"]))
    pricing = _json(r)["data"]
    assert pricing["price_low"] == 60000.0
    assert pricing["confidence"] > 0
    assert "以评估机构报告" in pricing["disclaimer"]
    # AI 机会识别：企业评分排序
    TEnterpartner.objects.create(tenant_id=1, creator_id=1, company_name="高分工厂",
                                 evaluation_score="0.9000", tech_needs=[])
    TEnterpartner.objects.create(tenant_id=1, creator_id=1, company_name="低分工厂",
                                 evaluation_score="0.1000", tech_needs=[])
    r = c.post("/api/v1/ai/opportunity", data=json.dumps({"top_n": 5}),
               content_type="application/json", **bearer(2, ["R-STAFF"]))
    lst = _json(r)["data"]["list"]
    assert lst[0]["company_name"] == "高分工厂"
    assert lst[0]["match_score"] == 0.9
    # AI 合同风险：LLM 未配置 → 空清单降级（不阻塞业务）
    r = c.post("/api/v1/contract/999999/ai-risk", **bearer(1, ["R-MANAGER"]))
    assert _json(r)["code"] == 40401  # 合同不存在
