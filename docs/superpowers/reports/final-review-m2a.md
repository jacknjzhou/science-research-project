# M2-a 终审评审报告（外部机构注册与门户骨架）

- 期次：M2-a（C1 外部机构注册 → 资质审核 → 门户骨架；C5 邮件通道最小实现）
- 仓库：`/Users/jacky/works/science-research-project`，分支 `develop`
- 评审范围：`BASE=72ee658` … `HEAD=f5cb8e8`，共 9 个提交、29 个文件（+3053 / −10）
- 计划：`docs/superpowers/plans/2026-11-18-m2a-partner-onboarding-portal.md`
- 台账：`.superpowers/sdd/2026-11-18-m2a-partner-onboarding-portal/progress.md`
- 评审方式：只读 HEAD 代码 + 独立运行验证 + 临时 sqlite 文件库运行时探针。除本报告外未修改任何源文件。

> 环境声明：评审时工作区存在未提交改动（`frontend/src/views/RegisterView.vue`、
> `frontend/src/api/mock/overrides/portal.ts` 以及若干 `docs/` 删除/未跟踪文件）。
> 后端的 pytest 与种子验证不受影响（后端无未提交改动）；**vue-tsc 的结论分别在
> “含未提交修复的工作区”和“`git archive HEAD` 的纯净副本”上各跑了一次**，两者均为 exit 0。
> 但请注意：HEAD 提交本身的前端注册页与后端契约键不一致（见 C-1），类型检查通过 ≠ 功能可用。

---

## 一、结论

**REQUEST_CHANGES（修后可合并）**

- 阻断项 2 个（Critical）：HEAD 的注册页字段与后端/契约完全错位，C1 自助注册 100% 失败；
  R-PARTNER 指南授权可读到 DRAFT 指南并跨租户读取他机构指南，破坏“tenant 隔离不破”硬约束。
- 需修项 6 个（Important）：审核状态机可把已通过机构改成驳回但账号仍 ACTIVE 且保留 R-PARTNER；
  驳回不发邮件（被锁账号无法登录看站内信，理由不可达）；R-PARTNER 角色缺失时审核静默成功；
  公开注册的 `tenant_id` 由客户端控制可跨租户写入；DDL 唯一索引与迁移的非唯一索引不一致；
  前端注册表单未要求联系电话/邮箱而后端必填（必然 400）。
- Minor 9 个，不阻断合并。

2 个 Critical 均可在小范围内修复（提交已存在的注册页修复 + 给指南详情补 tenant 过滤/收敛角色授权），
修复后需重跑本节“实测数字”中的全部命令并补充回归测试，故 merge-readiness = **修后可合并**。

---

## 二、必查项逐条结论

### 1. 认证与账号 —— PASS

| 检查点 | 结论 | 证据 |
|---|---|---|
| 注册建号 LOCKED，审核通过才 ACTIVE | PASS | `backend-django/apps/sysadmin/api.py:690`（`status="LOCKED"`，注释“未审核：既有登录逻辑对非 ACTIVE 一律 40302”）；`:767`（仅 APPROVE 分支置 `user.status = "ACTIVE"`） |
| 弱口令被拒 | PASS | `apps/sysadmin/api.py:616-623`（`len>=8`、非纯数字、至少含一个字母）；测试 `tests/test_sysadmin_partner.py:118-129`（纯数字/过短/缺邮箱/短信用代码/枚举外均 400/40001） |
| 重复用户名/信用代码被拒且不泄露枚举 | PASS | `apps/sysadmin/api.py:658-666` 两条 `exists()` 均抛 `ApiError(409, CODE_CONFLICT, "机构或用户名已注册")`，文案完全相同，无法区分命中哪个键 |
| 既有登录分支对 LOCKED 返回 40302 | PASS | `backend-django/core/auth/api.py:47-48`：`if user.status != "ACTIVE": raise ApiError(403, CODE_ACCOUNT_DISABLED, "账号已停用或锁定")`；`core/httpx.py` 中 `CODE_ACCOUNT_DISABLED=40302`；测试 `tests/test_sysadmin_partner.py:132` 断言 40302 |
| 注册端点确实无 auth | PASS | `backend-django/config/api.py:16` `api.post("/portal/register", tags=["portal"])` 不在受保护组；契约 `design/12-用户与权限-U.openapi.yaml:765` 显式 `security: []`；运行时无 token POST 返回 200 |

补充：密码哈希为 bcrypt（`$2` 前缀，`tests/test_sysadmin_partner.py:105`），注册体不接受 `role`/`status`/`security_level` 等提权字段（handler 按白名单逐字段读取）。

