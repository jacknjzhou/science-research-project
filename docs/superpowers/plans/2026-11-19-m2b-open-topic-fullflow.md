# M2-b 开放课题全流程（指南建议 → 申报 → 立项签约 → 任务书 → 阶段汇报 → 中期检查 → 验收结题）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一家外部机构用户（R-PARTNER）在线上走完「指南建议 → 在线申报 → 立项签约（任务书电子签章）→ 阶段汇报 → 验收结题」，与院内管理端（R-MANAGER/R-LEADER）在同一套 P/E 域数据上协作。

**Architecture:** 复用既有 P 域申报书与 E 域项目模型，不另造平行体系：申报主体从「院内部处室」扩为「院内 or 外部机构」（`p_application.applicant_org_id/applicant_type`），立项通过**任务书签订**落到 `E_PROJECT`（新增 `ext_org_id` 标记外部归属），阶段汇报与验收沿用既有 `EProgressReport/EFinalAccept`，靠 `ext_org_id == 当前用户 org_id` 做机构级隔离。指南建议作为新表 `p_guide_suggestion`，采纳后生成 `p_guideline` 草稿，接上 M1-d 的 `:publish/:close`。

**Tech Stack:** Django 5 + django-ninja（`backend-django`）、PostgreSQL 15（测试 sqlite）、Vue 3.4 + TypeScript（`frontend`）、Casbin（DB 策略，policy.csv 为源 + resync 迁移）、pytest（`django.test.Client` 集成风格）。

**Spec:** `docs/reports/2026-11-12-conow-alignment-roadmap.md` 的 `## 三、M2：多组织协同` C2 行（开放课题全流程）与 `验收口径`；上游已落地 `docs/superpowers/plans/2026-11-18-m2a-partner-onboarding-portal.md`（R-PARTNER 角色域、门户、邮件通道）。

## Global Constraints

- **租户隔离**：每个查询都必须带 `tenant_id=d.tenant_id`；**机构隔离**：外部用户的业务数据只按 `org_id` 过滤，跨机构一律 404（不是 403，不泄露存在性）。
- **金额**：`Decimal` 运算，对外 `num2()` → 字符串；非法金额 40001，**绝不静默归 0**。
- **响应键名**：P 域、E 域、U 域既有序列化器全 **snake_case** —— 新增序列化器沿用 snake_case（M2-a 已定稿，勿改成 camelCase）；请求体双读（camelCase 先、snake_case 兜底）仅用于既有契约已是 camelCase 的端点。
- **路由**：动作用冒号风格 `/path/{id}:action`；静态段必须先于动态段注册；动态段用 `{int:id}` 类型化。
- **错误码**：`40001` 参数/状态非法、`40301` 无权限（handler 内 `has_role`）、`40401` 不存在、`40901` 状态冲突、`40903` 重复。
- **契约双份**：改 `design/01-...P.openapi.yaml` / `design/02-...E.openapi.yaml` 后必须 `cp` 到 `frontend/src/api/schema/` 并 `cmp` 一致；改动后用 `backend-django/.venv/bin/python -c "import yaml;yaml.safe_load(...)"` 校验（系统 python3 无 yaml）。
- **Casbin**：运行时权威是数据库（`core/auth/casbin_util.py` DbAdapter）。只改 `config/casbin/policy.csv` **不生效**，每次改策略必须同时新增一个 `RunPython(sync_permissions_from_csv)` 的数据迁移。
- **迁移编号**：`apps/p/migrations/` 下一个是 `0003`；`apps/project/migrations/` 下一个是 `0006`；`apps/sysadmin/migrations/` 下一个是 `0012`。
- **TDD**：先写失败测试再写实现；集成测试用 `from django.test import Client` + `json.dumps` + `tests.conftest.bearer(uid, roles)`（参照 `tests/test_funding_m1c.py:47-52`）。
- **测试基线**：当前 `pytest` **381 passed**。每个任务完成后必须全绿，且 `makemigrations --check` 无变更。
- **前端校验**：`cd frontend && ./node_modules/.bin/vue-tsc --noEmit`（**不要**用 `pnpm exec vue-tsc`，会因 esbuild 未构建脚本失败）。
- **不重开的既有裁定**：`sys_notification` 不补 DDL、mock 层无错误通道、门户未读卡不跳转、`_guideline_status_scope` 的「仅单一 R-PARTNER 角色才算外部」规则。

## Review Focus

1. **外部用户能否绕过机构边界读到别家数据**：任何新增/改动的 P/E 端点，用 tenant-2 或 org-B 的身份访问 tenant-1/org-A 的记录必须 404 —— 现有代码已有三处裸查询（`get_application`、`_get_app_or_404`、`create_progress_report` 用的是无 tenant 的 `_get_project_or_404`），本计划必须全部收口。
2. **任务书签订是否把「一次」变成「两次」**：重复签同一角色、SIGNED 后再签、并发双签，都不得生成两个 `E_PROJECT`（`application_id` 唯一 + 事务内 `select_for_update`）。
3. **外部申报人能不能改自己的 PI/机构**：`create_application` 传 `pi_user_id` 指向别人、或传 `applicant_org_id` 指向别家机构时，必须以本机构/本人为准而不是报 500 或照单全收。
4. **签章后的金额与快照是否被人为改写**：`content_snapshot`、`total_budget`、`ext_org_id` 在 SIGNED 之后不可变；再改申报书返回 40901。
5. **外部用户是否被误放进涉密域或院内管理端点**：R-PARTNER 不得获得 `/api/v1/x/*`、`/api/v1/users/*`、`/api/v1/partner-orgs*`、`/api/v1/project/*` 的读权限（除本计划显式列出的机构作用域端点）。

---

### Task 1: 模型与迁移（机构化申报 + 指南建议 + 任务书 + 项目外部归属）

**Files:**
- Modify: `backend-django/apps/p/models.py`（`PApplication` 加两列；文件末尾新增 `PGuideSuggestion`、`PTaskBook`）
- Create: `backend-django/apps/p/migrations/0003_m2b_org_application_suggestion_taskbook.py`
- Modify: `backend-django/apps/project/models.py`（`EProject` 加 `ext_org_id`）
- Create: `backend-django/apps/project/migrations/0006_eproject_ext_org_id.py`
- Modify: `design/01-项目申报与立项-P.ddl.sql`（`p_application` 补两列 + 新增 `p_guide_suggestion` 表）
- Modify: `design/00-common.sql`（`seq_prefix_registry` 加 `SUG`；`p_task_book` 前缀 `PRJ` 已在，确认注释）
- Modify: `design/02-项目过程管理-E.ddl.sql`（`E_PROJECT` 补 `ext_org_id`）
- Test: `backend-django/tests/test_p_m2b.py`（新建）

