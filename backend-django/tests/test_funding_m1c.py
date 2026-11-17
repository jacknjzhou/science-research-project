"""M1-c：合同级拨款（F-22 F_DISBURSEMENT）模型冒烟。"""
import pytest

from apps.funding.models import FDisbursement


@pytest.mark.django_db
def test_m1c_fdisbursement_model_smoke():
    d = FDisbursement.objects.create(
        tenant_id=1, creator_id=1, code="DISB-2026-001",
        contract_id=100, outsource_unit_id=200, project_id=1, legal_entity_id=1,
        amount="50000.00", phase="进度",
        contract_amount="1000000.00", disbursed_before="100000.00",
        remain_contract_amount="900000.00",
        approval_chain=[{"node": 1, "role": "R-FINANCE"}],
        compliance_flags=["single_source_unexplained"],
    )
    assert d.id is not None
    # 默认值（DDL NOT NULL DEFAULT）
    assert d.status == "DRAFT"
    assert d.security_level == "INTERNAL"
    assert d.voucher_status == "PENDING"
    assert d.approval_chain == [{"node": 1, "role": "R-FINANCE"}]
    assert d.compliance_flags == ["single_source_unexplained"]
    assert str(d.disbursed_before) == "100000.00"
    assert d.deleted == 0 and d.remark is None and d.invoice_url is None
    assert d.policy_pack_id is None
    # 回读
    row = FDisbursement.objects.get(id=d.id)
    assert row.code == "DISB-2026-001" and row.contract_id == 100
    assert row.amount == pytest.approx(50000.00)
    # db_table 断言
    assert FDisbursement._meta.db_table == "f_disbursement"


# ===========================================================================
# M1-c Task 3：合同级拨款三端点（TDD 红→绿，真实 POST 集成路径）
# ===========================================================================
import json

from django.test import Client

from tests.conftest import bearer

from apps.procure.models import GContract

CREATE_URL = "/api/v1/disbursements"
CHECK_URL = "/api/v1/disbursements/check-contract"
ACTION_URL = "/api/v1/disbursements/{id}/action"


def _make_contract(amount="1000000.00"):
    return GContract.objects.create(
        tenant_id=1, creator_id=1, contract_type="外协分包",
        amount=amount, status="ACTIVE",
    )


def _create_body(contract_id, amount="500000.00", phase="进度", **kw):
    body = {
        "contractId": contract_id, "outsourceUnitId": 200,
        "projectId": 1, "amount": amount, "phase": phase,
    }
    body.update(kw)
    return body


def _post(url, body, roles=("R-FINANCE",), uid=1, **kw):
    return Client().post(
        url, data=json.dumps(body), content_type="application/json",
        **bearer(uid, list(roles)), **kw,
    )


def _get(url, roles=("R-FINANCE",)):
    return Client().get(url, **bearer(1, list(roles)))


def _resp_json(r):
    return json.loads(r.content)


def _err_code(r):
    return _resp_json(r).get("code")


# --- 1. check-contract：数学语义（REJECTED/SUBMITTED 不计入已拨） ---
@pytest.mark.django_db
def test_check_contract_math(seed_auth):
    c = _make_contract()
    # 已拨：APPROVED 10万 + PAID 5万 + VOUCHER_SYNCED 2万 = 12万计入；
    # SUBMITTED 3万 / REJECTED 999 / DRAFT 777 不计
    for st, amt in [("APPROVED", "100000.00"), ("PAID", "50000.00"),
                    ("VOUCHER_SYNCED", "20000.00"), ("SUBMITTED", "30000.00"),
                    ("REJECTED", "999.00"), ("DRAFT", "777.00")]:
        FDisbursement.objects.create(
            tenant_id=1, creator_id=1, contract_id=c.id,
            outsource_unit_id=200, project_id=1, legal_entity_id=1,
            amount=amt, phase="进度", status=st,
        )
    r = _post(CHECK_URL, {"contractId": c.id, "amount": "100000.00"})
    assert r.status_code == 200, r.content
    data = _resp_json(r)["data"]
    # 契约 DisbursementCheckResult 全键（03 yaml :2710）
    assert set(data.keys()) == {
        "contractId", "contractAmount", "disbursedBefore",
        "remainContractAmount", "canDisburse", "complianceFlags", "ruleHits",
    }
    assert data["contractAmount"] == "1000000.00"
    assert data["disbursedBefore"] == "170000.00"  # 仅 APPROVED+PAID+VOUCHER_SYNCED
    assert data["remainContractAmount"] == "830000.00"
    assert data["canDisburse"] is True
    assert data["complianceFlags"] == [] and data["ruleHits"] == []
    # 恰好等于剩余额 → 可拨（边界 ≤）
    r2 = _post(CHECK_URL, {"contractId": c.id, "amount": "830000.00"})
    assert _resp_json(r2)["data"]["canDisburse"] is True
    # 超剩余额 → 不可拨
    r3 = _post(CHECK_URL, {"contractId": c.id, "amount": "830000.01"})
    d3 = _resp_json(r3)["data"]
    assert d3["canDisburse"] is False
    assert d3["remainContractAmount"] == "830000.00"


