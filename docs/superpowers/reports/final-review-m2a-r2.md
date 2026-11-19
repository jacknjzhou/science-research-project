# M2-a 终审 r2：修复复核报告（独立复审）

- 评审对象：`develop` 分支 `72ee658..c3375ef`（12 个提交），HEAD = `c3375ef`
- 修复提交：`0d426af`（C-2）、`5023a79`（I-1..I-6）、`c3375ef`（C-1/I-6/Minor）
- 复核依据：`docs/superpowers/plans/2026-11-18-m2a-partner-onboarding-portal.md`、`/tmp/review-m2a-r2.diff`、`.superpowers/sdd/2026-11-18-m2a-partner-onboarding-portal/progress.md`、r1 报告 `docs/superpowers/reports/final-review-m2a.md`
- 复核方式：**只读代码 + 单进程文件库实测**。未修改任何源文件；本文件是唯一写入产物。
- 评审角色：独立复审（非 r1 作者，非开发方）

---

## 0. 结论

**APPROVED_WITH_MINOR — merge-ready。**

r1 的 2 个 Critical（C-1、C-2）与 6 个 Important（I-1..I-6）**全部实测关闭**，且关闭方式是"实现收口 + 回归测试锁定"，不是"测试放过"：

- C-1：注册面三方（前端表单 / 后端必填集 / 12-U 契约 `required`）现在**同一组 9 键、同名**；用与表单完全相同的 JSON 直接 POST 实测 200。
- C-2：外部角色对"未发布"与"跨租户"两维度都收口到 404，且列表侧强制 `status=PUBLISHED`、忽略调用方 `?status=` 参数；内部角色仍可读本租户 DRAFT、跨租户仍 404。

修复本身未引入 Critical / Important 级新缺陷，但引入了 **6 个 Minor**（见 §3），其中 N-1 是**功能性收窄**（非安全回退），需要在合入说明里登记，避免后续被当成 bug 重报。

合入前建议只做两件低成本动作（不阻断）：
1. 在白名单补 `R-FINANCE/R-AUDITOR/R-EXPERT/R-ETHICS`（N-1），或显式把"指南 DRAFT 仅四类内部角色可见"写进策略注释；
2. 把 `apps/sysadmin/api.py:632` 的陈旧 docstring 改掉（N-6）。

---

## 1. 复核方法与证据基座

| 维度 | 做法 |
|---|---|
| 静态 | 逐文件读 HEAD 实现（`apps/p/api.py`、`apps/sysadmin/api.py`、`apps/sysadmin/models.py`、迁移 0011、`config/settings/base.py`、`config/casbin/policy.csv`、`RegisterView.vue`、12-U 契约、mock overrides） |
| 动态（真实 HTTP） | 迁移 + `seed_demo` 建**单进程文件库** `/tmp/r2_m2a.sqlite3`，再用 `django.test.Client` 走真实路由/中间件/casbin，不 mock 业务层 |
| 契约形状 | 用 `yaml.safe_load` 直接读 `PartnerOrgRegisterRequest.required` 与 `properties`，与前端 `interface`、后端 `_str_field` 调用集做三方比对；再用**同一份 JSON** 打真实注册端点 |
| 库层约束 | 绕过 API 用 ORM 直插重复值，观察 `IntegrityError` 文本，确认约束名落到 `sys_partner_org.tenant_id, credit_code` |
| 邮件 | `locmem` 后端读 `mail.outbox`，断言收件人/主题/正文 |
| 环境变量 | 独立进程 `ARK_PARTNER_SIGNUP_TENANT=7` 复跑注册，确认配置真被读 |

探针脚本放在 `/tmp/r2_e2e.py`（**未入库**，避免污染仓库；内容说明见 §6）。

---

## 2. r1 八条逐条状态

