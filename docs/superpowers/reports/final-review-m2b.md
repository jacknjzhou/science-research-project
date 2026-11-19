# M2-b「开放课题全流程（C2）」终审评审报告

| 项 | 值 |
|---|---|
| 评审对象 | M2-b 开放课题全流程（C2），计划 `docs/superpowers/plans/2026-11-19-m2b-open-topic-fullflow.md`（9 个任务） |
| 范围 | `BASE=42eae59` → `HEAD=2c8d982`，9 个 commit，31 个文件，+2931 / −31 |
| 评审方式 | 独立终审：读计划与全量 diff、逐文件核对、**单进程文件库实测**（Django `Client` + SQLite）、casbin `key_match2` 实证、契约/迁移/测试/提交卫生核验 |
| 环境 | macOS；`backend-django/.venv`（Python 3.13）；`frontend/node_modules`；SQLite 文件库 `/tmp/m2b_ev.sqlite3`（`ARK_DB_ENGINE=sqlite`） |
| 结论 | **REQUEST_CHANGES** |
| 必须修 | **C1、C2、C3、C4**（四条均为本次引入的安全/状态机缺陷） |

> 说明：本报告只写 `docs/superpowers/reports/final-review-m2b.md`，未改动任何源码、迁移、契约或测试。所有状态码/布尔值均为本机真实运行输出，不是阅读代码推测。

---

## 0. 结论速览

M2-b 的骨架是完整的：模型/迁移、任务书快照与双签、项目 1:1 幂等、外部机构在**项目域/任务书域/指南建议域**的隔离、前端 5 个视图、seed 演示链路、契约副本与测试数都对得上。实测 `pytest 396 passed`、`vue-tsc 0 error`、`makemigrations --check` 无变更、两份契约逐字节一致、迁移在空库真实生效（R-PARTNER 的 28 条权限进了 DB）。

但**申报（P）域的机构隔离没有收口**：`GET detail` 做了 404，`documents / budget / sections / submit` 四个子资源仍只按 tenant 过滤；一个外部机构可以读、改、甚至提交另一个机构的申报。**任务书签署**只校验 `role` 字符串的字面值，不校验调用者身份与角色，外部机构可以自己把 PI 和 MANAGER 都签了直接立项，还能伪造 `signerId`；而且签署入口不校验申报状态，**已被终止（REJECTED）的申报仍能双签生成项目并把申报改回 EXECUTING**。此外，`applicant_org_id=NULL` 的外部账号会在列表中看到院内申报，并可读写院内申报内容（`create_user` 允许创建无机构的 R-PARTNER）。

这些不是"测试不够"的风格问题，而是可复现的越权与状态机缺陷，因此给出 `REQUEST_CHANGES`。

---

## 1. 实测验收数字（真实输出）

| 检查 | 命令 | 实测结果 |
|---|---|---|
| 后端全量测试 | `cd backend-django && .venv/bin/python -m pytest -q` | **396 passed, 7 warnings in 19.71s**（real 0m20.1s）。7 条 warning 为既有 naive-datetime 与 `PytestReturnNotNone` 类，无新增失败 |
| 迁移漂移 | `cd backend-django && .venv/bin/python manage.py makemigrations --check` | 输出 **`No changes detected`**，EXIT=0；stderr 有一条既有环境告警 `connection to server at 127.0.0.1, port 5432 ... Connection refused`（dev settings 连 PG 的探测，不影响判定） |
| 前端类型检查 | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | 无输出，**EXIT=0**（0 errors） |
| 契约副本 P | `cmp design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml` | **逐字节一致**（cmp 无输出，EXIT=0） |
| 契约副本 E | `cmp design/02-项目过程管理-E.openapi.yaml frontend/src/api/schema/02-项目过程管理-E.openapi.yaml` | **逐字节一致**（cmp 无输出，EXIT=0） |
| 契约 YAML 可解析 | `backend-django/.venv/bin/python -c "import yaml;yaml.safe_load(open(p))"` | 两份均 `yaml ok` |
| 空库迁移 | `ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate --no-input` | 全量成功，含 `Applying sysadmin.0012_resync_permissions... OK`、`project.0006_eproject_ext_org_id... OK`、`p.0003... OK` |
| 数据迁移是否真进 DB | `SysRolePermission.objects.filter(role=R-PARTNER).count()`（新库） | **28**；`SysPermission` 总数 366 → `0012_resync_permissions` 确实调用了 `sync_permissions_from_csv`，不是只改 CSV |
| 种子幂等 | `manage.py seed_demo` 连跑两遍（同一文件库） | 第 1 遍：`legal +2，staff +11，p +6，project +17，funding +23，output +7，expert +6，activity +4，archive +6，performance +6，transform +13，ethics +5，procure +8，asset +9，confsec +7，notify +5，partner +5，users +4，dicts +5，items +26，grants +78`；第 2 遍：`seed_demo 完成（幂等）：` 后**无任何计数**（全 0） |
| 提交卫生 | `git log --oneline 42eae59..2c8d982` / `git diff --check` | 9 条 conventional 风格 commit，无 fixup/squash；`diff --check` 干净（无空白错误） |

### 1.1 种子演示链路抽查（真实库查询）

```
guide [(1, 'PENDING', 'SUG-2026-000001', 1)]
ext app [(2, 'PUBLISHED', 1, 5)]
ext project [(4, 'ACTIVE', 2, 1)]
tb [(1, 'DRAFT', 2, 4)]
reports [(1, 1, '2026-Q3', 'SUBMITTED'), (2, 4, '2026Q1', 'SUBMITTED')]
```

- 指南建议：1 条，`PENDING`，`org_id=1` ✅
- 外部申报：`PUBLISHED / EXTERNAL / applicant_org_id=1 / pi=5` ✅
- 外部项目：`ext_org_id=1`、`status=ACTIVE`、`application_id=2` ✅（但见 M5：任务书还是 DRAFT 时项目已存在）
- 任务书：`DRAFT`、仅 PI 一条签署记录、`project_id` 已回填 ✅（同上，演示语义与"双签即立项"不一致）
- 阶段汇报：外部项目恰好 1 条（`2026Q1 / SUBMITTED`）✅

---

## 2. 五项 Review Focus 判定