**Interfaces:**
- Produces:
  - `PApplication.applicant_org_id: BigIntegerField(null=True)`、`PApplication.applicant_type: CharField(max_length=16, default="INTERNAL")`
  - `PGuideSuggestion`（`db_table="p_guide_suggestion"`）：`code`(64,null) / `tenant_id` / `org_id`(null) / `proposer_user_id` / `title`(256) / `background`(Text,null) / `objective`(Text,null) / `expected_output`(Text,null) / `contact_name`(64,null) / `contact_phone`(32,null) / `contact_email`(128,null) / `status`(32, default `PENDING`) / `review_user_id`(null) / `reviewed_at`(null) / `reject_reason`(512,null) / `guideline_id`(null) / `deleted` / `creator_id` / `modifier_id` / `created_at` / `updated_at` / `remark`
  - `PTaskBook`（`db_table="p_task_book"`，DDL 逐列）：`code`(64,null) / `tenant_id` / `status`(32, default `DRAFT`) / `deleted` / 审计列 / `application_id`(BigInteger) / `content_snapshot`(JSON, default dict) / `print_template_code`(64,null) / `signed_pdf_url`(512,null) / `sign_records`(JSON, default list) / `effective_date`(Date,null) / `project_id`(BigInteger,null)
  - `EProject.ext_org_id: BigIntegerField(null=True)`
- 状态枚举（与 DDL CHECK 一致，写进模型注释）：`PGuideSuggestion.status` ∈ `PENDING|ACCEPTED|REJECTED`；`PTaskBook.status` ∈ `DRAFT|SIGNED|EXECUTING`；`PApplication.applicant_type` ∈ `INTERNAL|EXTERNAL`。
- 索引：`PGuideSuggestion` Meta.indexes = `idx_p_guides_tenant_st (tenant_id,status)`、`idx_p_guides_org (org_id)`；`PTaskBook` Meta.indexes = `idx_p_tb_tenant_st (tenant_id,status)`、`idx_p_tb_project (project_id)`；条件唯一 `uk_p_task_book_app (application_id) WHERE deleted=0`、`uk_p_guides_code` 只做 DDL（不进 Meta，sqlite 不支持条件唯一，沿用既有先例）。

- [ ] **Step 1: 写失败测试 `tests/test_p_m2b.py::test_m2b_models_exist_with_ddl_columns`**

```python
from apps.p.models import PApplication, PGuideSuggestion, PTaskBook
from apps.project.models import EProject

def test_m2b_models_exist_with_ddl_columns(db):
    s = PGuideSuggestion.objects.create(
        tenant_id=1, creator_id=1, title="建议一", status="PENDING")
    assert s.deleted == 0 and s.status == "PENDING"
    t = PTaskBook.objects.create(
        tenant_id=1, creator_id=1, application_id=1, status="DRAFT")
    assert t.content_snapshot == {} and t.sign_records == []
    a = PApplication.objects.create(
        tenant_id=1, creator_id=1, title="T", project_type="ZIGE", pi_user_id=1)
    assert a.applicant_type == "INTERNAL" and a.applicant_org_id is None
    assert "ext_org_id" in [f.name for f in EProject._meta.get_fields()]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_p_m2b.py -q`
Expected: FAIL（`ImportError: cannot import name 'PGuideSuggestion'`）

- [ ] **Step 3: 实现模型三处**

`apps/p/models.py`：`PApplication` 在 `funding_channel` 后插入

```python
    applicant_org_id = models.BigIntegerField(null=True, blank=True)  # 外部机构 → sys_partner_org(id)；空=院内
    applicant_type = models.CharField(max_length=16, default="INTERNAL")  # INTERNAL/EXTERNAL
```

文件末尾按 DDL 加两个类（字段顺序与 DDL 一致、`Meta.db_table` 用 DDL 表名小写 `p_guide_suggestion` / `p_task_book`）。
`apps/project/models.py`：`EProject` 在 `category_id` 后加 `ext_org_id = models.BigIntegerField(null=True, blank=True)  # 外部合作机构 → sys_partner_org(id)`。

- [ ] **Step 4: 生成迁移并改名**

```bash
cd backend-django
.venv/bin/python manage.py makemigrations p --name m2b_org_application_suggestion_taskbook
.venv/bin/python manage.py makemigrations project --name eproject_ext_org_id
.venv/bin/python manage.py makemigrations --check   # 期望 No changes detected
```

- [ ] **Step 5: 补 DDL**

`design/01-项目申报与立项-P.ddl.sql`：`p_application` 建表列后补 `applicant_org_id BIGINT`（COMMENT：外部机构 → sys_partner_org(id)，空=院内）、`applicant_type VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'`（CHECK IN ('INTERNAL','EXTERNAL')）；文件末尾加 `p_guide_suggestion` 建表（含 status CHECK 三态、`idx_p_guides_tenant_st`、`idx_p_guides_org`、`uk_p_guides_code ON (tenant_id, code) WHERE deleted=0`）+ 尾注「M2-b 增补：前缀 SUG 已在 00-common.sql seq_prefix_registry 登记」。
`design/00-common.sql`：`seq_prefix_registry` INSERT 追加一行 `('SUG','指南建议','P','v1.2',TRUE)`。
`design/02-项目过程管理-E.ddl.sql`：`E_PROJECT` 补 `ext_org_id BIGINT`（COMMENT：外部合作机构→sys_partner_org(id)，空=院内自建）。

- [ ] **Step 6: 跑测试与全量**

Run: `cd backend-django && .venv/bin/python -m pytest -q` 
Expected: `382 passed`（381 + 1）

- [ ] **Step 7: Commit**

```bash
git add backend-django/apps/p/models.py backend-django/apps/p/migrations/0003_m2b_org_application_suggestion_taskbook.py backend-django/apps/project/models.py backend-django/apps/project/migrations/0006_eproject_ext_org_id.py backend-django/tests/test_p_m2b.py design/01-项目申报与立项-P.ddl.sql design/02-项目过程管理-E.ddl.sql design/00-common.sql
git commit -m "feat(p+project): M2-b 机构化申报/指南建议/任务书模型与项目外部归属列、迁移 0003+0006（C2 表结构）"
```

---

### Task 2: 机构/租户隔离收口 + R-PARTNER 业务策略域

**Files:**
- Create: `backend-django/core/org_scope.py`（机构作用域唯一入口，p/project 两域共用）
- Modify: `backend-django/apps/p/api.py`（`_get_app_or_404`、`get_application` 加 tenant；新增 `_partner_app_or_404`）
- Modify: `backend-django/apps/project/api.py`（`create_progress_report` 改用 `_get_project_or_404_tenant`；新增 `_partner_project_or_404(d, project_id)`）
- Modify: `backend-django/config/casbin/policy.csv`
- Create: `backend-django/apps/sysadmin/migrations/0012_resync_permissions.py`
- Test: `backend-django/tests/test_p_m2b.py`（追加）、`backend-django/tests/test_rbac.py`（追加）