| # | r1 意见 | r2 状态 | 证据（file:line） | 我的验证方式 |
|---|---|---|---|---|
| **C-1** | 注册页发 `name/short_name`，后端要 `org_name/real_name`，注册 100% 失败 | ✅ **已关闭** | `frontend/src/views/RegisterView.vue:8-18`（interface 9 键）、`:28-32`（reactive 初值）、`:60`（`api.post('/portal/register', { ...form })`）；`backend-django/apps/sysadmin/api.py:640-655`（`_str_field` 必填集）；`design/12-用户与权限-U.openapi.yaml:975`（`required` 9 键，`properties` 含 `address`、已无 `tenant_id`）；回归 `backend-django/tests/test_sysadmin_partner.py:303-313` | 三方集合比对 **完全相同**：`{org_name, credit_code, org_type, contact_name, contact_phone, contact_email, username, password, real_name}`。再用**与表单同形**的 9 键 JSON（外加 `tenant_id=2` 试探）直打 `POST /api/v1/portal/register` → **HTTP 200, code=0**，落库 `tenant_id=1, status=PENDING, credit_code=91310000MA1K3XY77Q`。不是"读代码推断" |
| **C-2** | R-PARTNER 可读 DRAFT 及跨租户指南，tenant 隔离被破 | ✅ **已关闭**（附 N-1 功能收窄） | `backend-django/apps/p/api.py:60`（`_INTERNAL_GUIDELINE_ROLES`）、`:63-69`（`_guideline_status_scope`）；`:73-79`（列表强制 scope、`elif` 才看 `?status=`）；`:92-96`（详情二次判定 404） | 实跑四组：① tenant-1 partner 列表只剩 `[(1,PUBLISHED)]`，加 `?status=DRAFT` 仍只回 PUBLISHED（scope 优先于 query）；② partner 读 tenant-1 DRAFT `id=2` → **404/40401**；③ partner 读 tenant-2 `id=3`(PUBLISHED)/`id=4`(DRAFT) → **404/404**；④ partner 读 tenant-1 PUBLISHED → 200。内部角色：R-STAFF 读 tenant-1 DRAFT → **200**，读 tenant-2 → **404**，列表 `[(2,DRAFT),(1,PUBLISHED)]`。`roles=[]` 分支返回 `"PUBLISHED"`（fail-closed，且 casbin 通常先 403，属纵深防御）；`R-PARTNER + R-STAFF` 并存时 `any()` 命中内部分支 → 可见 DRAFT（符合"内部分支胜出"的既有语义，非越权） |
| **I-1** | 任意状态可再审（APPROVED→REJECT 等） | ✅ **已关闭** | `backend-django/apps/sysadmin/api.py:768-778`（`atomic` → `select_for_update` → 同动作短路 → `status != "PENDING"` 抛 409）；回归 `tests/test_sysadmin_partner.py:354-365` | APPROVE → 200（user ACTIVE、`['R-PARTNER']`）→ **重放 200 幂等**；APPROVED→REJECT → **409/40901「该机构已审核完成，不可再次审核」**，且冲突后 org 仍 APPROVED、user 仍 ACTIVE、角色仍 1 条、**新增邮件 0 封**；REJECT → 200（org REJECTED、user **LOCKED**、`roles=[]`）→ **REJECTED→APPROVE 409/40901** → REJECT 重放 200 |
| **I-2** | 驳回不发邮件 | ✅ **已关闭** | `apps/sysadmin/api.py:821-829`（REJECT 分支 `notify_inapp(..., channel="BOTH")` + `send_mail_best_effort(org.contact_email, ...)`，正文拼 `reason`）；回归 `tests/test_sysadmin_partner.py:368-375` | 驳回后 `mail.outbox == 1`：收件人 `['r2reject@example.edu.cn']`，主题「机构资质审核未通过」，正文「R2 待驳回国立研究所 的注册申请未通过：资质证书过期」——**理由确在正文** |
| **I-3** | R-PARTNER 角色缺失时静默成功 | ✅ **已关闭** | `apps/sysadmin/api.py:799-802`（`role is None` → `ApiError(400, "角色未初始化，请先执行 seed_demo")`，位于 `with transaction.atomic()` 内 → 整笔回滚）；回归 `tests/test_sysadmin_partner.py:378-387` | 删角色后 APPROVE → **400/40001**，且 **org 仍 PENDING、user 仍 LOCKED、roles=[]**（实测回滚生效，无"半途 ACTIVE"） |
| **I-4** | 公开注册 body `tenant_id` 可控 | ✅ **已关闭** | `apps/sysadmin/api.py:638`（`tenant_id = int(getattr(dj_settings, "PARTNER_SIGNUP_TENANT_ID", 1))`）；`backend-django/config/settings/base.py:135-136`（`ARK_PARTNER_SIGNUP_TENANT`，默认 1）；回归 `tests/test_sysadmin_partner.py:316-320` | ① `tenant_id=2` 提交 → 落库 **tenant 1**；② 独立进程 `ARK_PARTNER_SIGNUP_TENANT=7` + body `tenant_id=1` → `settings.PARTNER_SIGNUP_TENANT_ID == 7`，落库 **tenant 7**（配置项**真被读**，不是硬编码 1） |
| **I-5** | DDL 唯一索引与迁移不一致 | ✅ **已关闭** | `apps/sysadmin/models.py:257-264`（`UniqueConstraint(["tenant_id","credit_code"], name="uk_ptn_credit", condition=Q(deleted=0))`）；`apps/sysadmin/migrations/0011_m2a_uk_ptn_credit.py:13-15`；`design/00-common.sql:370`（同名同列同谓词） | 迁移建库（sqlite）后 ORM 直插同租户同码 → `IntegrityError: UNIQUE constraint failed: sys_partner_org.tenant_id, sys_partner_org.credit_code`；`deleted=1` 同码 **可插**（软删不占槽）；`tenant_id=5` 同码 **可插**；API 重复注册 → 409/40901 |
| **I-6** | 前端未要求电话/邮箱 | ✅ **已关闭** | `frontend/src/views/RegisterView.vue:47-48`（`phoneOk`/`emailOk` 正则）、`:49-53`（`ready` 含 `phoneOk && emailOk`）、`:93-128`（模板全字段 `*`）；后端 `apps/sysadmin/api.py:648-651`；回归 `tests/test_sysadmin_partner.py:323-333` | 前端：`ready` 不含这两项时为 false（读实现 + `vue-tsc --noEmit` 通过）；后端：缺 `contact_phone` → 400「联系电话不能为空」、缺 `contact_email` → 400「联系邮箱不能为空」、缺 `real_name` → 400「姓名不能为空」；信用代码小写 `91310000ma1k3xy66n` → 200 且存库 `91310000MA1K3XY66N`（`:641` `.upper()` 归一） |

