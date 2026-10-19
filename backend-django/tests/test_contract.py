"""契约测试：对 design/*.openapi.yaml 全量 operation 断言可达且信封合规。

- 已手工实现的端点：真实响应（含业务 40401/40001 等，均合规）；
- 未实现的端点：stub 兜底（X-Stub: true，仍为合规信封）；
- 铁律：任何契约端点的响应必须是 JSON 统一信封（不允许 Django 默认 404 页/500 裸错）。
- 汇总打印 stub 命中清单，作为各 Phase 推进的覆盖度看板。
"""
from __future__ import annotations

import re

import pytest
from django.test import Client

from core import contract
from tests.conftest import bearer

_PARAM_SAMPLE = {
    "id": "1", "expenseId": "1", "applicationId": "1", "projectId": "1",
    "guidelineId": "1", "taskId": "1", "milestoneId": "1", "changeId": "1",
    "budgetId": "1", "incomeId": "1", "subjectId": "1", "outputId": "1",
    "claimId": "1", "patentId": "1", "expertId": "1", "reviewTaskId": "1",
    "reviewId": "1", "activityId": "1", "documentId": "1", "archiveId": "1",
    "schemeId": "1", "recordId": "1", "payoutId": "1", "dictId": "1",
    "itemId": "1", "roleId": "1", "userId": "1", "code": "demo",
    "bizId": "1", "noticeId": "1", "grantId": "1", "planId": "1",
    "categoryId": "1", "contractId": "1", "requisitionId": "1", "assetId": "1",
}


def _materialize(template: str) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1).strip("{}")
        return _PARAM_SAMPLE.get(name, "1")

    return re.sub(r"\{([^}]+)\}", sub, template)


@pytest.fixture
def seed_contract(db):
    from django.core.management import call_command

    call_command("seed_demo")
    from apps.notify.models import SysNotification
    from apps.sysadmin.models import SysDict

    SysDict.objects.get_or_create(
        code="demo", tenant_id=1, defaults={"name": "契约测试字典", "creator_id": 1}
    )
    SysNotification.objects.get_or_create(
        tenant_id=1, user_id=1, typ="TODO", title="契约测试",
        defaults={"content": "契约测试通知", "biz_ref": "CONTRACT"},
    )


@pytest.mark.django_db
def test_contract_full_coverage(seed_contract):
    c = Client()
    ops = contract.registry()
    assert len(ops) >= 300, f"契约 operation 数异常：{len(ops)}"

    stub_hits: list[str] = []
    failures: list[str] = []
    for op in ops:
        if op.template == "/api/v1/auth/login" and op.method == "POST":
            resp = c.post(
                "/api/v1/auth/login",
                data={"username": "ark", "password": "ark"},
                content_type="application/json",
            )
        else:
            url = _materialize(op.template)
            method = op.method.lower()
            kwargs = {"content_type": "application/json", **bearer(1, ["R-ADMIN"])}
            if method == "get":
                resp = c.get(url, **kwargs)
            elif method == "delete":
                resp = c.delete(url, **kwargs)
            else:
                resp = getattr(c, method)(url, data={}, **kwargs)

        try:
            body = resp.json()
        except Exception:
            failures.append(f"{op.method} {op.template} → 非JSON响应 {resp.status_code}")
            continue
        for key in ("code", "message", "data", "traceId", "timestamp"):
            if key not in body:
                failures.append(
                    f"{op.method} {op.template} → 信封缺字段 {key}（HTTP {resp.status_code}）"
                )
                break
        if resp.get("X-Stub") == "true":
            stub_hits.append(f"{op.method} {op.template}")

    assert not failures, "\n".join(failures[:30])
    implemented = len(ops) - len(stub_hits)
    print(
        f"\n[contract] 总 {len(ops)} ops：已实现 {implemented}，stub 兜底 {len(stub_hits)}"
    )
