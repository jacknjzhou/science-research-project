# M2-c 外部专家 / 供应商协同 / 消息通道 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让外部专家与外部供应商以独立身份在门户内自助完成"注册→被邀→响应→留痕"，并让所有对外通知同时走站内信与邮件。

**Architecture:** 复用 M2-a 的机构（`SysPartnerOrg`）与角色归一机制，把"外部角色独占"扩为**外部允许集 `{R-PARTNER, R-EXPERT}`**（内部角色仍一律剥离）；N 域新增专家自助注册与信用档案（信用为**计算式**，不落新表）；G 域给 `GSupplier` 加 `org_id` 把供应商绑定到机构，询价复用既有 `GBid.bids_json`，合同进度以**脱敏只读**视图对外；通知统一走 `apps/notify/email.py` 的 `notify_user`（站内信 + best-effort 邮件）。

**Tech Stack:** Django 5 + django-ninja、PostgreSQL（测试用 SQLite）、Casbin（DB 权威 + `policy.csv` 引导）、Vue 3 + TypeScript。

**Spec:** `docs/reports/2026-11-12-conow-alignment-roadmap.md`（`## 三、M2` 的 C3/C4/C5 行 + 验收口径）；契约真源 `design/15-专家与评审管理-N.openapi.yaml`、`design/09-采购与合同管理-G.openapi.yaml`、`design/12-用户与权限-U.openapi.yaml`；DDL 真源 `design/15-专家与评审管理-N.ddl.sql`、`design/09-采购与合同管理-G.ddl.sql`。

## Global Constraints

- **双层隔离**：所有查询必须带 `tenant_id`；涉及外部机构的数据再加机构口径，跨机构一律 `404`（不泄露存在性）。
- **金额**：一律 `Decimal`，响应经 `num2()` 输出**字符串**；非法金额返回 `40001`，**禁止静默归 0**。
- **序列化键**：N/G/U 域一律 `snake_case`（本仓既有风格）；新增契约字段与实现键名**必须逐一对应**。
- **动作路径**：`POST /path/{id}:action` 冒号风格；静态段必须注册在动态段之前；动态段用 `{int:id}`。
- **错误码**：`40001` 参数/校验失败、`40301` 无权限、`40401` 不存在、`409`+`40901` 状态冲突、`40903` 重复指纹。
- **契约双份**：`design/*.yaml` 与 `frontend/src/api/schema/*.yaml` 必须 `cp` 后 `cmp` 一致，并用 `backend-django/.venv/bin/python -c "import yaml;yaml.safe_load(open(...))"` 校验。
- **Casbin 运行时权威是 DB**：改 `config/casbin/policy.csv` 必须同时新增 `apps/sysadmin/migrations/00NN_resync_permissions.py`（`RunPython` 调 `from apps.sysadmin.permissions import sync_permissions_from_csv`）。
- **迁移编号**：`apps/procure/migrations/` 下一个 `0002`；`apps/sysadmin/migrations/` 下一个 `0015`。
- **测试**：`django.test.Client` + `json.dumps` + `tests.conftest.bearer`；基线 **418 passed**；TDD 必须先见红。
- **前端**：`cd frontend && ./node_modules/.bin/vue-tsc --noEmit` 必须 0 errors。
- **外部角色允许集**：`EXTERNAL_ROLES = ("R-PARTNER", "R-EXPERT")`；外部账号只允许持有该集合内的角色，内部角色一律剥离。

## Review Focus

1. **外部专家登录后角色被裁光**：外部账号若同时是专家，必须同时保留 `R-EXPERT`，否则拿不到 `/reviews/*` 权限，一次评审都做不了。
2. **停用账号的存量 JWT**：管理员停用账号后，旧令牌在有效期内必须立刻失效（当前 `ark_auth` 不查 `SysUser.status`）。
3. **专家替他人响应/打分**：`accept`/`decline`/`scores` 的身份必须取自令牌，body 里的 `expert_id` 不得决定"我是谁"。
4. **供应商越界**：供应商只能看到自己被邀请的询价、自己机构绑定的合同；改报价只能改自己的条目，且**不能改已定标**的询价。
5. **对外脱敏**：供应商看到的合同/询价不得包含内部甲方信息、内部备注、AI 风险结论等字段。

---

### Task 1: 供应商机构绑定列 + DDL

**Files:**
- Modify: `backend-django/apps/procure/models.py:43-67`（`GSupplier`）
- Create: `backend-django/apps/procure/migrations/0002_gsupplier_org_id.py`
- Modify: `design/09-采购与合同管理-G.ddl.sql:88`（`G_SUPPLIER`）
- Test: `backend-django/tests/test_procure_m2c.py`

**Interfaces:**
- Produces: `GSupplier.org_id: int | None`（`BigIntegerField(null=True, blank=True)`；`None` = 院内供应商）；`apps.procure.api._supplier_or_404(tenant_id: int, supplier_id: int) -> GSupplier`。

