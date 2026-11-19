# M2-a 外部机构注册与门户 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一家外部协作机构自助注册→管理员资质审核→拿到 R-PARTNER 机构账号登录→在门户首页看到本机构信息、公告与已发布指南推送，落地 roadmap M2-a（C1 机构注册与门户 + C5 邮件通道最小实现）。

**Architecture:** 外部机构建独立实体表 `sys_partner_org`（sysadmin 域，与 SysUser/SysRole 同域），`SysUser` 增 `org_id`/`user_source` 两列；**隔离维度是机构（org_id），tenant 仍是主办方**——外部机构用户与内部用户同租户，靠新角色 `R-PARTNER` 的 Casbin 收窄 + 门户端点内 org_id 过滤实现数据隔离，避免动全库 200+ 处 `tenant_id=d.tenant_id`。注册写入 `PENDING` 机构 + `LOCKED` 用户（既有登录逻辑对非 ACTIVE 一律 403，天然拦未审核账号），审核通过后置 `APPROVED`/`ACTIVE` 并授予 R-PARTNER，站内信与邮件双通道通知。

**Tech Stack:** Django 5 + django-ninja + SQLite/PG15；casbin（keyMatch2）；Django `django.core.mail`（locmem 测试后端）；Vue 3.4 + TS + Vite。

**Spec:** `docs/reports/2026-11-12-conow-alignment-roadmap.md`（M2 段 C1/C5 验收行）+ 本次决策记录（见本文件 Global Constraints 末条：按机构隔离、共用 tenant）。

## Global Constraints

- 所有查询带 `tenant_id` 且 `deleted=0`；门户端点额外带 `org_id`（机构隔离）。
- 金额（本期无）仍遵循 Decimal + `num2()` 字符串输出；时间用 `fmt_ts`。
- 无效输入一律 `ApiError(400, CODE_BAD_REQUEST, ...)`（40001），不静默归 0/空。
- 键名：sysadmin/U 域既有序列化器全 snake_case（`apps/sysadmin/mappings.py:24` `to_api_user`），本期新端点在 U 域内，**继续 snake_case**，与 `design/12-用户与权限-U.openapi.yaml` 同风格。
- 路由：静态段先于动态段注册（M1-c/M1-d 血泪）；`/admin/*` 前缀属 R-ADMIN 语义，机构审核走顶层 `/partner-orgs`。
- 测试基线：`pytest` **346 passed**（M1-d 收尾），每个任务结束时只增不减；`cd backend-django && .venv/bin/python -m pytest -q`。
- 前端类型检查：`cd frontend && ./node_modules/.bin/vue-tsc --noEmit`（**不要**用 `pnpm exec vue-tsc`，本机会因 `[ERR_PNPM_IGNORED_BUILDS] esbuild` 失败）。
- 契约双份：`design/12-用户与权限-U.openapi.yaml` 与 `frontend/src/api/schema/12-用户与权限-U.openapi.yaml` 改完 `cmp` 必须字节一致，且 `.venv/bin/python -c "import yaml,sys;yaml.safe_load(open(sys.argv[1]))"` 通过（系统 python3 无 yaml）。
- 涉密域（X）对外部用户默认全拒：R-PARTNER 不获任何 `/x/*`、`/confsec/*` 策略行，且 Task 2 用负面断言钉死。
- 执行方式：**native**（用户已选定同类偏好；每任务 TDD 红→绿→提交，全分支终审一次）。

## Review Focus

- 未审核账号能否绕过登录：注册后 `status=LOCKED` → 登录必须 403，审核后才 200；用户若直接改密码/角色也不行。
- 跨机构越权：机构 A 的用户读/写机构 B 的 `portal/org`、或读 B 的资质附件，必须 404（不泄露存在性）。
- 门户信息面收窄：`/portal/home` 的指南只允许 `PUBLISHED`，DRAFT/CLOSED 不得出现；公告只取本租户 ANNOUNCE。
- 注册滥用：同一统一社会信用代码重复注册、同一用户名重复注册必须 409；弱口令（<8 位或纯数字）必须 400，不得入库。
- 邮件失败不阻断业务：SMTP 抛异常时审核仍要成功落库（best-effort），只记日志。

---

### Task 1: 机构模型 + 用户归属列 + 迁移 0002 + DDL

**Files:**
- Modify: `backend-django/apps/sysadmin/models.py`（`SysUser` 加两列，文件末尾加 `SysPartnerOrg`）
- Create: `backend-django/apps/sysadmin/migrations/0002_syspartnerorg_sysuser_org.py`
- Modify: `design/00-common.sql`（`sys_user` CREATE TABLE 内加两列 + 文末「M2-a 增补」段：`sys_partner_org` 建表 + 既有库 ALTER 备注）
- Test: `backend-django/tests/test_sysadmin_partner.py`（新建）

**Interfaces:**
- Produces:
  - `SysPartnerOrg`（`db_table="sys_partner_org"`）字段：`id, code, tenant_id, name(max_length=256), short_name(128,null), credit_code(64), org_type(16, default "COLLAB"), contact_name(64), contact_phone(32), contact_email(128), address(256,null), qualification_json(JSONField default list), status(32, default "PENDING"), audit_user_id(BigInteger,null), audited_at(DateTime,null), reject_reason(512,null), remark(Text,null), deleted(0), creator_id, modifier_id(null), created_at, updated_at`；`Meta.indexes`：`(tenant_id, status)`、`(tenant_id, credit_code)`；`org_type ∈ COLLAB|SUPPLIER|UNIVERSITY|INSTITUTE`；`status ∈ PENDING|APPROVED|REJECTED|SUSPENDED`。
  - `SysUser.org_id: BigIntegerField(null=True, blank=True)`、`SysUser.user_source: CharField(max_length=16, default="INTERNAL")`（`INTERNAL|EXTERNAL`）。
  - 后续任务依赖 `SysPartnerOrg.objects.filter(tenant_id=..., deleted=0)` 与 `user.org_id`。

