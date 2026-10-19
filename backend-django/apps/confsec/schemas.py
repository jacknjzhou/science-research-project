"""X 涉密治理域 · 接口请求 Schema 验证定义（pydantic v2；键名对齐契约 camelCase）。"""
from __future__ import annotations

from core.reqschema import BaseIn


class EntityUpsertIn(BaseIn):
    name: str
    entityType: str
    id: int | None = None
    creditCode: str | None = None
    shortCode: str | None = None
    consolidated: bool | None = None
    parentId: int | None = None
    reportScope: str | None = None
    status: str | None = None


class PolicyPublishIn(BaseIn):
    matrixJson: dict
    appliedModules: list
    legalEntityId: int | None = None
    securityLevel: str | None = None
    effectiveFrom: str | None = None
    effectiveTo: str | None = None
    policyPackId: int | None = None
    remark: str | None = None


class GrantIn(BaseIn):
    subjectUserId: int
    scopeType: str
    grantedLevel: str
    networkZone: str
    scopeRef: int | None = None
    mfaBound: bool | None = None
    validFrom: str | None = None
    validTo: str | None = None
    legalEntityId: int | None = None
    remark: str | None = None


class RevokeIn(BaseIn):
    grantId: int
    action: str
    reason: str | None = None


class ExportApplyIn(BaseIn):
    direction: str
    objectType: str
    objectId: int
    toDomain: str
    payloadDigest: str
    fromDomain: str | None = None
    securityLevel: str | None = None
    desensitizeNote: str | None = None
    reason: str | None = None
    legalEntityId: int | None = None


class ExportApproveIn(BaseIn):
    exportId: int
    stage: str
    verdict: str
    approverId: int | None = None
    releaseScope: str | None = None
    comment: str | None = None


class ExportReleaseIn(BaseIn):
    exportId: int
    actualPayloadDigest: str
    secondVerifierId: int | None = None
    releaseScope: str | None = None


class ClassifyIn(BaseIn):
    targetType: str
    targetId: int
    op: str
    proposedLevel: str | None = None
    aiHint: dict | None = None
    reason: str | None = None
    legalEntityId: int | None = None


class SecLogIn(BaseIn):
    actorId: int
    networkZone: str
    action: str
    objectType: str
    objectId: int
    result: str
    tenantId: int | None = None
    legalEntityId: int | None = None
    actorRole: str | None = None
    fieldDiffJson: dict | None = None
    securityLevel: str | None = None
    grantedLevel: str | None = None
    riskFlag: int | None = None
    occurredAt: str | None = None
    sourceIp: str | None = None
    deviceId: str | None = None
    traceId: str | None = None


class PersonnelReviewIn(BaseIn):
    userId: int
    op: str
    staffId: int | None = None
    secretEligible: bool | None = None
    grantedLevel: str | None = None
    classifyStatus: str | None = None
    reviewDate: str | None = None
    nextReviewDate: str | None = None
    trainingRecord: dict | None = None
    leaveClearance: dict | None = None
    legalEntityId: int | None = None
    remark: str | None = None