- [ ] **Step 1: Write the failing test**

```python
def test_supplier_has_org_binding_column(seed_auth):
    from apps.procure.models import GSupplier
    from apps.sysadmin.models import SysPartnerOrg
    org = SysPartnerOrg.objects.create(
        code="PTN-2026-000101", tenant_id=1, name="外部供应商甲",
        org_type="SUPPLIER", status="APPROVED", creator_id=1,
    )
    s = GSupplier.objects.create(
        code="SUP-M2C-01", tenant_id=1, name="外部供应商甲", type="供应商",
        status="IN_LIBRARY", org_id=org.id, creator_id=1,
    )
    assert GSupplier.objects.get(id=s.id).org_id == org.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_procure_m2c.py -q`
Expected: FAIL — `TypeError: GSupplier() got unexpected keyword arguments: 'org_id'`

- [ ] **Step 3: Implement**

`apps/procure/models.py` 的 `GSupplier` 在 `expire_date` 之后加：

```python
    # M2-c：绑定外部合作机构（空=院内供应商）
    org_id = models.BigIntegerField(null=True, blank=True)
```

生成迁移 `apps/procure/migrations/0002_gsupplier_org_id.py`；`design/09-采购与合同管理-G.ddl.sql` 的 `G_SUPPLIER` 补 `org_id BIGINT NULL` 列注释 + `CREATE INDEX idx_sup_org ON G_SUPPLIER(org_id) WHERE deleted = 0;`。

同时在 `apps/procure/api.py` 末尾新增（T6/T7 复用）：

```python
def _supplier_or_404(tenant_id: int, supplier_id: int) -> GSupplier:
    s = GSupplier.objects.filter(id=supplier_id, tenant_id=tenant_id, deleted=0).first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "供应商不存在")
    return s


def _my_supplier(d) -> GSupplier | None:
    """外部账号 → 其机构绑定的供应商；无绑定返回 None（不抛，由调用点决定 403/空页）。"""
    from core.org_scope import current_org_id
    org_id = current_org_id(d)
    if not org_id:
        return None
    return GSupplier.objects.filter(
        tenant_id=d.tenant_id, org_id=org_id, deleted=0
    ).first()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_procure_m2c.py -q` → PASS；`pytest -q` → **419 passed**

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/procure/models.py backend-django/apps/procure/migrations/0002_gsupplier_org_id.py \
  backend-django/apps/procure/api.py design/09-采购与合同管理-G.ddl.sql backend-django/tests/test_procure_m2c.py
git commit -m "feat(procure): M2-c 供应商机构绑定列与 DDL（C4 表结构）"
```

---

### Task 2: 外部角色允许集 + 停用账号即时失效

**Files:**
- Modify: `backend-django/core/org_scope.py`
- Modify: `backend-django/core/auth/deps.py:36-58`
- Modify: `backend-django/core/auth/api.py`（登录签发处）
- Modify: `backend-django/apps/sysadmin/api.py:128-200`（`_assert_role_consistency` / `create_user`）、`:329`（`assign_role`）
- Modify: `backend-django/apps/p/api.py:78`（`_EXTERNAL_ROLE` 复用共享常量）
- Test: `backend-django/tests/test_auth_m2c.py`

**Interfaces:**
- Produces: `core.org_scope.EXTERNAL_ROLES: tuple[str, ...] = ("R-PARTNER", "R-EXPERT")`；`core.org_scope.external_roles_of(roles: list[str]) -> list[str]`（返回 `roles` 中属于允许集的项，保序去重）；`is_external_only(d)` 语义改为 `bool(set(roles) & set(EXTERNAL_ROLES))`；`apps.sysadmin.api._EXTERNAL_ROLE_CODES = ("R-PARTNER", "R-EXPERT")`。

- [ ] **Step 1: Write the failing tests**

```python
def test_external_expert_keeps_review_role(seed_auth):
    # 外部账号同时是专家：登录后应保留 R-EXPERT，剥掉内部角色
    from core.auth.jwt_util import gen_token
    from rest_framework.test import APIClient  # 本仓用 django.test.Client，见下
    ...


def test_external_roles_subset_kept_internal_stripped():
    from core.org_scope import external_roles_of
    assert external_roles_of(["R-PARTNER", "R-STAFF", "R-EXPERT"]) == ["R-PARTNER", "R-EXPERT"]
    assert external_roles_of(["R-STAFF"]) == []


def test_disabled_user_token_rejected_immediately(seed_auth):
    # 用真实登录拿令牌 → 停用账号 → 同一令牌请求必须 403/40302
    ...


def test_create_user_allows_partner_plus_expert(seed_auth):
    # EXTERNAL 账号允许 [R-PARTNER, R-EXPERT]；允许 [R-EXPERT] 不绑机构
    ...
