"""Phase 4 X 涉密管理与多法人治理域测试（纯契约域）。

法人树/并表 → 密级策略发布（MFA 三员分立）→ 授权（SECRET+ 强制 MFA）→
涉密输出双审 + 二次鉴别放行（指纹防篡改 + zone-guard 防探测）→
安全日志 SM3 哈希链（防篡改校验）→ 涉密人员审查/清退（授权自动收敛）。
"""
import json
from decimal import Decimal

from django.test import Client

from apps.asset.models import AAsset
from apps.confsec.models import XAccessGrant, XFlowAudit, XPersonnelSec, XSecLog
from apps.sysadmin.models import SysLegalEntity
from tests.conftest import bearer

AD = ["R-ADMIN"]
ST = ["R-STAFF"]
MFA = {"HTTP_X_MFA_ASSERT": "mfa-assert-token"}


def _c():
    return Client()


def _j(r):
    return r.json()


def _post(c, url, body, user=1, roles=AD, **extra):
    return c.post(url, data=json.dumps(body), content_type="application/json",
                  **bearer(user, roles), **extra)


def _get(c, url, user=1, roles=AD, **extra):
    return c.get(url, **bearer(user, roles), **extra)


def _entities():
    SysLegalEntity.objects.create(tenant_id=1, code="LE-2026-000001", name="总院",
                                  entity_type="TOTAL_INSTITUTE", consolidated=True)
    SysLegalEntity.objects.create(tenant_id=1, code="LE-2026-000002", name="第一分院",
                                  entity_type="BRANCH_INSTITUTE")


# ===========================================================================
# X-08/X-10：法人树 + 并表合并/下钻
# ===========================================================================


def test_entity_tree_and_upsert(seed_auth):
    c = _c()
    _entities()
    r = _get(c, "/api/v1/governance/entity", user=2, roles=ST)
    tree = _j(r)["data"]
    assert len(tree) == 1 and tree[0]["entity"]["name"] == "总院"
    assert tree[0]["asPrimary"] is True
    assert tree[0]["children"][0]["entity"]["name"] == "第一分院"
    assert tree[0]["children"][0]["asPrimary"] is False
    assert set(tree[0]["stats"].keys()) == {"projectCount", "expenseAmount",
                                            "assetCount", "personnelCount"}
    # 新增法人（R-ADMIN）
    r = _post(c, "/api/v1/governance/entity", {
        "name": "第二分院", "entityType": "BRANCH_INSTITUTE",
        "creditCode": "91330100MA000000XY", "consolidated": True})
    d = _j(r)["data"]
    assert d["code"].startswith("LE-") and d["status"] == "ACTIVE"
    # 变更
    r = _post(c, "/api/v1/governance/entity", {
        "id": d["id"], "name": "第二分院（更名）", "entityType": "BRANCH_INSTITUTE"})
    assert _j(r)["data"]["name"] == "第二分院（更名）"


def test_consolidate_merge_and_drill(seed_auth):
    c = _c()
    _entities()
    AAsset.objects.create(tenant_id=1, creator_id=1, code="AST-2026-900001",
                          category_code="CAT", name="分院设备", value=Decimal("10000"),
                          legal_entity_id=2, project_id=None)
    r = _get(c, "/api/v1/governance/consolidate?level=drill&dimension=ASSET")
    d = _j(r)["data"]
    assert d["level"] == "drill"
    rows = {x["legalEntityId"]: x for x in d["rows"]}
    assert rows[2]["role"] == "PARTICIPANT" and rows[2]["allocRatio"] == 0.5
    # merge：主责全额 + 参与 0.5 折算，去重口径说明
    r = _get(c, "/api/v1/governance/consolidate?level=merge&dimension=ASSET")
    m = _j(r)["data"]["merged"]
    assert m["totalAmount"] == 5000.0 and "dedupNote" in m
    # 下钻某法人
    r = _get(c, "/api/v1/governance/consolidate?level=drill&dimension=ASSET&legalEntityId=2")
    assert len(_j(r)["data"]["rows"]) == 1


# ===========================================================================
# X-01/02/05：策略发布（MFA）+ 查当前
# ===========================================================================