**八条结论：8/8 关闭，无"部分关闭"。** 新引入的问题全部落在 Minor（§3），不构成 r1 意见未闭合。

---

## 3. 修复引入的新问题

### Critical
无。

### Important
无。

### Minor（6 条，均不阻断合并）

**N-1 内部角色白名单过窄，四个内部角色丢失"读 DRAFT"能力（功能性收窄，fail-closed）**
`apps/p/api.py:60` 的白名单只有 `("R-ADMIN","R-MANAGER","R-LEADER","R-STAFF")`；`:63-69` 对集合外角色一律返回 `"PUBLISHED"`。
实测：`R-FINANCE` 读 tenant-1 DRAFT `id=2` → **404**；`R-AUDITOR` 读同一条 → **404**。而 `config/casbin/policy.csv:12` 给 R-AUDITOR 的是 `/api/v1/*, GET` 并注释「全量只读」，`:40/43/68` 让 R-FINANCE/R-EXPERT/R-ETHICS 经 `/api/v1/apply/*` 同样可达这两个 handler。
影响：R-AUDITOR 的"全量只读"在指南域被打破（财务/伦理/专家角色同理），属文档承诺与实现不一致；**方向是收紧，不存在提权**。
建议：把四角色并入 `_INTERNAL_GUIDELINE_ROLES`，或在 `policy.csv` 注释与本报告登记"指南 DRAFT 属内部受限数据，仅 ADMIN/MANAGER/LEADER/STAFF 可见"。