**Interfaces:**
- Consumes: `PApplication.applicant_org_id`（Task 1）、`EProject.ext_org_id`（Task 1）
- Produces:
  - `core.org_scope` 两个助手（见下）
  - `_get_app_or_404(tenant_id: int, app_id: int) -> PApplication`（**签名变更**：旧签名 `(app_id)` 删除，全部调用点同步改）
  - `_partner_app_or_404(d, app_id: int) -> PApplication`：跨租户或跨机构 → 404
  - `core.org_scope.current_org_id(d) -> int | None`：外部机构 id。**JWT claims 里没有 org_id**（`core/auth/jwt_util.py:15-34` 的 `gen_token` 只签 uid/tenant/legal_entity/security_level/roles），因此该助手按 `d.user_id` 查一次 `SysUser.org_id`（`d.user_id<=0` 直接 None）
  - `core.org_scope.is_external_only(d) -> bool`：角色集恰为 `{"R-PARTNER"}` 且 `current_org_id(d)` 非空才 True（与 M2-a 的 `_guideline_status_scope` 口径一致；无角色异常态返回 True 但 `current_org_id` 为 None → 调用方按 404 处理）
  - `_partner_project_or_404(d, project_id: int) -> EProject`：`ext_org_id == current_org_id(d)` 才算存在，否则 404
  - 响应：`{"detail": "..."}` 走既有 `ApiError` 信封

- [ ] **Step 1: 写失败测试（隔离）**

```python
def test_application_and_project_are_org_scoped(seed_auth):
    # tenant-2 的申报单，用 tenant-1 身份读必须 404
    other = PApplication.objects.create(tenant_id=2, creator_id=1, title="别家",
                                        project_type="ZIGE", pi_user_id=1)
    assert _get(f"/api/v1/apply/applications/{other.id}").status_code == 404
    # 外部机构 B 读机构 A 的项目必须 404
    proj = EProject.objects.create(tenant_id=1, creator_id=1, application_id=1,
                                   title="A 课题", pi_user_id=1, ext_org_id=11)
    assert _get(f"/api/v1/project/{proj.id}/progress-report",
                roles=("R-PARTNER",), uid=partner_b_uid).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_p_m2b.py -q -k org_scoped`
Expected: FAIL（tenant-2 记录返回 200）

- [ ] **Step 3: 实现隔离收口**

新建 `core/org_scope.py`：

```python
"""外部机构作用域（M2-b）：单一入口，避免各域各写一份角色/机构判定。"""
from __future__ import annotations

_EXTERNAL_ROLE = "R-PARTNER"


def current_org_id(d) -> int | None:
    """当前用户所属外部机构；院内用户/无 org 返回 None（每次调用一次轻量查询）。"""
    uid = getattr(d, "user_id", 0) or 0
    if uid <= 0:
        return None
    from apps.sysadmin.models import SysUser

    return (
        SysUser.objects.filter(id=uid, deleted=0)
        .values_list("org_id", flat=True)
        .first()
    )


def is_external_only(d) -> bool:
    """纯外部身份：角色集恰为 {R-PARTNER}（与 apps/p/api.py:65 的指南口径同源）。"""
    roles = [r for r in (getattr(d, "roles", None) or []) if r]
    return roles == [_EXTERNAL_ROLE]
```

`apps/p/api.py`：

```python
def _get_app_or_404(tenant_id: int, app_id: int) -> PApplication:
    a = PApplication.objects.filter(id=app_id, tenant_id=tenant_id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a


def _app_org_of(a: PApplication) -> int | None:
    return a.applicant_org_id


def _partner_app_or_404(d, app_id: int) -> PApplication:
    a = _get_app_or_404(d.tenant_id, app_id)
    if a.applicant_org_id is None or a.applicant_org_id != current_org_id(d):
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a
```

`get_application` 改 `PApplication.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0)`；`withdraw_application` / `terminate_application` 内 `_get_app_or_404(id)` 全部改 `_get_app_or_404(d.tenant_id, id)`（含 documents/budget/sections/submit 五处）。
`apps/project/api.py`：`create_progress_report` 第一行改 `_get_project_or_404_tenant(id, d.tenant_id)`；新增

```python
def _partner_project_or_404(d, project_id: int) -> EProject:
    p = EProject.objects.filter(id=project_id, tenant_id=d.tenant_id, deleted=0).first()
    if p is None or p.ext_org_id is None or p.ext_org_id != current_org_id(d):
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    return p
```

- [ ] **Step 4: 追加 policy 行 + resync 迁移**

`config/casbin/policy.csv` 末尾（`# —— M2-b 开放课题全流程 ——` 段）追加，列对齐公式 `"p, " + (role+",").ljust(11) + (path+",").ljust(39) + act`：

```
p, R-PARTNER, /api/v1/apply/guide-suggestions,       GET
p, R-PARTNER, /api/v1/apply/guide-suggestions,       POST
p, R-PARTNER, /api/v1/apply/guide-suggestions/*,     GET
p, R-PARTNER, /api/v1/apply/applications,            GET
p, R-PARTNER, /api/v1/apply/applications,            POST
p, R-PARTNER, /api/v1/apply/applications/*,          GET
p, R-PARTNER, /api/v1/apply/applications/*,          PUT
p, R-PARTNER, /api/v1/apply/applications/*/submit,   POST
p, R-PARTNER, /api/v1/apply/applications/*/sections/*, POST
p, R-PARTNER, /api/v1/apply/applications/*/budget,   GET
p, R-PARTNER, /api/v1/apply/applications/*/budget,   POST
p, R-PARTNER, /api/v1/apply/applications/*/documents, GET
p, R-PARTNER, /api/v1/apply/task-books/*,            GET
p, R-PARTNER, /api/v1/apply/task-books/*:sign,       POST
p, R-PARTNER, /api/v1/project/*/progress-report,     GET
p, R-PARTNER, /api/v1/project/*/progress-report,     POST
p, R-PARTNER, /api/v1/project/*/final-accept,        GET
p, R-PARTNER, /api/v1/project/*/final-accept,        POST
p, R-MANAGER, /api/v1/apply/guide-suggestions,       GET
p, R-MANAGER, /api/v1/apply/guide-suggestions/*,     GET
p, R-MANAGER, /api/v1/apply/guide-suggestions/*:accept, POST
p, R-MANAGER, /api/v1/apply/guide-suggestions/*:reject, POST
p, R-MANAGER, /api/v1/apply/task-books,              POST
p, R-MANAGER, /api/v1/apply/task-books/*,            GET
```

新建 `apps/sysadmin/migrations/0012_resync_permissions.py`（复制 `0011_m2a_uk_ptn_credit.py` 无关部分：`RunPython(lambda apps, se: sync_permissions_from_csv(settings.CASBIN_POLICY_PATH))`，`dependencies = [("sysadmin", "0011_m2a_uk_ptn_credit")]`）。

- [ ] **Step 5: 追加 RBAC 测试**

`tests/test_rbac.py` 末尾：

```python
def test_m2b_partner_business_rows_exist():
    rows = _policy_p_rows()
    expected = {
        ("R-PARTNER", "/api/v1/apply/guide-suggestions", "POST"),
        ("R-PARTNER", "/api/v1/apply/applications", "POST"),
        ("R-PARTNER", "/api/v1/apply/task-books/*:sign", "POST"),
        ("R-PARTNER", "/api/v1/project/*/final-accept", "POST"),
        ("R-MANAGER", "/api/v1/apply/guide-suggestions/*:accept", "POST"),
    }
    assert expected <= rows


def test_m2b_partner_denied_admin_and_secret_domains():
    from casbin.util import key_match2
    rows = _policy_p_rows()
    partner = [(p, a) for (r, p, a) in rows if r == "R-PARTNER"]
    for path in ("/api/v1/x/projects", "/api/v1/users", "/api/v1/partner-orgs",
                 "/api/v1/project/1/board"):
        for (p, a) in partner:
            assert not key_match2(path, p), f"{path} 不应被 {p} 匹配"
```

