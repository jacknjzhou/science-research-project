"""M1-a：差旅标准/开票/借款（A1-A3）"""
import json
from datetime import timedelta

from django.test import Client
from django.utils import timezone as dj_tz

from apps.funding.models import FExpense, FInvoice, FTravelStandard
from tests.conftest import bearer


def _c():
    return Client()


def _standard(**kw):
    base = dict(
        tenant_id=1,
        name="住宿标准",
        staff_category="普通员工",
        city_tier="一线城市",
        accommodation_cap=300,
        meals_cap=100,
        transport_cap=80,
        effective_from=dj_tz.localdate() - timedelta(days=30),
        effective_to=None,
        status="ACTIVE",
        creator_id=1,
    )
    base.update(kw)
    return FTravelStandard.objects.create(**base)


_CREATE_BODY = {
    "name": "住宿标准",
    "staffCategory": "普通员工",
    "cityTier": "一线城市",
    "accommodationCap": "300",
    "mealsCap": "100.5",
    "transportCap": "80",
    "effectiveFrom": "2026-01-01",
}


# ---------------------------------------------------------------------------
# 差旅费用标准（A3）
# ---------------------------------------------------------------------------
def test_travel_standard_create(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    w = r.json()["data"]
    assert w["id"] > 0
    assert w["name"] == "住宿标准"
    assert w["staffCategory"] == "普通员工" and w["cityTier"] == "一线城市"
    # 金额一律 num2 字符串
    assert w["accommodationCap"] == "300.00"
    assert w["mealsCap"] == "100.50"
    assert w["transportCap"] == "80.00"
    assert w["effectiveFrom"] == "2026-01-01"
    assert w["effectiveTo"] is None
    assert w["status"] == "ACTIVE"


def test_travel_standard_create_conflict_40901(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    wid = r.json()["data"]["id"]
    # 同 (staffCategory, cityTier) 再建 ACTIVE → 40901
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # 原记录置 DISABLED 后，同组合允许再建 ACTIVE
    r = c.put(
        f"/api/v1/travel-standards/{wid}",
        data=json.dumps({"status": "DISABLED"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.json()["data"]["status"] == "DISABLED"
    r = c.post(
        "/api/v1/travel-standards",
        data=json.dumps(_CREATE_BODY),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200


def test_travel_standard_update_conflict_40901(seed_auth):
    c = _c()
    a = _standard(staff_category="高管", city_tier="二线城市")
    b = _standard(staff_category="普通员工", city_tier="二线城市")
    # 把 b 改成与 a 相同的 ACTIVE 组合 → 40901
    r = c.put(
        f"/api/v1/travel-standards/{b.id}",
        data=json.dumps({"staffCategory": "高管"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # 自身不变更组合（排除自身）不冲突
    r = c.put(
        f"/api/v1/travel-standards/{a.id}",
        data=json.dumps({"name": "高管标准V2"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "高管标准V2"


def test_travel_standard_update_and_soft_delete(seed_auth):
    c = _c()
    row = _standard()
    r = c.put(
        f"/api/v1/travel-standards/{row.id}",
        data=json.dumps({"accommodationCap": "400", "name": "住宿标准V2"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["accommodationCap"] == "400.00" and d["name"] == "住宿标准V2"
    assert d["mealsCap"] == "100.00"  # 未传不覆盖
    # 软删：deleted=1，行仍在
    r = c.delete(f"/api/v1/travel-standards/{row.id}", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    assert FTravelStandard.objects.get(pk=row.id).deleted == 1
    # 列表不可见
    r = c.get("/api/v1/travel-standards", **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 0
    # 删后再 PUT/DELETE → 404
    r = c.put(
        f"/api/v1/travel-standards/{row.id}",
        data=json.dumps({"name": "x"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    r = c.delete(f"/api/v1/travel-standards/{row.id}", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 404


def test_travel_standard_list_filters(seed_auth):
    _standard(staff_category="普通员工", city_tier="一线城市")
    _standard(staff_category="高管", city_tier="二线城市")
    _standard(staff_category="普通员工", city_tier="二线城市", status="DISABLED")
    c = _c()
    r = c.get("/api/v1/travel-standards", **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 3
    r = c.get("/api/v1/travel-standards", data={"staffCategory": "普通员工"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 2
    r = c.get("/api/v1/travel-standards", data={"cityTier": "二线城市"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 2
    r = c.get("/api/v1/travel-standards", data={"status": "ACTIVE"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 2


def test_travel_standard_match(seed_auth):
    c = _c()
    today = dj_tz.localdate()
    row = _standard(
        staff_category="普通员工",
        city_tier="一线城市",
        effective_from=today - timedelta(days=30),
        effective_to=None,  # 长期有效
    )
    # 命中：date 缺省 → 今天
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "普通员工", "cityTier": "一线城市"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["id"] == row.id
    # 区间内指定日期 → 命中
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "普通员工", "cityTier": "一线城市", "date": str(today - timedelta(days=1))},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.json()["data"]["id"] == row.id
    # effective_to 边界：有效至今天 → 今天命中
    row2 = _standard(
        staff_category="高管",
        city_tier="一线城市",
        effective_from=today - timedelta(days=30),
        effective_to=today,
    )
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "高管", "cityTier": "一线城市"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.json()["data"]["id"] == row2.id
    # 过期（区间外）→ 40401
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "高管", "cityTier": "一线城市", "date": str(today + timedelta(days=1))},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # 无任何匹配记录 → 40401
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "外包", "cityTier": "三线城市"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # 缺必填参数 → 400
    r = c.get(
        "/api/v1/travel-standards/match",
        data={"staffCategory": "普通员工"},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 发票（A1）：CRUD + bind/void + is_duplicated
# ---------------------------------------------------------------------------
def _invoice_body(**kw):
    base = dict(
        number="INV2026001",
        invoiceCode="044032600111",
        invoiceType="ELECTRONIC",
        sellerName="某某科技有限公司",
        sellerTaxId="91440300MA5XXXXX00",
        buyerName="某研究院",
        buyerTaxId="12100000XXXXXXXXXX",
        amountExclTax="900",
        taxAmount="100",
        totalAmount="1000",
        issueDate="2026-11-01",
        remark="差旅住宿发票",
    )
    base.update(kw)
    return base


def _expense(**kw):
    base = dict(
        tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1,
        applicant_user_id=1, amount=1000, expense_type="TRAVEL",
    )
    base.update(kw)
    return FExpense.objects.create(**base)


def test_invoice_create(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body()),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    inv = r.json()["data"]
    assert inv["id"] > 0
    # 手工建票：status=DRAFT、code=INV-年-序 回填
    assert inv["status"] == "DRAFT"
    year = dj_tz.localdate().year
    assert inv["code"] == f"INV-{year}-{inv['id']:06d}"
    assert inv["number"] == "INV2026001"
    assert inv["totalAmount"] == "1000.00"
    assert inv["amountExclTax"] == "900.00"
    assert inv["taxAmount"] == "100.00"
    assert inv["issueDate"] == "2026-11-01"
    assert inv["remark"] == "差旅住宿发票"
    assert inv["isDuplicated"] is False
    assert inv["expenseId"] is None


def test_invoice_create_validation_40001(seed_auth):
    c = _c()
    # 必填校验：缺 number → 40001
    body = _invoice_body()
    body.pop("number")
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(body),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 400
    # 必填校验：缺 totalAmount → 40001
    body = _invoice_body()
    body.pop("totalAmount")
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(body),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 400
    # totalAmount 非法/≤0 → 40001
    for bad in ("abc", "0", "-5"):
        r = c.post(
            "/api/v1/invoices",
            data=json.dumps(_invoice_body(number=f"N-{bad}", totalAmount=bad)),
            content_type="application/json",
            **bearer(1, ["R-FINANCE"]),
        )
        assert r.status_code == 400


def test_invoice_create_duplicated_flag(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body()),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is False
    # 同号同额同日期第二张 → is_duplicated=true，仍创建成功（仅标记不拦截）
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body()),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    inv2 = r.json()["data"]
    assert inv2["isDuplicated"] is True
    # 第三张同样标记
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body()),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is True
    # 号码相同但金额不同 → 不算重复
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body(totalAmount="2000")),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is False
    # 号码相同金额日期相同但 issueDate 不同 → 不算重复
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body(issueDate="2026-11-02")),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is False
    # VOID 的重复源不参与查重：作废第一张后，新建同三元组不再标记
    first = FInvoice.objects.order_by("id").first()
    r = c.post(f"/api/v1/invoices/{first.id}/void", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body(issueDate="2026-11-03")),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is False


def test_invoice_get_update_40901(seed_auth):
    c = _c()
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body()),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    inv = r.json()["data"]
    iid = inv["id"]
    # GET 详情
    r = c.get(f"/api/v1/invoices/{iid}", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    assert r.json()["data"]["id"] == iid
    # PUT：部分更新（仅提供的字段被覆盖）
    r = c.put(
        f"/api/v1/invoices/{iid}",
        data=json.dumps({"totalAmount": "1200", "remark": "改过"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["totalAmount"] == "1200.00"
    assert d["remark"] == "改过"
    assert d["number"] == "INV2026001"  # 未传不覆盖
    assert d["status"] == "DRAFT"  # 修改不改变 status
    # PUT 后重算 is_duplicated：改成已有三元组 → true
    r = c.put(
        f"/api/v1/invoices/{iid}",
        data=json.dumps({"number": "DUP-001", "totalAmount": "55", "issueDate": "2026-10-01"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is False  # 仅自身一条
    # 再造一张同三元组的 → 新票标记 true（仅标记不拦截）
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body(number="DUP-001", totalAmount="55", issueDate="2026-10-01")),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is True
    # 已存票 #1 的存储标记不因他人创建而回溯翻转（标记只在自身写入时重算）
    r = c.get(f"/api/v1/invoices/{iid}", **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["isDuplicated"] is False
    # 自身再次 PUT（任意字段）→ 重算 exclude_id=self → 发现 #2 → true
    r = c.put(
        f"/api/v1/invoices/{iid}",
        data=json.dumps({"remark": "refresh"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["isDuplicated"] is True
    # PUT 不存在 → 40401
    r = c.put(
        "/api/v1/invoices/999999",
        data=json.dumps({"remark": "x"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # BOUND 后 PUT → 40901
    e = _expense()
    r = c.post(
        f"/api/v1/invoices/{iid}/bind",
        data=json.dumps({"expenseId": e.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "BOUND"
    r = c.put(
        f"/api/v1/invoices/{iid}",
        data=json.dumps({"remark": "no"}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901


def test_invoice_bind_and_void(seed_auth):
    c = _c()
    e = _expense()
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body()),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    iid = r.json()["data"]["id"]
    # bind 后：expense.invoice_ids 含该 id、发票 expense_id 落值、status=BOUND
    r = c.post(
        f"/api/v1/invoices/{iid}/bind",
        data=json.dumps({"expenseId": e.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "BOUND"
    e.refresh_from_db()
    assert iid in e.invoice_ids
    assert FInvoice.objects.get(pk=iid).expense_id == e.id
    # 幂等：重复 bind 同一 expense → 仍 200，invoice_ids 不重复追加
    r = c.post(
        f"/api/v1/invoices/{iid}/bind",
        data=json.dumps({"expenseId": e.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    e.refresh_from_db()
    assert e.invoice_ids.count(iid) == 1
    # bind 到不存在的 expense → 40401
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body(number="BIND2")),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    iid2 = r.json()["data"]["id"]
    r = c.post(
        f"/api/v1/invoices/{iid2}/bind",
        data=json.dumps({"expenseId": 999999}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # bind 已 BOUND 票到另一 expense → 40901（不可重复绑定）
    e2 = _expense()
    r = c.post(
        f"/api/v1/invoices/{iid}/bind",
        data=json.dumps({"expenseId": e2.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # void BOUND 票 → 40901
    r = c.post(f"/api/v1/invoices/{iid}/void", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # void DRAFT 票 → VOID（终态）
    r = c.post(f"/api/v1/invoices/{iid2}/void", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "VOID"
    # VOID 终态：再 void 仍 200 VOID；再 bind → 40901
    r = c.post(f"/api/v1/invoices/{iid2}/void", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "VOID"
    r = c.post(
        f"/api/v1/invoices/{iid2}/bind",
        data=json.dumps({"expenseId": e.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # OCR_DONE 也可 bind（发票须 DRAFT/OCR_DONE/CHECKED）
    inv3 = FInvoice.objects.create(
        tenant_id=1, creator_id=1, number="OCR1", status="OCR_DONE", total_amount=100,
    )
    r = c.post(
        f"/api/v1/invoices/{inv3.id}/bind",
        data=json.dumps({"expenseId": e.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "BOUND"
    # bind 缺 expenseId → 40001
    inv4 = FInvoice.objects.create(
        tenant_id=1, creator_id=1, number="OCR2", status="OCR_DONE", total_amount=100,
    )
    r = c.post(
        f"/api/v1/invoices/{inv4.id}/bind",
        data=json.dumps({}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 400
    # bind PAID 报销单 → 40901（报销单须未 PAID）
    e3 = _expense(status="PAID")
    inv5 = FInvoice.objects.create(
        tenant_id=1, creator_id=1, number="OCR3", status="OCR_DONE", total_amount=100,
    )
    r = c.post(
        f"/api/v1/invoices/{inv5.id}/bind",
        data=json.dumps({"expenseId": e3.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    # 不存在的发票 → 40401
    r = c.post("/api/v1/invoices/999999/void", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 404
    assert r.json()["code"] == 40401


def test_invoice_list_filters(seed_auth):
    c = _c()
    e = _expense()
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body(number="L1")),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    iid1 = r.json()["data"]["id"]
    r = c.post(
        "/api/v1/invoices",
        data=json.dumps(_invoice_body(number="L2")),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    iid2 = r.json()["data"]["id"]
    # 绑定第一张到 expense，作废第二张
    r = c.post(
        f"/api/v1/invoices/{iid1}/bind",
        data=json.dumps({"expenseId": e.id}),
        content_type="application/json",
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.status_code == 200
    r = c.post(f"/api/v1/invoices/{iid2}/void", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 200
    # 不带过滤：2 条
    r = c.get("/api/v1/invoices", **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 2
    # expenseId 过滤
    r = c.get("/api/v1/invoices", data={"expenseId": e.id}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["list"][0]["id"] == iid1
    # status 过滤
    r = c.get("/api/v1/invoices", data={"status": "BOUND"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["list"][0]["id"] == iid1
    r = c.get("/api/v1/invoices", data={"status": "VOID"}, **bearer(1, ["R-FINANCE"]))
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["list"][0]["id"] == iid2
    # status=BOUND + expenseId 组合过滤
    r = c.get(
        "/api/v1/invoices",
        data={"status": "BOUND", "expenseId": e.id},
        **bearer(1, ["R-FINANCE"]),
    )
    assert r.json()["data"]["total"] == 1
    # GET 不存在 → 40401
    r = c.get("/api/v1/invoices/999999", **bearer(1, ["R-FINANCE"]))
    assert r.status_code == 404
    assert r.json()["code"] == 40401