### 2. 授权（Casbin 最小集 / 迁移生效 / 负面断言） —— PASS（附 C-2 关联说明）

| 检查点 | 结论 | 证据 |
|---|---|---|
| R-PARTNER 只给门户+公开面 | PASS（行集本身） | `backend-django/config/casbin/policy.csv:864-873` 共 10 行：`/auth/me` GET、`/portal/org` GET+PUT、`/portal/home` GET、`/apply/guidelines` GET、`/apply/guidelines/*` GET、`/notifications` GET、`/notifications/*` POST、`/notifications/read-all` POST、`/dicts/*` GET；无任何 `/x/*`、`/confsec/*`、`/admin/*` |
| R-MANAGER 只给审核台 | PASS | `policy.csv:875-876`：`/partner-orgs` GET、`/partner-orgs/*/audit` POST。R-ADMIN 经 `policy.csv:6-9` 的 `/api/v1/*` 全方法通配可达审核台，符合“管理员兜底”设计 |
| DB 策略能生效（有 resync 迁移） | PASS | `apps/sysadmin/migrations/0009_resync_permissions.py` 与 `0010_resync_permissions.py` 均为 `RunPython(sync_permissions_from_csv(settings.CASBIN_POLICY_PATH))`，依赖链 `0008→0009→0010`；同步逻辑 `apps/sysadmin/permissions.py:27-80`（`get_or_create` 幂等） |
| `tests/test_rbac.py` 有真实负面断言 | PASS | `tests/test_rbac.py:473-493` 断言 12 条期望行是子集；`:496-509` 对 R-PARTNER 断言不存在 `/api/v1/x*`、`/api/v1/confsec*`、`/api/v1/admin*` 行（非恒真：用真实 `_policy_p_rows()` 过滤）；`:511-518` 断言指南详情 GET 被 keyMatch2 覆盖、POST 未被覆盖 |

关联说明：行集虽“最小”，但 `policy.csv:868-869` 把 `/apply/guidelines` 与 `/apply/guidelines/*` 授给了
R-PARTNER，而这两个 handler 没有 tenant/status 约束，构成**可利用的越权面**（C-2）。因此“策略行数最小”
成立，“授权实际安全”不成立，整改见 C-2。

### 3. 机构隔离 —— FAIL（C-2）；门户/审核台端点本身 PASS

| 检查点 | 结论 | 证据 |
|---|---|---|
| 门户只按登录用户 org_id 取数 | PASS | `_my_partner_org` `apps/sysadmin/api.py:596-601`（先查 `SysUser(tenant_id, id, deleted=0)` 取 `org_id`，再走 `_partner_org_or_404`）；`portal_org` `:798-804`、`portal_home` `:838-886` 均无路径/查询参数可指定别家机构 |
| 无法越权读别家机构（门户） | PASS | 门户端点不接收 org id，选机构完全由 token 的 user→org_id 决定；测试 `tests/test_sysadmin_partner.py:256-263` 两机构各自只看到自己 |
| PUT 只改四个联系字段 | PASS | `apps/sysadmin/api.py:804` `_PORTAL_EDITABLE = ("contact_name","contact_phone","contact_email","address")`，`:807-836` 仅白名单字段入 `update_fields`；测试 `:243-253` 传 `name/status/credit_code` 均不变 |
| 审核端机构查询带 tenant | PASS | `apps/sysadmin/api.py:587-593` `SysPartnerOrg.objects.filter(id=..., tenant_id=..., deleted=0)`，缺失即 404；运行时 tenant-1 管理员审核 tenant-2 机构 → 404，tenant-1 列表也不含 tenant-2 |
| **tenant 隔离整体不破** | **FAIL** | R-PARTNER 可经 `/api/v1/apply/guidelines/{id}` 读取**他租户**指南：`apps/p/api.py:74-78` 只按 `id + deleted=0` 查询，**无 `tenant_id` 过滤**；`policy.csv:869` 使该路径对 R-PARTNER 可达。实测 tenant-1 partner 读取 tenant-2 的 DRAFT 指南 id=3 → 200，正文为“租户2未公开指南” |

同一条越权面还包括：`apps/p/api.py:58-71` 的列表接口对 `status` 不做默认限制，R-PARTNER 传
`?status=DRAFT` 或干脆不传即可看到 DRAFT（实测返回 `[DRAFT, PUBLISHED]`）。这违反“门户信息面收窄：
DRAFT/CLOSED 不得出现”的验收口径（至少 DRAFT 部分已被实测击穿）；CLOSED 是否允许外部可见需产品确认，
`GuideView.vue:162-164` 目前是主动请求 CLOSED 的。