- [ ] **Step 6: 跑测试**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_p_m2b.py tests/test_rbac.py -q`
Expected: 全 PASS。另确认 `grep -rn "org_id" core/org_scope.py` 只有一处表查询（避免每请求多次查库）。

- [ ] **Step 7: Commit**

```bash
git add backend-django/core/org_scope.py backend-django/apps/p/api.py backend-django/apps/project/api.py backend-django/config/casbin/policy.csv backend-django/apps/sysadmin/migrations/0012_resync_permissions.py backend-django/tests/test_p_m2b.py backend-django/tests/test_rbac.py
git commit -m "feat(rbac): M2-b 外部机构业务策略域 + 申报/项目机构租户隔离收口（C2）"
```

---

### Task 3: 指南建议（外部提交 → 管理端采纳成指南草稿）

**Files:**
- Create: `backend-django/apps/p/mappings.py` 追加 `to_api_guide_suggestion`（同文件，不新建）
- Modify: `backend-django/apps/p/api.py`（新增四个 handler）
- Modify: `backend-django/config/api.py`（注册四条路由，静态段在 `/apply/guidelines/{id}` **之后**、`/apply/applications` 之前无冲突）
- Modify: `design/01-项目申报与立项-P.openapi.yaml` + 副本
- Test: `backend-django/tests/test_p_m2b.py`

**Interfaces:**
- Consumes: `PGuideSuggestion`（Task 1）、`_partner_app_or_404`/策略行（Task 2）、`code_of`（`apps/funding/mappings.py:56`）
- Produces:
  - `to_api_guide_suggestion(s: PGuideSuggestion) -> dict`（snake_case 22 键，时间走 `fmt_ts`）
  - `list_guide_suggestions(request) -> {list,total,page,size}`：R-PARTNER 只见本机构；内部角色按 `status/orgId` 过滤
  - `create_guide_suggestion(request) -> dict`：必填 `title`；外部用户 `org_id` 强制取 `d.org_id`、忽略 body
  - `get_guide_suggestion(request, id: int) -> dict`
  - `accept_guide_suggestion(request, id: int) -> dict`：PENDING → ACCEPTED + 建 `PGuideline`（`status="DRAFT"`、`title` 同名、`project_type` 缺省 `"开放课题"`）并回填 `guideline_id`；非 PENDING → 40901
  - `reject_guide_suggestion(request, id: int) -> dict`：必填 `reason`（→ `reject_reason`）；非 PENDING → 40901

- [ ] **Step 1: 写失败测试**

```python
def test_guide_suggestion_flow(seed_auth):
    # 外部机构 A 提交
    r = _post("/api/v1/apply/guide-suggestions",
              {"title": "智能育种方向建议", "background": "面向 2030",
               "org_id": 999},  # 传别家机构应被忽略
              roles=("R-PARTNER",), uid=partner_a_uid)
    assert r.status_code == 200, r.content
    sid = _data(r)["id"]
    assert _data(r)["org_id"] == 11
    # 机构 B 看不到、也读不到
    assert _data(_get("/api/v1/apply/guide-suggestions",
                      roles=("R-PARTNER",), uid=partner_b_uid))["total"] == 0
    assert _get(f"/api/v1/apply/guide-suggestions/{sid}",
                roles=("R-PARTNER",), uid=partner_b_uid).status_code == 404
    # 管理端采纳 → 生成 DRAFT 指南
    acc = _post(f"/api/v1/apply/guide-suggestions/{sid}:accept", {},
                roles=("R-MANAGER",))
    assert _data(acc)["status"] == "ACCEPTED"
    gid = _data(acc)["guideline_id"]
    assert PGuideline.objects.get(id=gid).status == "DRAFT"
    # 再采纳一次 40901
    assert _post(f"/api/v1/apply/guide-suggestions/{sid}:accept", {},
                 roles=("R-MANAGER",)).status_code == 409