| # | Focus | 判定 | 一句话结论 |
|---|---|---|---|
| 1 | 外部用户绕过机构边界读别的机构/院内的申报、任务书、项目、汇报、验收 | **FAIL** | 项目域、任务书域、指南建议域隔离有效；**申报子资源（documents/budget/sections/submit）与 NULL-org 列表未收口** |
| 2 | 一次立项会不会变成两个项目 | **PASS**（附条件） | 正常双签路径 `select_for_update` + `application_id` 幂等，重复调用返回同一项目、计数恒为 1；但"正常路径"本身被 C2/C3 绕过 |
| 3 | 外部申报人能否通过请求体改 PI 或申报机构 | **PASS（纯 R-PARTNER）/ FAIL（多角色账号）** | 纯外部账号的 `pi_user_id`、`applicant_org_id` 被服务端强制覆盖；持有 `R-PARTNER + 任一内部角色` 的账号走内部分支，可任意指定 `pi_user_id`/`applicant_org_id`（I2） |
| 4 | 任务书签订后快照/申报内容还能不能改 | **FAIL** | 三个写入口（section/budget/submit）确实 409；但 `:terminate` 未加冻结校验，签后可把申报改成 REJECTED 而项目仍 EXECUTING（C3） |
| 5 | 外部用户能否误入涉密/管理域（casbin 通配与 keyMatch2） | **PASS** | 实测 `R-PARTNER` 对 `/project/1/board`、`/project/eval-templates`、`/project/1`、`/project/1/tasks`、`/users`、`/funding/expenses`、`/partner-orgs`、`/x/projects` **全部 False**；未发现通配误放。`*:sign` 的 `:sign` 非字面量属 Minor 隐患（M1） |

---

## 3. 问题清单

### Critical

#### C1【本次引入】申报子资源只按 tenant 过滤，外部机构可跨机构读/写/提交他人申报

**位置**
- `backend-django/apps/p/api.py:319-324` `_get_app_or_404(tenant_id, app_id)`：仅 `id + tenant_id + deleted=0`，**没有机构条件**。
- 使用该函数的写/读入口（全部未做机构校验）：
  - `backend-django/apps/p/api.py:419-424` `list_application_documents`
  - `backend-django/apps/p/api.py:427-430` `get_application_budget`
  - `backend-django/apps/p/api.py:447-452` `upsert_budget_line`
  - `backend-django/apps/p/api.py:479-483` `save_application_section`
  - `backend-django/apps/p/api.py:502-507` `submit_application`
  - `backend-django/apps/p/api.py:344-352` `withdraw_application` / `:360-368` `terminate_application`（同函数，另见 C3）
- 对照：`backend-django/apps/p/api.py:326-334` `_partner_app_or_404`（detail 用）**有** `a.applicant_org_id is None or org is None or != org → 404` 的正确守卫；`get_application`（`:268-274`）调用了它，所以 detail 是 404，子资源却放行——这正是"收口只做了一半"。

**复现**（`/tmp/m2b_ev.sqlite3`，机构 B 用户 `ev_pb` uid=6，读机构 A 的 `app 2`）

```bash
# 前置
cd backend-django
rm -f /tmp/m2b_ev.sqlite3
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate --no-input
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python /tmp/m2b_evidence.py
```

真实输出片段：

```
== F1 跨机构申报子资源 (机构B -> 机构A app2) ==
GET /api/v1/apply/applications/2 -> 404 40401
GET /api/v1/apply/applications/2/documents -> 200 0
GET /api/v1/apply/applications/2/budget -> 200 0
PUT /api/v1/apply/applications/2/sections/background -> 200 0
POST /api/v1/apply/applications/2/budget -> 200 0
doc background now: B跨机构写入
A 建 DRAFT app 3 status DRAFT org 1
PUT /api/v1/apply/applications/3/sections/background -> 200 0
POST /api/v1/apply/applications/3/budget -> 200 0
POST /api/v1/apply/applications/3/submit -> 200 0
A's app after B submit: SUBMITTED | bg: B写A的草稿
```

**影响**：机构 B 可完整读取机构 A 的申报正文（9 节）、预算，还可改写正文/预算，并把 A 的草稿替 A 提交（`SUBMITTED`）。这是跨机构数据泄露 + 跨机构写，属最高级别隔离失效。detail 的 404 只挡住了"标题/状态"等元数据，正文反而全开。

**修法（建议）**
1. 抽一个统一入口，替换上述所有 `_get_app_or_404` 调用：

```python
def _app_scoped_or_404(d, app_id: int) -> PApplication:
    qs = PApplication.objects.filter(id=app_id, tenant_id=d.tenant_id, deleted=0)
    if is_external_only(d):
        org = current_org_id(d)
        if org is None:                     # fail-closed
            raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
        qs = qs.filter(applicant_org_id=org)
    a = qs.first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a
```
   `withdraw`/`terminate` 也必须改用它（否则跨机构 R-MANAGER 之外的未来角色同样可终止）。
2. `list_applications`（`:253-258`）在 `is_external_only` 且 `current_org_id(d) is None` 时直接返回空页/404，不要 `filter(applicant_org_id=None)`（见 C4）。
3. 回归测试必须覆盖 4 个子资源 + submit 的跨机构 404（现有 `tests/test_p_m2b.py:85-113` 只断言了 detail 和 project progress，未覆盖这些入口）。

---

#### C2【本次引入】任务书签署只校验 role 字面值：外部机构可自签 PI+MANAGER 完成立项，并可伪造 signerId

**位置**
- `backend-django/apps/p/api.py:929-960` `sign_task_book`：
  - `:934` 仅校验 `role in ("PI","MANAGER","LEADER")`；
  - `:956-957` **PI 分支不校验 `d.user_id == a.pi_user_id`**，直接把签署人记成 `a.pi_user_id`；
  - `:958-959` MANAGER/LEADER 分支 **不校验调用者角色**，签署人取 `body.get("signer_id") or d.user_id`——请求体可任意指定；
  - `:971-977` 凑齐 PI + (MANAGER|LEADER) 即 `_create_project_from_task_book` 并 `a.status = "EXECUTING"`。