@pytest.mark.django_db
def test_check_contract_unknown_contract(seed_auth):
    r = _post(CHECK_URL, {"contractId": 999999, "amount": "1.00"})
    assert r.status_code == 404 and _err_code(r) == 40401


# --- 2. create：校验链 + 快照 + 幂等防重 ---
@pytest.mark.django_db
def test_create_disbursement_ok_and_snapshot(seed_auth):
    c = _make_contract()
    # 预置一笔 APPROVED 占用 10 万
    FDisbursement.objects.create(
        tenant_id=1, creator_id=1, contract_id=c.id, outsource_unit_id=200,
        project_id=1, legal_entity_id=1, amount="100000.00", phase="预付",
        status="APPROVED",
    )
    r = _post(CREATE_URL, _create_body(c.id, "250000.00", securityLevel="SECRET", invoiceUrl="https://x/y.pdf"))
    assert r.status_code == 200, r.content
    d = _resp_json(r)["data"]
    # 契约 Disbursement schema 全键（03 yaml :2671）
    assert set(d.keys()) == {
        "id", "code", "contractId", "outsourceUnitId", "projectId",
        "securityLevel", "amount", "phase", "voucherStatus",
        "contractAmount", "remainContractAmount", "complianceFlags",
        "status", "policyPackId",
    }
    assert d["status"] == "SUBMITTED"  # R-3：无草稿端点，create 直落 SUBMITTED
    assert d["code"].startswith("DISB-")
    assert d["amount"] == "250000.00"
    assert d["contractAmount"] == "1000000.00"
    assert d["remainContractAmount"] == "650000.00"  # 100万 - 已拨10万 - 本次25万
    assert d["securityLevel"] == "SECRET"
    assert d["voucherStatus"] == "PENDING"
    assert d["complianceFlags"] == []
    row = FDisbursement.objects.get(id=d["id"])
    assert row.disbursed_before == __import__("decimal").Decimal("100000.00")
    assert row.remain_contract_amount == __import__("decimal").Decimal("650000.00")


@pytest.mark.django_db
def test_create_invalid_amount_40001(seed_auth):
    c = _make_contract()
    for bad in ("0", "-5", "abc", None, "1.999"):
        r = _post(CREATE_URL, _create_body(c.id, bad))
        assert r.status_code == 400 and _err_code(r) == 40001, (bad, r.content)


@pytest.mark.django_db
def test_create_missing_required_40001(seed_auth):
    c = _make_contract()
    body = {"contractId": c.id, "projectId": 1, "amount": "100.00"}  # 缺 outsourceUnitId/phase
    r = _post(CREATE_URL, body)
    assert r.status_code == 400 and _err_code(r) == 40001


@pytest.mark.django_db
def test_create_unknown_contract_40401(seed_auth):
    r = _post(CREATE_URL, _create_body(999999))
    assert r.status_code == 404 and _err_code(r) == 40401


@pytest.mark.django_db
def test_create_over_remain_422(seed_auth):
    c = _make_contract(amount="100000.00")
    r = _post(CREATE_URL, _create_body(c.id, "100000.01"))
    assert r.status_code == 422 and _err_code(r) == "42201"


@pytest.mark.django_db
def test_create_duplicate_phase_40901(seed_auth):
    c = _make_contract()
    r1 = _post(CREATE_URL, _create_body(c.id, "100.00"))
    assert r1.status_code == 200
    r2 = _post(CREATE_URL, _create_body(c.id, "200.00"))
    assert r2.status_code == 409 and _err_code(r2) == 40901
    # REJECTED 单不占用 (contract,phase) → 可再建
    FDisbursement.objects.filter(
        contract_id=c.id, tenant_id=1, deleted=0).update(status="REJECTED")
    r3 = _post(CREATE_URL, _create_body(c.id, "300.00"))
    assert r3.status_code == 200


