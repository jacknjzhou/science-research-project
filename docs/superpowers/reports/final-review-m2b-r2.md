# M2-b 第二轮终审（R2）：修复复核报告

- 评审对象：`2c8d982..e573c19`（4 个提交：`701f20f` / `f02733b` / `01e8855` / `e573c19`），HEAD = `e573c19`，18 files，+517/−32
- 复核依据：`docs/superpowers/reports/final-review-m2b.md`（r1）、`/tmp/review-m2b-fix.diff`、`design/01-项目申报与立项-P.openapi.yaml`、`design/02-项目过程管理-E.openapi.yaml`、`design/12-用户与权限-U.openapi.yaml`
- 复核方式：**只读源码 + 真实 HTTP（`django.test.Client` + 真 JWT + 真 casbin + 真迁移库）**。未修改任何源码、未提交；本文件是唯一写入产物。
- 评审角色：独立复审（非 r1 作者、非开发方）
- 探针：`/tmp/m2b_r2_probe.py`（97 项断言，独立 sqlite 库，跑前删库重建 + `seed_demo`），另有 7 个一次性最小复现脚本。脚本**未入库**。

---

## 0. 结论

**REQUEST_CHANGES — 不可合并。**

- r1 的 C1/C2/C3、I1/I2/I4 主体**确实关闭**（真实 HTTP 复核，非读码推断）；I3 的**出参**契约键已补齐，但**入参方向仍与契约相反**。
- **C4 未关闭**：`assign_role` 仍可把内部角色追加到已存在的 R-PARTNER 账号；并且空机构外部账号仍可**写**（建申报/建指南建议），C4 只补了读侧。
- 新增 **1 个 Critical**：任务书生成端点 `POST /apply/task-books` 未纳入机构收口，混合外部账号可跨机构读取他机构申报的完整 `content_snapshot`（含研究目标/技术路线/预算）与已签任务书——C1 的"404 不泄露"被同一类入口绕过。
- 新增 **5 个 Important**：授权一致性未闭环导致并集越权与 AI 引用泄露、02-E 创建接口拒收契约形状、空机构写入口、PI 有效性/改派缺失造成永久死锁、契约 `UserRequest` 缺 `org_id`。
- 新增 9 个 Minor（见 §3.2），均不单独阻断，但 M-2 的 500 与 M-3 的孤儿任务书建议一并修。
- 无"必须回滚"的回归：院内正常双签链路、seed、迁移、既有测试全部通过；新增 7 条回归用例在修复前**真红**（见 §5）。

---

## 1. 复核方法与证据基座

| 维度 | 做法 |
|---|---|
| 静态 | 逐文件读 HEAD 的 `apps/p/api.py`、`apps/sysadmin/api.py`、`apps/sysadmin/mappings.py`、`apps/project/api.py`、`apps/project/mappings.py`、`core/org_scope.py`、`config/api.py`、`config/casbin/policy.csv`、迁移 `0013_resync_permissions`、`TaskBookView.vue`/`ProjectReportView.vue`、三份契约 |
| 动态 | 独立 sqlite 库 `/tmp/m2b_r2_probe.sqlite3`：`migrate` + `seed_demo`，用 `django.test.Client` 走真实路由/中间件/casbin；`gen_token` 造真实 JWT（`tests/conftest.bearer`） |
| 角色 | 纯外部（R-PARTNER, orgA/B/null）、混合（R-PARTNER+R-STAFF）、院内（R-STAFF/R-MANAGER/R-LEADER/R-ADMIN）、只读（R-AUDITOR） |
| 契约 | `cmp -s` 三份 design↔frontend 副本；`yaml.safe_load` 解析；用契约里的 camelCase 形状**真打**创建端点 |
| 迁移 | 空库全量 `migrate`；已 seed 库 `migrate sysadmin 0012` → `migrate` 回放 0013；两遍 `seed_demo` |
| 非恒真 | `git archive 2c8d982` 到 `/tmp/m2b_r2_prefix`，仅拷入 HEAD 的 `tests/test_p_m2b.py`，用同一 venv 跑，确认新用例在旧实现上失败 |

关键身份（探针库）：`admin=1`、`manager=2`（R-MANAGER+R-LEADER）、`staff=3`、`finance=4`、`partner=5`（org1）、`ub=6`（org3）、`upnull=7`（org=None）、`umulti=8`（R-PARTNER+R-STAFF, org3）、`upi_a=9`（org1 非 PI）、`umgr=10`、`uleader=11`。租户 1 下 org1=机构 A、org3=机构 B、org4=PENDING、org5=租户 2。

---

## 2. 逐条复核（C1–C4、I1–I4）