**N-2 `except IntegrityError → 409` 语义过宽，可能把他类约束错误误报为"已注册"**
`apps/sysadmin/api.py:678-680`：`except IntegrityError: raise ApiError(409, CODE_CONFLICT, "机构或用户名已注册") from None`。
该路径目前可触发的约束只有 `uk_ptn_credit`（迁移建库）与 PG 上 design SQL 的 `uk_user_username`（`design/00-common.sql:46`）两类，两者语义都确实是"已注册"，故**当前影响可控**；但若将来给 `sys_partner_org`/`sys_user` 加 NOT NULL/CHECK/别的唯一键，会被误报成 409 而非 400/500，且 `from None` 抹掉栈。
建议：按约束名/`e.__cause__` 分支，或至少 `logger.warning` 保留原始异常。

**N-3 注册创建的账号 `security_level` 仍为默认 `INTERNAL`**
`apps/sysadmin/api.py:692-745` 创建 `SysUser` 时未显式给 `security_level`，走模型默认 `INTERNAL`（实测新账号 `sec=INTERNAL`）；而 M-5 只改了种子账号（`seed_demo.py:1067` → `PUBLIC`）。
不构成越权：`grep -rn security_level core/ config/ apps/` 显示该字段只在 `core/auth/deps.py:23/51` 透传 claim（无判定分支），无任何按密级的数据过滤。属语义不一致。
建议：注册处显式 `security_level="PUBLIC"`，与外部分身身份对齐。

**N-4 契约 `PUT /portal/org` 仍缺 403 声明（M-3 未完全闭合）**
`design/12-用户与权限-U.openapi.yaml:802-823` 仍只有 200/400/404；实测 `R-STAFF` 真实 `PUT /api/v1/portal/org` → **403/40301**。`/portal/home`（`:840`）与 `/partner-orgs/{id}/audit`（`:904-906`）已补齐，仅此一处漏项。

**N-5 迁移 0011 在"存量库已有重复 credit_code"时会直接失败**
`0011_m2a_uk_ptn_credit.py:13-15` 只做 `AddConstraint`，无前置去重。按 `design/00-common.sql` 建的库本就有该唯一索引、不可能有重复，故生产路径无风险；仅"历史上用迁移建库且已灌入重复数据"的 dev/预发库会迁移失败。
建议：合入说明里写明，必要时迁移前加一次重复检测并抛可读错误。

**N-6 `register_partner` docstring 与实现相反**
`apps/sysadmin/api.py:632` 仍写「tenant 取 body.tenant_id 或 1」，紧接着 `:635-638` 的实现与注释是"不接受请求体指定"。陈旧 docstring 会误导下一个改这里的人。

---

## 4. r1 Minor×9 的处置

