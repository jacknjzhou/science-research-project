"""E-7 confsec 域：授权/输出审批/降密按租户收口（跨租户一律 404 / 不生效）。"""
import json

from django.test import Client

from apps.confsec.models import XAccessGrant, XFlowAudit
from tests.conftest import bearer

MFA = {"HTTP_X_MFA_ASSERT": "mfa-ok"}


def _json(r):
    return json.loads(r.content.decode())


def _mk_grant(tenant_id: int = 1) -> XAccessGrant:
    return XAccessGrant.objects.create(
        tenant_id=tenant_id, creator_id=1, subject_user_id=2,
        scope_type="PROJECT", scope_ref=99, granted_level="SECRET", status="EFFECTIVE",
    )


def _mk_flow(tenant_id: int = 1, status: str = "APPLIED") -> XFlowAudit:
    return XFlowAudit.objects.create(
        tenant_id=tenant_id, object_type="DOC", object_id=5, applicant_id=2,
        status=status, security_level="INTERNAL", payload_digest="dig-1",
    )


def test_cross_tenant_revoke_is_404(seed_auth):
    g = _mk_grant()
    r = Client().post("/api/v1/security/revoke",
                      data=json.dumps({"grantId": g.id, "action": "REVOKE", "reason": "x"}),
                      content_type="application/json", **MFA,
                      **bearer(1, ["R-ADMIN"], tenant_id=2))
    assert r.status_code == 404
    g.refresh_from_db()
    assert g.status == "EFFECTIVE"


def test_cross_tenant_export_approve_is_404(seed_auth):
    f = _mk_flow(status="APPLIED")
    r = Client().post("/api/v1/security/export/approve",
                      data=json.dumps({"exportId": f.id, "stage": "PRE_REVIEW",
                                       "verdict": "APPROVE"}),
                      content_type="application/json",
                      **bearer(1, ["R-ADMIN"], tenant_id=2))
    assert r.status_code == 404
    f.refresh_from_db()
    assert f.status == "APPLIED"


def test_cross_tenant_export_release_is_404(seed_auth):
    f = _mk_flow(status="SEC_REVIEW")
    r = Client().post("/api/v1/security/export/release",
                      data=json.dumps({"exportId": f.id, "actualPayloadDigest": "dig-1"}),
                      content_type="application/json", **MFA,
                      **bearer(1, ["R-ADMIN"], tenant_id=2))
    assert r.status_code == 404
    f.refresh_from_db()
    assert f.status == "SEC_REVIEW"


def test_cross_tenant_export_detail_is_404(seed_auth):
    f = _mk_flow()
    r = Client().get(f"/api/v1/security/export/{f.id}", **bearer(2, ["R-STAFF"], tenant_id=2))
    assert r.status_code == 404


def test_cross_tenant_classify_does_not_touch_foreign_asset(seed_auth):
    from apps.asset.models import AAsset

    a = AAsset.objects.create(
        tenant_id=1, creator_id=1, code="AST-E7-1", name="涉密样机",
        category_code="DEV", security_level="INTERNAL",
    )
    r = Client().post("/api/v1/security/classify",
                      data=json.dumps({"targetType": "ASSET", "targetId": a.id,
                                       "op": "SET_LEVEL", "proposedLevel": "SECRET"}),
                      content_type="application/json", **MFA,
                      **bearer(1, ["R-ADMIN"], tenant_id=2))
    assert r.status_code == 200, r.content.decode()  # 登记审计仍可返回
    a.refresh_from_db()
    assert a.security_level == "INTERNAL", "不得改动他租户资产密级"