- 策略层：`backend-django/config/casbin/policy.csv:891` `p, R-PARTNER, /api/v1/apply/task-books/*:sign, POST` —— 外部机构本来就需要签 PI，这是设计使然；因此**服务端身份校验是唯一防线**，而它缺失。
- 前端放大：`frontend/src/views/portal/TaskBookView.vue:127-129` 对任何能打开该页的人（路由允许 R-PARTNER/R-MANAGER/R-LEADER，`frontend/src/router/index.ts:59`）都渲染"以 PI 身份签署 / 科研管理签署 / 院所领导签署"三个按钮，没有按当前用户角色/uid 隐藏。外部用户点两下即可完成双签。

**复现**

```
== F3 签署人身份/角色 ==
同机构他人(partner2)签 PI -> 200 recorded [{'role': 'PI', 'signerId': 5, ...}]
partner sign PI -> 200
partner sign MANAGER(signer_id=999999) -> 200 status SIGNED records [
  {'role': 'PI', 'signerId': 5, ...},
  {'role': 'MANAGER', 'signerId': 999999, ...}] project_id 6
project [(6, 'EXECUTING', 1)]
```

补充实测（前一轮 probe，同一 DB）：`R-MANAGER`（并非 PI）签 `role=PI` → 200，签署记录写成 `signerId=5`（伪造成 PI 本人）；`R-STAFF` 签 `role=MANAGER` → 200 并创建项目。

**影响**
- 外部机构单方即可完成"双签"，"PI 与管理端双签"这一立项控制点被完全绕过；
- 同机构的其他 R-PARTNER 可以替 PI 签署（记录成 PI 的 uid），签名不可归责；
- `signerId=999999` 这类不存在的用户被原样写入 `sign_records`，审计链失真；
- 与 C3 组合可给任意状态（含 REJECTED）的申报立项。

**修法（建议）**
1. `role == "PI"`：要求 `is_external_only(d)` 时 `d.user_id == a.pi_user_id`，否则 403；内部代签也只能由 `a.pi_user_id` 本人。
2. `role in ("MANAGER","LEADER")`：要求调用者具备对应角色（`R-MANAGER` / `R-LEADER`）且**不是** `R-PARTNER`；**忽略请求体 `signer_id`**，签署人恒为 `d.user_id`（或由服务端可信映射决定），并在响应中回显。
3. 前端 `TaskBookView.vue` 按 `auth.roles` 与 `currentUser.id` 控制按钮：外部用户只显示"以 PI 身份签署"，且仅当 `currentUser.id === content_snapshot.pi_user_id` 时可用。
4. 测试补：partner 签 MANAGER → 403；partner 签 PI 但 uid ≠ pi_user_id → 403；`signer_id` 被忽略；R-STAFF 签 MANAGER → 403（现有 `tests/test_p_m2b.py:288-300` 只测了非法 role 和重复签）。

---

#### C3【本次引入（legacy 状态机被放大）】签署入口不校验申报状态：REJECTED 的申报仍可双签立项；签后 `:terminate` 又能把申报改回 REJECTED 而项目存活

**位置**
- `backend-django/apps/p/api.py:929-977` `sign_task_book`：加载申报后**没有任何状态前置条件**，`complete` 时无条件 `_create_project_from_task_book` + `tb.status="SIGNED"` + `a.status="EXECUTING"`。
- `backend-django/apps/p/api.py:360-368` `terminate_application`：不调用 `_assert_application_mutable`；`_TERMINABLE`（`:316`）包含 `"SIGNED","EXECUTING"`（该集合自 `e9b6073` 既有），M2-b 让外部申报真正进入 `EXECUTING` 后才变得可触发。
- 对照：冻结守卫 `_assert_application_mutable`（`:1017-1021`）只被 `upsert_budget_line`/`save_application_section`/`submit_application` 三处调用，`withdraw`/`terminate` 未调用。

**复现**

```
== F4 冻结与状态机 ==
post-sign PUT /api/v1/apply/applications/7/sections/background -> 409 任务书已签订，申报内容不可修改
post-sign POST /api/v1/apply/applications/7/budget -> 409 任务书已签订，申报内容不可修改
post-sign POST /api/v1/apply/applications/7/submit -> 409 任务书已签订，申报内容不可修改
terminate SIGNED app -> 200 app status REJECTED project status EXECUTING
terminate PUBLISHED app -> 200 status REJECTED
sign PI on REJECTED app -> 200
sign MANAGER on REJECTED app -> 200
RESULT tb SIGNED project_id 7 | app EXECUTING | project [(7, 'EXECUTING', 8)]
```

（`sign ... on REJECTED app` 的两条均为 HTTP 200；脚本对这两步未打印 envelope，但随后 DB 状态 `tb SIGNED / app EXECUTING / project 7 EXECUTING` 证明请求成功且副作用完整发生。）

**影响**
- **状态机被双向绕过**：先终止再签署 → 已终止申报变成 EXECUTING 并产生项目；先签署再终止 → 申报 REJECTED 但项目仍 EXECUTING，财务/验收/统计将出现"无申报依据的在研项目"或"已终止却仍在研"的不一致数据。
- 这是数据正确性缺陷，不是展示问题；且 `_create_project_from_task_book` 不做任何源状态复核，无法在下游补救。

**修法（建议）**
1. `sign_task_book` 在 `tb` 校验后加：`if a.status not in ("PUBLISHED", "DECIDED"): raise ApiError(409, CODE_CONFLICT, "申报状态不允许立项")`（与 `_TASK_BOOK_GENERATABLE` 保持一致）。
2. `terminate_application` 调用 `_assert_application_mutable(a)`；若业务确需终止已立项申报，则必须显式级联：关闭项目（`EProject.status`）、撤销未完成任务书/验收，并写审计，不能只改 `a.status`。
3. 从 `_TERMINABLE` 移除 `SIGNED`/`EXECUTING`（或单独定义"可终止"集合供"立项后终止"专用流程使用）。
4. 测试补：terminate→sign 409；sign→terminate 409 且项目状态不变（现有 `tests/test_p_m2b.py:248-269` 只测三个冻结入口）。

---

#### C4【本次引入】`applicant_org_id=NULL` 的外部账号在列表里看到院内申报，并可读写院内申报内容