| # | r1 意见 | R2 判定 | 一句话证据 |
|---|---|---|---|
| **C1** | 申报子资源只按 tenant 过滤，外部可跨机构读写 | ✅ **PASS（清单内 8 个入口）**；覆盖缺口另立 **R2-C-1** | 机构 B 对机构 A 的 detail/documents/budget(GET+POST)/sections/submit 全 404，withdraw/terminate/ai-draft 403；机构 A 自己全 200 |
| **C2** | sign 只校验 role 字面值；signer_id 可伪造；PI 不校验本人 | ✅ **PASS**（附新风险 R2-I-4） | PI 非本人 403、跨机构 404、外部签 MANAGER 403；`signer_id` 完全忽略（记录 `[5,10]`）；双签后 EXECUTING |
| **C3** | REJECTED 可签；签后 terminate 留下项目 EXECUTING | ✅ **PASS**（附 Minor R2-M-3） | 非 PUBLISHED/DECIDED 签 → 409；已签 terminate/withdraw/sections/budget/submit 全 409，项目不变；终止后仍可生成孤儿任务书 |
| **C4** | 空机构 partner 命中院内 `applicant_org_id IS NULL`；建号无校验 | ❌ **FAIL** | 读侧已堵（列表空/子资源 404），但**写侧未堵**（空机构可建申报/建议），且 `assign_role` 可制造混合角色 |
| **I1** | 无 `:decide`，PUBLISHED 不可达 | ✅ **PASS** | SUBMITTED→PUBLISHED→生成任务书→双签全通；重复/非法/越权/跨租户分别 409/400/403/404 |
| **I2** | `is_external_only` 精确比较，混合角色走内部分支 | ✅ **PASS（P 域/指南）**；并集越权另立 **R2-I-1** | 混合账号列表只本机构、跨机构 404、建申报强制 pi=self/org=本机构；R-AUDITOR 仍可读 DRAFT 指南（未误伤） |
| **I3** | 02-E 契约 camelCase 与实现 snake_case 不一致 | ✅ **PASS（出参）**；入参方向另立 **R2-I-2** | `EProgressReport`/`EFinalAccept` 响应 `missing=[]`；前端注释已改对；但 camelCase **请求体**仍 400 |
| **I4** | R-LEADER 无 sign 策略；R-PARTNER 有越权面 | ✅ **PASS（handler 收口足够）**；策略残留见 R2-M-8 | R-LEADER/R-PARTNER 均可调 `:sign`，但 handler 限定 PI 本人 / 内部 R-MANAGER|R-LEADER；partner 只能签自己 PI 的那一份 |

### 2.1 C1 申报子资源机构收口 —— PASS（清单内）

真实 HTTP（机构 B 的纯 R-PARTNER 账号 `ub` 访问机构 A 的 `app2`）：

| 入口 | 结果 | 响应 |
|---|---|---|
| `GET /apply/applications/2` | **404** | `{"code":40401,"message":"记录不存在"}` |
| `GET /apply/applications/2/documents` | **404** | 同上 |
| `GET /apply/applications/2/budget` | **404** | 同上 |
| `POST /apply/applications/2/budget` | **404** | 同上 |
| `PUT /apply/applications/2/sections/background` | **404** | 同上 |
| `POST /apply/applications/2/submit` | **404** | 同上 |
| `POST /apply/applications/2:withdraw` | **403** | `{"code":40301,"message":"无权限"}`（policy 层先拒） |
| `POST /apply/applications/2:terminate` | **403** | 同上 |
| `POST /apply/ai/draft`（app2） | **403** | 同上（policy 层，见 R2-M-4） |

机构 A 自己（`partner=5`）同批入口：detail/documents/budget GET/budget POST/sections PUT/新建 DRAFT/submit 全 **200**；新建申报 `pi=self`、`applicant_org_id=1`、提交后 `SUBMITTED`。

代码：`_app_scoped_or_404`（`apps/p/api.py:339-352`）替换了 `:369 withdraw`、`:385 terminate`、`:443 documents`、`:451 budget GET`、`:474 budget POST`、`:503 section PUT`、`:531 submit`、`:567 ai_draft`。残留 `_get_app_or_404` 仅 `:276`（detail，external 已先走 `_partner_app_or_404`）、`:332`（partner helper 自身）、`:347`（scoped helper 自身），**逐个判断后均合理**。

> 但"覆盖所有该收口入口"不成立：`generate_task_book`（`:906-943`）用 `select_for_update().filter(...)` 内联查询，绕过了 `_get_app_or_404`，因此 grep 残留调用点看不到它 → 见 **R2-C-1**。

### 2.2 C2 签署身份 —— PASS

用**新建**的 PUBLISHED 申报 + 任务书（避开 seed 的 `tb1` 已带 PI 签名的假象）：