```

四个用例分别落在 `tests/test_auth_m2c.py`，用 `django.test.Client` + `json.dumps` + `tests.conftest.bearer`（真实登录用 `POST /api/v1/auth/login`）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth_m2c.py -q`
Expected: 4 failed（`ImportError: cannot import name 'external_roles_of'`；停用账号仍 200；`create_user` 拒绝 `[R-PARTNER, R-EXPERT]`）

- [ ] **Step 3: Implement**

`core/org_scope.py`：

```python
EXTERNAL_ROLES: tuple[str, ...] = ("R-PARTNER", "R-EXPERT")


def external_roles_of(roles: list[str] | None) -> list[str]:
    """保留外部允许集内的角色（保序去重）；其余（内部角色）由调用方剥离。"""
    out: list[str] = []
    for r in roles or []:
        if r in EXTERNAL_ROLES and r not in out:
            out.append(r)
    return out


def is_external_only(d) -> bool:
    return bool(set(getattr(d, "roles", []) or []) & set(EXTERNAL_ROLES))
```

`core/auth/api.py` 登录签发处与 `core/auth/deps.py` 的 `ark_auth`：把「含 `R-PARTNER` 即裁为 `["R-PARTNER"]`」改为「若角色集含任一外部角色 → `roles = external_roles_of(roles)`」。

`core/auth/deps.py` 在解析 claims 后新增账号状态校验（**不缓存**，语义优先；性能由索引承担）：

```python
    if not _user_active(user_id, tenant_id):
        raise ApiError(403, CODE_ACCOUNT_DISABLED, "账号已停用")
```

其中 `_user_active(user_id, tenant_id)` 查 `SysUser.objects.filter(id=user_id, tenant_id=tenant_id, deleted=0).values_list("status", flat=True).first() == "ACTIVE"`；`user_id` 为 0/缺省时视为无账号（测试桩令牌路径）→ 直接返回 `True` 以保持既有测试语义。

`apps/sysadmin/api.py`：`_EXTERNAL_ROLE_CODES = ("R-PARTNER", "R-EXPERT")`；`_assert_role_consistency` 改为「`role_codes` 与 `_EXTERNAL_ROLE_CODES` 有交集 → 不得同时含内部角色；`R-PARTNER` 必须有 `org_id` 且机构 APPROVED；`R-EXPERT` 不要求机构」；`create_user` 的 EXTERNAL 分支允许 `role_codes ⊆ _EXTERNAL_ROLE_CODES`；`assign_role` 对带外部角色的账号拒绝追加内部角色。

`apps/p/api.py` 的 `_EXTERNAL_ROLE` 改为 `from core.org_scope import EXTERNAL_ROLES` 并用 `bool(set(roles) & set(EXTERNAL_ROLES))`。

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_auth_m2c.py -q` → 4 passed；`pytest -q` → **423 passed**（含既有 M2-a/M2-b 用例不回归；`test_c4_*`、`test_i4_*` 的归一断言按新语义调整）

- [ ] **Step 5: Commit**

```bash
git add backend-django/core/org_scope.py backend-django/core/auth/deps.py backend-django/core/auth/api.py \
  backend-django/apps/sysadmin/api.py backend-django/apps/p/api.py backend-django/tests/test_auth_m2c.py
git commit -m "feat(auth): M2-c 外部角色允许集（R-PARTNER+R-EXPERT）与停用账号即时失效（C3 前置）"
```

---

### Task 3: N 域租户与身份收口

**Files:**
- Modify: `backend-django/apps/expertreview/api.py:54-70`（`_get_expert_or_404`、`_get_task_or_404`）、`:291-340`（`_respond`、`submit_score`）
- Test: `backend-django/tests/test_expertreview_m2c.py`

**Interfaces:**
- Consumes: `core.org_scope.current_org_id(d)`、Task 2 的 `EXTERNAL_ROLES`
- Produces: `_get_expert_or_404(tenant_id: int, expert_id: int) -> NExpert`；`_get_task_or_404(tenant_id: int, task_id: int) -> NReviewTask`（**签名变更**，全部调用点同步）；`_my_expert_or_403(d) -> NExpert`（按 `user_id` 反查，找不到 → 40301）。

- [ ] **Step 1: Write the failing tests**

```python
def test_expert_and_task_lookups_are_tenant_scoped(seed_auth):
    # tenant=2 的 expert/task 在 tenant=1 下访问必须 404
    ...


def test_respond_uses_token_identity_not_body(seed_auth):
    # expert B 的令牌 + body.expert_id=专家A → 40001/40301，且 A 的邀请状态不变
    ...


def test_respond_rejects_other_experts_invitation(seed_auth):
    ...


def test_submit_score_ignores_foreign_expert_id(seed_auth):
    ...