**位置**
- `backend-django/apps/p/api.py:253-258` `list_applications`：外部分支 `qs.filter(applicant_org_id=current_org_id(d))`，**无 None 守卫**；`current_org_id` 为 None 时等价于 `filter(applicant_org_id=None)`，命中的正是院内申报（`PApplication.applicant_org_id` 默认 NULL）。
- `backend-django/apps/p/api.py:721` `list_guide_suggestions`：同一写法（`org_id=current_org_id(d)`），同样存在 None 语义问题（当前 seed 无院内建议，故实测 total=0，属同型隐患）。
- 细节守卫对照：`_partner_app_or_404`（`:326-334`）对 `org is None` 会 404，所以 detail 挡住了；子资源没有（C1），于是列表泄露 id 后可直接按 id 读正文。
- 账号来源：`backend-django/apps/sysadmin/api.py:140-155` `create_user` **完全不接收 `org_id`/`user_source`**，却接受任意 `roles`（`:151-157`）——管理员通过用户管理创建 R-PARTNER 时必然得到 `org_id=NULL`；`assign_role`（`:253-264`）也可给任意用户追加 R-PARTNER。正常的自助注册路径（`apps/sysadmin/api.py:724-725`）会写 `org_id`/`user_source`，但管理端路径不会。

**复现**

```
== F1 NULL-org partner ==
NULL list 200 total 1 ids [1] types ['INTERNAL']
NULL GET internal app1 documents -> 200
NULL PUT internal app1 section -> 200
app1 bg: NULL写院内
```

**影响**：一个"外部机构"账号（org_id 为空）能在"我的申报"里看到院内申报（含 id/标题/状态），并可进一步读取 9 节正文/预算、改写院内申报正文。列表虽只泄露元数据，但配合 C1 的子资源缺口即构成院内申报全文泄露 + 写入。

**修法（建议）**
1. `list_applications`：`if is_external_only(d): org = current_org_id(d); if org is None: return ok(request, {"list": [], "total": 0, ...}); qs = qs.filter(applicant_org_id=org)`；`list_guide_suggestions` 同改。
2. `create_user` 增加 `org_id`/`user_source` 入参：角色含 `R-PARTNER` 时强制 `org_id` 非空且机构存在；禁止 `R-PARTNER` 与内部角色同时授予（同时修 I2）。`assign_role` 同样加一致性校验。
3. 测试补：NULL-org partner 列表 total=0、documents/budget 404；`create_user` 创建 R-PARTNER 不带 org → 400。

---

### Important

#### I1【既有缺口，本次"全流程"依赖它】Django 侧没有把 P 申报推进到 `PUBLISHED/DECIDED` 的入口，真实链路走不到任务书

**位置/证据**
- `backend-django/apps/p/api.py` 中 `PApplication.status` 的写入只有：`DRAFT`（`:296-309` 创建，`status="DRAFT"` 在 `:297`）、`SUBMITTED`（`:516`）、`WITHDRAWN`（`:352`）、`REJECTED`（`:368`）、`EXECUTING`（`:976`）；`PUBLISHED`/`DECIDED` 仅出现在 `_TERMINABLE`、`_TASK_BOOK_GENERATABLE`（`:846`）和任务书校验（`:903`）中。
- 路由清单 `backend-django/config/api.py:110-135` 只有 `POST /apply/applications`（建 DRAFT）、`submit`、`withdraw`、`terminate`、`sections`、`budget`、`documents`，**没有** `:publish` / `:decide` / `approve` 之类入口。`/api/v1/applications/{id}/approve`（`config/api.py:248`）作用于旧 `EApplication`（`apps/project/api.py:1173`），不是 `PApplication`。
- 实际演示数据是把 `PUBLISHED` 直接写库（`backend-django/apps/sysadmin/management/commands/seed_demo.py:1108-1113`），项目也是直接写库（`:1117-1122`）。

**影响**：除 seed 之外，外部 PI 提交申报后没有任何 API 能把它推进到"立项通过"，`generate_task_book` 永远 409（"仅立项通过…"），M2-b 宣称的"全流程"在真实 API 上不可达。计划 Task 5 的前提"立项通过（PUBLISHED/DECIDED）后生成"在 Django 实现中没有生产入口。

**修法**：补一个受限的状态推进端点（如 `POST /apply/applications/{id}:decide {"decision":"PUBLISHED|DECIDED","comment":...}`，仅 R-MANAGER/R-LEADER，带审计与前置状态校验），或在本里程碑明确标注"P 评审流由 Go 侧/上游提供，Django 只负责后半段"，并把 seed 的直写标记为 demo-only。无论哪种，验收测试必须能从 `SUBMITTED` 走到 `EXECUTING` 而不直接改库。

---

#### I2【本次引入】`is_external_only` 用"角色列表精确等于 `["R-PARTNER"]`"判定，多角色账号直接获得内部权限并可伪造 PI/机构

**位置**
- `backend-django/core/org_scope.py:26-32`：`return roles == ["R-PARTNER"]`（顺序敏感、精确匹配）。
- `backend-django/apps/p/api.py:281-309` `create_application`：多角色时 `external=False`，于是 `pi_user_id = body.get("pi_user_id")`、`applicant_org_id = body.get("applicant_org_id")`、`applicant_type="INTERNAL"`。
- 授权路径：`backend-django/apps/sysadmin/api.py:253-264` `assign_role` 可给任意用户追加角色（含内部角色）。

**复现**

```
== F1 多角色 partner ==
MULTI GET A app2 docs -> 200
MULTI create -> 200 pi 999 org 2 type INTERNAL
```

（用户 `ev_pmulti`：`roles=["R-PARTNER","R-STAFF"]`，`org_id=机构B`；创建出的申报 `pi_user_id=999`、`applicant_org_id=2`、`applicant_type=INTERNAL`。）

**影响**：一次管理员"顺手加个 R-STAFF"就会把外部账号提升为内部身份：既可读其他机构申报，又可在请求体里伪造 PI 与申报机构。外部隔离变成"取决于角色列表恰好只有一项"的脆弱假设。

**修法**：`is_external_only` 改为 fail-closed：`return _EXTERNAL_ROLE in roles`（或按 `user_source == "EXTERNAL"` 判定）；同时在 `create_user`/`assign_role` 中禁止 `R-PARTNER` 与内部角色共存。若"多角色"是合法场景，必须显式定义其为内部身份并在 UI/文档说明，且禁止其访问 portal 外部端点。