- [ ] **Step 1: 写失败测试**

```python
# backend-django/tests/test_sysadmin_partner.py
import pytest
from apps.sysadmin.models import SysPartnerOrg, SysUser

pytestmark = pytest.mark.django_db


def _org(**kw):
    base = dict(code="PTN-2026-000001", tenant_id=1, name="示例大学", credit_code="91310000MA1K3XY12A",
                org_type="UNIVERSITY", contact_name="张三", contact_phone="13800000000",
                contact_email="z@example.edu.cn", creator_id=1)
    base.update(kw)
    return SysPartnerOrg.objects.create(**base)


def test_partner_org_defaults():
    o = _org()
    assert o.status == "PENDING"  # 注册即待审
    assert o.qualification_json == []
    assert o.deleted == 0
    assert o.audit_user_id is None


def test_user_carries_org_and_source():
    o = _org()
    u = SysUser.objects.create(username="p1", real_name="外部用户", status="LOCKED",
                               tenant_id=1, creator_id=1, org_id=o.id, user_source="EXTERNAL")
    assert u.org_id == o.id
    assert u.user_source == "EXTERNAL"
    assert SysUser.objects.create(username="i1", real_name="内部用户",
                                  tenant_id=1, creator_id=1).user_source == "INTERNAL"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend-django && .venv/bin/python -m pytest tests/test_sysadmin_partner.py -q`
Expected: FAIL / ERROR —— `ImportError: cannot import name 'SysPartnerOrg'`

- [ ] **Step 3: 写模型与迁移**

在 `apps/sysadmin/models.py`：`SysUser` 内 `legal_entity_id` 之后插入 `org_id`、`user_source` 两列；文件末尾新增 `class SysPartnerOrg(models.Model)`（字段与 Interfaces 完全一致，`Meta.db_table="sys_partner_org"`，`Meta.indexes` 两条）。生成迁移：

```bash
cd backend-django && .venv/bin/python manage.py makemigrations sysadmin --name syspartnerorg_sysuser_org
.venv/bin/python manage.py makemigrations --check   # 期望 No changes detected
```

`design/00-common.sql`：`sys_user` 表内加

```sql
  org_id          BIGINT,                      -- M2-a：外部机构 sys_partner_org.id（内部用户为 NULL）
  user_source     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                  CHECK (user_source IN ('INTERNAL','EXTERNAL')),
```

文末追加「M2-a 增补」段：`CREATE TABLE sys_partner_org (...)`（逐列对齐模型，`status` CHECK 四态、`org_type` CHECK 四态、`CREATE INDEX idx_ptn_tenant_status`、`CREATE UNIQUE INDEX uk_ptn_credit ON sys_partner_org(tenant_id, credit_code) WHERE deleted = 0`），并注明既有库需 `ALTER TABLE sys_user ADD COLUMN ...`（doc-only，不生成数据迁移）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_sysadmin_partner.py -q` → 2 passed。
Run: `.venv/bin/python -m pytest -q` → **348 passed**（346+2）。

- [ ] **Step 5: 提交**

```bash
git add backend-django/apps/sysadmin/models.py backend-django/apps/sysadmin/migrations/0002_syspartnerorg_sysuser_org.py backend-django/tests/test_sysadmin_partner.py design/00-common.sql
git commit -m "feat(sysadmin): M2-a 外部机构模型与用户归属列、迁移 0002+DDL（C1 表结构）"
```

---

### Task 2: R-PARTNER 策略域 + 涉密默认全拒

**Files:**
- Modify: `backend-django/config/casbin/policy.csv`
- Create: `backend-django/apps/sysadmin/migrations/0008_resync_permissions.py`（数据迁移，复用 `apps/sysadmin/permissions.py:sync_permissions_from_csv`，照抄 `0007_resync_permissions.py` 结构——**只改 policy.csv 不改 DB 权限目录，运行时 casbin 不生效**）
- Modify: `backend-django/apps/sysadmin/management/commands/seed_demo.py:19-28`（`ROLES` 加 `("R-PARTNER", "外部机构用户")`）
- Modify: `backend-django/tests/conftest.py`（`seed_auth` 的角色列表加 `("R-PARTNER", "外部机构用户")`，否则审核端点测试取不到角色行）
- Test: `backend-django/tests/test_rbac.py`

**Interfaces:**
- Consumes: Task 1 的 `SysPartnerOrg`（本任务不需要，仅策略）。
- Produces: 角色码 `R-PARTNER`（sys_role 行 + casbin 子句 + DB 权限目录），后续任务的门户端点全靠它放行。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_rbac.py` 末尾；复用同文件既有 `_policy_p_rows()`（`:239`）与 `from casbin.util import key_match2` 的风格，`test_rbac.py` 里**没有** `_enforcer()` 辅助，勿引用）