| 调用者 / 角色 | 签署 role | 结果 |
|---|---|---|
| 机构 B 的 R-PARTNER（`ub`） | PI | **404**（任务书不可见，不泄露存在性） |
| 机构 A 非 PI（`upi_a`） | PI | **403** `仅申报负责人本人可签署 PI` |
| 机构 A PI 本人（`partner=5`），body `signer_id=424242` | PI | **200**，记录 `{'role':'PI','signerId':5,...}` |
| 机构 A PI 再次签 PI | PI | **409** `该角色已签署` |
| R-PARTNER（机构 A） | MANAGER | **403** `仅 R-MANAGER 可签署 MANAGER` |
| R-STAFF（`staff=3`） | MANAGER | **403** 同上 |
| R-ADMIN（`admin=1`） | MANAGER | **403** 同上（handler 只认 R-MANAGER/R-LEADER） |
| R-MANAGER（`umgr=10`），body `signer_id=777` | MANAGER | **200**，`signerId=10`；记录 `[5,10]` |
| 双签完成 | — | app `EXECUTING`、tb `SIGNED`、project `EXECUTING` |

代码：`:1022` 先查同角色已签；`:1025` 完全忽略 `body.signer_id`；`:1026-1028` PI 必须 `d.user_id == a.pi_user_id`；`:1029-1034` MANAGER/LEADER 必须内部且持对应角色。顺序上"已签 409"先于"身份 403"（对同机构可见者会先看到已签，无信息增量）。

**未误伤院内**：`mgr 建 app pi=staff3 → staff3 submit → mgr decide → generate → staff3 PI 200 → manager2 MANAGER 200` 全通，app `EXECUTING`。**新风险**见 R2-I-4（PI 指向不存在/离职用户时永久卡死）。

### 2.3 C3 状态机 —— PASS

| 场景 | 结果 |
|---|---|
| `REJECTED` 申报的 tb，PI/MANAGER 签 | **409** `申报状态不允许立项` |
| `APPROVED` 申报的 tb，PI 签 | **409** 同上 |
| 已双签（app EXECUTING）`:terminate` | **409** `任务书已签订，申报内容不可修改`；app 仍 `EXECUTING`，`EProject` 仍 `EXECUTING` count=1 |
| 已双签 `:withdraw` | **409** `当前状态不可撤回，已进入评审的申报只能终止` |
| 已双签 sections PUT / budget POST / submit | **409**（冻结生效） |
| `PUBLISHED` app5 `:terminate` | **200** → `REJECTED`；随后 `:sign` **409** |
| 终止后的 app5 `POST /apply/task-books` | **200**，返回 id=5 的孤儿 `DRAFT` tb（见 R2-M-3） |

代码：`_TERMINABLE`（`:317-320`）已移除 SIGNED/EXECUTING；`terminate`（`:386-394`）先 `_assert_application_mutable` 再判状态；冻结判定在 `:1092-1100`，被 `:386/:475/:504/:532` 复用。"签后终止"无成功路径，**未发现不一致数据路径**（除 R2-M-3 的孤儿 tb）。

### 2.4 C4 空机构 —— FAIL

**读侧已关闭**：
- `upnull`（org=None 的 R-PARTNER）`GET /apply/applications` → `{"list":[],"total":0}`；院内 `app1` 的 documents/budget GET/budget POST → **404**；`guide-suggestions` 列表 `total=0`。

**建号入口已关闭（正向）**：
| 请求（R-ADMIN） | 结果 |
|---|---|
| `roles=["R-PARTNER"]` 无 `org_id` | **400** `外部机构角色必须绑定机构（org_id）` |
| `roles=["R-PARTNER","R-STAFF"]`, org=1 | **400** `外部机构角色 R-PARTNER 不能与内部角色共存：R-STAFF` |
| `roles=["R-PARTNER"]`, org=1 | **200** `org_id=1, user_source=EXTERNAL, roles=[R-PARTNER]` |
| `roles=["R-PARTNER"]`, org=99999 | **400** `机构不存在或跨租户` |
| `roles=["R-PARTNER"]`, 租户 2 的 org | **400** 同上 |
| 给院内 R-STAFF 授 R-PARTNER | **400**（混合拦截） |

**未关闭（FAIL 的两条）**：
1. **空机构仍可写**：`upnull` `POST /apply/applications {"title":"无机构申报"}` → **200**，落库 `id=9, applicant_org_id=None, applicant_type=EXTERNAL, status=DRAFT`；`create_application` 在 `:286-288` 只强制 `pi=self`，`:305` 直接写 `current_org_id(d)`（None），**无兜底**。该记录进入院内 `applicant_org_id IS NULL` 空间，本人却读不到（detail 404），成为孤儿/污染。同型漏洞在 `create_guide_suggestion`（`apps/p/api.py:781-789`）：`upnull` POST 建议 → **200**，`org_id=None, status=PENDING`，院内 R-MANAGER 列表 `total` 由 1 变 **2**。
2. **`assign_role` 未闭环**：对已存在的 R-PARTNER 账号 `POST /admin/users/{id}/roles {role_id: R-STAFF}` → **200**，`role_codes_of` 变 `['R-PARTNER','R-STAFF']`、`user_source=EXTERNAL`。`apps/sysadmin/api.py:302-304` 只在**新增角色是 R-PARTNER** 时调 `_assert_role_consistency`；反向追加内部角色不校验。docstring（`:131-137`）却写"两条都在授权入口拦死"。