def test_guide_suggestion_reject_requires_reason(seed_auth):
    sid = _data(_post("/api/v1/apply/guide-suggestions", {"title": "建议X"},
                      roles=("R-PARTNER",), uid=partner_a_uid))["id"]
    bad = _post(f"/api/v1/apply/guide-suggestions/{sid}:reject", {}, roles=("R-MANAGER",))
    assert bad.status_code == 400 and json.loads(bad.content)["code"] == 40001
    okr = _post(f"/api/v1/apply/guide-suggestions/{sid}:reject", {"reason": "方向不符"},
                roles=("R-MANAGER",))
    assert _data(okr)["status"] == "REJECTED" and _data(okr)["reject_reason"] == "方向不符"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_p_m2b.py -q -k suggestion`
Expected: FAIL（404 Not Found / 路由未注册）

- [ ] **Step 3: 实现映射与四个 handler**

`apps/p/api.py` 末尾（指南区）：

```python
def list_guide_suggestions(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PGuideSuggestion.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if is_external_only(d):
        qs = qs.filter(org_id=current_org_id(d))
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    total = qs.count()
    return ok(request, {"list": [to_api_guide_suggestion(s) for s in qs.order_by("-id")[offset:offset+limit]],
                        "total": total, "page": page, "size": size})
```

`is_external_only` / `current_org_id` 均从 `core.org_scope` 导入（Task 2），本任务不重复实现判定。
`create_guide_suggestion`：`title` 空 → 40001；`org_id = current_org_id(d) if is_external_only(d) else body.get("org_id")`；`proposer_user_id=d.user_id`；创建后 `code_of("SUG", id)` 回填；通知 `_notify_role(tenant_id,"R-MANAGER","TODO","新的指南建议", title, f"guide-suggestion:{id}")`。
`accept_guide_suggestion`：`select_for_update()` 取行 → 非 PENDING 40901 → `PGuideline.objects.create(tenant_id=d.tenant_id, title=s.title, project_type="开放课题", status="DRAFT", creator_id=d.user_id)`（`PGuideline` 列见 `apps/p/models.py:9-33`，`publish_at` 保持 null 直到 `:publish`）→ `s.guideline_id=g.id`、`s.status="ACCEPTED"`、`review_user_id/reviewed_at` → 通知建议人。
`reject_guide_suggestion`：`_require_reason(body)`（既有函数，`apps/p/api.py:300`）→ `status="REJECTED"`。

- [ ] **Step 4: 注册路由**

```python
api.get("/apply/guide-suggestions", auth=ark_auth, tags=["p"])(p_api.list_guide_suggestions)
api.post("/apply/guide-suggestions", auth=ark_auth, tags=["p"])(p_api.create_guide_suggestion)
api.post("/apply/guide-suggestions/{id}:accept", auth=ark_auth, tags=["p"])(p_api.accept_guide_suggestion)
api.post("/apply/guide-suggestions/{id}:reject", auth=ark_auth, tags=["p"])(p_api.reject_guide_suggestion)
api.get("/apply/guide-suggestions/{id}", auth=ark_auth, tags=["p"])(p_api.get_guide_suggestion)
```

（`:accept`/`:reject` 必须在 `/{id}` 之前注册。）

- [ ] **Step 5: 补契约**

`design/01-项目申报与立项-P.openapi.yaml`：在 `/apply/guidelines/{id}` 之前插入 5 条路径 + `GuideSuggestion` / `GuideSuggestionRequest` / `GuideSuggestionRejectRequest` 三个 schema（snake_case 键，与 `to_api_guide_suggestion` 逐键一致；`status` enum 三态；409 声明在 accept/reject）→ `cp` 到 `frontend/src/api/schema/` → `cmp` 一致 → `yaml.safe_load` 通过。

- [ ] **Step 6: 跑测试**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_p_m2b.py -q` 
Expected: 全 PASS；再跑全量 `pytest -q` 全绿

- [ ] **Step 7: Commit**

```bash
git add backend-django/apps/p/api.py backend-django/config/api.py backend-django/tests/test_p_m2b.py design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml
git commit -m "feat(p): 指南建议——外部机构提交/机构隔离/管理端采纳生成指南草稿（C2）"
```

---

### Task 4: 申报机构化（外部机构发起申报 + 机构内可见）

**Files:**
- Modify: `backend-django/apps/p/api.py`（`create_application`、`list_applications`、`get_application`）
- Modify: `backend-django/apps/p/mappings.py`（`to_api_application` 加两键）
- Modify: `design/01-项目申报与立项-P.openapi.yaml`（`Application` + `ApplicationCreateRequest`）+ 副本
- Test: `backend-django/tests/test_p_m2b.py`

**Interfaces:**
- Consumes: `is_external_only`/`current_org_id`（`core/org_scope.py`，Task 2）、`_partner_app_or_404`（Task 2）、`PApplication.applicant_org_id/applicant_type`（Task 1）
- Produces:
  - `create_application`：外部用户强制 `pi_user_id=d.user_id`、`applicant_org_id=d.org_id`、`applicant_type="EXTERNAL"`（body 里的 `pi_user_id`/`org` 一律忽略，不报错）；院内用户保持现状 + `applicant_type="INTERNAL"`
  - `list_applications`：外部用户只列 `applicant_org_id == d.org_id`
  - `get_application`：外部用户走 `_partner_app_or_404`
  - `to_api_application` 增 `"applicant_org_id"`、`"applicant_type"`

- [ ] **Step 1: 写失败测试**

```python
def test_partner_application_is_org_bound(seed_auth):
    r = _post("/api/v1/apply/applications",
              {"title": "开放课题甲", "project_type": "开放课题",
               "pi_user_id": 999, "applicant_org_id": 999},
              roles=("R-PARTNER",), uid=partner_a_uid)
    assert r.status_code == 200, r.content
    d = _data(r)
    assert d["pi_user_id"] == partner_a_uid and d["applicant_org_id"] == 11
    assert d["applicant_type"] == "EXTERNAL"
    aid = d["id"]
    assert _data(_get("/api/v1/apply/applications", roles=("R-PARTNER",), uid=partner_b_uid))["total"] == 0
    assert _get(f"/api/v1/apply/applications/{aid}",
                roles=("R-PARTNER",), uid=partner_b_uid).status_code == 404


def test_internal_application_stays_internal(seed_auth):
    d = _data(_post("/api/v1/apply/applications",
                    {"title": "院内课题", "project_type": "ZIGE", "pi_user_id": 2},
                    roles=("R-STAFF",), uid=2))
    assert d["applicant_type"] == "INTERNAL" and d["applicant_org_id"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_p_m2b.py -q -k application`
Expected: FAIL（`pi_user_id` 被 body 覆盖 / 机构 B 能看到机构 A 的申报）

- [ ] **Step 3: 实现**

`create_application` 顶部：

```python
    external = is_external_only(d)
    if external:
        pi_user_id = d.user_id
    else:
        pi_user_id = body.get("pi_user_id")
```

创建时：`applicant_org_id=(current_org_id(d) if external else body.get("applicant_org_id"))`、`applicant_type=("EXTERNAL" if external else "INTERNAL")`。
`list_applications`：`if is_external_only(d): qs = qs.filter(applicant_org_id=current_org_id(d))`。
`get_application`：`a = _partner_app_or_404(d, id) if is_external_only(d) else _get_app_or_404(d.tenant_id, id)`。
`mappings.to_api_application` 追加两个键（`applicant_org_id`、`applicant_type`）。

- [ ] **Step 4: 补契约**（`Application` 增 `applicant_org_id`/`applicant_type`；`ApplicationCreateRequest` 增可选 `applicant_org_id`，注释「外部用户忽略，取本机构」）+ 副本 `cp`/`cmp`/`safe_load`

- [ ] **Step 5: 跑测试与全量**

Run: `cd backend-django && .venv/bin/python -m pytest -q` 
Expected: 全绿（较基线 +4 左右，具体以实测为准，写进报告）

- [ ] **Step 6: Commit**

```bash
git add backend-django/apps/p/api.py backend-django/apps/p/mappings.py backend-django/tests/test_p_m2b.py design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml
git commit -m "feat(p): 申报主体扩为外部机构——PI/机构强制归本机构、机构内可见（C2）"
```

---

### Task 5: 任务书生成 / 详情 / 电子签章签订 → 立项建项

**Files:**
- Create: `backend-django/apps/p/mappings.py` 追加 `to_api_task_book`
- Modify: `backend-django/apps/p/api.py`（三个 handler + `_task_book_snapshot`）
- Modify: `backend-django/config/api.py`（三条路由）
- Modify: `design/01-项目申报与立项-P.openapi.yaml`（`TaskBook` 增 `project_id`/`ext_org_id` 说明与 `:sign` 的 400 声明）+ 副本
- Test: `backend-django/tests/test_p_m2b.py`

**Interfaces:**
- Consumes: `PTaskBook`（Task 1）、`PApplication.applicant_org_id`（Task 1/4）、`EProject.ext_org_id`（Task 1）、`code_of`、`_notify`/`_notify_role`
- Produces:
  - `generate_task_book(request) -> dict`：body `{application_id, print_template_code?}`；仅 `PApplication.status in ("PUBLISHED","DECIDED")` 可生成（否则 40901）；幂等：同 `application_id` 已存在则原样返回（`duplicated=true` 不返回，直接返回 task book）；`content_snapshot` 冻结：`{title, project_type, pi_user_id, applicant_org_id, total_budget(num2 str), duration_months, abstract, research_target, technical_route, expected_output, guideline_id, frozen_at}`；`code_of("PRJ", id)` 回填；状态 `DRAFT`
  - `get_task_book(request, id: int) -> dict`：外部用户只能读本机构申报对应的任务书（否则 404）
  - `sign_task_book(request, id: int) -> dict`：body `{role, signer_id?, sig_result?}`；`role="PI"` 时 `signer_id` 强制为 `application.pi_user_id`，`role` ∈ `PI|MANAGER|LEADER`，其它 40001；同 role 重复签 → 40901；累计出现 `PI` 与（`MANAGER` 或 `LEADER`）→ 置 `SIGNED` + `effective_date=localdate()`，并在**同一 atomic** 内建 `EProject`（`status="EXECUTING"`, `application_id=application.id`, `title`, `project_type`, `pi_user_id`, `total_budget`, `legal_entity_id=1`, `ext_org_id=application.applicant_org_id`）→ `task_book.project_id` 回填、`PApplication.status="EXECUTING"`；SIGNED 后再签 → 40901

- [ ] **Step 1: 写失败测试**

```python
def test_task_book_sign_creates_project_once(seed_auth):
    aid = _approved_application(pi_uid=partner_a_uid)       # 辅助：建 PUBLISHED 申报
    tb = _data(_post("/api/v1/apply/task-books", {"application_id": aid},
                     roles=("R-MANAGER",)))
    assert tb["status"] == "DRAFT" and tb["content_snapshot"]["pi_user_id"] == partner_a_uid
    assert _data(_post("/api/v1/apply/task-books", {"application_id": aid},
                       roles=("R-MANAGER",)))["id"] == tb["id"]      # 幂等
    # PI 签
    s1 = _data(_post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "PI"},
                     roles=("R-PARTNER",), uid=partner_a_uid))
    assert s1["status"] == "DRAFT" and len(s1["sign_records"]) == 1
    # 管理端签 → SIGNED + 建项
    s2 = _data(_post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "MANAGER"},
                     roles=("R-MANAGER",)))
    assert s2["status"] == "SIGNED" and s2["project_id"]
    proj = EProject.objects.get(id=s2["project_id"])
    assert proj.ext_org_id == 11 and proj.pi_user_id == partner_a_uid
    # 再签 40901，且只有 1 个项目
    assert _post(f"/api/v1/apply/task-books/{tb['id']}:sign", {"role": "MANAGER"},
                 roles=("R-MANAGER",)).status_code == 409
    assert EProject.objects.filter(application_id=aid).count() == 1


def test_application_is_frozen_after_task_book_signed(seed_auth):
    """Review Focus 4：签订后申报书内容冻结（分节保存/预算行/再提交一律 40901）。"""
    tb = _signed_task_book(pi_uid=partner_a_uid)          # 辅助：已双签，返回 task book dict
    aid = _app_id_of(tb)
    sec = _put(f"/api/v1/apply/applications/{aid}/sections/GOAL",
               {"content_rich": "签后偷偷改"}, roles=("R-PARTNER",), uid=partner_a_uid)
    assert sec.status_code == 409 and json.loads(sec.content)["code"] == 40901
    bud = _post(f"/api/v1/apply/applications/{aid}/budget",
                {"subject_code": "7201", "amount": "1000.00"},
                roles=("R-PARTNER",), uid=partner_a_uid)
    assert bud.status_code == 409
    sub = _post(f"/api/v1/apply/applications/{aid}/submit", {}, roles=("R-PARTNER",), uid=partner_a_uid)
    assert sub.status_code == 409


def test_task_book_requires_published_and_partner_cannot_see_others(seed_auth):
    draft_aid = _draft_application(pi_uid=partner_a_uid)
    assert _post("/api/v1/apply/task-books", {"application_id": draft_aid},
                 roles=("R-MANAGER",)).status_code == 409
    tb = _task_book_for(pi_uid=partner_a_uid)
    assert _get(f"/api/v1/apply/task-books/{tb['id']}",
                roles=("R-PARTNER",), uid=partner_b_uid).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_p_m2b.py -q -k task_book` 
Expected: FAIL（路由未注册 / 404）

- [ ] **Step 3: 实现三个 handler**

`_task_book_snapshot(a: PApplication) -> dict` 返回 Step 1 所列键（金额 `num2(a.total_budget)`）。
`generate_task_book`：`select_for_update` 取 application；状态校验；`PTaskBook.objects.filter(application_id=aid, deleted=0).first()` 命中直接返回。
`sign_task_book`：`transaction.atomic()` + `PTaskBook.objects.select_for_update().filter(id=id, tenant_id=d.tenant_id, deleted=0).first()`；外部用户校验归属（`_task_book_visible(d, tb)`）；`records = list(tb.sign_records or [])`；role 重复 → 40901；append `{"role": role, "signerId": pid, "signedAt": dj_tz.now().isoformat(), "result": body.get("sig_result") or "OK"}`；两侧齐 → 建 `EProject`（字段见 Interfaces）→ 回填；`_notify(application.pi_user_id, "TODO", "任务书已签订", ...)`。
`get_task_book`：`_task_book_visible` 判定（外部：`application.applicant_org_id == current_org_id(d)`；内部：同租户即可）。
**冻结守卫（Review Focus 4）**：在 `save_application_section`、`upsert_budget_line`、`submit_application` 三处入口加同一段判定 —— 该申报已有 `PTaskBook` 且其 `status in ("SIGNED","EXECUTING")` 时抛 `ApiError(409, CODE_CONFLICT, "任务书已签订，申报内容不可修改")`。实现为一个共用函数 `_assert_application_mutable(a: PApplication) -> None`。

- [ ] **Step 4: 注册路由（静态先于动态）**

```python
api.post("/apply/task-books", auth=ark_auth, tags=["p"])(p_api.generate_task_book)
api.post("/apply/task-books/{id}:sign", auth=ark_auth, tags=["p"])(p_api.sign_task_book)
api.get("/apply/task-books/{id}", auth=ark_auth, tags=["p"])(p_api.get_task_book)
```

- [ ] **Step 5: 补契约**（`TaskBook` 的 `project_id` 描述改为「签订后回填 E_PROJECT(id)，外部课题带 ext_org_id」；`:sign` 增 `400` 声明；`SignRequest` 的 `role` 加 enum `[PI, MANAGER, LEADER]`）+ 副本 `cp`/`cmp`/`safe_load`

- [ ] **Step 6: 跑测试与全量** + **Step 7: Commit**

```bash
git add backend-django/apps/p/api.py backend-django/config/api.py backend-django/tests/test_p_m2b.py design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml
git commit -m "feat(p): 任务书生成/电子签章签订——双签即立项建项并回填项目（C2 立项签约）"
```

---

### Task 6: 阶段汇报（外部 PI 提交，机构隔离 + 通知管理端）

**Files:**
- Modify: `backend-django/apps/project/api.py`（`create_progress_report` 走机构校验 + 通知；新增 `list_progress_reports` 若不存在）
- Modify: `design/02-项目过程管理-E.openapi.yaml`（`/project/{id}/progress-report` 增 GET 与 403 说明）+ 副本
- Test: `backend-django/tests/test_p_m2b.py` 或 `tests/test_project_domain.py`（择一，建议前者集中 M2-b 用例）

**Interfaces:**
- Consumes: `_partner_project_or_404`（Task 2）、`EProgressReport`（既有）
- Produces:
  - `create_progress_report`：外部用户先 `_partner_project_or_404(d, id)`；创建后 `_notify_role(d.tenant_id, "R-MANAGER", "TODO", "阶段汇报已提交", f"{p.title} · {period}", f"progress-report:{r.id}")`
  - `list_progress_reports(request, id: int) -> {list,total,page,size}`：机构隔离同 `_partner_project_or_404`

- [ ] **Step 1: 写失败测试**

```python
def test_partner_submits_progress_report_within_own_org(seed_auth):
    proj = _ext_project(org_id=11, pi_uid=partner_a_uid)
    r = _post(f"/api/v1/project/{proj.id}/progress-report",
              {"period": "2026Q1", "report_type": "QUARTERLY", "progress_percent": 40},
              roles=("R-PARTNER",), uid=partner_a_uid)
    assert r.status_code == 200, r.content
    assert _data(r)["period"] == "2026Q1"
    assert SysNotification.objects.filter(typ="TODO").exists()
    lst = _data(_get(f"/api/v1/project/{proj.id}/progress-report",
                     roles=("R-PARTNER",), uid=partner_a_uid))
    assert lst["total"] == 1
    # 机构 B 不可见
    assert _get(f"/api/v1/project/{proj.id}/progress-report",
                roles=("R-PARTNER",), uid=partner_b_uid).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败** → `FAIL（404 / 405）`
- [ ] **Step 3: 实现**（`create_progress_report` 首行改为机构分支；新增 `list_progress_reports`）
- [ ] **Step 4: 路由**：`api.get("/project/{id}/progress-report", ...)`（静态无冲突，与既有 POST 同路径不同方法）
- [ ] **Step 5: 契约 + 副本 cmp**
- [ ] **Step 6: 全量测试** + **Step 7: Commit** `feat(project): 阶段汇报外部化——机构内提交与查看、管理端通知（C2）`

---

### Task 7: 验收结题外部化（外部 PI 申请验收 + 结题通知与邮件）

**Files:**
- Modify: `backend-django/apps/project/api.py`（`create_final_accept`、`conclude_final_accept` 通知；`get_final_accept` 机构隔离，若无则新增）
- Modify: `design/02-项目过程管理-E.openapi.yaml`（`/project/{id}/final-accept` 增 GET + 403）+ 副本
- Test: `backend-django/tests/test_p_m2b.py`

**Interfaces:**
- Consumes: `_partner_project_or_404`（Task 2）、`_notify`/`_notify_role`、`send_mail_best_effort`（`apps/notify/email.py`）
- Produces:
  - `create_final_accept`：外部用户先 `_partner_project_or_404`；创建后通知 R-MANAGER（站内信）
  - `get_final_accept(request, id: int)`：外部用户只读本项目本机构；内部同租户
  - `conclude_final_accept(final_accept_id, status)`：`APPROVED` 时除既有批文外，追加 `_notify(PI)` + 机构邮箱邮件（`contact_email`）——**邮件放在 handler 层**（`single-writer` 函数不感知 HTTP，且需读 org）

- [ ] **Step 1: 写失败测试**

```python
def test_partner_applies_final_accept_and_gets_notified(seed_auth):
    proj = _ext_project(org_id=11, pi_uid=partner_a_uid)
    r = _post(f"/api/v1/project/{proj.id}/final-accept",
              {"outputSummary": "完成 3 篇论文"}, roles=("R-PARTNER",), uid=partner_a_uid)
    assert r.status_code == 200, r.content
    fa = _data(r)
    assert _data(_get(f"/api/v1/project/{proj.id}/final-accept",
                      roles=("R-PARTNER",), uid=partner_a_uid))["id"] == fa["id"]
    assert _get(f"/api/v1/project/{proj.id}/final-accept",
                roles=("R-PARTNER",), uid=partner_b_uid).status_code == 404
    # 管理端结题通过 → PI 收站内信、机构邮箱收到邮件
    _conclude(fa["id"], "APPROVED")
    assert SysNotification.objects.filter(user_id=partner_a_uid).exists()
    assert mail.outbox and "验收" in mail.outbox[0].subject
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现**（机构分支 + 通知/邮件；`conclude_final_accept` 内保持单一写者，邮件在调用它的 handler `conclude_final_accept_route` 中发）
- [ ] **Step 4: 路由**（GET 与 POST 同路径，无冲突）
- [ ] **Step 5: 契约 + 副本 cmp**
- [ ] **Step 6: 全量测试** + **Step 7: Commit** `feat(project): 验收结题外部化——机构内申请与查看、结题通知与邮件（C2）`

---

### Task 8: 前端（门户三块 + 管理端指南建议审核）

**Files:**
- Create: `frontend/src/views/portal/ApplicationsView.vue`（我的申报：列表 + 新建 + 提交 + 任务书签订入口）
- Create: `frontend/src/views/portal/GuideSuggestView.vue`（指南建议：提交 + 我的建议列表）
- Create: `frontend/src/views/portal/TaskBookView.vue`（任务书详情 + PI 签署）
- Create: `frontend/src/views/portal/ProjectReportView.vue`（阶段汇报 + 验收申请）
- Create: `frontend/src/views/admin/GuideSuggestionsView.vue`（管理端：建议列表 + 采纳/驳回）
- Modify: `frontend/src/router/index.ts`（4 条参考页路由 + 1 条管理路由）
- Modify: `frontend/src/App.vue`（nav：机构门户组三项；系统组一项）
- Modify: `frontend/src/api/mock/overrides/portal.ts`（新增 9 个端点 mock）
- Modify: `frontend/src/api/mock/overrides/auth.ts`（`PAGE_GRANTS` 加 5 行；`ROLE_CAPS` 的 R-PARTNER 段加业务 caps）
- Test: 手工 + `vue-tsc`

**Interfaces:**
- Consumes: Task 2 的策略行、Task 3/4/5/6/7 的端点与响应键（**全部 snake_case**）
- Produces: 路由名 `portal-applications` / `portal-guide-suggest` / `portal-task-book` / `portal-project-report` / `admin-guide-suggestions`

- [ ] **Step 1: 视图骨架 + 数据加载**

每个视图用 `api.get` / `api.post` 直连（参照 `frontend/src/views/PortalView.vue` 的写法：`const data = ref<any[]>([])`、`onMounted(load)`、`err` ref 承接 `ApiError.message`）。申报列表列：编号/标题/状态/机构/预算/更新时间 + 操作（提交、查看任务书）；建议列表列：标题/状态/驳回理由/时间；任务书详情：编号/状态/快照键值表/签署记录表/「以 PI 身份签署」按钮（仅 `status=DRAFT` 且当前用户是 PI）；汇报页：项目选择（`/portal/home` 的课题列表或手填 projectId）+ 汇报表 + 验收申请按钮。

- [ ] **Step 2: 路由与 nav**

```ts
{ path: '/portal/applications', name: 'portal-applications',
  meta: { zh: '我的申报', en: 'My Applications', roles: ['R-PARTNER'] },
  component: () => import('../views/portal/ApplicationsView.vue') },
```

其余 4 条同形（管理端 `roles: ['R-MANAGER','R-ADMIN']`）。`App.vue` 的「机构门户」组加三条 `{ v: 'portal-applications', ic: '▤', label: '我的申报', roles: ['R-PARTNER'] }` 等；「系统」组加 `{ v: 'admin-guide-suggestions', ic: '✎', label: '指南建议审核', roles: ['R-MANAGER','R-ADMIN'] }`。

- [ ] **Step 3: mock overrides**

`portal.ts` 追加键（**当前 mock 层按 `overrides` 只做 demo，列表返回内存数组即可**）：
`'GET /apply/guide-suggestions'`、`'POST /apply/guide-suggestions'`、`'POST /apply/guide-suggestions/{id}:accept'`、`':reject'`、`'GET /apply/applications'`、`'POST /apply/applications'`、`'POST /apply/applications/{id}/submit'`、`'POST /apply/task-books'`、`'GET /apply/task-books/{id}'`、`'POST /apply/task-books/{id}:sign'`、`'GET /project/{id}/progress-report'`、`'POST /project/{id}/progress-report'`、`'POST /project/{id}/final-accept'`。`auth.ts`：`PAGE_GRANTS` 加 `['portal-applications','R-PARTNER']`、`['portal-guide-suggest','R-PARTNER']`、`['portal-task-book','R-PARTNER']`、`['portal-project-report','R-PARTNER']`、`['admin-guide-suggestions','R-MANAGER']`、`['admin-guide-suggestions','R-ADMIN']`；`ROLE_CAPS` 的 `R-PARTNER` 段补 `W('/apply/guide-suggestions POST', ...)` 形式（照该文件既有 `W()` 助手写法）。

- [ ] **Step 4: 校验**

```bash
cd frontend && ./node_modules/.bin/vue-tsc --noEmit   # 期望 0 errors
cd backend-django && .venv/bin/python -m pytest -q     # 期望与 Task 7 相同数字（前端不改后端）
```

- [ ] **Step 5: Commit** `feat(fe): 门户申报/指南建议/任务书签订/汇报验收 + 管理端建议审核——契约驱动 mock 对齐 M2-b`

---

### Task 9: 种子数据 + README + 全量验收

**Files:**
- Modify: `backend-django/apps/sysadmin/management/commands/seed_demo.py`
- Modify: `README.md`（测试数三处）
- Test: `backend-django/tests/test_seed_demo.py`（既有幂等用例，若计数硬编码需同步）

**Interfaces:**
- Consumes: 全部 Task 1-8
- Produces: 演示链路可直接点：机构 A（已有 `PTN-2026-000001`）→ 一条 PENDING 指南建议 → 一条 EXTERNAL 申报（PUBLISHED）→ 任务书（DRAFT，只有 PI 已签）→ 一个 `E_PROJECT(ext_org_id=机构A)` 带 1 条阶段汇报

- [ ] **Step 1: 写种子（放在既有 M2-a 段之后，`_seed_domains` 内、`return cnt` 之前）**

```python
    # —— M2-b 开放课题全流程演示 ——
    ptn_a = SysPartnerOrg.objects.filter(code="PTN-2026-000001").first()
    partner = SysUser.objects.filter(username="partner").first()
    sug, sug_created = PGuideSuggestion.objects.get_or_create(
        tenant_id=1, title="开放课题：智能育种方向建议",
        defaults={"org_id": ptn_a.id if ptn_a else None,
                  "proposer_user_id": partner.id if partner else 2,
                  "background": "面向 2030 的育种智能化",
                  "status": "PENDING", "creator_id": 1},
    )
    if sug_created and not sug.code:
        sug.code = f"SUG-{sug.id:06d}"; sug.save(update_fields=["code"])
```

（申报/任务书/项目/汇报用 `get_or_create` 以 `(tenant_id, title)` 或 `code` 为键；任务书 `content_snapshot` 用与 `_task_book_snapshot` 同形的键。）

- [ ] **Step 2: 幂等验证（单进程文件库两遍）**

```bash
cd backend-django
rm -f /tmp/m2b_seed.sqlite3
for i in 1 2; do ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_seed.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate --no-input >/dev/null; ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_seed.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo; done
```
Expected: 第一遍有新增计数，第二遍 **全零**。

- [ ] **Step 3: 全量验收**

```bash
cd backend-django && .venv/bin/python -m pytest -q                    # 全绿
.venv/bin/python manage.py makemigrations --check                     # No changes
cd ../frontend && ./node_modules/.bin/vue-tsc --noEmit                # 0 errors
cd .. && cmp design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml && cmp design/02-项目过程管理-E.openapi.yaml frontend/src/api/schema/02-项目过程管理-E.openapi.yaml
```

- [ ] **Step 4: e2e 冒烟（单进程文件库，一脚本跑完）**

外部机构：登录 `partner/Partner@123456` → 提交指南建议 → 新建申报 → 提交 → （切 manager）采纳建议、审核通过申报（P 域状态推到 PUBLISHED，可按需直接 DB 置位以便演示）→ 生成任务书 → PI 签 → manager 签 → 断言生成 `E_PROJECT` 且 `ext_org_id=机构A` → 提交阶段汇报 → 提交验收申请 → 读结论；全程断言跨机构读取 404。

- [ ] **Step 5: README 计数**

```bash
python3 - <<'PY'
import io, pathlib
p = pathlib.Path("README.md"); s = p.read_text(encoding="utf-8")
s = s.replace("381 passed", "N passed")   # 用实测数字
p.write_text(s, encoding="utf-8")
PY
grep -n "passed" README.md
```

- [ ] **Step 6: Commit** `chore(seed+readme): M2-b 开放课题全流程演示数据 + 测试数更新为实测 N`

---

## 自审记录（写完即查）

- **Spec 覆盖**：C2 六个环节各有任务——指南建议 Task 3；在线申报（主体扩机构）Task 4；立项签约 Task 5；任务书 Task 5（含 Task 1 建表）；阶段汇报 Task 6；中期检查（既有 `EMidCheck` + M1-d `EEvalTemplate`，本计划不新增端点，由 Task 7 的验收通知串起）；验收结题 Task 7。验收口径「外部身份独立角色域」= Task 2；「tenant 隔离覆盖」= Task 2 + 各任务 404 断言；「涉密域全拒」= Task 2 Step 5 的 `key_match2` 反向断言。
- **类型一致性**：`_get_app_or_404(tenant_id, app_id)` 在 Task 2 改签名，Task 3/4/5 一律按新签名调用；`_partner_project_or_404` 在 Task 2 定义，Task 6/7 使用；`to_api_*` 全部 snake_case。
- **Review Focus 落地**：1 → Task 2 Step 1/5；2 → Task 5 Step 1（重复签 409 + 计数 1）；3 → Task 4 Step 1/3；4 → Task 5 的 SIGNED 后不可变（在 Step 3 实现里对 `status in ("SIGNED","EXECUTING")` 的申报拒绝再改，测试加在 Task 5）；5 → Task 2 Step 5 反向断言 + Task 6/7 的跨机构 404。
- **比例**：本计划约 40 步 / 9 任务，与 M2-a 同量级；代码块只保留签名、路由与测试断言，未转写实现体。
