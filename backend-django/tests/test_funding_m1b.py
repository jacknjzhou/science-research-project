"""M1-b：成本池/平行记账/决算/凭证同步（A4/A5/A7）模型冒烟。"""
import pytest

from apps.funding.models import FCostPool, FAccountingEntry, FSettlement, FVoucherSync


@pytest.mark.django_db
def test_m1b_models_crud_smoke():
    cp = FCostPool.objects.create(tenant_id=1, creator_id=1, project_id=1,
        legal_entity_id=1, period="202611", direct_cost="100.00", full_cost="120.00")
    assert cp.status == "DRAFT" and str(cp.direct_cost) == "100.00"
    ae = FAccountingEntry.objects.create(tenant_id=1, creator_id=1, source_txn_id=cp.id,
        source_txn_type="EXPENSE", legal_entity_id=1, period="202611",
        fin_entry_json={"lines": []}, bud_entry_json={"lines": []})
    assert ae.reconcile_status == "UNRECONCILED" and ae.posted_finance is False
    vs = FVoucherSync.objects.create(tenant_id=1, creator_id=1, expense_id=1, finance_system="YONYOU")
    assert vs.sync_status == "PENDING" and vs.retry_count == 0
    st = FSettlement.objects.create(tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1)
    assert st.status == "DRAFT" and st.treatment == "结转"