> 结论：C4 只闭合了"读"和"建号"，没有闭合"写"和"角色变更"。这是 r1 C4 的原始范围（"含 `assign_role`"）明确要求的，故判 **FAIL**。

### 2.5 I1 `:decide` —— PASS

| 场景 | 结果 |
|---|---|
| 纯 R-PARTNER `:decide` | **403**（policy 无行） |
| R-STAFF `:decide` | **403**（policy 宽行放行，handler 拒） |
| R-ADMIN `:decide` | **403**（handler：仅 R-MANAGER/R-LEADER） |
| `decision=APPROVED` | **400** `decision 须为 PUBLISHED 或 DECIDED` |
| R-MANAGER `decision=PUBLISHED` | **200**，status=PUBLISHED，modifier=10 |
| 重复决定 | **409** `当前状态不可作出评审决议` |
| 真 DRAFT 申报 | **409** 同上 |
| 跨租户申报 | **404** |
| R-LEADER `decision=DECIDED` | **200** |
| decide 后 `POST /apply/task-books` | **200**（id=6） |
| 之后 PI 签 + MANAGER 签 | 均 200 → app `EXECUTING`，project 7 `EXECUTING` |

代码 `:948-992`：`_DECIDE_TARGETS`/`_DECIDABLE`、非法 decision 400、外部或非管理/领导 403、`select_for_update` 后状态 409、`_notify` 给 PI。策略行 `config/casbin/policy.csv:903-904` 仅 R-MANAGER/R-LEADER；seed 后 DB 权限 `apply.applications.x:decide.post` 也仅这两个角色持有。

> 注：契约里 `comment` 字段被 handler 忽略（R2-M-6）。

### 2.6 I2 fail-closed —— PASS（P 域与指南）

- 混合账号（`umulti`, R-PARTNER+R-STAFF, org3）：`GET /apply/applications` 只有本机构 1 条；跨机构 detail/documents 404；`POST /apply/applications` **200** 且强制 `pi=8`、`applicant_org_id=3`、`applicant_type=EXTERNAL`（忽略请求体里的 pi/org）；自有 section PUT 200。
- 指南：纯外部与混合都只见 PUBLISHED（"已发布指南R2" + seed 已发布）；`R-AUDITOR` 仍能读到 DRAFT（200，含"草稿指南R2"）→ **内部只读角色未被误伤**，M2-a 的 `_guideline_status_scope` 行为一致。
- 代码：`core/org_scope.py:26-32` `return _EXTERNAL_ROLE in roles`；`apps/p/api.py:81-90` 指南 scope 同样 `has_role(roles, _EXTERNAL_ROLE)`。

**但系统级仍有并集放大**：同一混合账号可读院内 `/expenses`、`/staff`、`/output`、`/budgets`（见 R2-I-1）。P 域的"外部口径"成立，其他域没有调用该口径。

### 2.7 I3 02-E 契约键 —— PASS（出参）

- `EProgressReport` 契约 props：`attachmentIds, contentRich, id, issuesText, nextPlan, period, progressPercent, projectId, reportType, status, submittedAt`；真实响应 **missing=[]**。
- `EFinalAccept` 契约 props：`id, projectId, applyAt, acceptAt, outputSummary, templateId, approvalDocId, financeReportId, expertIds, conclusion, attachmentIds, archiveChecklistId, status`；真实响应 **missing=[]**。
- 前端 `ProjectReportView.vue:6` 注释已改为"后端当前返回 snake_case（并同时补了契约 camelCase 别名）"，不再说反。
- 但**入参**未闭环：按契约 POST 仍 400（R2-I-2）。故本项只对"响应键/别名/注释"判 PASS。

### 2.8 I4 签署策略 —— PASS（handler 足够）

DB 权限（seed + 0013 后）：

| 角色 | `POST .../task-books/1:sign` | `POST .../applications/1:decide` |
|---|---|---|
| R-LEADER | **True** | True |
| R-PARTNER | True | **False** |
| R-STAFF | True（`/apply/* POST` 宽行） | True（同宽行） |
| R-MANAGER | True | True |

R-PARTNER 的 `:sign` 行（`policy.csv:891`）修复前就存在，**不能**在策略层直接删除：外部 PI 签署自己机构的 PI 是业务必需。handler 已把越权面收到"只能签自己作为 PI 的任务书"，MANAGER/LEADER 还要求内部角色，实测外部/院内非管理者全部 403。**判断：handler 收口足够，策略层无需收窄该行**；策略层可收窄的是 R-STAFF 的 `/apply/* POST` 宽行（R2-M-8），属纵深防御。

---

## 3. 新发现问题

### 3.0 Critical

