"""A 资产耗材域 · 接口请求 Schema 验证定义（pydantic v2；键名对齐契约 camelCase）。"""
from __future__ import annotations

from pydantic import model_validator

from core.reqschema import BaseIn


class AssetIn(BaseIn):
    assetType: str
    categoryCode: str
    name: str
    brand: str | None = None
    model: str | None = None
    serialNo: str | None = None
    value: float | None = None
    purchaseDate: str | None = None
    inDate: str | None = None
    deprMethod: str | None = None
    deprYears: int | None = None
    custodianId: int | None = None
    deptId: int | None = None
    location: str | None = None
    sourceType: str | None = None
    sourceRef: int | None = None
    projectId: int | None = None
    legalEntityId: int | None = None
    securityLevel: str | None = None
    shareFlag: bool | None = None
    openFlag: bool | None = None
    policyPackId: int | None = None
    remark: str | None = None


class FromReceiptIn(BaseIn):
    orderId: int | None = None
    order_id: int | None = None
    target: str | None = None
    serial_nos: list | None = None
    batch_info: dict | None = None
    contractId: int | None = None
    custodianId: int | None = None
    deptId: int | None = None
    location: str | None = None
    projectId: int | None = None
    legalEntityId: int | None = None

    @model_validator(mode="after")
    def _need_order(self):
        if self.orderId is None and self.order_id is None:
            raise ValueError("orderId 必填")
        return self


class IssueIn(BaseIn):
    projectId: int
    custodianId: int | None = None
    deptId: int | None = None
    location: str | None = None
    usageRate: float | None = None
    relatedExpenseId: int | None = None
    remark: str | None = None


class TransferIn(BaseIn):
    toLegalEntityId: int
    toDeptId: int
    toCustodianId: int | None = None
    toLocation: str | None = None
    secrecyReviewId: int | None = None
    remark: str | None = None


class StockInIn(BaseIn):
    qty: float
    batchNo: str | None = None
    name: str | None = None
    category: str | None = None
    isHazard: bool | None = None
    hazardLevel: str | None = None
    msdsUrl: str | None = None
    unit: str | None = None
    produceDate: str | None = None
    expireDate: str | None = None
    safeStock: float | None = None
    amount: float | None = None
    location: str | None = None
    custodianId: int | None = None
    legalEntityId: int | None = None
    securityLevel: str | None = None
    remark: str | None = None


class StockOutIn(BaseIn):
    qty: float
    projectId: int
    operatorId: int
    batchNo: str | None = None
    doubleConfirmBy: int | None = None
    usage: str | None = None
    relatedExpenseId: int | None = None
    fifoExempt: bool | None = None
    fifoExemptApproverId: int | None = None


class DepreciationRunIn(BaseIn):
    period: str
    legalEntityId: int | None = None
    policyPackId: int | None = None
    assetIds: list | None = None


class VoucherItemIn(BaseIn):
    depreciationId: int
    voucherId: int
    posted: bool = True


class VoucherCallbackIn(BaseIn):
    period: str
    items: list[VoucherItemIn]


class DisposalIn(BaseIn):
    method: str
    appraisal: dict | None = None
    residualValue: float | None = None
    approvalChain: list | None = None
    archiveRef: str | None = None
    remark: str | None = None


class InventoryItemIn(BaseIn):
    serialNo: str
    assetCode: str | None = None
    qty: float | None = None
    location: str | None = None


class InventoryIn(BaseIn):
    items: list[InventoryItemIn]
    planId: int | None = None
    deptId: int | None = None
    legalEntityId: int | None = None
    collectedBy: int | None = None