```python
def test_m2a_partner_policy_rows_exist():
    rows = _policy_p_rows()
    expected = {
        ("R-PARTNER", "/api/v1/portal/org", "GET"),
        ("R-PARTNER", "/api/v1/portal/org", "PUT"),
        ("R-PARTNER", "/api/v1/portal/home", "GET"),
        ("R-PARTNER", "/api/v1/apply/guidelines", "GET"),
        ("R-PARTNER", "/api/v1/apply/guidelines/*", "GET"),
        ("R-PARTNER", "/api/v1/notifications", "GET"),
        ("R-PARTNER", "/api/v1/notifications/*", "POST"),
        ("R-PARTNER", "/api/v1/notifications/read-all", "POST"),
        ("R-PARTNER", "/api/v1/dicts/*", "GET"),
        ("R-PARTNER", "/api/v1/auth/me", "GET"),
    }
    assert expected <= rows


def test_m2a_partner_denied_secret_domain():
    """涉密域对外部用户默认全拒（roadmap 验收口径）：R-PARTNER 无任何 x_ 域策略行。"""
    rows = _policy_p_rows()
    assert not [r for r in rows if r[0] == "R-PARTNER" and (
        r[1].startswith("/api/v1/x") or r[1].startswith("/api/v1/confsec")
        or r[1].startswith("/api/v1/admin"))]


def test_m2a_partner_keymatch2_guideline_detail_covered():
    """指南详情 /apply/guidelines/{id} 由 /api/v1/apply/guidelines/* 覆盖；写操作不被覆盖。"""
    from casbin.util import key_match2
    rows = _policy_p_rows()
    assert key_match2("/api/v1/apply/guidelines/12", "/api/v1/apply/guidelines/*")
    assert ("R-PARTNER", "/api/v1/apply/guidelines", "POST") not in rows
    assert ("R-PARTNER", "/api/v1/apply/guidelines/*", "POST") not in rows
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_rbac.py -k m2a -q` → FAIL（策略行缺失）

- [ ] **Step 3: 加策略与角色**

`policy.csv` 末尾新增一段（列对齐用既有公式 `"p, "+(role+",").ljust(11)+(path+",").ljust(38)+"GET"`，并与文件现有空格风格一致）：

```
# —— M2-a 外部机构门户（R-PARTNER：只读本机构与已发布指南，无任何写业务权）——
p, R-PARTNER, /api/v1/auth/me,                          GET
p, R-PARTNER, /api/v1/portal/org,                       GET
p, R-PARTNER, /api/v1/portal/org,                       PUT
p, R-PARTNER, /api/v1/portal/home,                      GET
p, R-PARTNER, /api/v1/apply/guidelines,                 GET
p, R-PARTNER, /api/v1/apply/guidelines/*,               GET
p, R-PARTNER, /api/v1/notifications,                    GET
p, R-PARTNER, /api/v1/notifications/*,                  POST
p, R-PARTNER, /api/v1/notifications/read-all,           POST
p, R-PARTNER, /api/v1/dicts/*,                          GET
```

`seed_demo.py` `ROLES` 加 `("R-PARTNER", "外部机构用户")`；`tests/conftest.py` 的 `seed_auth` 角色列表同样加一行（否则审核端点测试里 `SysRole.objects.filter(code="R-PARTNER")` 取不到行）。

新增数据迁移 `apps/sysadmin/migrations/0008_resync_permissions.py`（内容照抄 `0007_resync_permissions.py`，仅改 `dependencies` 指向 `("sysadmin", "0007_resync_permissions")`）：`migrations.RunPython(sync, desync)` 调 `sync_permissions_from_csv(settings.CASBIN_POLICY_PATH)`——**这一步是运行时生效的关键**：DB 是唯一权威（`core/auth/casbin_util.py:29-53` `DbAdapter`），只改 CSV 不改 DB，`enforce_any` 依旧拒绝 R-PARTNER。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_rbac.py -q`（原有 + 3 新例全绿）；再跑 `.venv/bin/python -m pytest -q` → **351 passed**。

- [ ] **Step 5: 提交**

```bash
git add backend-django/config/casbin/policy.csv backend-django/apps/sysadmin/migrations/0008_resync_permissions.py backend-django/apps/sysadmin/management/commands/seed_demo.py backend-django/tests/conftest.py backend-django/tests/test_rbac.py
git commit -m "feat(rbac): M2-a R-PARTNER 门户策略域（涉密域默认全拒）"
```

---

### Task 3: 自助注册端点（公开，无需登录）

**Files:**
- Modify: `backend-django/apps/sysadmin/api.py`（末尾新增注册区）
- Modify: `backend-django/apps/sysadmin/mappings.py`（`to_api_partner_org`）
- Modify: `backend-django/config/api.py`（**不传 `auth=`**，公开路由）
- Test: `backend-django/tests/test_sysadmin_partner.py`

**Interfaces:**
- Consumes: `hash_password`（`apps/sysadmin/api.py:62`）、`SysPartnerOrg`/`SysUser`（Task 1）。
- Produces:
  - `to_api_partner_org(o: SysPartnerOrg) -> dict`（snake_case：`id, code, tenant_id, name, short_name, credit_code, org_type, contact_name, contact_phone, contact_email, address, qualification_json, status, audit_user_id, audited_at, reject_reason, creator_id, created_at, updated_at`）。
  - `register_partner(request: HttpRequest) -> object`（POST `/portal/register`）。
  - 后续任务复用：`_partner_org_or_404(tenant_id: int, org_id: int) -> SysPartnerOrg`、`_my_partner_org(tenant_id: int, user_id: int) -> SysPartnerOrg`。

- [ ] **Step 1: 写失败测试**（沿用 `tests/test_funding_m1c.py:47-52` 的 `django.test.Client` + `json.dumps` + `tests.conftest.bearer` 风格；注册是**公开**路由，不带 bearer）

```python
import json
from django.test import Client
from tests.conftest import bearer