#### R2-C-1 任务书生成未收口：混合外部账号可跨机构读取申报快照与已签任务书

- 文件：`backend-django/apps/p/api.py:906-943`（内联查询 `:914-919`；`exist` 分支 `:920-922` 早于状态检查 `:923-926`）；`config/casbin/policy.csv:16`（R-STAFF `/api/v1/apply/* POST`）
- 复现（真实 HTTP，探针库；`umulti` = R-PARTNER+R-STAFF，org3；`app2` 属 org1）：

```python
u = SysUser.objects.get(username="umulti")
tok = bearer(u.id, ["R-PARTNER", "R-STAFF"])
r = Client().post("/api/v1/apply/task-books",
                  data=json.dumps({"application_id": 2}),
                  content_type="application/json", **tok)
```

- 实测（**HTTP 200**，返回的是机构 A 的 tb1）：

```
{'id': 1, 'status': 'DRAFT', 'application_id': 2,
 'content_snapshot': {'title': '智能育种联合建模（外部机构申报·演示）',
                      'pi_user_id': 5, 'applicant_org_id': 1,
                      'total_budget': '300000.00', 'duration_months': 24,
                      'research_target': '表型-基因型联合建模方法',
                      'technical_route': '多组学特征融合 + 迁移学习',
                      'expected_output': '论文 2 篇、工具链 1 套'},
 'sign_records': [{'signerId': 5, 'role': 'PI', ...}]}
```

  同一账号对院内已执行申报 `app17` 调同一端点，也返回 **200** 的已签任务书（tb9，`sign_records=[PI 3, MANAGER 2]`）——机构 3 的外部账号读到了院内项目的任务书。

- 影响：C1 建立的"跨机构一律 404、不泄露存在性"在同域的另一入口被绕过；泄露内容包含研究目标、技术路线、预算、PI、签署记录。**前置条件**是存在混合角色账号——而该账号可被 `assign_role` 造出来（R2-I-1），两个缺陷串成一条现实攻击链。纯 R-PARTNER 在 policy 层被 403，所以不是"任意外部账号"直接可用，但一旦混合账号存在即为 Critical。
- 为什么 grep 没抓到：该端点用 `PApplication.objects.select_for_update().filter(...)` 内联查询，**没有**调用 `_get_app_or_404`，所以"残留调用点"清单里看不到它；`_app_scoped_or_404` 的 docstring（`:340`）自称"申报读写的**唯一**入口"，与事实不符。
- 修法：
  1. 生成端点改用 scoped 入口（需保留行锁：可加 `_app_scoped_for_update_or_404(d, aid)`，或先在事务内 `_app_scoped_or_404` 再 `select_for_update` 重取）；
  2. 创建任务书限定内部 R-MANAGER/R-LEADER（policy 收窄 + handler `has_role` 双保险）；
  3. `exist` 分支先判 `a.status in _TASK_BOOK_GENERATABLE`，再返回/创建（同时修 R2-M-3）；
  4. 回归用例：混合账号跨机构 POST → 404；纯外部 → 403；院内正常 → 200。

### 3.1 Important

#### R2-I-1 授权一致性未闭环：`assign_role` 可造混合角色，进而并集越权与 AI 引用泄露

- 文件：`backend-django/apps/sysadmin/api.py:302-304`（只在新增 R-PARTNER 时校验）、`:128-153`（docstring 声称"两条都在授权入口拦死"）、`:157-186`（`create_user` 对非 R-PARTNER 不校验 org/user_source 一致性）；`core/org_scope.py:26-32`；`apps/p/api.py:578-582`（AI 引用查询无机构过滤）
- 复现与实测：

```
POST /api/v1/admin/users/8/roles {"role_id": <R-STAFF>}   -> 200
role_codes_of(8) = ['R-PARTNER','R-STAFF']; user_source = EXTERNAL
GET /api/v1/expenses  -> 200  (EXP-DEMO-0002 ...)
GET /api/v1/staff     -> 200  (STU-DEMO-01 ...)
GET /api/v1/output    -> 200
GET /api/v1/budgets   -> 200  (BUD-DEMO-M1C-01 ...)
纯 R-PARTNER 对同四路径 -> 403
POST /api/v1/apply/ai/draft {"application_id": <自有>, "section_code": "background"}
  -> 200 references=[{"project_code":"PRJ-17","title":"院内正常课题"},
                     {"project_code":"PRJ-16","title":"院内死锁课题"}]
```