### 4. 幂等与状态机 —— FAIL（I-1；其余 PASS）

| 检查点 | 结论 | 证据 |
|---|---|---|
| APPROVE 重复调用幂等 | PASS | `apps/sysadmin/api.py:743-745`：已是 APPROVED 直接返回原对象，不重复授权/通知；测试 `tests/test_sysadmin_partner.py:169` |
| REJECT 必填理由 | PASS | `apps/sysadmin/api.py:747` `_str_field(body, "reason", "驳回理由", max_len=512)`（required 默认 True）；测试 `:171` 先断言缺 reason → 400 |
| APPROVE 只授一次 R-PARTNER（get_or_create） | PASS | `apps/sysadmin/api.py:771-775` `SysUserRole.objects.get_or_create(user_id, role_id, defaults={"tenant_id"})`；测试 `:163` 二次通过后角色数仍为 1 |
| REJECTED 后账号仍 LOCKED | PASS（仅正常 PENDING→REJECTED 路径） | REJECT 分支不动 `user.status`；测试 `:179-187` 断言仍 LOCKED |
| 审核状态机完备（任意状态可再审） | **FAIL** | `apps/sysadmin/api.py:743-757` 只在 APPROVE 且已 APPROVED、REJECT 且已 REJECTED 时短路；**APPROVED → REJECT 没有守卫**：`:751-757` 直接把机构改成 REJECTED，而 `:763-771` 的解锁/授权逻辑只在 APPROVE 分支执行，账号保持 ACTIVE 且继续持有 R-PARTNER。运行时实测：register→APPROVE（user ACTIVE + R-PARTNER）→REJECT 同一机构 → 200，`org.status=REJECTED`，账号仍 ACTIVE、角色仍在、仍可登门户 |

### 5. 通知不阻断 —— PASS（I-2 属“该发未发”，不属“阻断”）

| 检查点 | 结论 | 证据 |
|---|---|---|
| `send_mail_best_effort` 地址非法/异常返回 False 且不抛 | PASS | `backend-django/apps/notify/email.py`：`_valid_address` 拒绝空/无 `@`/含空格；`send_mail_best_effort` 全函数 `try/except Exception` → `logger.warning` + `return False`，无 re-raise；`tests/test_notify_email.py` 覆盖无效地址与后端抛异常两种情形 |
| 注册通知失败不影响落库 | PASS | `apps/sysadmin/api.py:697-704` 在事务提交后调用 `_notify_role_inapp`，后者 `:561-584` 整体 `try/except Exception: return 0` |
| 审核通知失败不影响审核 | PASS | `apps/sysadmin/api.py:778-793`：通知在 `with transaction.atomic()` 之外，整段 `try/except Exception: pass`；`notify_inapp` 与 `send_mail_best_effort` 各自也有保护 |
| 驳回也发邮件（计划 Task 5 要求） | **不符** | `apps/sysadmin/api.py:790-792` 驳回分支只 `notify_inapp`，没有 `send_mail_best_effort`；而账号处于 LOCKED 无法登录，站内信实际不可达（见 I-2） |

> 已裁定事项“`sys_notification` 不补 DDL”不重开；`channel` 字段仅 ORM 使用，落库在 sqlite/PG 均由
> Django 建表承载，本期不涉及手写 DDL。

### 6. 契约一致 —— PASS（契约↔后端）；前端 RegisterView 违约另见 C-1

| 检查点 | 结论 | 证据 |
|---|---|---|
| 6 路径 / 5 schema 与 handler 请求响应键一致 | PASS | 契约 `design/12-用户与权限-U.openapi.yaml:760`（register）、`:784`（org GET）/`:795`（org PUT）、`:824`（home）、`:841`（partner-orgs）、`:876`（audit）；schema `:939` PartnerOrg、`:971` RegisterRequest（required 9 键）、`:989` UpdateRequest（4 键）、`:997` AuditRequest（required action）、`:1005` PortalHome。`apps/sysadmin/mappings.py:93-116` 输出键与 `:939` 完全同名（snake_case，时间经 `fmt_ts`） |
| 错误码 400/403/404/409 对齐 | PASS（实现）；文档缺 403 声明 | handler：`:635` 40001、`:658` 40901、`:587` 40401、casbin 403；契约 register 声明 200/400/409、org GET 200/403/404、org PUT 200/400/404、home 200/404、list 200/403、audit 200/400/404。**PUT/home/audit 未声明 403**，而越权时 casbin 会返回 403（Minor M-3） |
| 两份 yaml 副本一致 | PASS | `cmp design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml` → exit 0 |
| 前端三视图路径/键与契约同形 | **FAIL** | `PortalView.vue`（`/portal/home`、PUT 4 键）与 `PartnerOrgsView.vue`（`/partner-orgs`、`{action, reason}`）同形；`RegisterView.vue` HEAD 用 `name`/`short_name` 而非 `org_name`/`real_name`（C-1） |