def test_policy_publish_current_and_supersede(seed_auth):
    c = _c()
    matrix = {"SECRET": {"visible_zones": ["SECRET_NET"], "can_export": False}}
    # 缺 MFA → 40301
    r = _post(c, "/api/v1/security/policy", {"matrixJson": matrix,
                                             "appliedModules": ["E", "F"]})
    assert _j(r)["code"] == 40301
    r = _post(c, "/api/v1/security/policy", {"matrixJson": matrix,
                                             "appliedModules": ["E", "F"]}, **MFA)
    d = _j(r)["data"]
    assert d["status"] == "ACTIVE" and d["code"].startswith("SEC-")
    assert d["appliedModules"] == ["E", "F"]
    # 查当前
    r = _get(c, "/api/v1/security/policy/current?module=E")
    assert _j(r)["data"]["id"] == d["id"]
    # 重复发布同模块集合 → 旧版 SUPERSEDED
    r = _post(c, "/api/v1/security/policy", {"matrixJson": matrix,
                                             "appliedModules": ["E", "F"]}, **MFA)
    d2 = _j(r)["data"]
    assert d2["version"] > d["version"]
    old = XSecurityPolicyStatus(d["id"])
    assert old == "SUPERSEDED"
    # 未覆盖模块无 ACTIVE → 404
    r = _get(c, "/api/v1/security/policy/current?module=X")
    assert _j(r)["code"] == 40401


def XSecurityPolicyStatus(pid):
    from apps.confsec.models import XSecurityPolicy
    return XSecurityPolicy.objects.get(id=pid).status


# ===========================================================================
# X-01/04/11：授权（SECRET+ 强制 MFA/mfa_bound）+ 吊销/冻结
# ===========================================================================


def test_grant_and_revoke(seed_auth):
    c = _c()
    # INTERNAL 授权无需 MFA
    r = _post(c, "/api/v1/security/grant", {
        "subjectUserId": 2, "scopeType": "PROJECT", "scopeRef": 5,
        "grantedLevel": "INTERNAL", "networkZone": "OFFICE"})
    assert _j(r)["data"]["status"] == "EFFECTIVE"
    assert _j(r)["data"]["mfaBound"] is False
    # SECRET 授权缺 MFA → 40301
    r = _post(c, "/api/v1/security/grant", {
        "subjectUserId": 2, "scopeType": "SECURITY_LEVEL",
        "grantedLevel": "SECRET", "networkZone": "SECRET_NET"})
    assert _j(r)["code"] == 40301
    r = _post(c, "/api/v1/security/grant", {
        "subjectUserId": 2, "scopeType": "SECURITY_LEVEL",
        "grantedLevel": "SECRET", "networkZone": "SECRET_NET"}, **MFA)
    d = _j(r)["data"]
    assert d["mfaBound"] is True
    # 冻结 / 吊销（均须二次鉴别）
    r = _post(c, "/api/v1/security/revoke",
              {"grantId": d["id"], "action": "FREEZE", "reason": "复审逾期"}, **MFA)
    assert _j(r)["data"]["status"] == "FROZEN"
    r = _post(c, "/api/v1/security/revoke",
              {"grantId": d["id"], "action": "REVOKE"}, **MFA)
    assert _j(r)["data"]["status"] == "REVOKED"
    # 查询
    r = _get(c, "/api/v1/security/grant?subjectUserId=2")
    assert _j(r)["data"]["total"] == 2


# ===========================================================================
# X-05/06：涉密输出双审 + 二次鉴别放行（指纹 + zone-guard 防探测）
# ===========================================================================


def _apply_export(c, digest="DIGEST-AAA"):
    r = _post(c, "/api/v1/security/export", {
        "direction": "DOWN", "objectType": "DOC", "objectId": 8,
        "toDomain": "OFFICE", "payloadDigest": digest,
        "securityLevel": "SECRET", "desensitizeNote": "已脱密",
        "reason": "课题结题材料输出"}, user=2, roles=ST)
    assert _j(r)["code"] == 0, _j(r)
    return _j(r)["data"]