---

#### I3【既有命名差异，本次新 GET/新前端使其显性化】02-E 的 `EProgressReport`/`EFinalAccept` 是 camelCase，实现与前端是 snake_case，且前端注释把契约说反

**位置**
- 契约：`design/02-项目过程管理-E.openapi.yaml:1108-1115`（`EProgressReport`，字段 `progressPercent`、`reportType`、`contentRich`、`issuesText`、`nextPlan`、`attachmentIds`、`projectId`、`submittedAt`）；`:1217-1230`（`EFinalAccept`，字段 `acceptAt`、`applyAt`、`archiveChecklistId`、`expertIds`、`financeReportId`、`outputSummary`、`projectId`、`attachmentIds`）。
- 实现：`backend-django/apps/project/mappings.py:72-81` 输出 `project_id/period/report_type/content_rich/progress_percent/issues_text/next_plan/attachment_ids/submitted_at`，**无任何 camelCase 别名**；`:123-134` 的 `EFinalAccept` 只有 `templateId`/`approvalDocId` 两个双写别名，其余仍为 snake_case。同文件 `to_api_mid_check`（`:84-95`）已经有双写先例。
- 前端：`frontend/src/views/portal/ProjectReportView.vue:6` 注释写"字段全 snake_case（02-E 契约 EProgressReport / EFinalAccept）"——**与契约相反**；接口定义按 snake_case 消费。
- Mock：`frontend/src/api/mock/overrides/portal.ts:320-355` 也返回 snake_case；且 mock 的 final-accept 是幂等的（返回已存在），真实后端每次新建（见 M4）。

**实测键名对照**（脚本用 `yaml.safe_load` + 真实 ORM 行）

```
TaskBook:        schema 17 props / mapping 17 / missing [] / extra []        → 一致
GuideSuggestion: schema 22 props / mapping 22 / missing [] / extra []        → 一致
EProgressReport: schema 11 props（camelCase）/ mapping 19 keys（snake_case）
                 missing 9: attachmentIds, contentRich, issuesText, nextPlan,
                            period, progressPercent, projectId, reportType, submittedAt
EFinalAccept:    schema 13 props（camelCase）/ mapping 23 keys
                 missing 8: acceptAt, applyAt, archiveChecklistId, attachmentIds,
                            expertIds, financeReportId, outputSummary, projectId
```

**影响**：按契约生成客户端/与 Go 版对齐的调用方会拿到一堆 `undefined`；后端自测与前端联调都用 snake_case 所以"本机通过"，契约实际上失效。M2-b 新增的 `GET /project/{id}/progress-report`（列表）和 `GET /project/{id}/final-accept` 把这一不一致直接暴露给新前端/外部方。

**修法**：二选一并落成测试：
- 推荐：按 02-E 输出 camelCase（可先双写 snake_case 过渡，参照 `to_api_mid_check`），前端改用契约字段；同步修正 `ProjectReportView.vue:6` 的错误注释；
- 或者：把 02-E 这两个 schema 改成 snake_case（需与契约维护方/Go 侧确认，改动面更大）。
加一条契约测试：对每个 schema，`mapping(row).keys()` 必须 ⊇ `schema.properties`（当前 `TaskBook`/`GuideSuggestion` 已可作样板）。

---

#### I4【本次引入】R-LEADER 无法完成双签：handler/路由/导航都支持 LEADER，但 casbin 没有 `:sign` 的 POST 权限

**位置**
- `backend-django/config/casbin/policy.csv:877-903` M2-b 块里，R-LEADER **没有** `task-books/*:sign POST`；R-LEADER 只有既有的 `/api/v1/apply/* GET`（`:21`）和 `PUT`（`:22`）。
- 但：`backend-django/apps/p/api.py:934` 接受 `LEADER`；`frontend/src/router/index.ts:59` 把 `/portal/task-book` 开放给 R-LEADER；`frontend/src/views/portal/TaskBookView.vue:129` 渲染"院所领导签署"按钮。
- 实际生效的是"谁有 `/apply/* POST`"：`policy.csv:19` 的 R-MANAGER 宽行让 R-MANAGER 能签；`policy.csv:15-17` 的 R-STAFF 宽行让 **R-STAFF 也能签**（C2 的另一入口）。

**实测**

```
R-LEADER POST /apply/task-books/1:sign -> False
R-STAFF  POST /apply/task-books/1:sign -> True
R-MANAGER POST /apply/task-books/1:sign -> True
```

**影响**：计划 Task 5 明确"PI + (MANAGER|LEADER)"，但 LEADER 点击签署必然 403；同时 R-STAFF 反而能签，权限矩阵与业务语义错位。

**修法**：`policy.csv` 增加 `p, R-LEADER, /api/v1/apply/task-books/*:sign, POST`；服务端在 C2 修复时按 `R-MANAGER`/`R-LEADER` 校验角色，R-STAFF 一律 403；补 RBAC 用例覆盖四种角色 × PI/MANAGER/LEADER。

---

### Minor

#### M1【本次引入，潜在】`keyMatch2` 的 `:sign` 不是字面量，`/task-books/*:sign` 同时匹配 `/task-books/{id}`

**位置**：`backend-django/config/casbin/policy.csv:891`；`backend-django/config/casbin/model.conf` 使用 `keyMatch2`。casbin 的 `key_match2` 会把 `*:sign` 中的 `*` 换成 `.*` 后，再用 `KEY_MATCH2_PATTERN` 把 `:sign` 当作命名参数替换为 `[^/]+`，因此：

```
R-PARTNER POST /api/v1/apply/task-books/1      -> True   # 无冒号也匹配
R-PARTNER POST /api/v1/apply/task-books/1:sign -> True
```

**影响**：当前没有 `POST /apply/task-books/{id}` 路由，所以不可利用；但未来若新增"更新任务书"的 POST，外部机构会凭空获得权限。

**修法**：改用 `keyMatch3` 并把该行写成 `/api/v1/apply/task-books/{id}:sign`（keyMatch3 只替换 `{...}`，`:sign` 保持字面量），或改 `regexMatch`；并加一条"`/task-books/1` POST 应 False"的回归断言。