### 7. 前端 —— FAIL（C-1、I-6）；其余 PASS

| 检查点 | 结论 | 证据 |
|---|---|---|
| RegisterView 覆盖契约 required 9 键 | **FAIL** | `frontend/src/views/RegisterView.vue`（HEAD，经 `git show`）：接口字段 `name:9`、`short_name:17`；表单 `v-model="form.name"`（`:91`）、`form.short_name`（`:100`）；**没有 `org_name`，也没有 `real_name`**。后端必填 `org_name`（`apps/sysadmin/api.py:634`）、`real_name`（`:651`）→ HEAD 页面提交必 400（实测 `{"code":40001,"message":"机构名称不能为空"}`） |
| 注册按钮必填校验覆盖 required | **FAIL** | `RegisterView.vue:47-49` 的 `ready` 只要求 org_name(原 name)/credit_code/contact_name/username/password（工作区修复版另加 real_name），**不含 `contact_phone`/`contact_email`**；模板 `:113-119` 电话标“选填”、邮箱无 `*`，而后端 `:644-646` 两者均必填。用户可填出必 400 的表单（I-6） |
| PortalView 只渲染后端数据（无前端过滤冒充权限） | PASS | `PortalView.vue:58` 仅 `GET /portal/home`；`:68` 表单 4 键；`:82` `PUT /portal/org {...form}`；模板直接渲染 `home.org/guidelines/announcements`，无按角色/状态的前端过滤 |
| PartnerOrgsView 审核动作传 `{action, reason}` | PASS | `frontend/src/views/admin/PartnerOrgsView.vue:89` `{action:'REJECT', reason}`、`:104` `{action:'APPROVE'}`；`:81-84` 驳回前端已要求理由 |
| router 三条路由 meta 正确 | PASS | `frontend/src/router/index.ts:53-55`：`/register` `public:true`；`/portal` `roles:['R-PARTNER']`；`/admin/partner-orgs` `roles:['R-MANAGER','R-ADMIN']`；`App.vue:201/205` 导航角色一致，`:264` 登录浮层挂 `#/register` |
| mock 镜像 policy.csv 与 seed PAGE_GRANTS | PASS（1 处 Minor） | `frontend/src/api/mock/overrides/auth.ts:79-87` R-PARTNER 10 条与 `policy.csv:864-873` 一一对应；`:76` R-MANAGER 两条；`:126-128` PAGE_GRANTS 与 `seed_demo.py:80-113` 的门户/审核台行一致。`overrides/portal.ts` 的 `GET /partner-orgs` 忽略 `status/keyword`（M-4，仅开发态） |
| `/guide` 对 R-PARTNER 可达 | 需注意 | `router/index.ts:21` `/guide` 无 `roles`，任何登录用户可达；`PortalView.vue:166` 点击指南行 `router.push('/guide')`，`GuideView.vue:162-164` 会请求 `/apply/guidelines?status=...`——这正是 C-2 越权面的前端入口 |

### 8. 种子与幂等 —— PASS

| 检查点 | 结论 | 证据 |
|---|---|---|
| seed 可重跑全零 | PASS | 文件库 `/tmp/fr_m2a.sqlite3` 连跑两遍：第一遍各模块 +N，第二遍输出“seed_demo 完成（幂等）：”且所有计数为 0（明细见第四节） |
| `partner` 账号可被门户/审核台使用 | PASS | `backend-django/apps/sysadmin/management/commands/seed_demo.py:1063-1087`：`status=ACTIVE`、`user_source=EXTERNAL`、`org_id=ptn_a.id`、`get_or_create` R-PARTNER；测试 `tests/test_sysadmin_partner.py:271-301` 用该账号登录→门户 200、`/expenses` 403、`/partner-orgs` 403 |
| 机构 B 为 PENDING（审核台有可操作数据） | PASS | `seed_demo.py:1057-1065` `code=PTN-2026-000002`、`status=PENDING`；机构 A `:1048-1056` APPROVED |
| 种子账号安全等级 | 注意 | `seed_demo.py:1067` 外部账号 `security_level="INTERNAL"`（M-5） |

### 9. 工程卫生 —— PASS（附工作区脏，M-7）