| # | r1 Minor | 处置 | 证据 |
|---|---|---|---|
| M-1 | 审核未加 `select_for_update` | ✅ 已修 | `apps/sysadmin/api.py:771` `SysPartnerOrg.objects.select_for_update().get(id=org.id)`，在 `:768` `atomic` 内；状态判定用加锁后的重读值。sqlite 忽略该子句（Django 对 `has_select_for_update=False` 后端跳过，实测无报错），PG 生效 |
| M-2 | 信用代码校验偏弱（`len==18 and isalnum`） | ✅ 已修 | `api.py:561-562` `_CREDIT_CODE_RE = re.compile(r"^[0-9A-Z]{18}$")` + `:641` 先 `.upper()` 再匹配 + `:642-643` 400。实测 18 个汉字 / 16 位 / 20 位均 400，小写 18 位归一后 200 |
| M-3 | 契约缺 403 声明 | 🟡 部分修 | home `:840`、audit `:904-906` 已补；**PUT `/portal/org` 仍缺**（N-4） |
| M-4 | mock `GET /partner-orgs` 忽略筛选 | ✅ 已修 | `frontend/src/api/mock/overrides/portal.ts:111-124` 按 `status`/`keyword` 过滤并按 `-id` 倒序；注册 override 同步改 `b.org_name`（`:86-87`） |
| M-5 | 种子外部账号 `security_level=INTERNAL` | 🟡 部分修 | `seed_demo.py:1067` 已改 `PUBLIC`；**注册创建的账号仍 INTERNAL**（N-3） |
| M-6 | 测试缺口 | 🟡 大部分修 | 新增：`test_p_domain.py:307` partner 只见 PUBLISHED、`:315` DRAFT/跨租户 404（含 R-STAFF 200 正例）；`test_sysadmin_partner.py:390` 跨租户审核 404 + 列表 tenant 集；`:368` 驳回邮件；`:354` APPROVED→REJECT；`:342` 库层唯一 + 软删不占槽；`:303` 契约形状注册。**未锁**：`:108-115` 仍未断言"信用代码冲突"与"用户名冲突"的 message 完全一致（防枚举性质无测试护栏）——可接受留档 |
| M-7 | 工作区脏 / 关键修复未提交 | 🟡 部分修 | `RegisterView.vue`、mock、契约、测试均已入库（`git log` 可见）；但 `git status` 仍有 ` M docs/.DS_Store`、7 个 `D docs/*.png|jpeg`、未跟踪 `dump.rdb`/`uv.lock`/`frontend/pnpm-lock.yaml`/`scripts/ocr_*`/`docs/superpowers/*`。与 M2-a 代码无关，按既有裁定不阻断 |
| M-8 | 口令提示与规则不符 | ❌ 未修 | `api.py:625` 仍为「口令须同时包含字母」（规则只要求含字母且非纯数字） |
| M-9 | 通知 `typ="TODO"` | ❌ 未修 | `api.py:684` 仍把 `"TODO"` 当业务类型写进站内信 |

**统计：已修 3（M-1、M-2、M-4）；部分修 4（M-3 缺 PUT 403、M-5 只改种子、M-6 缺 message 一致性断言、M-7 工作区仍脏）；未修 2（M-8、M-9）。** 未修与部分修的 6 项均为文案/常量/开发态卫生，零功能与安全风险，留档即可。

---

## 5. 实测数字

| 命令 | 结果 |
|---|---|
| `backend-django/.venv/bin/python -m pytest -q` | **380 passed, 7 warnings in 18.45s**，exit 0 |
| `backend-django/.venv/bin/python manage.py makemigrations --check` | **No changes detected**，exit 0（仅一条 PG 5432 连接被拒的 `RuntimeWarning`，因未起 PG；不影响判定） |
| `frontend ./node_modules/.bin/vue-tsc --noEmit` | exit **0**，无输出 |
| `cmp design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml` | exit **0**（双份契约逐字节一致） |
| 迁移 | `migrate --no-input` 全绿，含 `0011_m2a_uk_ptn_credit` |
| 种子第 1 遍 | `legal +2，staff +11，p +3，project +15，funding +23，output +7，expert +6，activity +4，archive +6，performance +6，transform +13，ethics +5，procure +8，asset +9，confsec +7，notify +5，partner +5，users +4，dicts +5，items +26，grants +78` |
| 种子第 2 遍 | 仅打印「seed_demo 完成（幂等）：」，**全零** |
| HEAD | `c3375ef` |

---

## 6. 附录 A：e2e 实测输出（摘录，未删改）