```

- [ ] **Step 2: Run to fail**：`pytest tests/test_expertreview_m2c.py -q` → 4 failed

- [ ] **Step 3: Implement**

`_get_expert_or_404(tenant_id, expert_id)`、`_get_task_or_404(tenant_id, task_id)` 均加 `tenant_id=tenant_id` 过滤（`NExpert`/`NReviewTask` 都有 `tenant_id` 列）；所有调用点改为传 `d.tenant_id`。

`_respond(request, id, resp)`：删除 body 取 `expert_id` 的路径，改为

```python
    d = domain_from(request)
    expert = _my_expert_or_403(d)
    inv = NReviewInvitation.objects.filter(
        tenant_id=d.tenant_id, task_id=id, expert_id=expert.id, deleted=0
    ).first()
```

`body.expert_id` 若存在且 `!= expert.id` → `ApiError(400, CODE_BAD_REQUEST, "不得代他人响应")`。`submit_score` 同样以 `_my_expert_or_403(d)` 取代 body 的 `expert_id`。

- [ ] **Step 4: Run**：`pytest tests/test_expertreview_m2c.py -q` → 4 passed；`pytest -q` → **427 passed**

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/expertreview/api.py backend-django/tests/test_expertreview_m2c.py
git commit -m "fix(expertreview): M2-c 专家/评审按租户与令牌身份收口（C3）"
```

---

### Task 4: 专家自助注册 + 管理端审核

**Files:**
- Create: `backend-django/apps/expertreview/portal.py`（登录态专家门户 handler 集中处）
- Modify: `backend-django/apps/expertreview/mappings.py`（`to_api_expert_application`）
- Modify: `backend-django/config/api.py`（注册 `/portal/expert-apply`、`/expert-applications`、`/expert-applications/{id}/audit`）
- Modify: `backend-django/config/casbin/policy.csv` + Create `backend-django/apps/sysadmin/migrations/0015_resync_permissions.py`
- Modify: `design/15-专家与评审管理-N.openapi.yaml` + `frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml`
- Test: `backend-django/tests/test_expertreview_m2c.py`

**Interfaces:**
- Produces: `POST /api/v1/portal/expert-apply`（body: `name/title/org_name/field_tags` + 可选 `phone/email/cv_doc_ids`）、`GET /api/v1/expert-applications`（R-MANAGER）、`POST /api/v1/expert-applications/{id}/audit`（body `{"action": "APPROVE"|"REJECT", "reason": "..."}`）；`to_api_expert_application(e: NExpert) -> dict`。

- [ ] **Step 1: Write the failing tests**

```python
def test_partner_user_can_apply_as_expert(seed_auth):
    # POST /portal/expert-apply → 200；NExpert(status="CANDIDATE", source="EXTERNAL", user_id=本人)
    ...


def test_apply_twice_conflicts(seed_auth):
    # 第二次 → 409 40901
    ...


def test_manager_approves_expert_and_grants_role(seed_auth):
    # APPROVE → status=ACTIVE + 用户获得 R-EXPERT（内部角色不追加）+ 站内信 + mailoutbox 一件
    ...


def test_reject_requires_reason(seed_auth):
    # 缺 reason → 40001；有 reason → status 保持 CANDIDATE
    ...


def test_other_tenant_cannot_audit(seed_auth):
    # tenant=2 的申请在 tenant=1 下 audit → 404
    ...
```

- [ ] **Step 2: Run to fail**：5 failed（404 路由不存在）

- [ ] **Step 3: Implement**

`apps/expertreview/portal.py`：

```python
def apply_expert(request):
    """外部用户自助申请成为评审专家：建 CANDIDATE 记录，通知 R-MANAGER。"""


def list_expert_applications(request):
    """管理端列表：status 过滤（缺省 CANDIDATE），分页 {list,total,page,size}。"""


def audit_expert_application(request, id: int):
    """APPROVE：status=ACTIVE + 授 R-EXPERT（不追加内部角色）+ 双通道通知；
    REJECT：必填 reason，status 保持 CANDIDATE 并记录 remark。"""
```

要点：申请幂等键 `(tenant_id, user_id, deleted=0)` 已存在则 `409/40901`；`code` 用 `code_of("EXP", id)` 回填（`apps.procure.mappings` 无 `code_of` → 复用 `apps.funding.mappings.code_of`，前缀 `EXP` 已在 `00-common.sql` 前缀表则直接使用，否则在 `design/00-common.sql` 前缀表补一行 `('EXP','评审专家','N','v1.2',TRUE)`）；通知用 `apps.notify.email.notify_user`（Task 8 落地前的临时实现：直接 `notify_inapp(..., channel="BOTH")` + `send_mail_best_effort`）。

`policy.csv` 追加（列对齐既有 R-PARTNER 段）：`R-PARTNER /api/v1/portal/expert-apply POST`、`R-EXPERT /api/v1/portal/expert-apply POST`、`R-MANAGER /api/v1/expert-applications GET`、`R-MANAGER /api/v1/expert-applications/*/audit POST`。新增迁移 `0015_resync_permissions.py`。