| 检查点 | 结论 | 证据 |
|---|---|---|
| 提交数与文件范围与台账一致 | PASS | `git log 72ee658..f5cb8e8` 共 9 个提交：a287981（models）、2c748a2（rbac）、412a127（register）、76e96b8（notify email）、87d5a63（audit desk）、12311a8（portal）、713f4bc（contract）、24ba539（fe）、f5cb8e8（seed+readme）；`git diff --stat` 29 文件 +3053/−10，与台账 Task 1-9 文件清单对齐 |
| 无 `docs/` 无关改动 | PASS | 分支 diff 不含 `docs/`；仅 `README.md` 与 `backend-django/README.md` 的计数/说明更新 |
| 无遗留调试代码 / TODO / 恒真断言 | PASS | 扫描新增行无 `print(`/`pdb`/`breakpoint`；唯一 `TODO` 是 `apps/sysadmin/api.py:700` 作为通知 `typ` 的业务值（M-9，命名不佳但非调试残留）；`tests/test_rbac.py` 负面断言基于真实策略行过滤，非恒真 |
| `makemigrations --check` clean | PASS | `manage.py makemigrations --check` → “No changes detected”，exit 0 |
| 工作区干净 | **不符** | `git status`：` M frontend/src/views/RegisterView.vue`、` M frontend/src/api/mock/overrides/portal.ts`、` M docs/.DS_Store`、多个 `D docs/*.jpeg/png`、未跟踪的 doc 计划/`dump.rdb`/`uv.lock`/`pnpm-lock.yaml`/`scripts/ocr_*`。**使 HEAD 注册页可用的修复未提交**，这本身是发布卫生问题（M-7） |

---

## 三、问题清单

### Critical

#### C-1 HEAD 注册页字段与后端/契约完全错位，C1 自助注册 100% 失败
- 位置：`frontend/src/views/RegisterView.vue:9`（`name: string`）、`:17`（`short_name: string`）、`:47-49`（`ready`）、`:57`（`api.post('/portal/register', { ...form })`）、`:91`（`v-model="form.name"`）、`:100`（`v-model="form.short_name"`）；后端必填 `backend-django/apps/sysadmin/api.py:634`（`org_name`）、`:651`（`real_name`）。
- 问题：HEAD 提交的表单体键为 `name`/`short_name`，且完全没有 `real_name` 字段；后端按 `org_name`/`real_name` 读取，`_str_field` 直接 400。
- 影响：外部机构从 UI 注册必然失败（实测 POST HEAD 表单体 → `{"code":40001,"message":"机构名称不能为空"}`）。C1 主流程在 HEAD 不可用；单测/tsc 全绿也发现不了（纯净 HEAD `vue-tsc` 也 exit 0，因为类型自洽）。
- 建议修法：把工作区已有的未提交修复提交进来（`name→org_name`、`short_name→real_name` 并补 `*` 必填），同时把 `contact_phone`/`contact_email` 纳入 `ready`（I-6）；补一条“用表单同形 payload 调注册接口”的前端契约测试或 e2e，防止再次漂移。

#### C-2 R-PARTNER 可读取 DRAFT 及跨租户申报指南（tenant 隔离被打破）
- 位置：`backend-django/config/casbin/policy.csv:868-869`（R-PARTNER 获 `/apply/guidelines`、`/apply/guidelines/*` GET）；`backend-django/apps/p/api.py:58-71`（列表仅按可选 `status` 过滤，无默认 PUBLISHED）；`apps/p/api.py:74-78`（详情 `filter(id=id, deleted=0)`，**无 `tenant_id`**）；路由 `config/api.py:76`、`:86`。
- 问题：新增角色把两个既有 handler 暴露给外部身份，而 handler 没有“非管理员只能看本租户 PUBLISHED”的约束。
- 影响（实测，`/tmp/fr_probe2.sqlite3`）：tenant-1 partner 调 `GET /api/v1/apply/guidelines?size=50` → 200，返回 `[DRAFT, PUBLISHED]`；调 `GET /api/v1/apply/guidelines/3`（tenant-2 的 DRAFT）→ 200，正文“租户2未公开指南”。既泄露未发布信息，也直接违反“tenant 隔离不破”硬约束；前端 `/guide` 对 R-PARTNER 可达（`router/index.ts:21`），构成可点击入口。
- 建议修法（二选一或并用）：
  1. `get_guideline` 增加 `tenant_id=d.tenant_id`；`list_guidelines` 对非管理角色强制 `status='PUBLISHED'`（或仅在显式允许时返回 CLOSED），并补“partner 读 DRAFT → 404/403”“partner 读他租户 id → 404”的回归测试；
  2. 收敛授权：删除 `policy.csv:868-869`，门户指南只经 `/portal/home` 下发（已限定 PUBLISHED + 本租户），如确需指南详情则新增 `/portal/guidelines/{id}` 专用端点并复用 portal 的 org/tenant 过滤。