#### M2【本次引入】`PTaskBook.status` 永远不会变成 `EXECUTING`，枚举里的状态是死状态

`backend-django/apps/p/models.py:140-141` 注释 `DRAFT/SIGNED/EXECUTING`；`sign_task_book` 只在 `:941` 把 `SIGNED/EXECUTING` 当"已签"拦截、`:973` 写 `SIGNED`，全仓没有写入 `EXECUTING` 的路径（`grep -n 'tb.status' apps/p/api.py` 仅此两处）。建议删除该枚举值，或在生效日期到达时由定时任务迁移，避免消费方按三态编码。

#### M3【本次引入】通知类型占位符 `"TODO"` 落库，通知中心无法归类

`backend-django/apps/p/api.py:773`（指南建议）、`:915`（任务书待核对）、`apps/project/api.py:300`（阶段汇报）、`:738`（结题验收）均以 `typ="TODO"` 创建 `SysNotification`。`_notify` 不校验类型（`apps/project/api.py:1266-1270`），所以会静默写入未知类型，前端按类型渲染/筛选时表现异常。建议改为 `GUIDE_SUGGESTION`/`TASK_BOOK`/`PROGRESS_REPORT`/`FINAL_ACCEPT` 等稳定枚举，并补一条断言。

#### M4【本次引入，契约已提供机制】重复提交验收申请：不带 `Idempotency-Key` 时后端每次都新建，mock 却幂等

**复现**

```
POST final-accept 1 -> 200 id 1
POST final-accept 2 -> 200 id 2
final accepts [(1, 'APPLIED'), (2, 'APPLIED')]
```

契约 `design/02-项目过程管理-E.openapi.yaml:397` 声明了 `IdempotencyKey`，`core/idempotency.py:17` 也确实只在带该头时生效；前端 `ProjectReportView.vue` 的提交没有带 `Idempotency-Key`，而 mock（`frontend/src/api/mock/overrides/portal.ts:320-355`）是"已存在则返回旧的"，联调时会掩盖重复申请。建议前端提交时生成并复用 key（同一草稿重试不变），后端可另加"同项目仅允许一条未结案验收"的业务约束（若产品如此定义）。

#### M5【本次引入（计划明确要求，但与语义冲突）】seed 在任务书还是 DRAFT 时就预创建了项目，掩盖了"双签即立项"

实测 `tb [(1, 'DRAFT', 2, 4)]` 同时 `ext project [(4, 'ACTIVE', 2, 1)]`；计划 `docs/superpowers/plans/2026-11-19-m2b-open-topic-fullflow.md:732` 明确要求演示链路含"任务书（DRAFT，只有 PI 已签）→ 一个 E_PROJECT(ext_org_id=机构A) + 1 条汇报"。这与 Task 5"双签即立项"相矛盾：演示账号在签署前就已有项目，也掩盖了 C2（外部自签即可"再"建一个项目）。建议 demo 改为"任务书 DRAFT 时无项目，双签后项目出现"，或在 seed 注释/README 明示这是"历史遗留数据"而非流程结果。

#### M6【流程】计划文件与评审报告目录均未纳入版本库

`git status --porcelain` 显示 `?? docs/superpowers/plans/2026-11-19-m2b-open-topic-fullflow.md` 与 `?? docs/superpowers/reports/`（内含 m1d/m2a 等此前评审报告）。这是仓库既有习惯（非本次引入），但意味着"M2-b 的计划"本身不在提交历史里，无法与 9 个 commit 建立可审计对应。建议把当前计划随里程碑一起提交（评审报告是否入库由流程决定）。

#### M7【本次引入，信息完整性】`EProject.ext_org_id` 只进 DB/DDL，不进 API 形状

`backend-django/apps/project/mappings.py:23-34` `to_api_project` 无 `ext_org_id`；02-E 的 `EProject` schema 也未加该字段。隔离逻辑依赖它（`_partner_project_or_404`），但管理端/排障时看不到项目归属机构，只能反查申报。建议在 `to_api_project` 与 02-E 补 `ext_org_id`（外部机构可读，内部只读），并同步契约副本。

---

### 既有问题（legacy）与本轮关系

| 编号 | 问题 | 来源 | 是否被本次放大 |
|---|---|---|---|
| L1 | `_TERMINABLE` 含 `SIGNED/EXECUTING`，`terminate/withdraw` 无冻结校验 | `e9b6073`（2026-10-17） | **是**：M2-b 让外部申报真正进入 `EXECUTING`，C3 由此可触发；本次应一并收口 |
| L2 | P 申报评审/立项通过的状态推进未移植到 Django | Phase 0–4 重写期 | **是**：M2-b 的"全流程"以 `PUBLISHED` 为前提，但 Django 没有生产入口（I1） |
| L3 | E 域 API 形状 snake_case 与 02-E camelCase 契约不一致 | 既有 `apps/project/mappings.py` | **是**：M2-b 新增 GET list/final-accept 与新前端，使不一致进入新链路（I3） |
| L4 | `sync_permissions_from_csv` 只增不删（`apps/sysadmin/permissions.py` 全为 `get_or_create`） | 既有设计 | 否；但 `0012` 依赖它，未来删改 `policy.csv` 行不会回收 DB 权限，建议单独治理 |
| L5 | `create_user` 不写 `org_id/user_source`，却可授 `R-PARTNER` | M2-a 遗留（`apps/sysadmin/api.py:140-155`） | **是**：直接为 C4 制造 NULL-org 外部账号 |

---

## 4. 提交卫生

### 4.1 commit 列表（9 条，风格一致）

```
2c8d982 chore(seed+readme): M2-b 开放课题全流程演示数据 + 测试数更新为实测 396
bf3c667 feat(fe): 门户申报/指南建议/任务书签订/汇报验收 + 管理端建议审核——契约驱动 mock 对齐 M2-b
5de8ac0 feat(project): 验收结题外部化——机构内申请与查看、结题通知与邮件（C2）
6a75e91 feat(project): 阶段汇报外部化——机构内提交与查看、管理端通知（C2）
9c1415f feat(p): 任务书生成/电子签章签订——双签即立项建项并回填项目（C2 立项签约）
010d151 feat(p): 申报主体扩为外部机构——PI/机构强制归本机构、机构内可见（C2）
404e30b feat(p): 指南建议端点——外部机构提交/机构隔离/管理端采纳转指南草稿与驳回（C2）
ca5d2e9 feat(rbac): M2-b 外部机构业务策略域 + 申报/项目机构租户隔离收口（C2）
c720be8 feat(p+project): M2-b 机构化申报/指南建议/任务书模型与项目外部归属列、迁移 0003+0006（C2 表结构）
```