契约（`15-N`）：`/portal/expert-apply` POST（200/400/409）、`/expert-applications` GET、`/expert-applications/{id}/audit` POST（200/400/404/409）+ `ExpertApplication`/`ExpertApplyRequest`/`ExpertAuditRequest` 三个 schema。

- [ ] **Step 4: Run**：5 passed；`pytest -q` → **432 passed**；契约副本 `cmp` SAME + `yaml.safe_load` OK

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/expertreview/portal.py backend-django/apps/expertreview/mappings.py \
  backend-django/config/api.py backend-django/config/casbin/policy.csv \
  backend-django/apps/sysadmin/migrations/0015_resync_permissions.py \
  design/15-专家与评审管理-N.openapi.yaml frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml \
  design/00-common.sql backend-django/tests/test_expertreview_m2c.py
git commit -m "feat(expertreview): 外部专家自助注册与资质审核（C3）"
```

---

### Task 5: 专家信用档案 + 门户评审/学术活动只读

**Files:**
- Modify: `backend-django/apps/expertreview/portal.py`
- Modify: `backend-django/config/api.py`
- Modify: `design/15-专家与评审管理-N.openapi.yaml` + 副本
- Test: `backend-django/tests/test_expertreview_m2c.py`

**Interfaces:**
- Produces: `_expert_credit(tenant_id: int, expert_id: int) -> dict`（键：`expertId, name, reviewCount, invitedCount, acceptedCount, declinedCount, expiredCount, acceptRate, onTimeRate, abstainCount, avgScore, lastReviewAt`，比率为 `str` 两位小数）；`GET /api/v1/experts/{id}/credit`（R-MANAGER/R-LEADER/R-EXPERT 只读本人由门户端点承载）；`GET /api/v1/portal/expert/credit`、`GET /api/v1/portal/expert/reviews`、`GET /api/v1/portal/expert/activities`。

- [ ] **Step 1: Write the failing tests**

```python
def test_credit_computes_rates_from_invitations(seed_auth):
    # 2 邀 1 接 1 拒 → acceptRate="0.50"；onTimeRate 按 responded_at-invited_at<=72h
    ...


def test_portal_credit_only_self(seed_auth):
    # 专家 A 令牌拿不到专家 B 的 credit（404）
    ...


def test_portal_reviews_lists_only_my_invitations(seed_auth):
    ...


def test_portal_activities_lists_invited_activities(seed_auth):
    # VActivityParticipant.user_id=我的活动
    ...
```

- [ ] **Step 2: Run to fail**：4 failed

- [ ] **Step 3: Implement**

`_expert_credit` 用 `NReviewInvitation` 聚合（`invitedCount`=全部、`accepted/declined/expired` 按 `response`）、`NReviewScore` 聚合（`avgScore` 用 `Avg("total_score")`，`abstainCount` 数 `status="ABSTAIN"`）、`onTimeRate = 72h 内 responded / responded 总数`，分母为 0 时比率返回 `"0.00"`。

门户三端点均以 `_my_expert_or_403(d)` 取本人；`/portal/expert/activities` 查 `VActivityParticipant.objects.filter(tenant_id=d.tenant_id, user_id=d.user_id, deleted=0)` 关联 `VActivity`（只读 `id/title/start_at/location/role`）。

契约：`/experts/{id}/credit` GET + `ExpertCredit` schema；`/portal/expert/credit` GET、`/portal/expert/reviews` GET、`/portal/expert/activities` GET。

- [ ] **Step 4: Run**：4 passed；`pytest -q` → **436 passed**

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/expertreview/portal.py backend-django/config/api.py \
  design/15-专家与评审管理-N.openapi.yaml frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml \
  backend-django/tests/test_expertreview_m2c.py
git commit -m "feat(expertreview): 专家信用档案与门户评审/学术活动只读（C3）"
```

---

### Task 6: 供应商门户询价与应价

**Files:**
- Create: `backend-django/apps/procure/portal.py`
- Modify: `backend-django/config/api.py`
- Modify: `backend-django/config/casbin/policy.csv` + Create `backend-django/apps/sysadmin/migrations/0016_resync_permissions.py`
- Modify: `design/09-采购与合同管理-G.openapi.yaml` + 副本
- Test: `backend-django/tests/test_procure_m2c.py`

**Interfaces:**
- Consumes: Task 1 的 `_my_supplier(d)`、`_supplier_or_404`
- Produces: `GET /api/v1/portal/supplier/inquiries`、`POST /api/v1/portal/supplier/inquiries/{id}:quote`（body `{"totalAmount": "1234.00", "remark": "..."}`）、`_bid_or_404(tenant_id: int, bid_id: int) -> GBid`、`_my_bid_or_404(d, bid_id) -> GBid`。

- [ ] **Step 1: Write the failing tests**