- 备注：`tests/test_rbac.py:511-518` 目前把“详情路径对 R-PARTNER 可达”当作正向断言，整改时需同步改为“不可达/受限”。

### Important

#### I-1 APPROVED → REJECT 后账号仍 ACTIVE 且保留 R-PARTNER（状态机漏洞）
- 位置：`backend-django/apps/sysadmin/api.py:743-757`（仅对“已是同状态”短路，无“仅 PENDING 可审”守卫）、`:763-771`（解锁/授权只在 APPROVE 分支）。
- 问题：机构被驳回后 `status=REJECTED`，但先前 APPROVED 时激活的账号不回锁、角色不撤销。
- 影响：资质被撤销的机构仍可登录门户、读本机构数据与指南；审计记录与实际权限不一致。实测：APPROVE 后 REJECT → 200，`org.status=REJECTED`、user ACTIVE、`SysUserRole` 仍含 R-PARTNER。
- 建议修法：状态机显式化——`if org.status != "PENDING": raise ApiError(409/400, "当前状态不可审核")`（或允许 REJECT 时同步 `user.status="LOCKED"` 并删除 R-PARTNER 授权）；补“APPROVE→REJECT 后账号不可登录/门户 403”的测试。注意 JWT 内角色在过期前仍有效，必要时配合 token 版本/短 TTL。

#### I-2 驳回不发邮件，而被锁账号无法登录查看驳回理由
- 位置：`backend-django/apps/sysadmin/api.py:790-792`（REJECT 仅 `notify_inapp`）；计划 Task 5 明确“REJECT … 发邮件”。
- 问题：驳回理由只写进站内信，收件账号处于 LOCKED，登录被 40302 拒绝，永远看不到这条站内信。
- 影响：外部机构不知道驳回原因，审核闭环断裂；与计划/验收口径不符。
- 建议修法：REJECT 分支同样调用 `send_mail_best_effort(org.contact_email, ...)`（保持 best-effort，不阻断）；补邮件失败仍 200 的测试。

#### I-3 R-PARTNER 角色行缺失时审核静默成功，账号 ACTIVE 但无门户权限
- 位置：`backend-django/apps/sysadmin/api.py:770-771` `role = ...first()`；`if role is not None:` 才授权。
- 问题：计划要求角色缺失时返回 400“角色未初始化，请先执行 seed_demo”，实现选择静默跳过。
- 影响：新环境未 seed 时，机构显示“已通过”、账号可登录，但访问 `/portal/*` 一律 403，故障难定位。实测：删除 R-PARTNER 角色后 APPROVE → 200、user ACTIVE、roles `[]`。
- 建议修法：在 `transaction.atomic()` 内、修改状态前 `if role is None: raise ApiError(400, "角色未初始化，请先执行 seed_demo")`；补对应测试。

#### I-4 公开注册的 `tenant_id` 由请求体控制，未认证即可向任意租户写入
- 位置：`backend-django/apps/sysadmin/api.py:632` `tenant_id = int(body.get("tenant_id") or 1)`；契约 `design/12-用户与权限-U.openapi.yaml:971` 将 `tenant_id` 标为可选“缺省 1”。
- 问题：无登录态的公开端点信任客户端 tenant，攻击者可批量向 tenant 2/3… 灌机构与账号。
- 影响：跨租户数据污染、审核台被垃圾数据淹没、跨租户占用用户名；实测 `tenant_id=2` 注册 → 200 且机构落在 tenant 2。
- 建议修法：租户由服务端决定（`settings.DEFAULT_TENANT_ID` 或按 Host/域名映射），忽略或校验 body 的 `tenant_id`；同时加注册限流/验证码类防刷。契约同步改为“服务端确定，忽略请求值”。