- 影响：以"外部机构账号"身份读到院内经费/人员/成果/预算数据；`ai_draft` 把院内项目标题作为"参考"返回给外部账号。这直接击穿 Review Focus ⑤。另：`create_user` 允许 `user_source=EXTERNAL` + `roles=["R-STAFF"]` + 任意 `org_id`（实测 200），说明"外部来源"与"外部权限"没有绑定关系。
- 修法：
  1. 把校验下沉为 `assert_role_consistency(tenant, final_roles, org_id)`，在 `create_user`、`assign_role`（**无论新增哪个角色**，用 `existing ∪ {new}`）、`revoke_role` 后都调用；对已存在的混合账号，登录/取 token 时拒绝或降级；
  2. 规则补全：含 R-PARTNER ⇔ 必须有效 org 且 `user_source=EXTERNAL`；不含 R-PARTNER 且 `user_source=EXTERNAL` 应 400；
  3. `ai_draft` 的 references 对 `is_external_only` 过滤 `applicant_org_id == current_org_id(d)`（或直接不返回 references）；
  4. 增加"通过 `assign_role` 追加内部角色必须 400"的回归用例——当前 7 条新测试没有覆盖这个入口，所以全绿掩盖了漏洞。

#### R2-I-2 02-E 创建接口拒收契约形状（I3 只修了出参）

- 文件：`backend-django/apps/project/api.py:280-284`（只读 `period/report_type/progress_percent/content_rich/...`）；契约 `design/02-项目过程管理-E.openapi.yaml:1096-1106`（`EProgressReportCreate` 必填 `period/reportType/progressPercent`，全 camelCase）
- 复现（R-STAFF，真实 HTTP）：

```
POST /api/v1/project/7/progress-report
{"period":"2026Q1","report_type":"SELF","progress_percent":30,"content_rich":"x"}
-> 200, id=4

POST 同端点，契约形状
{"period":"QUARTER","reportType":"SELF","progressPercent":30,"contentRich":"x"}
-> 400 {"code":40001,"message":"请求参数错误"}
```

- 影响：任何按契约生成的客户端/第三方集成 100% 失败；前端 `ProjectReportView.vue:18-30` 自己用 snake_case，所以 UI 正常，掩盖了契约违约。I3 的修复只对 GET 做了双拼写，POST 没做。
- 修法：`body.get("reportType") or body.get("report_type")` 等六个键全部双读（`create_progress_report`）；`create_final_accept` 已是双读，可作为模板；补一条"契约形状 POST → 200"的测试。

#### R2-I-3 空机构外部账号仍可写入：建申报、建指南建议

- 文件：`backend-django/apps/p/api.py:284-305`（create_application 无 org 兜底）、`:781-789`（create_guide_suggestion 同型）
- 复现与实测：

```
upnull (id=7, org_id=None, R-PARTNER)
POST /api/v1/apply/applications {"title":"无机构申报"}
-> 200, id=9, applicant_org_id=None, applicant_type=EXTERNAL, status=DRAFT

POST /api/v1/apply/guide-suggestions {"title":"无机构建议"}
-> 200, id=2, org_id=None, status=PENDING
R-MANAGER GET /apply/guide-suggestions -> total=2（含这条）
```

- 影响：污染院内 `applicant_org_id IS NULL` 与 `org_id IS NULL` 空间；记录对创建者本人不可见（404），成为"写入即孤儿"；内部列表/统计会看到无机构的外部数据。C4 的回归用例只锁了读侧，所以没红。
- 修法：`if external and current_org_id(d) is None: raise ApiError(403, ..., "外部账号未绑定机构，无法申报")`（申报/建议/上传等所有写入口统一）；或建号时强制 org 非空并在登录时拒绝无 org 的外部账号。

#### R2-I-4 PI 有效性缺失且无改派入口：一次错误赋值造成永久死锁

- 文件：`backend-django/apps/p/api.py:285-291`（内部建申报时 `pi_user_id` 直接取 body，不校验存在/同租户/在职）、`:1026-1028`（PI 必须 `d.user_id == a.pi_user_id`）；`config/api.py` 无更新申报 PI 的路由
- 复现与实测：

```
staff 建 app pi_user_id=999999 -> 200
submit -> 200; R-MANAGER decide -> 200; generate task-book -> 200
staff(3) 签 PI -> 403 "仅申报负责人本人可签署 PI"
umgr(10) 签 PI -> 403 同上
umgr 签 MANAGER -> 200
=> tb 停在 DRAFT，只有 MANAGER 记录；app 停在 PUBLISHED
=> 无任何 API 可改 pi_user_id，永远无法完成 PI 签署
```

- 影响：单条申报永久卡死；PI 离职/停用/跨租户 id 碰撞同理。C2 把"可伪造签署人"改成了"不可恢复的错绑"，是修复引入的**可用性回归**（安全性本身提升）。
- 修法：建/改申报时校验 PI 存在、同租户、`status=ACTIVE`；增加"变更负责人"端点（R-MANAGER 限定、仅签前、留审计）；或允许 R-MANAGER 在 PI 不可用时以 `role=PI, signerId=pi_user_id` 代签并记录 `onBehalfOf`，同时写审计。补死锁回归用例。

#### R2-I-5 契约 `UserRequest` 缺 `org_id`/`user_source`，契约客户端无法创建外部账号