- 无 `fixup!`/`squash!`/`WIP` 残留；无 merge commit；每条对应计划中的一个 Task，Task 1–9 齐全。
- `git diff --stat 42eae59..2c8d982`：31 files changed, 2931 insertions(+), 31 deletions(-)；改动范围 = `backend-django`（p/project/sysadmin/config/core/tests）、`design`（00-common、01-P、02-E 的 DDL/OpenAPI）、`frontend`（5 视图 + 路由 + mock + auth）、`README`、`seed_demo`。**没有** `design/` 之外的意外目录，没有 `git add -A` 带入的构建产物。
- `git diff --check` 干净。

### 4.2 工作区残留（`git status --porcelain`，24 项）

```
 M docs/.DS_Store
 D docs/IMG_1355.jpeg … docs/spm9.png（7 个图片文件）
?? backend-django/uv.lock
?? docs/img/
?? docs/reports/.DS_Store
?? docs/reports/2026-11-12-conow-alignment-roadmap.md
?? docs/superpowers/plans/2026-11-12-m1a…、2026-11-17-m1b…、2026-11-17-m1c…
?? docs/superpowers/plans/2026-11-18-m1d…、2026-11-18-m2a…、2026-11-19-m2b-open-topic-fullflow.md
?? docs/superpowers/reports/
?? dump.rdb
?? frontend/pnpm-lock.yaml、frontend/pnpm-workspace.yaml
?? scripts/ocr_jxa.js、scripts/ocr_screenshots.swift
```

分类判断：
- **BASE 前既有**：docs 图片移动/删除、`docs/img/`、`docs/reports/*`、`dump.rdb`、`scripts/ocr_*`、`frontend/pnpm-*`、`backend-django/uv.lock`（这些在 `42eae59` 之前就存在或属于本地环境产物）；
- **本次相关但未提交**：`docs/superpowers/plans/2026-11-19-m2b-open-topic-fullflow.md`、本报告所在 `docs/superpowers/reports/`——属流程性遗漏（M6），不是代码遗漏；`git status` 中**没有** M2-b 的 backend/frontend/design 代码残留，说明 9 个 commit 已覆盖全部实现。

结论：提交卫生**通过**，仅计划文件未入库（M6，建议补提交）。

---

## 5. 复现脚本（关键片段）

以下脚本在 `/tmp/m2b_ev.sqlite3` 上复现 C1–C4、Focus 2/5 与重复验收；完整版即 `/tmp/m2b_evidence.py`（本次评审实际执行）。关键夹具：

```python
import os, sys, json, django
sys.path.insert(0, os.getcwd()); django.setup()
from django.test import Client
from core.auth.jwt_util import gen_token
from core.auth.casbin_util import get_enforcer
from apps.sysadmin.models import SysUser, SysUserRole, SysRole, SysPartnerOrg
from apps.p.models import PApplication, PApplicationDoc, PTaskBook
from apps.project.models import EProject, EFinalAccept

def H(uid, roles): return {"HTTP_AUTHORIZATION": "Bearer " + gen_token(uid, 1, 0, "INTERNAL", roles)}
c = Client()
orgB = SysPartnerOrg.objects.create(code="EV-ORG-B", tenant_id=1, name="机构B", credit_code="91310000MA1K3XY99B",
    org_type="UNIVERSITY", contact_name="B", contact_phone="13800000001", contact_email="b@example.com",
    status="APPROVED", creator_id=1)
def mkuser(name, org_id, roles):
    u = SysUser.objects.create(username=name, real_name=name, tenant_id=1, org_id=org_id,
        user_source="EXTERNAL" if org_id else "INTERNAL", creator_id=1, status="ACTIVE")
    for rc in roles:
        SysUserRole.objects.create(user_id=u.id, role_id=SysRole.objects.get(code=rc, tenant_id=1).id, tenant_id=1)
    return u
partner = SysUser.objects.get(username="partner")          # seed 的机构 A 用户
pb     = mkuser("ev_pb", orgB.id, ["R-PARTNER"])            # 机构 B
pnull  = mkuser("ev_pnull", None, ["R-PARTNER"])            # NULL 机构
pmulti = mkuser("ev_pmulti", orgB.id, ["R-PARTNER", "R-STAFF"])
mgr    = mkuser("ev_mgr", None, ["R-MANAGER"])
```

C1（跨机构子资源）：

```python
for m, p, body in [
    ("get",  "/api/v1/apply/applications/2", None),
    ("get",  "/api/v1/apply/applications/2/documents", None),
    ("get",  "/api/v1/apply/applications/2/budget", None),
    ("put",  "/api/v1/apply/applications/2/sections/background", {"content_rich": "B跨机构写入"}),
    ("post", "/api/v1/apply/applications/2/budget", {"subject_code": "7201", "amount": "1.00"}),
]:
    r = getattr(c, m)(p, data=json.dumps(body) if body else None,
                      content_type="application/json", **H(pb.id, ["R-PARTNER"]))
    print(m.upper(), p, "->", r.status_code, r.json().get("code"))
# 实测：detail 404；documents/budget 200；PUT/POST 200
```

C2（自签双签 + 伪造 signerId）：

