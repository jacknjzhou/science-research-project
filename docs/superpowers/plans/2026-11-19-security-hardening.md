# 安全收口（Security Hardening）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清掉 M2 三期终审反复记录、具备真实越权后果的五条安全债（E-3 登录后门、E-1 N 域跨租户、E-2 G 域跨租户、E-4 打分无邀请校验、E-5 付款额口径错），每处配「旧码必红」的双租户回归，不引入新功能。

**Architecture:** 全部是横切收口，不改表结构、不加迁移（不需要 makemigrations）。三处是「查询补 tenant 过滤」，一处是「把无门禁的 dev 后门改成显式开关 + 收紧签发角色」，一处是「补一条状态/邀请前置校验」，一处是一行聚合字段改对。所有改动集中在 `core/auth/api.py`、`apps/expertreview/api.py`、`apps/procure/api.py` 三个文件 + 一份新测试文件。

**Tech Stack:** Django 5 + django-ninja、pytest + pytest-django（sqlite 测试库）、casbin（policy 不动）。

---

## Global Constraints

1. **只补隔离与校验，不改业务语义**：不新增端点、不改契约（OpenAPI 零改动）、不改 DDL、不生成迁移。
2. **跨租户一律 404**（不泄露存在性），跨出租户的「状态机/黑名单」类拦截仍沿用既有 `409 CODE_CONFLICT` / `403 CODE_BLACKLIST`。
3. **多租户测试必须真的跨租户**：`bearer(uid, roles, tenant_id=2)` 显式传 tenant；默认 `bearer()` 的 tenant_id 是 1。
4. **每条修复都要「旧码必红」证据**：先写测试 → 在未修复源码上跑出红 → 再实现 → 转绿。测试文件统一 `backend-django/tests/test_security_hardening.py`。
5. **不许放宽既有断言来过关**：如果新校验让既有用例失败，先判断是用例构造不合法（缺 accept 步骤等），在用例里补合法前置；只有在用例本身在测「不应存在的放行」时才改判据，并在 commit message 说明。
6. **提交纪律**：每个任务一个 commit，只 stage 该任务涉及的文件；禁 `git add -A`；不动 `docs/`（本计划文件除外）、不动 `frontend/pnpm-*.yaml` 等 BASE 前未跟踪文件。
7. **测试基线 472 passed**，逐任务只增不减；每任务结束 `cd backend-django && .venv/bin/python -m pytest -q` 必须全绿。
8. **迁移编号**：本计划不新增迁移。若某任务误触发 `makemigrations` 提示，说明改到了模型，必须回退。
9. **错误码纪律**：`40001 CODE_BAD_REQUEST`、`40301 CODE_FORBIDDEN`、`40302 CODE_ACCOUNT_DISABLED`、`40401 CODE_NOT_FOUND`、`40901 CODE_CONFLICT`、`40913 CODE_BLACKLIST`。

---

## Review Focus（终审必查五项）

1. **dev 登录后门是否真的在生产不可达**：非 `DEBUG` 即使设了 `ARK_DEV_LOGIN=1` 也必须 401；错误码与真实账号错误一致（不得泄露「后门存在」）。
2. **后门签发的角色域是否最小**：不得再固定带 `R-MANAGER`。
3. **N 域三条列表/抽取是否全部带 tenant**：`list_experts`、`list_reviews`、`draw_experts` 的候选池，且新代码没有引入「先查后过滤」的越权窗口。
4. **G 域是否全链路带 tenant**：`create_bid` / `award_bid` / `create_contract` 及其 helper（`_get_req_or_404` / `_get_contract_or_404` / 五处 `GSupplier` 裸查），且既有 6 个按 id 取合同的端点未被改坏。
5. **E-4 是否挡住「未受邀/未接受」与「非收分期」**：且合法路径（accept → COLLECTING → 打分）仍然 200。

---

## 文件结构