REGISTER_URL = "/api/v1/portal/register"


def _register_body(**kw):
    body = {
        "org_name": "示例大学", "credit_code": "91310000MA1K3XY12A", "org_type": "UNIVERSITY",
        "contact_name": "张三", "contact_phone": "13800000000",
        "contact_email": "z@example.edu.cn",
        "username": "p_example", "password": "Partner@2026", "real_name": "张三",
    }
    body.update(kw)
    return body


def _post(url, body, roles=None, uid=1):
    kw = {} if roles is None else bearer(uid, list(roles))
    return Client().post(url, data=json.dumps(body), content_type="application/json", **kw)


def _data(resp):
    return json.loads(resp.content)["data"]


def test_register_creates_pending_org_and_locked_user():
    resp = _post(REGISTER_URL, _register_body())
    assert resp.status_code == 200, resp.content
    data = _data(resp)
    assert data["status"] == "PENDING" and data["code"].startswith("PTN-")
    org = SysPartnerOrg.objects.get(id=data["id"])
    u = SysUser.objects.get(username="p_example")
    assert u.status == "LOCKED" and u.org_id == org.id and u.user_source == "EXTERNAL"
    assert u.password_hash and u.password_hash.startswith("$2")


def test_register_rejects_duplicate_credit_code_and_username():
    assert _post(REGISTER_URL, _register_body()).status_code == 200
    dup_credit = _post(REGISTER_URL, _register_body(username="other_user"))
    assert dup_credit.status_code == 409 and json.loads(dup_credit.content)["code"] == 40901
    dup_user = _post(REGISTER_URL, _register_body(credit_code="91110000MA2C4AB34B"))
    assert dup_user.status_code == 409 and json.loads(dup_user.content)["code"] == 40901


def test_register_rejects_weak_password_and_bad_input():
    base = _register_body()
    for bad in ({**base, "password": "12345678"},              # 纯数字
                {**base, "password": "Ab1!"},                  # 太短
                {**base, "contact_email": ""},                 # 必填缺失
                {**base, "credit_code": "abc"},                 # 信用代码长度错
                {**base, "org_type": "NOT_A_TYPE"}):            # 枚举外
        r = _post(REGISTER_URL, bad)
        assert r.status_code == 400, bad
        assert json.loads(r.content)["code"] == 40001


def test_locked_user_cannot_login_until_approved():
    _post(REGISTER_URL, _register_body())
    r = _post("/api/v1/auth/login", {"username": "p_example", "password": "Partner@2026"})
    assert r.status_code == 403
    assert json.loads(r.content)["code"] == 40302   # CODE_ACCOUNT_DISABLED，见 core/httpx.py
```

- [ ] **Step 2: 跑测试确认失败** → `AttributeError`/404（路由不存在）

- [ ] **Step 3: 实现**

`register_partner` 校验顺序：必填（org_name/credit_code/contact_name/contact_email/username/password/real_name）→ `credit_code` 长度 18 且首字符大写字母/数字 → 邮箱含 `@` → 密码 `len>=8` 且含字母与数字 → 用户名 `len>=3`。冲突：`(tenant_id, credit_code, deleted=0)` 存在或 `(tenant_id, username, deleted=0)` 存在 → `ApiError(409, CODE_CONFLICT, "机构或用户名已注册")`（40901）。`transaction.atomic()` 内：建 org（`code=code_of("PTN", <id>)` 回填，`code_of` 见 `apps/funding/mappings.py:56`；本域无编号器时用 `f"PTN-{year}-{id:06d}"`）→ 建 user（`status="LOCKED"`, `org_id`, `user_source="EXTERNAL"`, `creator_id=1`, `remark="self-register"`）→ `SysNotification` 给本租户 R-MANAGER（typ=TODO, title="外部机构待审核", biz_ref=f"partner-org:{org.id}"）。返回 `to_api_partner_org(org)`。租户取 body 的 `tenant_id` 或 1（公开端点无 domain）。

`config/api.py`：在「用户管理」段之前加 `api.post("/portal/register", tags=["portal"])(sysadmin_api.register_partner)`（**无 auth**）。

- [ ] **Step 4: 跑测试确认通过** → `.venv/bin/python -m pytest tests/test_sysadmin_partner.py -q` 全绿；全量 **356 passed**。

- [ ] **Step 5: 提交**

```bash
git add backend-django/apps/sysadmin/api.py backend-django/apps/sysadmin/mappings.py backend-django/config/api.py backend-django/tests/test_sysadmin_partner.py
git commit -m "feat(sysadmin): 外部机构自助注册——待审机构+LOCKED 账号（C1）"
```

---

### Task 4: 邮件通道工具 + 通知渠道

**Files:**
- Create: `backend-django/apps/notify/email.py`
- Modify: `backend-django/config/settings/base.py`（EMAIL 配置，env 驱动）
- Modify: `backend-django/apps/notify/models.py`（`SysNotification` 加 `channel` 列）+ 迁移
- Test: `backend-django/tests/test_notify_email.py`（新建）

**Interfaces:**
- Produces:
  - `send_mail_best_effort(to: str | None, subject: str, body: str, *, tenant_id: int, biz_ref: str = "") -> bool`（`apps/notify/email.py`）：收件人为空/无 `@` 直接返回 False；`send_mail` 抛任何异常 → 记 `logging.getLogger(__name__).warning` 后返回 False，**绝不抛出**。
  - `SysNotification.channel: CharField(max_length=16, default="INAPP")`（`INAPP|EMAIL|BOTH`）。
  - `notify_inapp(tenant_id: int, user_id: int, typ: str, title: str, content: str | None, biz_ref: str | None, channel: str = "INAPP") -> SysNotification`（`apps/notify/email.py` 内薄封装，供审核端点复用）。

- [ ] **Step 1: 写失败测试**

```python
import pytest
from django.core import mail
from apps.notify.email import send_mail_best_effort, notify_inapp