#### I-5 DDL 的唯一索引与 Django 迁移的非唯一索引不一致
- 位置：`design/00-common.sql:370` `CREATE UNIQUE INDEX uk_ptn_credit ON sys_partner_org(tenant_id, credit_code) WHERE deleted = 0`；`backend-django/apps/sysadmin/migrations/0008_syspartnerorg_sysuser_org.py:51` 仅 `models.Index(fields=['tenant_id','credit_code'], name='idx_ptn_credit')`（非唯一）；模型 `apps/sysadmin/models.py:253-254` 同。
- 问题：按 Django 迁移建库（开发 sqlite / 未执行 design SQL 的环境）没有该唯一约束；PRAGMA 实测 `unique=0`。
- 影响：应用层 `exists()` 检查存在并发竞态，两个相同 `credit_code` 的注册可同时通过，产生重复机构；与设计文档承诺不一致。
- 建议修法：模型加 `UniqueConstraint(fields=['tenant_id','credit_code'], condition=Q(deleted=0), name='uk_ptn_credit')` 并生成迁移；或明确以 design SQL 为准并在迁移中 `RunSQL` 建唯一索引；补并发/重复路径测试。

#### I-6 注册表单未要求联系电话/邮箱，后端必填导致必然 400
- 位置：`frontend/src/views/RegisterView.vue:47-49`（`ready` 不含 phone/email）、`:113-119`（电话标“选填”、邮箱无 `*`）；后端 `backend-django/apps/sysadmin/api.py:644-646` 两者均 `_str_field(required=True)`。
- 问题：契约 `:971` required 9 键含 `contact_phone`/`contact_email`，前端却允许空提交。
- 影响：用户填完可见的“必填项”仍被 400，体验与契约不一致；也是 C-1 修复后仍会残留的失败路径。
- 建议修法：`ready` 加入两项非空校验，模板补 `*` 与格式提示（邮箱至少含 `@`）；补前端表单校验测试。

### Minor

- **M-1 审核未加 `select_for_update`**：`apps/sysadmin/api.py:741`，计划 Task 5 要求。并发双审可能重复发通知/覆盖 `audit_user_id`（角色 `get_or_create` 已防重复授权）。建议 `select_for_update()` 或带状态条件的 `UPDATE ... WHERE status='PENDING'`。
- **M-2 信用代码校验偏弱**：`apps/sysadmin/api.py:638` 仅 `len==18 and credit_code[0].isalnum()`，中文/小写字母可通过（实测 18 个“中” → 200）。建议 `re.fullmatch(r"[0-9A-Z]{18}", credit_code)`（按登记规则可放宽首字符）。
- **M-3 契约缺 403 声明**：`design/12-用户与权限-U.openapi.yaml:795-822` 的 PUT、`:824` home、`:876` audit 未列 403，但 casbin 越权会返回 403。建议补齐 `Forbidden` 响应，避免前端错误处理遗漏。
- **M-4 mock 列表忽略筛选**：`frontend/src/api/mock/overrides/portal.ts` 的 `GET /partner-orgs` 未处理 `status/keyword`，开发态“筛选无效”易被误判为后端缺陷。建议按 query 过滤。
- **M-5 seed 外部账号 `security_level=INTERNAL`**：`seed_demo.py:1067`（注册创建的账号同样走默认 INTERNAL）。当前没有基于 `security_level` 的核心授权，但语义上外部身份不应带内部密级。建议外部账号显式设 `PUBLIC`/`EXTERNAL` 对应级别，并确认下游无隐式依赖。
- **M-6 测试缺口**：`tests/test_sysadmin_partner.py:190` 只测“不存在的 id → 404”，未测跨租户 id（运行时已验证 404）；无“驳回发邮件/驳回后不可登录”测试；无“partner 读 DRAFT/他租户指南”回归；`tests/test_sysadmin_partner.py:108-115` 未断言两种冲突的 message 完全一致（防枚举性质未被测试锁定）。
- **M-7 工作区脏 / 关键修复未提交**：`frontend/src/views/RegisterView.vue` 与 mock 的修复、`docs/` 删除与未跟踪文件均未入库；提交前应 `git add` 必要文件并清理无关产物（`dump.rdb`、`uv.lock`、`scripts/ocr_*` 等）。
- **M-8 口令提示文案与规则不符**：`apps/sysadmin/api.py:622` 报错“口令须同时包含字母”，但规则只要求“含字母且非纯数字”，并不要求数字。建议改为“口令须包含字母”。
- **M-9 通知 `typ="TODO"`**：`apps/sysadmin/api.py:700` 把占位词当业务类型写入站内信，后续按 typ 过滤/展示会踩坑。建议定义 `PARTNER_APPLY` 之类常量（如需新增类型，注意已裁定“不为 channel 补 DDL”的边界，typ 是既有列）。

---

## 四、实测数字