| 文件 | 作用 | 本计划改动 |
|---|---|---|
| `backend-django/core/auth/api.py` | 登录端点（含 dev 后门） | E-3 门禁 + 角色收紧 |
| `backend-django/apps/expertreview/api.py` | N 域专家/评审 | E-1 三处 tenant；E-4 邀请校验 |
| `backend-django/apps/procure/api.py` | G 域采购/合同 | E-2 helper 与 3 个 handler；E-5 聚合字段 |
| `backend-django/tests/test_security_hardening.py` | 新增回归 | 全计划 12+ 用例 |
| `README.md` | 测试计数 | 472 → 最终数 |

---

### Task 1: E-3 登录后门加门禁并收紧签发角色

**Files:**
- Modify: `backend-django/core/auth/api.py:24-56`（`DEV_USER`/`DEV_PASSWORD` 与其后分支）
- Test: `backend-django/tests/test_security_hardening.py`（新建）

**Interfaces:**
- 新增 `_dev_login_enabled() -> bool`：`return bool(getattr(settings, "DEBUG", False)) and os.environ.get("ARK_DEV_LOGIN") == "1"`。
- `login` 行为：`(username, password) == (DEV_USER, DEV_PASSWORD)` 且 `_dev_login_enabled()` → 签发 `user_id=1, tenant_id=body.tenant_id or 1, legal_entity_id=0, security_level="INTERNAL", roles=["R-STAFF"]`；否则 `ark/ark` 走普通账号查询路径，库里没有该用户 → `ApiError(401, CODE_BAD_CREDENTIALS, "账号或密码错误")`（与真实错误同码同文案，不泄露后门）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_security_hardening.py
import json

import pytest
from django.test import Client

from core.auth.api import _dev_login_enabled

pytestmark = pytest.mark.django_db


def _login(client, username, password, tenant_id=1):
    return client.post(
        "/api/v1/auth/login",
        data=json.dumps({"username": username, "password": password, "tenant_id": tenant_id}),
        content_type="application/json",
    )