def test_export_flow_double_review_and_release(seed_auth):
    c = _c()
    d = _apply_export(c)
    assert d["status"] == "APPLIED" and d["code"].startswith("EXF-")
    # 审批人=申请人 → 40001（申请人兼任 R-MANAGER 以过 casbin，验证业务同人拦截）
    r = _post(c, "/api/v1/security/export/approve", {
        "exportId": d["id"], "stage": "PRE_REVIEW", "verdict": "PASS"},
        user=2, roles=["R-STAFF", "R-MANAGER"])
    assert _j(r)["code"] == 40001
    # 跳过初审直接复审 → 40901
    r = _post(c, "/api/v1/security/export/approve", {
        "exportId": d["id"], "stage": "SEC_REVIEW", "verdict": "PASS"})
    assert _j(r)["code"] == 40901
    # 初审 → PRE_REVIEW
    r = _post(c, "/api/v1/security/export/approve", {
        "exportId": d["id"], "stage": "PRE_REVIEW", "verdict": "PASS",
        "approverId": 1, "comment": "同意输出"})
    assert _j(r)["data"]["status"] == "PRE_REVIEW"
    # 复审 → SEC_REVIEW
    r = _post(c, "/api/v1/security/export/approve", {
        "exportId": d["id"], "stage": "SEC_REVIEW", "verdict": "PASS",
        "releaseScope": "仅结题汇报材料"})
    assert _j(r)["data"]["status"] == "SEC_REVIEW"
    # 放行缺 MFA → 40301
    r = _post(c, "/api/v1/security/export/release", {
        "exportId": d["id"], "actualPayloadDigest": "DIGEST-AAA"})
    assert _j(r)["code"] == 40301
    # 指纹不符 → 二次拦截 40901 + risk_flag=2 日志
    r = _post(c, "/api/v1/security/export/release", {
        "exportId": d["id"], "actualPayloadDigest": "DIGEST-TAMPERED"}, **MFA)
    assert _j(r)["code"] == 40901
    assert XSecLog.objects.filter(risk_flag=2, action="EXPORT").exists()
    # 指纹一致 → RELEASED
    r = _post(c, "/api/v1/security/export/release", {
        "exportId": d["id"], "actualPayloadDigest": "DIGEST-AAA",
        "secondVerifierId": 1}, **MFA)
    assert _j(r)["data"]["status"] == "RELEASED"
    # zone-guard：涉密单据非 SECRET_NET → 403（不暴露存在性）
    r = _get(c, f"/api/v1/security/export/{d['id']}", user=2, roles=ST,
             HTTP_X_NETWORK_ZONE="OFFICE")
    assert _j(r)["code"] == 40301
    r = _get(c, f"/api/v1/security/export/{d['id']}", user=2, roles=ST,
             HTTP_X_NETWORK_ZONE="SECRET_NET")
    assert _j(r)["data"]["status"] == "RELEASED"


def test_export_reject_path(seed_auth):
    c = _c()
    d = _apply_export(c)
    r = _post(c, "/api/v1/security/export/approve", {
        "exportId": d["id"], "stage": "PRE_REVIEW", "verdict": "REJECT",
        "approverId": 1, "comment": "涉密等级不足输出"})
    assert _j(r)["data"]["status"] == "REJECTED"
    # 终态后再审批 → 40901
    r = _post(c, "/api/v1/security/export/approve", {
        "exportId": d["id"], "stage": "PRE_REVIEW", "verdict": "PASS"})
    assert _j(r)["code"] == 40901


# ===========================================================================
# X-07：安全日志 SM3 哈希链（防篡改）+ 稽核查询
# ===========================================================================


def test_sec_log_chain_and_query(seed_auth):
    c = _c()
    body = {"actorId": 2, "networkZone": "SECRET_NET", "action": "READ",
            "objectType": "DOC", "objectId": 1, "result": "ALLOW"}
    r = _post(c, "/api/v1/security/log", body)
    d1 = _j(r)["data"]
    assert d1["hashSelf"].startswith("sm3-") and d1["async"] is True
    r = _post(c, "/api/v1/security/log", {**body, "objectId": 2, "result": "DENY",
                                          "riskFlag": 1})
    d2 = _j(r)["data"]
    # 链式：第二条 hash_prev = 第一条 hash_self
    from apps.confsec.models import XSecLog
    assert XSecLog.objects.get(id=d2["id"]).hash_prev == d1["hashSelf"]
    # 稽核查询 + 链校验完好
    r = _get(c, "/api/v1/security/log", user=3, roles=["R-AUDITOR"])
    d = _j(r)["data"]
    assert d["chainIntact"] is True and d["total"] == 2
    # risk 过滤
    r = _get(c, "/api/v1/security/log?risk=true", user=3, roles=["R-AUDITOR"])
    assert _j(r)["data"]["total"] == 1
    # 篡改 → 链断裂检出
    lg = XSecLog.objects.get(id=d1["id"])
    lg.hash_self = "sm3-tampered"
    lg.save()
    r = _get(c, "/api/v1/security/log", user=3, roles=["R-AUDITOR"])
    assert _j(r)["data"]["chainIntact"] is False