@pytest.mark.django_db
def test_send_mail_writes_outbox():
    assert send_mail_best_effort("a@b.com", "主题", "正文", tenant_id=1) is True
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["a@b.com"]

@pytest.mark.django_db
def test_send_mail_swallows_failure(monkeypatch):
    import apps.notify.email as m
    monkeypatch.setattr(m, "send_mail", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    assert send_mail_best_effort("a@b.com", "s", "b", tenant_id=1) is False  # 不抛

@pytest.mark.django_db
def test_send_mail_skips_invalid_address():
    assert send_mail_best_effort("not-an-email", "s", "b", tenant_id=1) is False

@pytest.mark.django_db
def test_notify_inapp_marks_channel():
    n = notify_inapp(1, 7, "TODO", "标题", "正文", "ref:1")
    assert n.channel == "INAPP" and n.user_id == 7
```

- [ ] **Step 2: 跑测试确认失败** → `ModuleNotFoundError: apps.notify.email`

- [ ] **Step 3: 实现**

`config/settings/base.py` 末尾：

```python
EMAIL_BACKEND = os.environ.get("ARK_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("ARK_EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("ARK_EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("ARK_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("ARK_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("ARK_EMAIL_TLS", "") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("ARK_EMAIL_FROM", "noreply@ark.local")
```

`apps/notify/email.py`：`from django.core.mail import send_mail`（**模块级导入**，测试 monkeypatch 该名字）；`send_mail_best_effort` 按 Interfaces 语义；`notify_inapp` 直接 `SysNotification.objects.create(...)`。

`tests/conftest.py`（若不存在则创建；存在则在其中追加 `autouse` fixture）设 `settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"`，保证 `mail.outbox` 可断言。

`SysNotification.channel` 加列 + `manage.py makemigrations notify --name notification_channel`，同步 `design/00-common.sql`（`sys_notification` 加列，doc-only）。

- [ ] **Step 4: 跑测试确认通过** → 4 passed；全量 **360 passed**。

- [ ] **Step 5: 提交**

```bash
git add backend-django/apps/notify/email.py backend-django/apps/notify/models.py backend-django/apps/notify/migrations/ backend-django/config/settings/base.py backend-django/tests/test_notify_email.py backend-django/tests/conftest.py design/00-common.sql
git commit -m "feat(notify): 邮件通道 best-effort + 通知渠道列（C5 最小实现）"
```

---

### Task 5: 机构审核端点（R-MANAGER）

**Files:**
- Modify: `backend-django/apps/sysadmin/api.py`
- Modify: `backend-django/config/api.py`
- Modify: `backend-django/config/casbin/policy.csv`（`/partner-orgs` 两条）
- Test: `backend-django/tests/test_sysadmin_partner.py`

**Interfaces:**
- Consumes: `to_api_partner_org`、`_partner_org_or_404`（Task 3）、`notify_inapp`/`send_mail_best_effort`（Task 4）、`SysRole`/`SysUserRole`。
- Produces:
  - `list_partner_orgs(request: HttpRequest)`（GET `/partner-orgs?status=&keyword=&page=&size=`，返回 `{"list": [...], "total", "page", "size"}`）。
  - `audit_partner_org(request: HttpRequest, id: int)`（POST `/partner-orgs/{id}/audit`，body `{action: "APPROVE"|"REJECT", reason?: str}`），返回 `to_api_partner_org`。

- [ ] **Step 1: 写失败测试**（同 Task 3 的 `_post`/`_data` 帮助；管理端带 `roles=("R-MANAGER",)`）

```python
AUDIT_URL = "/api/v1/partner-orgs/{id}/audit"


def _register_then_approve(action="APPROVE", reason=None, **kw):
    oid = _data(_post(REGISTER_URL, _register_body(**kw)))["id"]
    body = {"action": action} if reason is None else {"action": action, "reason": reason}
    return oid, _post(AUDIT_URL.format(id=oid), body, roles=("R-MANAGER",))


def test_approve_activates_user_grants_role_and_notifies(seed_auth):
    oid, resp = _register_then_approve()
    assert resp.status_code == 200, resp.content
    data = _data(resp)
    assert data["status"] == "APPROVED" and data["audit_user_id"]
    u = SysUser.objects.get(username="p_example")
    assert u.status == "ACTIVE"
    assert SysUserRole.objects.filter(user_id=u.id, role__code="R-PARTNER").count() == 1
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["z@example.edu.cn"]
    assert SysNotification.objects.filter(user_id=u.id, typ="ANNOUNCE").exists()


def test_approve_twice_is_idempotent(seed_auth):
    oid, _ = _register_then_approve()
    resp = _post(AUDIT_URL.format(id=oid), {"action": "APPROVE"}, roles=("R-MANAGER",))
    assert resp.status_code == 200
    u = SysUser.objects.get(username="p_example")
    assert SysUserRole.objects.filter(user_id=u.id, role__code="R-PARTNER").count() == 1


def test_reject_requires_reason_and_keeps_user_locked(seed_auth):
    oid, bad = _register_then_approve(action="REJECT")
    assert bad.status_code == 400 and json.loads(bad.content)["code"] == 40001
    _, ok = _register_then_approve(action="REJECT", reason="资质不全", username="p_two",
                                   credit_code="91310000MA1K3XY12B")
    assert _data(ok)["status"] == "REJECTED"
    assert SysUser.objects.get(username="p_two").status == "LOCKED"


def test_audit_unknown_or_cross_tenant_org_is_404(seed_auth):
    assert _post(AUDIT_URL.format(id=99999), {"action": "APPROVE"},
                 roles=("R-MANAGER",)).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败** → 404（路由未注册）

- [ ] **Step 3: 实现**

`list_partner_orgs`：`tenant_id=d.tenant_id`、`deleted=0`、可选 `status`/`keyword`（name/credit_code icontains）、`order_by("-created_at","-id")`，分页复用本文件既有 `page_args`。

`audit_partner_org`：`atomic()` + `SysPartnerOrg.objects.select_for_update().filter(id=id, tenant_id=d.tenant_id, deleted=0)`（否则 404）；`action` 非二值 → 40001；`APPROVE` 时若已 `APPROVED` 直接返回（幂等），否则置 `APPROVED`/`audited_at=dj_tz.now()`/`audit_user_id=d.user_id`，并把该 org 名下 `user_source="EXTERNAL"` 且未删的用户置 `ACTIVE`、`get_or_create` `SysUserRole`（`R-PARTNER`，角色缺失则 500 前置检查：`SysRole.objects.filter(code="R-PARTNER")` 不存在 → `ApiError(400, CODE_BAD_REQUEST, "角色未初始化，请先执行 seed_demo")`），最后 `notify_inapp(... typ="ANNOUNCE" title="机构审核通过")` + `send_mail_best_effort(org.contact_email, ...)`；`REJECT` 要求 `reason` 非空（40001），置 `REJECTED`+`reject_reason`，发邮件，用户保持 `LOCKED`。

`policy.csv` 加：`p, R-MANAGER, /api/v1/partner-orgs, GET`、`p, R-MANAGER, /api/v1/partner-orgs/*, POST`（裸路径不覆盖 `*`，M1-c 已实证）。

`config/api.py`：`api.get("/partner-orgs", auth=ark_auth, tags=["portal"])(sysadmin_api.list_partner_orgs)`、`api.post("/partner-orgs/{id}/audit", auth=ark_auth, tags=["portal"])(sysadmin_api.audit_partner_org)`（`{id}` 无需类型化：本段无同级静态竞态）。

- [ ] **Step 4: 跑测试确认通过** → 本文件全绿；全量 **365 passed**。

- [ ] **Step 5: 提交**

```bash
git add backend-django/apps/sysadmin/api.py backend-django/config/api.py backend-django/config/casbin/policy.csv backend-django/tests/test_sysadmin_partner.py
git commit -m "feat(sysadmin): 机构资质审核——通过即激活账号授 R-PARTNER 并双通道通知（C1）"
```

---

### Task 6: 门户端点（R-PARTNER）

**Files:**
- Modify: `backend-django/apps/sysadmin/api.py`
- Modify: `backend-django/config/api.py`
- Test: `backend-django/tests/test_sysadmin_partner.py`

**Interfaces:**
- Consumes: `_my_partner_org`（Task 3）、Task 5 审核后的 `APPROVED` 机构。
- Produces:
  - `portal_org(request)`（GET `/portal/org`）→ `to_api_partner_org`；无机构（内部用户误访）→ `ApiError(404, CODE_NOT_FOUND)`。
  - `update_portal_org(request)`（PUT `/portal/org`，只接受 `contact_name/contact_phone/contact_email/address`，其余键忽略）→ 更新后 `to_api_partner_org`。
  - `portal_home(request)`（GET `/portal/home`）→ `{"org": {...}, "announcements": [{id,title,content,created_at}], "guidelines": [{id,code,title,project_type,apply_start_at,apply_end_at,publish_at}], "todos": {"unread_notifications": int, "pending_applications": 0}}`。

- [ ] **Step 1: 写失败测试**（复用 Task 3/5 的 `_post`/`_data`；门户调用带 `roles=("R-PARTNER",)` 与真实 `uid`）

```python
def _approved_partner(seed_auth, **kw):
    """注册→审核→返回 (org, user)：portal 测试的前置。"""
    oid, _ = _register_then_approve(**kw)
    return SysPartnerOrg.objects.get(id=oid), SysUser.objects.get(username=kw.get("username", "p_example"))


def test_portal_home_lists_only_published_guidelines(seed_auth):
    org, u = _approved_partner(seed_auth)
    from apps.p.models import PGuideline  # 顶部导入
    PGuideline.objects.create(tenant_id=1, title="已发布指南", project_type="NSFC",
                             status="PUBLISHED", creator_id=1)
    PGuideline.objects.create(tenant_id=1, title="草稿指南", project_type="NSFC",
                             status="DRAFT", creator_id=1)
    SysNotification.objects.create(tenant_id=1, user_id=u.id, typ="ANNOUNCE", title="公告A")
    resp = Client().get("/api/v1/portal/home", **bearer(u.id, ["R-PARTNER"]))
    data = _data(resp)
    assert [g["title"] for g in data["guidelines"]] == ["已发布指南"]
    assert [a["title"] for a in data["announcements"]] == ["公告A"]
    assert data["todos"]["unread_notifications"] == 1
    assert data["org"]["id"] == org.id


def test_portal_org_update_only_contact_fields(seed_auth):
    org, u = _approved_partner(seed_auth)
    r = Client().put("/api/v1/portal/org",
                     data=json.dumps({"contact_phone": "13900000000",
                                      "name": "改名尝试", "status": "APPROVED"}),
                     content_type="application/json", **bearer(u.id, ["R-PARTNER"]))
    assert r.status_code == 200
    o = SysPartnerOrg.objects.get(id=org.id)
    assert o.contact_phone == "13900000000"
    assert o.name == org.name and o.status == "APPROVED"


def test_portal_is_org_scoped(seed_auth):
    """机构 A 的用户只能看到 A；B 的用户看到 B（互不可见）。"""
    org_a, ua = _approved_partner(seed_auth)
    org_b, ub = _approved_partner(seed_auth, username="p_b", credit_code="91310000MA1K3XY12C",
                                  org_name="示例B学院")
    da = _data(Client().get("/api/v1/portal/org", **bearer(ua.id, ["R-PARTNER"])))
    db_ = _data(Client().get("/api/v1/portal/org", **bearer(ub.id, ["R-PARTNER"])))
    assert da["id"] == org_a.id and db_["id"] == org_b.id


def test_internal_user_without_org_is_rejected(seed_auth):
    """内部用户（无 org_id）访问门户：无 R-PARTNER 角色 → 403（策略层先拦）。"""
    r = Client().get("/api/v1/portal/org", **bearer(2, ["R-STAFF"]))
    assert r.status_code == 403
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`portal_home` 取 `org = _my_partner_org(...)`（无 → 404）；`announcements`：`SysNotification.objects.filter(tenant_id=d.tenant_id, typ="ANNOUNCE", user_id=d.user_id)` 最近 5 条，按 `-created_at`；`guidelines`：`PGuideline.objects.filter(tenant_id=d.tenant_id, deleted=0, status="PUBLISHED")` 最近 5 条；`todos.unread_notifications` 用 `read_at__isnull=True` 计数。

`config/api.py`：`portal/org`（GET/PUT）、`portal/home`（GET），全部 `auth=ark_auth, tags=["portal"]`。

- [ ] **Step 4: 跑测试确认通过** → 全量 **369 passed**。

- [ ] **Step 5: 提交**

```bash
git add backend-django/apps/sysadmin/api.py backend-django/config/api.py backend-django/tests/test_sysadmin_partner.py
git commit -m "feat(sysadmin): 机构门户——本机构资料与首页（公告/已发布指南/待办，C1）"
```

---

### Task 7: 契约补 6 路径 + 5 schema（12-U，双份一致）

**Files:**
- Modify: `design/12-用户与权限-U.openapi.yaml`
- Modify: `frontend/src/api/schema/12-用户与权限-U.openapi.yaml`（`cp` 后 `cmp`）

**Interfaces:**
- Produces（供 Task 8 前端按契约对齐）：`PartnerOrg`、`PartnerOrgRegisterRequest`、`PartnerOrgAuditRequest`、`PartnerOrgUpdateRequest`、`PortalHome`。

- [ ] **Step 1: 编辑 `design/12-...U.openapi.yaml`**

在 `/messages` 之后追加 6 条路径：`/portal/register`（POST，`security: []` 公开，200 `data: PartnerOrg`，409`40901`、400`40001`）、`/portal/org`（GET/PUT）、`/portal/home`（GET）、`/partner-orgs`（GET，分页三件套）、`/partner-orgs/{id}/audit`（POST，409?? 无——幂等 200，400 缺 reason）。schema 全 snake_case（与同文件 `item_code`/`page_name` 风格一致），字段严格对齐 Task 1 模型与 Task 3 序列化器输出键，`PartnerOrgRegisterRequest.required` = `[org_name, credit_code, org_type, contact_name, contact_phone, contact_email, username, password, real_name]`。

- [ ] **Step 2: 校验**

```bash
cd /Users/jacky/works/science-research-project
cp design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml
cmp design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml && echo SAME
backend-django/.venv/bin/python -c "import yaml;yaml.safe_load(open('design/12-用户与权限-U.openapi.yaml'));print('YAML_OK')"
grep -c "^  /portal/\|^  /partner-orgs" design/12-用户与权限-U.openapi.yaml   # 期望 5（路径条数）
```

- [ ] **Step 3: 提交**

```bash
git add design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml
git commit -m "feat(contract): 12-U 补机构注册/门户/审核 6 路径与 5 schema（M2-a）"
```

---

### Task 8: 前端——注册页 / 门户首页 / 机构审核

**Files:**
- Create: `frontend/src/views/RegisterView.vue`
- Create: `frontend/src/views/PortalView.vue`
- Create: `frontend/src/views/admin/PartnerOrgsView.vue`
- Modify: `frontend/src/router/index.ts`（`/register` 加 `meta: { public: true }`；`/portal` roles `['R-PARTNER']`；`/admin/partner-orgs` roles `['R-MANAGER','R-ADMIN']`）
- Modify: `frontend/src/App.vue`（nav：门户对 R-PARTNER 可见、机构审核对 R-MANAGER 可见）
- Modify: `frontend/src/api/mock/overrides/`（新增 `portal.ts`：`POST /portal/register`、`GET/PUT /portal/org`、`GET /portal/home`、`GET /partner-orgs`、`POST /partner-orgs/{id}/audit`）
- Modify: `frontend/src/api/mock/overrides/auth.ts`（`PAGE_GRANTS` 加 `portal`/`admin-partner-orgs`；`ROLE_CAPS` 加 R-PARTNER 镜像 policy.csv）
- Modify: `frontend/src/views/admin/UsersView.vue` 或登录浮层加「外部机构注册」入口链接（**一处即可**）

**Interfaces:**
- Consumes: Task 7 契约形态（snake_case 键）。
- Produces: 三条路由 `register` / `portal` / `admin-partner-orgs`，页面名与 `PAGE_GRANTS` 的 `page_name` 一致。

- [ ] **Step 1: 注册页**：表单字段对齐 `PartnerOrgRegisterRequest`；提交 `api.post('/portal/register', form)`；成功态展示「已提交，等待资质审核」文案 + 返回首页链接；400/409 错误按 `message` 提示；样式沿用既有 view 的卡片/栅格风格（参考 `GuideView.vue` 的 `panel`/`field` 类）。
- [ ] **Step 2: 门户首页**：`api.get('/portal/home')` 渲染机构卡（name/credit_code/org_type/contact_*）+ 公告列表 + 指南推送列表（表格 columns：标题/类型/申报期/发布时间，行点击跳 `/guide`）+ 待办数字卡；`api.get('/portal/org')` 支撑「机构资料」抽屉，`PUT /portal/org` 保存四个可编辑字段。
- [ ] **Step 3: 审核视图**：`api.get('/partner-orgs', { params: { page, size, status } })` 列表（状态徽标 PENDING/APPROVED/REJECTED）+ 行内「通过 / 驳回」按钮，驳回弹 reason 输入；`api.post('/partner-orgs/'+id+'/audit', { action, reason })` 后就地刷新。
- [ ] **Step 4: 类型检查** `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` → **0 errors**；`cd backend-django && .venv/bin/python -m pytest -q` → 仍 369（前端不改后端）。
- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/RegisterView.vue frontend/src/views/PortalView.vue frontend/src/views/admin/PartnerOrgsView.vue frontend/src/router/index.ts frontend/src/App.vue frontend/src/api/mock/overrides/portal.ts frontend/src/api/mock/overrides/auth.ts
git commit -m "feat(fe): 机构注册页/门户首页/机构审核视图——契约驱动 mock 对齐 M2-a"
```

---

### Task 9: 种子数据 + README

**Files:**
- Modify: `backend-django/apps/sysadmin/management/commands/seed_demo.py`
- Modify: `README.md`（三处测试数）

**Interfaces:**
- Consumes: Task 1 模型、Task 2 角色、Task 5 审核语义。

- [ ] **Step 1: 种子**
  - `ROLES` 已在 Task 2 加 `R-PARTNER`（此处只校验存在）。
  - 机构 A（已通过）：`code="PTN-2026-000001"`, `name="合作示例大学"`, `credit_code="91310000MA1K3XY12A"`, `org_type="UNIVERSITY"`, `status="APPROVED"`, `audit_user_id=2`, `audited_at=now`, 联系人信息齐；用户 `username="partner"`, `real_name="合作单位联系人"`, `status="ACTIVE"`, `password="Partner@123456"`, `org_id=机构A.id`, `user_source="EXTERNAL"`, 角色 `R-PARTNER`。
  - 机构 B（待审）：`code="PTN-2026-000002"`, `name="待审核协作单位"`, `credit_code="91110000MA2C4AB34B"`, `status="PENDING"`，无用户。
  - 全部 `get_or_create`（幂等键：`(tenant_id, code)`），并复用既有 `_filt` 辅助。
- [ ] **Step 2: 跑幂等验证**

```bash
cd backend-django
rm -f /tmp/m2a_seed.sqlite3
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2a_seed.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate --no-input >/dev/null
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2a_seed.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2a_seed.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo   # 二次必须全零
```

- [ ] **Step 3: 更新 README 三处计数为实测值**（`grep -n "342\|346" README.md` 定位，改成本任务结束后的 `pytest` 数字），提交。
- [ ] **Step 4: 提交**

```bash
git add backend-django/apps/sysadmin/management/commands/seed_demo.py README.md
git commit -m "chore(seed+readme): M2-a 演示数据（已审/待审机构+外部账号）+ 测试数更新"
```

---

## 自审记录

**1. Spec 覆盖**：C1（注册→审核→登录→门户看指南推送）= Task 1/3/5/6 + Task 8 前端；C5（邮件）= Task 4。C2/C3/C4 明确不在本期（M2-b/M2-c），已在 Goal 与 Open objectives 写明。
**2. 步骤扫描**：每个 Step 有可检查结果（命令 + 期望数字）；无「TBD/handle edge cases」式空步。
**3. 类型一致性**：`to_api_partner_org` / `_partner_org_or_404` / `_my_partner_org` / `notify_inapp` / `send_mail_best_effort` 在 Interfaces 与实现步中同名同签名。
**4. Review Focus**：5 条分别由 Task 3（弱口令/重复/锁定登录）、Task 5（幂等/驳回/跨租户）、Task 6（跨机构/仅 PUBLISHED）、Task 4（邮件失败不阻断）覆盖。
**5. 比例**：计划 9 任务，正文以签名+断言为主，未抄实现体。