def test_dev_login_disabled_when_not_debug(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv("ARK_DEV_LOGIN", "1")
    assert _dev_login_enabled() is False
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 401
    assert r.json()["code"] == 40102


def test_dev_login_disabled_without_env_flag(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.delenv("ARK_DEV_LOGIN", raising=False)
    assert _dev_login_enabled() is False
    assert _login(Client(), "ark", "ark").status_code == 401


def test_dev_login_enabled_issues_minimal_roles(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setenv("ARK_DEV_LOGIN", "1")
    assert _dev_login_enabled() is True
    r = _login(Client(), "ark", "ark")
    assert r.status_code == 200
    tok = r.json()["data"]["token"]
    from core.auth.jwt_util import parse_token

    claims = parse_token(tok)
    assert claims["roles"] == ["R-STAFF"]
    assert "R-MANAGER" not in claims["roles"]
```

- [ ] **Step 2: 跑测试确认红**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_security_hardening.py -q`
Expected: 3 failed（`ImportError: cannot import name '_dev_login_enabled'`）

- [ ] **Step 3: 实现**

在 `core/auth/api.py` 顶部加 `import os`、`from django.conf import settings`（若已局部 import 则提到模块级），新增：

```python
def _dev_login_enabled() -> bool:
    """冒烟后门开关：必须同时满足 DEBUG=True 与显式 ARK_DEV_LOGIN=1。"""
    return bool(getattr(settings, "DEBUG", False)) and os.environ.get("ARK_DEV_LOGIN") == "1"
```

把 `if username != DEV_USER or password != DEV_PASSWORD:` 改为：

```python
    is_dev_login = username == DEV_USER and password == DEV_PASSWORD and _dev_login_enabled()
    user = None
    if not is_dev_login:
        ...（原有账号查询/校验逻辑不动）

    if is_dev_login:
        claims = _issue(request, 1, tenant_id, 0, "INTERNAL", ["R-STAFF"])
    else:
        ...（原有签发逻辑不动）
```

- [ ] **Step 4: 跑测试确认绿 + 全量回归**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_security_hardening.py -q && .venv/bin/python -m pytest -q`
Expected: 3 passed；全量 475 passed

- [ ] **Step 5: Commit**

```bash
git add backend-django/core/auth/api.py backend-django/tests/test_security_hardening.py
git commit -m "fix(auth): 登录后门加 DEBUG+ARK_DEV_LOGIN 双门禁并收紧为 R-STAFF（E-3）"
```

---

### Task 2: E-1 N 域列表与抽取补租户过滤

**Files:**
- Modify: `backend-django/apps/expertreview/api.py:92-101`、`:225-236`、`:268-280`
- Test: `backend-django/tests/test_security_hardening.py`（追加）

**Interfaces:**
- `list_experts`：`qs = NExpert.objects.filter(tenant_id=d.tenant_id, deleted=0)`。
- `list_reviews`：`qs = NReviewTask.objects.filter(tenant_id=d.tenant_id, deleted=0)`。
- `draw_experts`：候选池 `NExpert.objects.filter(tenant_id=d.tenant_id, status="ACTIVE", deleted=0)`。

- [ ] **Step 1: 写失败测试**

```python
def _expert(tenant_id, name="专家"):
    from apps.expertreview.models import NExpert

    return NExpert.objects.create(tenant_id=tenant_id, name=name, status="ACTIVE",
                                  source="INTERNAL", field_tags=[])


def _task(tenant_id, title="评审任务"):
    from apps.expertreview.models import NReviewTask

    return NReviewTask.objects.create(tenant_id=tenant_id, title=title) \
        if "title" in [f.name for f in NReviewTask._meta.fields] else \
        NReviewTask.objects.create(tenant_id=tenant_id)


def test_list_experts_is_tenant_scoped(seed_auth):
    from tests.conftest import bearer

    mine = _expert(1, "本租户专家")
    other = _expert(2, "他租户专家")
    r = Client().get("/api/v1/experts", HTTP_AUTHORIZATION=bearer(seed_auth["admin"], ["R-ADMIN"]))
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["data"]["list"]]
    assert mine.id in ids and other.id not in ids


def test_list_reviews_is_tenant_scoped(seed_auth):
    from tests.conftest import bearer

    mine = _task(1); other = _task(2)
    r = Client().get("/api/v1/reviews", HTTP_AUTHORIZATION=bearer(seed_auth["admin"], ["R-ADMIN"]))
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["data"]["list"]]
    assert mine.id in ids and other.id not in ids
```

（`draw_experts` 用例：建 tenant1 任务 + 仅 tenant2 有 ACTIVE 专家 → 抽取返回 0 席位；用 `models.py` 实际字段名构造，若 `NReviewTask` 无 `title` 则去掉该参数。）

- [ ] **Step 2: 跑测试确认红**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_security_hardening.py -q -k "tenant_scoped"`
Expected: FAIL（`assert other.id not in ids` → 他租户 id 出现在列表）

- [ ] **Step 3: 实现**（三处查询按 Interfaces 加 `tenant_id=`）

- [ ] **Step 4: 跑测试确认绿 + 全量**

Run: `cd backend-django && .venv/bin/python -m pytest -q`
Expected: 47x passed

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/expertreview/api.py backend-django/tests/test_security_hardening.py
git commit -m "fix(expertreview): 专家/评审列表与抽取池补租户过滤（E-1）"
```

---

### Task 3: E-2 G 域采购与合同补租户过滤

**Files:**
- Modify: `backend-django/apps/procure/api.py`：`_get_req_or_404`(:82)、`_get_contract_or_404`(:89)、`create_bid`(:297-318)、`:332`（bid 内供应商批量）、`award_bid`(:354-372)、`:413`（投标供应商映射）、`:479`、`create_contract`(:550-560)
- Test: `backend-django/tests/test_security_hardening.py`（追加）

**Interfaces:**
- `_get_req_or_404(tenant_id: int, rid: int) -> GRequisition`、`_get_contract_or_404(tenant_id: int, cid: int) -> GContract`（不匹配 → 404「采购申请不存在」/「合同不存在」）。
- 全部 `GSupplier.objects.filter(id=... , deleted=0)` 补 `tenant_id=dom.tenant_id`；批量处补 `tenant_id=`。
- 调用点：`:258`、`:272`、`:303`（req）；`:595/622/641/659/675/709`（contract），全部传 `dom.tenant_id` 或 `domain_from(request).tenant_id`。

- [ ] **Step 1: 写失败测试**

```python
def test_create_bid_rejects_foreign_requisition(seed_auth):
    from apps.procure.models import GRequisition
    from tests.conftest import bearer

    r2 = GRequisition.objects.create(tenant_id=2, applicant_id=1, category="设备",
                                     item_name="他租户需求", est_amount=1000)
    r = Client().post("/api/v1/procurement/bids",
                      data=json.dumps({"requisition_id": r2.id, "method": "询价"}),
                      content_type="application/json",
                      HTTP_AUTHORIZATION=bearer(seed_auth["admin"], ["R-MANAGER"]))
    assert r.status_code == 404


def test_award_bid_rejects_foreign_bid(seed_auth):
    # tenant2 的 bid，用 tenant1 令牌定标 → 404
    ...


def test_create_contract_rejects_foreign_supplier(seed_auth):
    # supplier 属 tenant2，用 tenant1 令牌建合同 → 40313（_check_supplier_usable 收到 None）
    ...
```

（`GRequisition` 必填列按 `models.py` 实际字段；`award_bid`/`create_contract` 用例按既有 `tests/test_phase*.py` 的构造范式补齐必填项。）

- [ ] **Step 2: 跑测试确认红**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_security_hardening.py -q -k "foreign"`
Expected: FAIL（200/正常创建而非 404/403）

- [ ] **Step 3: 实现**（helper 签名 + 7 处调用点 + 5 处供应商裸查）

- [ ] **Step 4: 跑测试确认绿 + 全量**

Run: `cd backend-django && .venv/bin/python -m pytest -q`
Expected: 全绿（既有 G 域用例因 seed 数据都在 tenant 1，不受影响）

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/procure/api.py backend-django/tests/test_security_hardening.py
git commit -m "fix(procure): 采购申请/招标/合同与供应商查询补租户过滤（E-2）"
```

---

### Task 4: E-4 打分前校验邀请与任务状态

**Files:**
- Modify: `backend-django/apps/expertreview/api.py:372-400`（`submit_score`）
- Test: `backend-django/tests/test_security_hardening.py`（追加）

**Interfaces:**
- 新增 `_require_accepted_invitation(t, expert) -> None`：查 `NReviewInvitation.objects.filter(task_id=t.id, expert_id=expert.id)`，无邀请 → `ApiError(403, CODE_FORBIDDEN, "未被邀请参与该评审")`；`response != "ACCEPT"` → `ApiError(409, CODE_CONFLICT, "尚未接受邀请，不可打分")`。
- 任务状态守卫：`t.status not in ("COLLECTING", "DRAWN")` → `ApiError(409, CODE_CONFLICT, f"当前状态不可打分：{t.status}")`。

- [ ] **Step 1: 写失败测试**

```python
def test_score_requires_accepted_invitation(seed_auth):
    # 建专家（绑真实用户）+ 任务，不建邀请 → 打分 403
    ...
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_score_rejects_pending_invitation(seed_auth):
    # 邀请 response=PENDING → 409/40901
    ...


def test_score_allowed_after_accept(seed_auth):
    # 邀请 ACCEPT + 任务 COLLECTING → 200 且落库
    ...
```

- [ ] **Step 2: 跑测试确认红**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_security_hardening.py -q -k "score"`
Expected: 前两条 FAIL（当前直接 200 落库）

- [ ] **Step 3: 实现** 并在 `submit_score` 内、写库前调用两个守卫

- [ ] **Step 4: 跑测试确认绿 + 全量**

Run: `cd backend-django && .venv/bin/python -m pytest -q`
Expected: 全绿；若 `test_phase3_domains.py` 或 `test_m2c_review_fixes.py` 因缺前置失败，按约束 5 在用例内补「先 accept 邀请」步骤（不改断言口径）

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/expertreview/api.py backend-django/tests/test_security_hardening.py backend-django/tests/test_phase3_domains.py backend-django/tests/test_m2c_review_fixes.py
git commit -m "fix(expertreview): 打分须已接受邀请且任务在收分期（E-4）"
```

---

### Task 5: E-5 合同列已付额改按实付聚合

**Files:**
- Modify: `backend-django/apps/procure/api.py:519-526`
- Test: `backend-django/tests/test_security_hardening.py`（追加）

**Interfaces:**
- `annotate(paid_sum=Sum("paid_amount"))`（原来是 `Sum("plan_amount")`，把计划额当已付额）。

- [ ] **Step 1: 写失败测试**

```python
def test_contract_list_paid_sum_uses_paid_amount(seed_auth):
    # 合同 + 两期付款：期1 plan 40000/paid 40000（PAID），期2 plan 58000/paid 0（PLANNED）
    # 列表 paid_sum 必须 == 40000，而不是 98000
    ...
    assert row["paid_sum"] == "40000.00"
```

- [ ] **Step 2: 跑测试确认红**：Expected: `assert '98000.00' == '40000.00'`

- [ ] **Step 3: 实现**（一行字段名）

- [ ] **Step 4: 跑测试确认绿 + 全量**

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/procure/api.py backend-django/tests/test_security_hardening.py
git commit -m "fix(procure): 合同列表已付额按 paid_amount 聚合（E-5）"
```

---

### Task 6: 全量验收与 README 计数

**Files:**
- Modify: `README.md`（三处测试计数）
- Verify: 全仓

- [ ] **Step 1: 全量套件**

Run: `cd backend-django && .venv/bin/python -m pytest -q`
记录最终 N（预期 480±5）。

- [ ] **Step 2: 迁移与前端零漂移**

Run:
```bash
cd backend-django && .venv/bin/python manage.py makemigrations --check --dry-run
cd ../frontend && ./node_modules/.bin/vue-tsc --noEmit
```
Expected: `No changes detected`；tsc 无输出。

- [ ] **Step 3: 契约零改动确认**

Run: `cd /Users/jacky/works/science-research-project && git diff --stat 9f087e9..HEAD -- design/ frontend/src/api/schema/`
Expected: 空输出（本计划不碰契约）。

- [ ] **Step 4: README 计数**

把三处 472 改成实际 N。

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "chore(readme): 安全收口后测试计数更新为实测 N"
```

---

## Self-Review

**1. Spec 覆盖：** E-3 → Task 1；E-1 → Task 2；E-2 → Task 3；E-4 → Task 4；E-5 → Task 5；验收 → Task 6。五条债全覆盖，无遗漏（E-6 契约漂移属文档同步，不在本次安全范围，留 M3）。

**2. 类型一致性：** `_dev_login_enabled()` 返回 bool 且被测试直接 import；`_get_req_or_404(tenant_id, rid)` / `_get_contract_or_404(tenant_id, cid)` 的新签名在 Task 3 一次性改完 8 处调用点，避免半途 `TypeError`；`_require_accepted_invitation` 只在 `submit_score` 调用一次。

**3. 落地映射：** 所有 `Files:` 行都是绝对可定位的 `路径:行号`，行号取自 2026-11-19 10:32 的 `dev`/`develop` HEAD `b908490`。

**4. 比例：** 6 个任务、约 12 个新用例、4 个源文件改动；无新表、无迁移、无契约变更——与「横切收口」的量级匹配。

**5. 风险：** (a) Task 4 可能让 2–3 个既有用例红，已在约束 5 给出「补合法前置而非放宽断言」的处理办法；(b) Task 1 改变 ark/ark 的可用性，仓库内无任何代码/脚本引用该凭据（已 grep 确认），只影响人工冒烟习惯，计划用 `ARK_DEV_LOGIN=1` 保留该能力。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-11-19-security-hardening.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 每任务派一个新 subagent 实现，任务间我做 review，迭代快。

**2. Inline Execution** — 用 executing-plans 在本会话内逐任务 TDD 执行，每任务一个 commit，最后跑一次独立终审。

（按 M1-a…M2-c 的既有惯例，我默认走 **Inline + 末尾独立终审**；若你要每任务双人复核，选 1。）