```python
def test_supplier_sees_only_invited_inquiries(seed_auth):
    # 邀请了我 → 列表可见；未邀请 → 不可见（404 而非 403）
    ...


def test_supplier_quote_appends_to_bids_json(seed_auth):
    # 应价后 bids_json 含 {"supplierId":..., "totalAmount":"1234.00"}，金额为字符串
    ...


def test_supplier_quote_rejected_after_award(seed_auth):
    # bid.status != "PUBLICIZING" → 409 40901
    ...


def test_supplier_cannot_quote_others_inquiry(seed_auth):
    ...


def test_unbound_partner_gets_empty_list(seed_auth):
    # 机构未绑定供应商 → 列表空、应价 403
    ...
```

- [ ] **Step 2: Run to fail**：5 failed

- [ ] **Step 3: Implement**

`apps/procure/portal.py`：`list_supplier_inquiries(request)`（`GBid.objects.filter(tenant_id=..., deleted=0, invited_supplier_ids__contains=[s.id])` 用 JSON contains；Django 在 SQLite 上 `__contains` 对 JSON 数组可用；返回 `{id, code, method, title, deadline, quoted: bool}`，**不含** 内部 requisition 明细与预算）、`quote_inquiry(request, id: int)`（`_my_supplier` → `None` 则 40301；`_my_bid_or_404` → `s.id in invited_supplier_ids` 否则 404；`status != "PUBLICIZING"` → 409/40901；`_money_strict(body.get("totalAmount"))`（复用 `apps.funding.api._money_strict` 的语义：非法/非正 → 40001）→ 以 `supplierId` 去重后 append 进 `bids_json`）。

policy 追加：`R-PARTNER /api/v1/portal/supplier/inquiries GET`、`R-PARTNER /api/v1/portal/supplier/inquiries/*:quote POST`；迁移 `0016_resync_permissions.py`。

契约 `09-G`：两条路径 + `SupplierInquiry`/`SupplierQuoteRequest` schema。

- [ ] **Step 4: Run**：5 passed；`pytest -q` → **441 passed**；契约 cmp SAME

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/procure/portal.py backend-django/config/api.py \
  backend-django/config/casbin/policy.csv backend-django/apps/sysadmin/migrations/0016_resync_permissions.py \
  design/09-采购与合同管理-G.openapi.yaml frontend/src/api/schema/09-采购与合同管理-G.openapi.yaml \
  backend-django/tests/test_procure_m2c.py
git commit -m "feat(procure): 供应商门户询价列表与在线应价（C4）"
```

---

### Task 7: 供应商合同进度（脱敏只读）

**Files:**
- Modify: `backend-django/apps/procure/portal.py`
- Modify: `backend-django/config/api.py`
- Modify: `design/09-采购与合同管理-G.openapi.yaml` + 副本
- Test: `backend-django/tests/test_procure_m2c.py`

**Interfaces:**
- Produces: `GET /api/v1/portal/supplier/contracts`；`_api_contract_for_supplier(c: GContract) -> dict`，返回键固定为 `id, code, name, amount, signedAt, endDate, payPhaseCount, paidAmount, paidRatio, status`（**不含** `party_a`/`remark`/`ai_parse_json`/`ai_risk_json`/`requisitionId`）。

- [ ] **Step 1: Write the failing tests**

```python
def test_supplier_sees_own_contracts_only(seed_auth):
    ...


def test_contract_payload_is_masked(seed_auth):
    # 断言响应键集合 == 白名单；"party_a"/"remark"/"ai_risk_json" 不在其中
    ...


def test_paid_ratio_is_string_two_decimals(seed_auth):
    ...
```

- [ ] **Step 2: Run to fail**：3 failed

- [ ] **Step 3: Implement**

`list_supplier_contracts(request)`：`_my_supplier(d)` → `None` 返回空页；否则 `GContract.objects.filter(tenant_id=d.tenant_id, supplier_id=s.id, deleted=0)`；`paidAmount = Sum(GContractPayment.paid_amount)`，`paidRatio = num2(paid/amount)`（`amount` 为 0 时 `"0.00"`）；`payPhaseCount` 数 payment 行数。

契约 `09-G` 补 `GET /portal/supplier/contracts` + `SupplierContract` schema（上述 10 键）。

- [ ] **Step 4: Run**：3 passed；`pytest -q` → **444 passed**

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/procure/portal.py backend-django/config/api.py \
  design/09-采购与合同管理-G.openapi.yaml frontend/src/api/schema/09-采购与合同管理-G.openapi.yaml \
  backend-django/tests/test_procure_m2c.py
git commit -m "feat(procure): 供应商门户合同进度脱敏只读（C4）"
```

---

### Task 8: 统一外发通道 `notify_user` + 四处接线