```
### C-1 注册：与 RegisterView 表单完全同形的 9 键 JSON（+ tenant_id=2 试探）
C-1 注册（表单同形 9 键 + tenant_id=2）: HTTP 200 code=0 msg='ok'
    -> 落库 tenant_id=1 status=PENDING credit_code=91310000MA1K3XY77Q username=r2_partner
    -> 新账号 status=LOCKED org_id=3 user_source=EXTERNAL sec=INTERNAL

### C-1 未审核登录
未审核登录（期望 403/40302）: HTTP 403 code=40302 msg='账号已停用或锁定'

### I-2 驳回邮件
REJECT（R-MANAGER）: HTTP 200 code=0 msg='ok'
    -> mail.outbox=1 封
    -> 收件人: ['r2reject@example.edu.cn'] | 主题: 机构资质审核未通过
    -> 正文: R2 待驳回国立研究所 的注册申请未通过：资质证书过期
    -> 驳回后 org.status=REJECTED user.status=LOCKED roles=[]

### I-1 审核状态机
APPROVE（首次）: HTTP 200 code=0 msg='ok'
    -> user.status=ACTIVE roles=['R-PARTNER']
APPROVE 重放（期望 200 幂等）: HTTP 200 code=0 msg='ok'
APPROVED→REJECT（期望 409/40901）: HTTP 409 code=40901 msg='该机构已审核完成，不可再次审核'
    -> 冲突后 org.status=APPROVED user.status=ACTIVE roles=['R-PARTNER'] 新增邮件=0
REJECTED→APPROVE（期望 409/40901）: HTTP 409 code=40901 msg='该机构已审核完成，不可再次审核'
REJECT 重放（期望 200 幂等）: HTTP 200 code=0 msg='ok'

### I-3 角色缺失
APPROVE 但 R-PARTNER 缺失（期望 400）: HTTP 400 code=40001 msg='角色未初始化，请先执行 seed_demo'
    -> org.status=PENDING user.status=LOCKED roles=[]

### 门户
GET /portal/home（新审核账号）: HTTP 200 code=0 msg='ok'
    -> org: R2 契约形状大学 | 指南: ['2026 年度国家自然科学基金申报指南（演示）']
GET /portal/org: HTTP 200 code=0 msg='ok'

### C-2 指南
partner GET /apply/guidelines?size=50: HTTP 200 -> [(1, '...演示)', 'PUBLISHED')]
partner GET ?status=DRAFT（应被忽略）: HTTP 200 -> [(1, 'PUBLISHED')]
partner 读 tenant-1 DRAFT id=2（期望 404）: HTTP 404 code=40401 msg='记录不存在'
partner 读 tenant-2 PUBLISHED id=3（期望 404）: HTTP 404 code=40401 msg='记录不存在'
partner 读 tenant-2 DRAFT id=4（期望 404）: HTTP 404 code=40401 msg='记录不存在'
partner 读 tenant-1 PUBLISHED id=1（期望 200）: HTTP 200 code=0 msg='ok'
R-STAFF 读 tenant-1 DRAFT id=2（期望 200）: HTTP 200 code=0 msg='ok'
R-STAFF 读 tenant-2 id（期望 404）: HTTP 404 code=40401 msg='记录不存在'
R-STAFF 列表（可选 status）: HTTP 200 -> [(2, 'DRAFT'), (1, 'PUBLISHED')]
R-STAFF ?status=DRAFT: HTTP 200 -> [(2, 'DRAFT')]
R-FINANCE 读 tenant-1 DRAFT id=2: HTTP 404 code=40401 msg='记录不存在'   # N-1
R-AUDITOR 读 tenant-1 DRAFT id=2: HTTP 404 code=40401 msg='记录不存在'   # N-1

### 跨租户审核 / 列表隔离
tenant-1 manager 审核 tenant-2 机构（期望 404）: HTTP 404 code=40401 msg='机构不存在'
tenant-1 manager 机构列表: HTTP 200 -> tenant 集: [1] ids: [5, 4, 3, 2, 1]

### I-5 信用代码
重复 credit_code 注册（期望 409/40901）: HTTP 409 code=40901 msg='机构或用户名已注册'
小写 credit_code 注册（应归一为大写）: HTTP 200 -> 存库: 91310000MA1K3XY66N
PASS: 库层 UniqueConstraint 生效 -> UNIQUE constraint failed: sys_partner_org.tenant_id, sys_partner_org.credit_code
PASS: deleted=1 的同码行可插入（软删不占槽）
PASS: 不同租户同码允许

### I-6 后端必填
缺少 contact_phone 注册（期望 400）: HTTP 400 code=40001 msg='联系电话不能为空'
缺少 contact_email 注册（期望 400）: HTTP 400 code=40001 msg='联系邮箱不能为空'
缺少 real_name 注册（期望 400）: HTTP 400 code=40001 msg='姓名不能为空'

### 403 真实性（契约新增声明）
R-STAFF GET /portal/home（期望 403）: HTTP 403 code=40301 msg='无权限'
R-STAFF POST audit（期望 403）: HTTP 403 code=40301 msg='无权限'
R-STAFF PUT /portal/org（期望 403）: HTTP 403 code=40301 msg='无权限'   # 契约未声明（N-4）
R-FINANCE GET /portal/home: HTTP 403 code=40301 msg='无权限'
```