- 文件：`design/12-用户与权限-U.openapi.yaml:1079-1091`（`UserRequest` 只有 username/real_name/password/email/phone/staff_no/security_level/employment_status/roles）；`UserUpdateRequest:1092-1099` 同样没有
- 实测：响应 `User` 已有 `org_id`/`user_source`（`:1074-1075`），但创建请求没有；而 `create_user` 对 R-PARTNER 强制要求 `org_id` → **按契约生成的客户端永远 400**。
- 修法：`UserRequest` 增 `org_id`（nullable int64）与 `user_source`（enum，可选，默认按角色推导）；`UserUpdateRequest` 至少增 `org_id`；同步 `frontend/src/api/schema/12-...yaml`（`cmp` 必须仍一致）。补契约形状测试。

### 3.2 Minor

| # | 问题 | 位置 | 实测 / 说明 | 建议 |
|---|---|---|---|---|
| R2-M-1 | PENDING 机构可建号/授角色 | `apps/sysadmin/api.py:148-153` 只查 `deleted=0` | `org_id=<PENDING org>` + R-PARTNER → **200** | 加 `status="APPROVED"`；PENDING 应 400 |
| R2-M-2 | `org_id` 非数字 500；内部建号不校验 org | `:181-182`（`int(org_id)`）、`:149`（仅 partner 校验） | `org_id="abc"` → **500** `ValueError` 栈；`roles=["R-STAFF"], org_id=99999` → **200** 悬挂引用 | 先做类型/存在性校验（任何角色只要给 org）；非法 → 400 |
| R2-M-3 | 终止后仍可生成/读取孤儿任务书 | `apps/p/api.py:920-926`（exist 早于状态） | app5 终止后 `POST /apply/task-books` → **200** id=5 `DRAFT`；对已执行 app17 也 200 返回已签 tb | 状态检查前置；或 terminate 时软删 DRAFT tb |
| R2-M-4 | 纯 R-PARTNER 无 `ai/draft` 策略行（既有缺口） | `policy.csv` 无 R-PARTNER `/apply/ai/draft` | 机构 A 自己调也 **403**；`_app_scoped_or_404` 在 ai_draft 对纯外部是死代码 | 补 policy 行（R-PARTNER POST ai/draft）并让 references 按机构过滤 |
| R2-M-5 | 多余契约外键 `outputSummaryText` | `apps/project/mappings.py:144` | 响应多一个契约没有的键 | 删除 |
| R2-M-6 | `decide` 忽略契约 `comment` | `apps/p/api.py:955-986`；契约 `01:658` | 传 comment 不落库、不进通知 | 持久化到审计/通知，或从契约删字段 |
| R2-M-7 | 陈旧/重复注释 | `apps/p/api.py:71-73`（仍写 fail-open 的"纯外部"）、`:81-83`（docstring 与实现相反）、`:318-319`（同句重复两遍）；`core/org_scope.py:30-34`（称混合"业务上不是合法形态"，但 assign_role 允许） | 读码即可确认 | 随 R2-I-1 一并改 |
| R2-M-8 | R-STAFF 宽策略 `/apply/* POST` 覆盖 decide/sign/create-taskbook | `policy.csv:16`；`apps/p/api.py:906-943` 无角色校验 | `staff(3)` `POST /apply/task-books` → **200** id=10 `DRAFT`（任意 PUBLISHED 申报，含他机构）；decide/sign 已被 handler 拒 | policy 收窄到具名端点；handler 加 R-MANAGER/R-LEADER 校验（与 R2-C-1 一起修） |
| R2-M-9 | 前端 `period` 自由文本 vs 契约 enum | `frontend/src/views/portal/ProjectReportView.vue:18-30`；契约 `02:1100` | 前端可发 `2026Q1`，契约只允许 QUARTER/HALF_YEAR/YEAR | 前端改下拉，或契约放宽（二选一并保持一致） |

**无 Critical 之外的系统性回归**：院内创建→提交→决议→生成→双签全链路 200/409 符合预期；seed 账号（含 partner=5）在新增校验下均可用（seed 走 ORM，不经过 create_user 校验）。

---

## 4. Review Focus 五项判定

