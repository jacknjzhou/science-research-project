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