**Files:**
- Modify: `backend-django/apps/notify/email.py`
- Modify: `backend-django/apps/expertreview/api.py:531`（invite）、`apps/expertreview/portal.py`（审核结论）
- Modify: `backend-django/apps/procure/api.py`（`create_bid` 邀请通知）、`apps/procure/portal.py`（应价成功回执）
- Modify: `backend-django/apps/p/api.py`（`decide_application` 决议通知）
- Test: `backend-django/tests/test_notify_email.py`

**Interfaces:**
- Produces: `notify_user(tenant_id: int, user_id: int, typ: str, title: str, content: str, biz_ref: str = "", *, channel: str = "BOTH") -> int` —— 站内信一行 + `channel` 含邮件时按 `SysUser.email` 发 best-effort 邮件；返回 `SysNotification.id`；**任何异常均不抛**。

- [ ] **Step 1: Write the failing tests**

```python
def test_notify_user_writes_inapp_and_sends_mail(seed_auth):
    # 返回 id>0；SysNotification.channel=="BOTH"；len(mail.outbox)==1
    ...


def test_notify_user_without_email_still_writes_inapp(seed_auth):
    ...


def test_expert_invite_triggers_mail(seed_auth):
    # /reviews/{id}/invite 后 outbox 有发给专家 email 的邮件
    ...


def test_decide_application_notifies_partner_by_mail(seed_auth):
    ...
```

- [ ] **Step 2: Run to fail**：4 failed

- [ ] **Step 3: Implement**

`apps/notify/email.py` 新增 `notify_user(...)`（内部先 `notify_inapp(..., channel=channel)`，再 `if "EMAIL" in channel or channel == "BOTH"` → 查 `SysUser.email` → `send_mail_best_effort`，整体 `try/except` 包住）。

四处接线：`invite` 给每位被邀专家发「评审邀请」+ 邮件；`audit_expert_application` 结论；`create_bid` 给 `invited_supplier_ids` 对应机构联系人发询价邀请；`decide_application` 给 PI（外部则同时给机构邮箱）发决议。

- [ ] **Step 4: Run**：4 passed；`pytest -q` → **448 passed**

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/notify/email.py backend-django/apps/expertreview/api.py \
  backend-django/apps/expertreview/portal.py backend-django/apps/procure/api.py \
  backend-django/apps/procure/portal.py backend-django/apps/p/api.py \
  backend-django/tests/test_notify_email.py
git commit -m "feat(notify): M2-c 统一外发通道 notify_user 并接线四处对外通知（C5）"
```

---

### Task 9: 前端——专家门户 / 供应商门户 / 管理端

**Files:**
- Create: `frontend/src/views/portal/ExpertView.vue`（申请状态 + 我的评审 + 信用卡 + 学术活动）
- Create: `frontend/src/views/portal/SupplierView.vue`（询价列表 + 应价抽屉 + 合同进度）
- Create: `frontend/src/views/admin/ExpertApplicationsView.vue`（列表 + 通过/驳回）
- Modify: `frontend/src/router/index.ts`、`frontend/src/App.vue`（nav）
- Modify: `frontend/src/api/mock/overrides/portal.ts`、`frontend/src/api/mock/overrides/auth.ts`（caps + `PAGE_GRANTS`）
- Test: `cd frontend && ./node_modules/.bin/vue-tsc --noEmit`

**Interfaces:**
- Consumes: Task 4/5/6/7 的端点路径与响应键（`ExpertCredit`/`SupplierInquiry`/`SupplierContract`）
- Produces: 路由名 `portal-expert`、`portal-supplier`、`admin-expert-applications`

- [ ] **Step 1: Write the three views**

`portal/ExpertView.vue`：未申请时显示「申请成为评审专家」表单（`name/title/org_name/field_tags`）；已申请显示状态徽标（CANDIDATE/ACTIVE）；ACTIVE 时展示信用卡（`acceptRate`/`onTimeRate`/`avgScore`）、我的评审列表（任务标题/截止/响应状态）、学术活动列表。

`portal/SupplierView.vue`：询价表（编号/标题/截止/是否已应价）+ 应价抽屉（金额必填、两位小数、备注）；合同进度表（编号/金额/已付/比例/状态），**不渲染任何甲方内部字段**。

`admin/ExpertApplicationsView.vue`：状态过滤（缺省 CANDIDATE）+ 通过/驳回抽屉（驳回理由必填）。

- [ ] **Step 2: Wire router / nav / mock / caps**

`router/index.ts` 三条路由：`/portal/expert`（`meta.roles: ['R-PARTNER','R-EXPERT']`）、`/portal/supplier`（`meta.roles: ['R-PARTNER']`）、`/admin/expert-applications`（`meta.roles: ['R-MANAGER','R-ADMIN']`）。`App.vue` nav 对应三项。`mock/overrides/portal.ts` 补 8 个端点（含 `:quote`）；`auth.ts` 的 `ROLE_CAPS` 补 `R-EXPERT` 段与 `R-PARTNER` 新增 caps，`PAGE_GRANTS` 补 3 行。

- [ ] **Step 3: Typecheck**

Run: `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` → 0 errors

- [ ] **Step 4: Backend regression**

Run: `cd backend-django && .venv/bin/python -m pytest -q` → **448 passed**（前端提交不动后端）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/portal/ExpertView.vue frontend/src/views/portal/SupplierView.vue \
  frontend/src/views/admin/ExpertApplicationsView.vue frontend/src/router/index.ts frontend/src/App.vue \
  frontend/src/api/mock/overrides/portal.ts frontend/src/api/mock/overrides/auth.ts
git commit -m "feat(fe): 专家门户/供应商门户/专家申请审核视图——契约驱动 mock 对齐 M2-c"
```