| # | Focus | 判定 | 依据 |
|---|---|---|---|
| ① | 外部跨机构读申报/任务书/项目/汇报/验收 | ❌ **FAIL（一条路径）** | 申报子资源/项目/汇报/验收均 404（`_partner_app_or_404`、`_partner_project_or_404`）；但**任务书生成**端点未收口，混合外部账号可读他机构申报快照与已签任务书（R2-C-1） |
| ② | 一次立项两个项目 | ✅ **PASS** | `_create_project_from_task_book` 按 `application_id` 幂等（`:1067-1071`）；实测双签后 `EProject.objects.filter(application_id=...)` 仅 1 条；重复签被 409/状态锁挡住 |
| ③ | 请求体改 PI/机构 | ✅ **PASS（P 域）** | 外部/混合建申报强制 `pi=self`、`applicant_org_id=current_org_id`（`:284-307`），实测请求体传他人 pi/他机构 org 均被覆盖；签署 `signer_id` 100% 忽略。**但**内部建申报可传任意 `pi_user_id` 且无校验 → R2-I-4 |
| ④ | 签后改内容 | ✅ **PASS** | 已签/执行中 sections PUT、budget POST、submit、terminate、withdraw 全 409；app/project 状态不变（实测）；遗留 R2-M-3（终止后孤儿 tb）不构成"改动已签内容" |
| ⑤ | 外部误入涉密/管理域 | ❌ **FAIL** | 纯 R-PARTNER 被 policy 挡住；但混合账号（assign_role 可造）可读院内 `/expenses`、`/staff`、`/output`、`/budgets`，AI 起草还泄露院内项目标题（R2-I-1） |

---

## 5. 实跑数字

| 命令 | 结果 |
|---|---|
| `backend-django/.venv/bin/python -m pytest -q` | **404 passed, 7 warnings in 18.25s**，exit 0 |
| 非恒真验证：`2c8d982` 代码 + HEAD `tests/test_p_m2b.py` | **7 failed, 13 passed in 2.13s**（c1/c2/c3/c4×2/i1/i4 七条全红） |
| `makemigrations --check --dry-run` | **No changes detected**，exit 0（stderr 一条 PG 5432 连接被拒的既有 RuntimeWarning） |
| `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | exit **0**，无输出 |
| `cmp -s design/01… frontend/src/api/schema/01…` | exit **0**（IDENTICAL） |
| `cmp -s design/02… frontend/…/02…` | exit **0**（IDENTICAL） |
| `cmp -s design/12… frontend/…/12…` | exit **0**（IDENTICAL） |
| `yaml.safe_load`（01/02/12） | 三份均可解析；`paths` 计数 **40 / 26 / 27** |
| 空库 `migrate` | 全绿，含 `sysadmin.0012_resync_permissions … OK`、`0013_resync_permissions … OK` |
| `seed_demo` 第 1 遍 | `legal +2，staff +11，p +6，project +17，funding +23，output +7，expert +6，activity +4，archive +6，performance +6，transform +13，ethics +5，procure +8，asset +9，confsec +7，notify +5，partner +5，users +4，dicts +5，items +26，grants +78` |
| `seed_demo` 第 2 遍 | 仅 `seed_demo 完成（幂等）：`，**全 0** |
| 种子后基数 | users 5 / orgs 2 / roles 9；角色权限数 R-MANAGER **247**、R-LEADER **85**、R-PARTNER **28**、R-STAFF **131**、R-AUDITOR **25** |
| 0013 可重复性（已 seed 库） | `migrate sysadmin 0012`（Unapply OK）→ `migrate`（Apply OK）；权限数仍 247/85/28；再跑 `seed_demo` 仍全 0 |
| 探针断言 | **97 项，94 PASS / 3 FAIL**（3 FAIL = R2-I-3 的两条 + R2-I-2 的 camelCase） |

---

## 6. 合并门槛结论

**不可合并（REQUEST_CHANGES）。**

阻断项（修完需重新终审）：

1. **R2-C-1**（Critical）：任务书生成未收口，跨机构可读申报快照/已签任务书；
2. **R2-I-1**（Important）：`assign_role` 未闭环 + 混合角色读内部域 + AI 引用泄露；
3. **R2-I-3**（Important，C4 未闭合）：空机构外部账号可建申报/建建议；
4. **R2-I-2**（Important）：02-E 创建接口仍拒收契约形状；
5. **R2-I-4**（Important）：PI 无效/无改派 → 永久死锁；
6. **R2-I-5**（Important）：`UserRequest` 缺 `org_id`。

修法验收标准（建议直接写进回归测试，当前必须在旧实现上红）：

- 混合账号跨机构 `POST /apply/task-books` → **404**；纯外部 → **403**；院内 R-MANAGER/R-LEADER 正常 200；
- `assign_role` 给 R-PARTNER 追加任意内部角色 → **400**；给 `user_source=EXTERNAL` 授予内部角色 → 400；
- 空机构外部账号 `POST /apply/applications` 与 `/apply/guide-suggestions` → **403**；
- 契约形状 `POST /project/{id}/progress-report`（camelCase）→ **200**；
- 内部建申报 `pi_user_id` 不存在/跨租户 → **400**；新增改派端点后死锁链可恢复；
- `UserRequest` 补 `org_id` 后，契约形状建号 → **200**。

Minor 可留作 follow-up，但建议顺手修 R2-M-2（500）与 R2-M-3（孤儿任务书），成本极低。C1/C2/C3/I1/I2/I4 的修复方向与实测均成立，**不需要回滚**；本轮阻塞点是"覆盖不全 + 边界写入口 + 契约入参"三类收尾问题。