# --- 3. action：approve/pay 状态机 + 角色 + 分录 ---
@pytest.mark.django_db
def test_approve_then_pay_with_entry(seed_auth):
    c = _make_contract()
    r = _post(CREATE_URL, _create_body(c.id, "1000.00"))
    did = _resp_json(r)["data"]["id"]
    # R-STAFF（过 casbin? 不——先验 handler 40301：admin 有 casbin 通配）
    r_admin = _post(ACTION_URL.format(id=did), {"action": "approve"}, roles=("R-ADMIN",))
    assert r_admin.status_code == 403 and _err_code(r_admin) == 40301  # R-ADMIN 不代行（R-5）
    r_ok = _post(ACTION_URL.format(id=did), {"action": "approve"}, roles=("R-FINANCE",))
    assert r_ok.status_code == 200, r_ok.content
    assert _resp_json(r_ok)["data"]["status"] == "APPROVED"
    # approve 重放 → 40901
    r_again = _post(ACTION_URL.format(id=did), {"action": "approve"})
    assert r_again.status_code == 409 and _err_code(r_again) == 40901
    # pay 前角色闸（staff 不持 R-FINANCE；R-STAFF 无 casbin action 行也 403，改用双角色验证 handler 闸）
    r_st = _post(ACTION_URL.format(id=did), {"action": "pay"}, roles=("R-MANAGER", "R-STAFF"))
    assert r_st.status_code == 403  # casbin 层即拒（R-MANAGER 无 action 行）
    # pay 成功 → PAID + 分录
    r_pay = _post(ACTION_URL.format(id=did), {"action": "pay"})
    assert r_pay.status_code == 200, r_pay.content
    assert _resp_json(r_pay)["data"]["status"] == "PAID"
    from apps.funding.models import FAccountingEntry
    ae = FAccountingEntry.objects.filter(
        tenant_id=1, source_txn_type="DISBURSEMENT", source_txn_id=did, deleted=0).first()
    assert ae is not None and ae.status == "POSTED"
    fin = ae.fin_entry_json["lines"]
    assert {(x["subject"], x["direction"]) for x in fin} == {("7701", "debit"), ("1002", "credit")}
    assert all(x["amount"] == "1000.00" for x in fin)
    # pay 重放 → 40901
    r_pay2 = _post(ACTION_URL.format(id=did), {"action": "pay"})
    assert r_pay2.status_code == 409 and _err_code(r_pay2) == 40901


@pytest.mark.django_db
def test_pay_requires_approved_state(seed_auth):
    c = _make_contract()
    r = _post(CREATE_URL, _create_body(c.id, "50.00"))
    did = _resp_json(r)["data"]["id"]
    # SUBMITTED 直接 pay → 40901（仅 APPROVED 可 pay）
    r_pay = _post(ACTION_URL.format(id=did), {"action": "pay"})
    assert r_pay.status_code == 409 and _err_code(r_pay) == 40901


@pytest.mark.django_db
def test_action_bad_action_and_unknown_id(seed_auth):
    c = _make_contract()
    r = _post(CREATE_URL, _create_body(c.id, "60.00"))
    did = _resp_json(r)["data"]["id"]
    r_bad = _post(ACTION_URL.format(id=did), {"action": "foo"})
    assert r_bad.status_code == 400 and _err_code(r_bad) == 40001
    r_404 = _post(ACTION_URL.format(id=999999), {"action": "approve"})
    assert r_404.status_code == 404 and _err_code(r_404) == 40401


# --- 4. 分页过滤 ---
@pytest.mark.django_db
def test_page_disbursements_filters(seed_auth):
    c1, c2 = _make_contract(), _make_contract()
    _post(CREATE_URL, _create_body(c1.id, "100.00"))
    _post(CREATE_URL, _create_body(c2.id, "200.00", phase="尾款"))
    r = _get(f"{CREATE_URL}?contractId={c1.id}")
    lst = _resp_json(r)["data"]["list"]
    assert len(lst) == 1 and lst[0]["contractId"] == c1.id
    r2 = _get(f"{CREATE_URL}?projectId=1&status=SUBMITTED")
    assert _resp_json(r2)["data"]["total"] == 2
    r3 = _get(f"{CREATE_URL}?status=PAID")
    assert _resp_json(r3)["data"]["total"] == 0