`ARK_PARTNER_SIGNUP_TENANT=7` 独立进程复跑：

```
settings.PARTNER_SIGNUP_TENANT_ID = 7
register: 200 {"code": 0, ...}
落库 tenant_id = 7 （body 里塞的是 1）
```

---

## 7. 附录 B：探针说明与两个坑

`/tmp/r2_e2e.py` 做的事：建 client → 4 个种子账号登录取 JWT → 表单同形注册（带 `tenant_id=2`）→ 未审核登录 → 注册第二家并 REJECT（查 `mail.outbox`）→ APPROVE / 重放 / APPROVED→REJECT / REJECTED→APPROVE / REJECT 重放 → 删角色后 APPROVE → 审核后登录 + `/portal/home` + `/portal/org` → partner 指南列表/DRAFT/跨租户 → R-STAFF、R-FINANCE、R-AUDITOR 对照 → 跨租户审核与列表隔离 → 重复码/小写码/ORM 直插/deleted=1/跨租户同码 → 缺 phone/email/real_name → 403 三连。

两个**探针自身**的坑（记录在此以免后人误判为产品缺陷）：

1. `mail.outbox` 只在 locmem 后端**首次实例化**时由 `EmailBackend.__init__` 创建（`django/core/mail/backends/locmem.py:23-24`）；不 `setup_test_environment()` 直接 `mail.outbox.clear()` 会 `AttributeError`。已改为先实例化一次后端。
2. 为造"角色缺失"场景删除 `SysRole(code="R-PARTNER")` 时，`sys_user_role` 因 FK `CASCADE` 被一并删除，导致**后续同一账号登录拿不到角色 → `/portal/home` 误报 403**。已在 `finally` 里重建角色并把 `(user_id, tenant_id)` 授权逐条还原（实测"恢复 2 条授权"）后复跑通过。这不是产品缺陷；但顺带确认了一件真实行为：删角色会连带撤销所有已授该角色的用户授权（符合预期）。

---

## 8. 已裁定不重开（本轮未计入任何意见）

1. `sys_notification` 不补 DDL；
2. 门户未读通知卡不跳转；
3. 迁移编号 0008–0011 不重排；
4. mock 层无错误通道（冲突仅 `console.warn`，不改数据）。

---

## 9. 合并建议

- **判定：APPROVED_WITH_MINOR，可合并。**
- 合并说明中请登记三条"已知行为"，避免后续被当 bug 重报：
  1. 指南 DRAFT 仅 `R-ADMIN/R-MANAGER/R-LEADER/R-STAFF` 可见，R-AUDITOR/R-FINANCE/R-EXPERT/R-ETHICS 与外部角色一律 404（N-1）；
  2. 公开注册的租户由 `ARK_PARTNER_SIGNUP_TENANT` 决定，请求体 `tenant_id` 被忽略（I-4 的预期行为）；
  3. 审核状态机只允许 `PENDING → APPROVED|REJECTED`；同动作重放 200，跨动作 409。
- 建议下一个期次顺手清掉 N-1、N-4、N-6（各几行），并把 M-8/M-9 一起收掉。