| 验证 | 命令 | 结果 |
|---|---|---|
| 后端全量测试 | `cd backend-django && .venv/bin/python -m pytest -q` | **368 passed**, 7 warnings, 18.24s（基线 346 → +22；7 条 warning 中 2 条为既有 `PytestReturnNotNoneWarning`：`test_phase4_ethics.py`、`test_phase4_transform.py`） |
| 迁移一致性 | `manage.py makemigrations --check` | `No changes detected`，exit 0（仅 PostgreSQL 连接被拒的 history 检查 warning，不影响结论） |
| 前端类型检查（工作区） | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | exit 0 |
| 前端类型检查（纯净 HEAD） | `git archive HEAD frontend` 到 `/tmp/m2a_head` 后 `vue-tsc --noEmit` | exit 0（说明 C-1 是运行时键错位，不是类型错误） |
| 契约副本 | `cmp design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml` | exit 0 |
| 种子第 1 遍 | 文件库 `/tmp/fr_m2a.sqlite3`：`migrate` → `seed_demo` | legal +2、staff +11、p +3、project +15、funding +23、output +7、expert +6、activity +4、archive +6、performance +6、transform +13、ethics +5、procure +8、asset +9、confsec +7、notify +5、partner +5、users +4、dicts +5、items +26、grants +78 |
| 种子第 2 遍 | 同库再跑 `seed_demo` | 全部为 0，输出“seed_demo 完成（幂等）：” |
| 运行时探针 A | HEAD 注册表单同形 payload（`name`/`short_name`）POST `/api/v1/portal/register` | 400 `{"code":40001,"message":"机构名称不能为空"}` |
| 运行时探针 B | partner 调 `GET /api/v1/apply/guidelines?size=50` | 200，`total=2`，status 含 `DRAFT` |
| 运行时探针 C | partner 调 `GET /api/v1/apply/guidelines/3`（tenant-2 DRAFT） | 200，正文“租户2未公开指南” |
| 运行时探针 D | register→APPROVE→REJECT 同一机构 | 200；`status=REJECTED`；user 仍 ACTIVE 且持有 R-PARTNER；邮件计数不变（仅 1 封通过邮件），站内信 +1 |
| 运行时探针 E | 删除 R-PARTNER 角色后 register→APPROVE | 200；user ACTIVE；roles `[]` |
| 运行时探针 F | tenant-1 管理员审核 tenant-2 机构 / 列表 | 404 / 列表不含 tenant-2 |
| 运行时探针 G | 公开注册带 `tenant_id=2` | 200，机构落在 tenant 2 |

> 探针均使用独立文件库（`/tmp/fr_probe*.sqlite3`，`migrate` + `seed_demo`），未使用 `:memory:`；
> 所有 200/400/403/404 均为真实 HTTP 响应，非 mock。

---

## 五、已裁定事项（不重开）

以下台账 Ruling 在本报告中仅作为前提引用，不作为问题项：

1. **`sys_notification` 不补 DDL**：`channel` 字段为 M2-a 新增的 ORM 字段，设计 SQL 未收录该表，按裁定不补手写 DDL；Django 迁移负责建表/加列。
2. **门户未读通知卡不跳转**：前端无 `/messages` 路由，未读卡仅展示计数，不做跳转，符合已裁定口径。
3. **review 迁移编号 0008-0010**：`0008` 建表/加列、`0009`/`0010` resync 权限的编号与顺序不再调整。

---

## 六、合并前最低动作清单（建议顺序）

1. **C-1**：提交注册页修复（`org_name`/`real_name`），补 `real_name` 必填与表单同形 payload 测试；顺带修 I-6（phone/email 必填）。
2. **C-2**：`get_guideline` 加 `tenant_id`；非管理角色列表强制 `PUBLISHED`（或删除 `policy.csv:868-869` 改走门户专用接口）；把 `tests/test_rbac.py:511-518` 的正向断言改为受限断言，并补 DRAFT/跨租户 404 用例。
3. **I-1 / I-3**：审核状态机加 `PENDING` 守卫（或 REJECT 时回锁账号+撤角色）；角色缺失返回 400；补测试。
4. **I-2**：驳回补 `send_mail_best_effort`（best-effort，不阻断）。
5. **I-4 / I-5**：注册租户服务端化 + 限流；唯一约束与 design SQL 对齐（迁移或 RunSQL）。
6. 复跑：`pytest -q`（期望 ≥368 且新增用例通过）、`makemigrations --check`、`vue-tsc --noEmit`、`cmp`、种子两遍全零；确认 `git status` 干净后再合并。

---

### 附：评审范围提交

```
f5cb8e8 chore(seed+readme)      24ba539 feat(fe)           713f4bc feat(contract)
12311a8 feat(portal endpoints)  87d5a63 feat(audit desk)   76e96b8 feat(notify email)
412a127 feat(register)          2c748a2 feat(rbac)         a287981 feat(models)
```