---

### Task 10: 种子 + README + 全量验收

**Files:**
- Modify: `backend-django/apps/sysadmin/management/commands/seed_demo.py`（M2-b 段之后追加 M2-c 段）
- Modify: `README.md`（三处测试数 418 → 实测 N）
- Test: `backend-django/tests/test_seed_demo.py`、全量套件

**Interfaces:**
- Consumes: 前面全部任务

- [ ] **Step 1: 追加种子段**

在 M2-b 段之后、`return cnt` 之前追加：①外部供应商机构 `PTN-2026-000003`（`org_type="SUPPLIER"`、`status="APPROVED"`）+ `GSupplier` 绑定 `org_id`；②`GBid` 一条 `PUBLICIZING` 且 `invited_supplier_ids=[该供应商]`；③`GContract`+两条 `GContractPayment`（一条 `PAID`）绑该供应商；④外部专家账号 `expert_ext`（`user_source="EXTERNAL"`、角色 `["R-EXPERT"]`、无 `org_id`）+ `NExpert(status="ACTIVE", user_id=该账号, source="EXTERNAL")`；⑤一条 `CANDIDATE` 专家申请（挂 `partner` 账号）留给审核演示；⑥`VActivity`+`VActivityParticipant(user_id=expert_ext)`。

- [ ] **Step 2: 幂等验证**

Run（单进程文件库）：
```bash
cd backend-django && ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2c_seed.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate && \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2c_seed.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo
```
再跑一次 seed → 第二遍 `created=0` 全零。

- [ ] **Step 3: 更新 README 三处测试数**

Run: `cd backend-django && .venv/bin/python -m pytest -q` → 记录 N，回填 README 三处。

- [ ] **Step 4: 全量验收**

```bash
cd backend-django && .venv/bin/python -m pytest -q          # N passed
.venv/bin/python manage.py makemigrations --check --dry-run  # No changes
.venv/bin/python -c "import yaml;[yaml.safe_load(open(f)) for f in __import__('glob').glob('../design/*.yaml')]"
cd ../frontend && ./node_modules/.bin/vue-tsc --noEmit        # 0 errors
```

- [ ] **Step 5: Commit**

```bash
git add backend-django/apps/sysadmin/management/commands/seed_demo.py README.md
git commit -m "chore(seed+readme): M2-c 演示数据（外部专家/供应商询价/合同）+ 测试数更新"
```

---

## Self-Review

1. **Spec 覆盖**：C3（专家注册→信用档案→学术活动邀请→accept/decline）= Task 4/5 + Task 3 收口；C4（询价比价→供应商门户→合同进度脱敏）= Task 1/6/7；C5（站内信+email 对外）= Task 8（+Task 9 前端只读）。验收口径三条：外部角色域=Task 2；tenant/机构隔离测试=Task 3/6/7；涉密域默认全拒=Task 2 的既有 `test_m2b_partner_denied_admin_and_secret_domains` 延续。
2. **步进扫描**：每个 Step 单一动作，测试步给出用例名与断言，代码步给出签名与落点，无「TBD/适当处理」类空步。
3. **类型一致**：`_get_expert_or_404(tenant_id, expert_id)`、`_get_task_or_404(tenant_id, task_id)`、`_my_expert_or_403(d)`、`_my_supplier(d)`、`_supplier_or_404(tenant_id, supplier_id)`、`_bid_or_404(tenant_id, bid_id)`、`notify_user(...)`、`external_roles_of(roles)` 在后续任务中的调用均与 Interfaces 一致。
4. **Review Focus**：5 条各有序例归属（1→Task 2、2→Task 2、3→Task 3、4→Task 6/7、5→Task 7）。
5. **比例**：文档以签名为准，未复写实现体；总长与 3 个功能面相符。

## Execution Handoff

- 执行方式：**native**（沿用 M2-a/M2-b，用户已多次指定）；逐任务 TDD + `task-done` 记账 + 每任务提交，最后一位独立评审守 auth/租户/机构/脱敏边界。
- ledger：`.superpowers/sdd/2026-11-19-m2c-expert-supplier-channel/progress.md`，BASE=`9f087e9`。