```python
# 建 DRAFT → submit → 直接改库置 PUBLISHED（I1：无 API 可达），再由 R-MANAGER 生成任务书
aid = 0
r = c.post("/api/v1/apply/applications", data=json.dumps({"title": "自签双签", "project_type": "开放课题"}),
           content_type="application/json", **H(partner.id, ["R-PARTNER"]))
aid = r.json()["data"]["id"]
c.post(f"/api/v1/apply/applications/{aid}/submit", data="{}", content_type="application/json", **H(partner.id, ["R-PARTNER"]))
PApplication.objects.filter(id=aid).update(status="PUBLISHED")
tb = c.post("/api/v1/apply/task-books", data=json.dumps({"application_id": aid}),
            content_type="application/json", **H(mgr.id, ["R-MANAGER"])).json()["data"]
print(c.post(f"/api/v1/apply/task-books/{tb['id']}:sign", data=json.dumps({"role": "PI"}),
             content_type="application/json", **H(partner.id, ["R-PARTNER"])).status_code)   # 200
r = c.post(f"/api/v1/apply/task-books/{tb['id']}:sign",
           data=json.dumps({"role": "MANAGER", "signer_id": 999999}),
           content_type="application/json", **H(partner.id, ["R-PARTNER"]))
print(r.status_code, r.json()["data"]["status"], r.json()["data"]["sign_records"])
# 实测：200 SIGNED，MANAGER 的 signerId=999999，项目已创建
```

C3（签后终止 / 终止后签）：

```python
# 签后终止
r = c.post(f"/api/v1/apply/applications/{aid}:terminate", data=json.dumps({"reason": "签后终止"}),
           content_type="application/json", **H(mgr.id, ["R-MANAGER"]))
print(r.status_code, PApplication.objects.get(id=aid).status,
      EProject.objects.get(application_id=aid).status)     # 200 REJECTED EXECUTING

# 终止后签：新建 → 置 PUBLISHED → 生成 tb → terminate → 双签
# 实测 terminate 200 REJECTED；sign PI 200；sign MANAGER 200；
#      tb SIGNED / project_id 7 / app EXECUTING / project EXECUTING
```

C4（NULL-org）：

```python
r = c.get("/api/v1/apply/applications", **H(pnull.id, ["R-PARTNER"]))
print(r.json()["data"]["total"], [x["id"] for x in r.json()["data"]["list"]])   # 1 [1]
print(c.get("/api/v1/apply/applications/1/documents", **H(pnull.id, ["R-PARTNER"])).status_code)  # 200
```

Focus 5（casbin）：

```python
e = get_enforcer()
for path, method in [("/api/v1/project/1/board", "GET"), ("/api/v1/project/eval-templates", "GET"),
                     ("/api/v1/project/1", "GET"), ("/api/v1/project/1/tasks", "GET"),
                     ("/api/v1/users", "GET"), ("/api/v1/funding/expenses", "GET"),
                     ("/api/v1/partner-orgs", "GET"), ("/api/v1/x/projects", "GET")]:
    print(path, e.enforce("R-PARTNER", path, method))
# 实测全部 False（安全）
```

---

## 6. 合并前必须修

| 编号 | 必修理由 | 最小修复 |
|---|---|---|
| **C1** | 跨机构读/写/提交申报正文与预算 | 统一 `_app_scoped_or_404` 替换 5 个入口 + 列表 None fail-closed + 跨机构回归测试 |
| **C2** | 外部单方完成双签、伪造签署人 | PI 校验 `d.user_id == a.pi_user_id`；MANAGER/LEADER 校验角色、忽略 `signer_id`；前端按角色/uid 隐藏按钮 |
| **C3** | REJECTED 申报可立项；签后终止造成数据不一致 | `sign_task_book` 前置状态校验；`terminate` 接冻结守卫或级联项目状态；补状态机测试 |
| **C4** | NULL-org 外部账号可读/写院内申报 | 列表 None fail-closed；`create_user`/`assign_role` 强制 R-PARTNER 必须带 org 且不得与内部角色共存 |

建议同批修复（低成本、直接影响可验收性）：
- **I4**：给 R-LEADER 补 `task-books/*:sign POST`，否则"院所领导签署"按钮 100% 403；
- **I2**：`is_external_only` 改为包含式（`R-PARTNER in roles`）或禁止角色混授；
- **I3**：至少先把 `ProjectReportView.vue:6` 的错误注释改掉，并决定 snake/camel 的唯一口径；
- **I1**：若本里程碑要宣称"全流程"，补 P 申报 `:decide` 入口；否则在 README/验收说明中明确"P 评审流不在本里程碑"。

---

## 7. 评审方法附录（命令清单）

```bash
# 1) 套件
cd backend-django && .venv/bin/python -m pytest -q
cd backend-django && .venv/bin/python manage.py makemigrations --check
cd frontend && ./node_modules/.bin/vue-tsc --noEmit

# 2) 契约双份 + 解析
cmp design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml
cmp design/02-项目过程管理-E.openapi.yaml frontend/src/api/schema/02-项目过程管理-E.openapi.yaml
backend-django/.venv/bin/python -c "import yaml; yaml.safe_load(open('design/01-项目申报与立项-P.openapi.yaml')); yaml.safe_load(open('design/02-项目过程管理-E.openapi.yaml')); print('yaml ok')"

# 3) 空库 + seed（可重复）
cd backend-django
rm -f /tmp/m2b_ev.sqlite3
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate --no-input
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo   # 第二遍全 0

# 4) 越权/状态机实测
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python /tmp/m2b_evidence.py

# 5) 迁移真进 DB / casbin 实际匹配
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2b_ev.sqlite3 DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python -c "
import django; django.setup()
from apps.sysadmin.models import SysRole, SysRolePermission
r=SysRole.objects.get(code='R-PARTNER', tenant_id=1)
print('R-PARTNER perms:', SysRolePermission.objects.filter(role=r).count())"     # 28
```

---

## 8. 最终裁定

**VERDICT: `REQUEST_CHANGES`**

- 合并前必须修：**C1、C2、C3、C4**。
- 五项 Review Focus：**1 FAIL / 2 PASS / 3 PASS(纯外部)+FAIL(多角色) / 4 FAIL / 5 PASS**。
- 最值得先修的三条（按风险×可复现性排序）：
  1. **C2 任务书签署身份/角色校验**——外部机构自签双签即可立项，且签署人可伪造，直接击穿本里程碑的业务控制点；
  2. **C1 申报子资源机构隔离**——跨机构读/写/提交申报正文与预算，数据泄露面最大；
  3. **C3 签署/终止状态机**——REJECTED 申报可立项、签后终止留下"在研项目无申报"，数据正确性问题会污染后续决算/验收。
  （C4 紧随其后，修复成本极低，建议与 C1 同一个 PR 完成。）