# ===========================================================================
# X-11：涉密人员审查/清退（授权自动收敛）
# ===========================================================================


def test_personnel_review_and_clearance(seed_auth):
    c = _c()
    # SECRET 许可但无对应授权 → 40001
    r = _post(c, "/api/v1/security/personnel/review", {
        "userId": 2, "op": "ONBOARD_REVIEW", "secretEligible": True,
        "grantedLevel": "SECRET"}, **MFA)
    assert _j(r)["code"] == 40001
    # 先授 SECRET 权限（MFA），再入职审查
    _post(c, "/api/v1/security/grant", {
        "subjectUserId": 2, "scopeType": "SECURITY_LEVEL",
        "grantedLevel": "SECRET", "networkZone": "SECRET_NET"}, **MFA)
    r = _post(c, "/api/v1/security/personnel/review", {
        "userId": 2, "op": "ONBOARD_REVIEW", "secretEligible": True,
        "grantedLevel": "SECRET"}, **MFA)
    d = _j(r)["data"]
    assert d["status"] == "GRANTED" and d["code"].startswith("SEC-")
    # 在岗复审
    r = _post(c, "/api/v1/security/personnel/review", {
        "userId": 2, "op": "INPOST_RE_REVIEW", "reviewDate": "2026-10-17",
        "nextReviewDate": "2027-10-17",
        "trainingRecord": {"type": "保密培训", "result": "合格"}}, **MFA)
    assert _j(r)["data"]["status"] == "GRANTED"
    # 离岗清退三要素未完成 → FROZEN + 授权自动收敛
    r = _post(c, "/api/v1/security/personnel/review", {
        "userId": 2, "op": "LEAVE_CLEARANCE",
        "leaveClearance": {"carrierReturned": True, "accessRevoked": False}}, **MFA)
    assert _j(r)["data"]["status"] == "FROZEN"
    g = XAccessGrant.objects.filter(subject_user_id=2).first()
    assert g.status == "FROZEN"
    # 补齐三要素 → CLEARED_OUT
    r = _post(c, "/api/v1/security/personnel/review", {
        "userId": 2, "op": "LEAVE_CLEARANCE",
        "leaveClearance": {"carrierReturned": True, "accessRevoked": True,
                           "undertakingSigned": True}}, **MFA)
    assert _j(r)["data"]["status"] == "CLEARED_OUT"


# ===========================================================================
# X-13/14：定密/降密/解密（AI 仅提示，永不自动生效）
# ===========================================================================


def test_classify_requires_mfa_and_approval(seed_auth):
    c = _c()
    a = AAsset.objects.create(tenant_id=1, creator_id=1, code="AST-2026-900002",
                              category_code="CAT", name="涉密设备", value=Decimal("1"),
                              legal_entity_id=1, status="IN_USE", custodian_id=2)
    body = {"targetType": "OBJECT", "targetId": a.id, "op": "SET_LEVEL",
            "proposedLevel": "SECRET",
            "aiHint": {"hitKeywords": ["涉密"], "suggestedLevel": "SECRET",
                       "confidence": 0.42}}
    r = _post(c, "/api/v1/security/classify", body)
    assert _j(r)["code"] == 40301
    r = _post(c, "/api/v1/security/classify", body, **MFA)
    d = _j(r)["data"]
    assert d["needApproval"] is True and d["securityLevel"] == "SECRET"
    a.refresh_from_db()
    assert a.security_level == "SECRET"
    # 人员解密工作态
    r = _post(c, "/api/v1/security/classify", {
        "targetType": "PERSONNEL", "targetId": 2, "op": "DECLASSIFY",
        "proposedLevel": "INTERNAL"}, **MFA)
    d = _j(r)["data"]
    assert d["classifyStatus"] == "DECLASSIFY" and d["needApproval"] is True
    assert XPersonnelSec.objects.filter(user_id=2).exists()
