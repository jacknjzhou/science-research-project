# M2-c 终审第 4 轮复审报告（独立复评）

- **复审范围**：`git diff 92625d0..27c1789`（1 commit，7 文件 +110/−17）
- **HEAD**：`27c17899845fc6bc66b36021492145a03f32c5a2`（`fix(m2c): 终审 r3——外部角色只授外部账号、R-PARTNER 恒按外部判据、E 域口径统一`）
- **上轮报告**：`docs/superpowers/reports/final-review-m2c-r3.md`（REQUEST_CHANGES，唯一阻断 I-1）
- **本轮定位**：只读复审 + 独立探针复现；未改任何源码、未 commit（临时文件全部在 `/tmp`）

## verdict

**APPROVED_WITH_MINOR**

> 一句话门槛：r3 唯一阻断 **I-1 已实质关闭**（管理端两步造态被 400 挡住，运行期对 ORM 写脏账号仍 fail-closed，官方 API 穷举无第三条造态路径），**I-2 同步关闭**；无 Critical。唯一 **Important** 是本轮修复的副作用——`assign_role` 连带拒绝 `R-EXPERT`，使管理端无法给院内账号加专家角色（专家审核流程可替代），建议下个提交把拒绝面收窄到 `R-PARTNER`，**不阻断本次合并**。

---

## 1. 门槛项 I-1：已关闭（双层证据）

### 1.1 入口层：管理端两步造态现在 400

实测（HEAD，探针 `test_p1_admin_two_step_blocked`）：

| 步骤 | 请求 | 实测 | 期望 |
|---|---|---|---|
| ① 建号 | `POST /api/v1/admin/users {"username":"r4_inner","roles":[],"org_id":<APPROVED>}` | **200**，DB `sys_user.user_source=INTERNAL`、`org_id=1` | 200（第一步本身合法） |
| ② 授 R-PARTNER | `POST /api/v1/admin/users/3/roles {"role_id":<R-PARTNER>}` | **400** `{"code":40001,"message":"外部角色只能授予外部账号（请先通过机构/专家注册流程建号）"}`，`sys_user_role` **无写入** | 400 |
| ② 授 R-EXPERT（对照） | 同上，role=R-EXPERT | **400**（同一条消息） | 计划书未要求（见 §5 Important-1） |

代码位置：`backend-django/apps/sysadmin/api.py:340-348`（`is_external_account_row = (u.user_source or "INTERNAL").upper() == "EXTERNAL"`；非外部账号 + `role.code in _EXTERNAL_ROLE_CODES` → 400），`_EXTERNAL_ROLE_CODES` 定义在 `backend-django/apps/sysadmin/api.py:129`。

### 1.2 运行期层：ORM 直接写脏仍 fail-closed

构造：`sys_user{user_source=INTERNAL, org_id=A}` + `sys_user_role{R-PARTNER}`，令牌 `roles=['R-PARTNER']`（`test_p3` / `test_p8` / `test_p7`）：

| 端点 | 实测 | 期望 |
|---|---|---|
| `GET /apply/applications` | **200**，`ids=[1]`（只有本机构 A 的申报；B 机构那条不可见） | 仅本机构 |
| `GET /apply/applications/{B机构申报}` | **404** `{"code":40401,"message":"记录不存在"}` | 404 |
| `GET /apply/applications/{A机构申报}` | **200** | 200 |
| `POST /apply/applications` body 伪 `pi_user_id=<staff>`、`applicant_org_id=<B>` | **200**，但落库 `pi_user_id=3(本人)`、`applicant_org_id=1(本机构 A)`、`applicant_type=EXTERNAL` | 强制本人/本机构 |
| `POST /apply/applications/{B机构申报}/budget` | **404** | 404 |
| `POST /project/{B机构项目}/progress-report` | **404** `{"message":"项目不存在"}` | 404 |
| `POST /project/{A机构项目}/progress-report` | **200** | 200（口径与 P 域一致） |
| 真实 `POST /auth/login` | **200**，JWT claims `roles=['R-PARTNER']`、`security_level=INTERNAL` | 登录后该账号被判外部 |

判据代码：`backend-django/core/org_scope.py:88-104`（`roles` 含 `R-PARTNER` 恒 `True`；否则 `user_source_of(d)`；无库内账号回退 `has_external_role`）。

### 1.3 入口穷举：确认没有第三条"外部角色 + 院内来源"造态路径

| 路径 | 实测 | 结论 |
|---|---|---|
| `create_user` `roles=["R-PARTNER"]`（`user_source` 缺省） | **200** 且落库 **EXTERNAL** | 造不出 |
| `create_user` `roles=["R-PARTNER"], user_source="INTERNAL"` | **200** 且落库 **EXTERNAL**（来源被强制覆盖） | 造不出 |
| `create_user` `roles=["R-EXPERT"], user_source="INTERNAL"` | **200** 且落库 **EXTERNAL** | 造不出 |
| `create_user` 绑 PENDING 机构（`roles=[]` / `["R-PARTNER"]` / `["R-EXPERT"]`） | **全部 400**「机构尚未通过资质审核」 | 造不出 |
| `assign_role` 给不存在用户 | **404**「用户不存在」 | 造不出 |
| `update_user` | 不改 `org_id`/`user_source`（`apps/sysadmin/api.py:238-259`） | 造不出 |
| `audit_partner_org` 直接 `SysUserRole.get_or_create(R-PARTNER)`（`apps/sysadmin/api.py:886-893`） | 只能命中"绑定到 PENDING 机构"的账号；而绑 PENDING 机构已被 `create_user` 400 挡住，自助注册建的是 `user_source=EXTERNAL`（`:779-815`），且全仓**无**改机构状态的写接口（`config/api.py:17-19` 只有 list/audit） | 不可达 |
| `audit_expert_application` → `_grant_expert_role`（`apps/expertreview/portal.py:206-222`） | **200** 且给 INTERNAL 账号写入 `R-EXPERT`（`user_source` 仍 INTERNAL） | 可达，但产出的是 `R-EXPERT` 而非 `R-PARTNER`，不触发 I-1 攻击面（见 §5 Important-1） |
| 直接 ORM 写 `sys_user.user_source` | 需库写权限，属威胁模型外；即便写脏，§1.2 已证明运行期仍 fail-closed | 可接受 |

**结论：I-1 关闭。** 入口拒绝 + 运行期 fail-closed 双保险成立，且 R-PARTNER 的脏状态在官方 API 面上已不可达。

---

## 2. I-2：已关闭

| 场景 | 实测 | 期望 |
|---|---|---|
| 院内专家（`user_source=INTERNAL`，令牌 `R-STAFF,R-EXPERT`）作为 PI：`POST /project/{id}/progress-report` | **200**（`test_p5`） | 200 |
| 同一账号 `GET /project/{id}/progress-report` | **200** | 200 |
| **外部**账号（`EXTERNAL`，`R-PARTNER`，org A）打他机构（`ext_org_id=B`）项目 `POST progress-report` | **404**「项目不存在」 | 404 |
| 外部账号打本机构（`ext_org_id=A`）项目 | **200**（未误伤合法外部） | 200 |

代码位置：`backend-django/apps/project/api.py:55`（import）与 `:279`、`:346`、`:755`、`:783` 均已改为 `is_external_account`；`is_external_only` 在 `apps/project/api.py` 已无调用点。

---

## 3. 三条新回归测试在 `92625d0` 上真红（已恢复并 `cmp` 校验）

做法：`git archive 92625d0` → `/tmp/m2c_r3base`，**只**把 HEAD 版 `tests/test_m2c_review_fixes.py`（+ 探针文件）覆盖进去，源码保持 `92625d0`；`cmp`/`diff` 校验三份文件一致（`TESTFILE_SAME_AS_HEAD`、`ORG_SCOPE_IS_92625d0`、`SYSADMIN_IS_92625d0`）。

| 用例 | `92625d0` 实测 | HEAD 实测 |
|---|---|---|
| `test_r3_assign_partner_role_to_internal_user_is_rejected` | **FAIL**，`tests/test_m2c_review_fixes.py:479`：`assert 200 == 400`（旧码授权成功） | PASS（400） |
| `test_r3_dirty_internal_partner_account_still_fails_closed` | **FAIL**，`:509`：`assert 200 == 404`（旧码跨机构读到正文） | PASS |
| `test_r3_internal_expert_pi_can_report_progress` | **FAIL**，`:532`：`assert 404 == 200`（旧码 E 域把院内专家当外部） | PASS（200） |

基线对照探针（同一文件，仅换源码）复现了 r3 描述的漏洞面：`GET /apply/applications` → **`ids=[2,1]`（A 租户下两个机构的申报全可见）**；院内专家 PI 阶段汇报 → **404**。HEAD 上分别变为 `ids=[1]` 与 **200**。

真红性质：3/3 均为**断言红**（非 ImportError/夹具错误），失败点与修复点一一对应，测试有判别力。

---

## 4. 上轮 Minor 残留逐条点名（m-1 … m-14）

| # | 上轮结论 | 本轮 HEAD 实测/静态核对 | 状态 |
|---|---|---|---|
| m-1 | 跨租户 uid 孤儿站内信 | `apps/notify/email.py:96-103` 仍按 `tenant_id+deleted=0` 过滤，不存在即 `return None` | **已修（维持）** |
| m-2 | `_notify_invitees` 取 `NExpert` 无 tenant；`set_mid_check_experts` 无租户 | `apps/expertreview/api.py:312-327`、`apps/project/api.py:1288-1294` 本轮**未改动**（diff 未触及） | **仍在** |
| m-3 | "邀请评审/发标"两例只断言 `len(outbox)`/subject，不校验 `to` | `tests/test_m2c_review_fixes.py:52-53` 仅 `len==1` + subject；`:91-92` 仅 `len>=1` + subject | **仍在** |
| m-4 | 侧栏 expert-apply 带 `R-STAFF` 死链 | `frontend/src/App.vue:216` 仍为 `['R-PARTNER','R-EXPERT']` | **已修（维持）** |
| m-5 | mock `W(['GET'])` 通配宽于 policy | `frontend/src/api/mock/overrides/auth.ts:33`、`:35`、`:50`、`:68`、`:117` 仍为 `/api/v1/* GET` 通配 | **仍在** |
| m-6 | `notify_user` 无 `channel` 形参、返回类型与计划书漂移 | `apps/notify/email.py:76-124`：签名仍无 `channel`，返回 `SysNotification|None` | **仍在** |
| m-7 | 通知 `typ="TODO"` 5 处 | 现有 5 处：`apps/procure/portal.py:157`、`:175`、`apps/procure/api.py:344`、`apps/expertreview/api.py:322`、`apps/expertreview/portal.py:122` | **仍在（未增未减）** |
| m-8 | 发标只找机构下 ACTIVE 账号邮箱，机构只有 `contact_email` 时 0 封 | `apps/procure/api.py:326-350` 未改：`GSupplier` 模型无 `contact_email` 字段（`apps/procure/models.py:43-69`），实际依赖 `SysUser.email`；机构 `contact_email`（`apps/sysadmin/models.py:237`）未参与 | **仍在** |
| m-9 | I-4 缺 BLACKLIST 负例 | `tests/test_m2c_review_fixes.py:402 test_r2_blacklisted_expert_cannot_reapply` 覆盖 | **实质关闭（维持）** |
| m-10 | `reject_reason = None` 死赋值 | 已改为注释 + 保留 `remark` | **已修** |
| m-11 | 复审复位清空 `remark` | `apps/expertreview/portal.py:94`：删除 `existing.remark = None`，注释「唯一驳回留痕，清空等于抹掉历史」 | **已修（本轮）** |
| m-12 | `_app_scoped_or_404` docstring 与行为相反 | `apps/p/api.py:368-375` 已改写为「持 R-PARTNER 一律按外部 fail-closed，其余看 `user_source`」 | **已修（本轮）** |
| m-13 | 每请求 +1 条 `sys_user` 查询 | 设计已知、可接受；本轮未改缓存实现 | **接受（维持）** |
| m-14 | 机构副本与 PI 邮箱同址时重复发信 | `apps/p/api.py:1053-1061` 新增 `if org and org.lower() == (pi_email or "").lower(): return` | **已修（本轮）** |

另：上轮 I-3（`apps/expertreview/api.py:227 list_reviews` 无 `tenant_id`）本轮**仍未修**，且不在本轮 diff 内——与上轮定性一致，**不计门槛**。

---

## 5. 本轮新发现

### Critical

无。

### Important

**Important-1｜`assign_role` 把 `R-EXPERT` 一并拒绝，管理端无法给院内账号加专家角色（功能收紧，非安全）**

- 位置：`backend-django/apps/sysadmin/api.py:340-348`（`role.code in _EXTERNAL_ROLE_CODES` → 400，而 `_EXTERNAL_ROLE_CODES = ("R-PARTNER","R-EXPERT")` 定义在 `:129`）
- 实测：
  - 院内账号（INTERNAL）授 `R-PARTNER` → 400（**期望**）；
  - 院内账号授 **`R-EXPERT`** → **400**，消息「外部角色只能授予外部账号（请先通过机构/专家注册流程建号）」；
  - 已经由专家审核获得 `R-EXPERT` 的院内专家，再走管理端重复授权 → 仍 **400**（非幂等，`test_p10`）；
  - 而同一状态经由 N 域审核可达：`POST /api/v1/experts {user_id:<INTERNAL staff>, source:"INTERNAL"}` → 200，`POST /api/v1/expert-applications/{id}/audit {action:"APPROVE"}` → **200** 且 `SysUserRole` 已写入 `R-EXPERT`、`user_source` 仍 INTERNAL（`test_p6`）。
- 影响：`frontend/src/views/admin/UsersView.vue:158` 的角色分配按钮对院内研究员点 `R-EXPERT` 必然 400，管理员只能改走「专家管理 → 新增 → 审核」；消息文案对 `R-EXPERT` 也不成立（院内专家是合法形态，见 `docs/superpowers/plans/2026-11-19-m2c-expert-supplier-channel.md:299`、`:329`，且 r2 `final-review-m2c-r2.md:110` 已把「院内 staff 授 R-EXPERT」记为已满足验收）。
- 为什么不算阻断：方向是「更严」，不会多给权限；计划书 `:194` 只要求单向（外部账号不得追加内部角色），本条属修复越界；替代路径真实可用且是计划书设计的正路。
- 建议（3 行）：把 `:343` 的判定收窄为 `role.code == "R-PARTNER"`（或 `"R-PARTNER" in _EXTERNAL_ROLE_CODES and role.code == _EXTERNAL_ROLE_CODE`），消息改为「R-PARTNER 只能授予外部机构账号」；补一条「院内账号授 R-EXPERT → 200 且登录后保留 R-STAFF+R-EXPERT」的回归。`_assert_role_consistency` 已负责「外部角色与内部角色不得共存」，无需在这里重复兜 `R-EXPERT`。

### Minor

**Minor-1｜新增的脏账号回归用例判别力偏弱**

- 位置：`backend-django/tests/test_m2c_review_fixes.py:511`（`assert r2.json()["data"]["list"] == []`）
- 问题：只断言「列表为空」，没有像 r3 §4.2 要求的那样断言「本机构那条仍可见、他机构不可见」。若 `list_applications` 整体坏掉（任何人返回空集），该用例仍会通过。建议改为「本机构 1 条可见 + 他机构 0 条」。
- 另：`:463-480` 的入口用例用 ORM 建账号，而 r3 §4.2 明确要求用 `POST /admin/users` + `POST /admin/users/{id}/roles` 两步造态；两步造态本轮仅由我的探针覆盖（`test_p1`），未进仓库。建议补进测试。

**Minor-2｜`is_external_only` 已成死代码且 docstring 过时**

- 位置：`backend-django/core/org_scope.py:107-119`
- 事实：全仓已无生产调用点（仅 `tests/test_p_domain.py:335`、`apps/sysadmin/api.py:149` 的注释提及）；docstring 写「只要持有 R-PARTNER 即按外部」，但实现 `has_external_role` 对 `R-EXPERT` 也返回 True（`core/org_scope.py:11`、`:23-24`）。建议删除或标注 deprecated，避免下一位评审再被误导。

**Minor-3｜`is_external_account` 的 docstring 未反映新增的 R-PARTNER 前置规则**

- 位置：`backend-django/core/org_scope.py:89-97`
- 现状：正文仍写「以 `sys_user.user_source` 为准：EXTERNAL → 外部；INTERNAL → 院内」，只有行内注释提到 R-PARTNER 恒真。签名级文档与实际优先级不一致（r3 的 I-1 建议正是要求文档与行为同步）。

**Minor-4｜仍有 2 处「只看来源」的外部判定，与统一口径不一致**

- 位置：`backend-django/apps/p/api.py:318`、`:1117`（`(pi_user.user_source or "INTERNAL").upper() == "EXTERNAL"` → 400「申报负责人不得为外部机构账号」）
- 事实：对合法账号两者等价；只有「INTERNAL+R-PARTNER」脏账号会出现「按来源放行、按账号判据却是外部」的分歧（该 PI 建出的院内申报自己看不到）。因脏状态已不可由 API 造出，风险为 0，但既然本轮提交名为「口径统一」，建议一并换成 `is_external_account`（或抽 `user_source_is_external(user)` 供账号行使用，注意这两处判定的是**他人的** PI 行、不能直接套 `Domain`）。

**Minor-5｜规则 1 依赖「令牌里的角色」，不是 DB 角色**

- 位置：`backend-django/core/auth/deps.py:67`（`roles = [str(r) for r in claims.get("roles", [])]`）+ `core/org_scope.py:94-95`
- 事实：`ark_auth` 只按 DB `user_source` **裁剪**令牌角色，不重查 `sys_user_role`。因此「先在库侧获得 R-PARTNER、但令牌是授权前签发的」这一瞬间，账号仍按 INTERNAL 判（要重登才变外部）。当前 R-PARTNER 已无官方运行时授予路径（§1.3），实际不可达；记录以备将来引入「运行时授权」时复核。

---

## 6. 我亲自跑的数字（全部本轮实测）

| # | 项目 | 命令 | 结果 |
|---|---|---|---|
| 1 | 后端全量 | `cd backend-django && .venv/bin/python -m pytest -q` | **471 passed, 5 warnings in 18.63s**（exit 0） |
| 2 | 用例收集 | 同上 `--collect-only -q` | **471 tests collected** |
| 3 | 本轮新增 3 例（HEAD） | `pytest tests/test_m2c_review_fixes.py -q -k r3_` | **3 passed, 19 deselected**（该文件现共 22 例） |
| 4 | 真红（`92625d0`） | 同上，源码回退、测试覆盖为 HEAD 版 | **3 failed**：`:479 200!=400`、`:509 200!=404`、`:532 404!=200`；恢复后 `cmp` 全 ok |
| 5 | 独立探针（HEAD 副本） | `/tmp/m2c_r4_wt`：`pytest tests/test_r4_probe.py -q` | **10 passed**（管理端两步、create_user 造态、脏账号 P/E 域、院内侧、I-2、专家审核、真实登录、PENDING 机构、重复授权） |
| 6 | 前端类型 | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | **exit 0，无输出** |
| 7 | 迁移漂移 | `python manage.py makemigrations --check --dry-run` | **No changes detected**（exit 0） |
| 8 | seed 幂等 | 独立 sqlite：`migrate` → `seed_demo` ×3 | 第 2/3 遍均「新增 0」；**142 张表**行数逐表 `diff` 为空（`IDEMPOTENT_AFTER_3RD_SEED=YES`） |
| 9 | 契约双份 | `cmp design/<f>.openapi.yaml frontend/src/api/schema/<f>.openapi.yaml`（16 对） | **13 SAME / 3 DIFF**；DIFF 仍为 `04-科研成果管理-R`、`08-数据分析与决策-D`、`14-科研绩效评价-M`（与 r2/r3 基线同，非本轮引入）；**09-G、15-N 均 SAME**；`git diff 92625d0..27c1789 -- design frontend/src/api/schema` 为空 |
| 10 | README 计数 | `grep -n 471 README.md` | **3 处**（`:5`、`:29`、`:73`）均为 471，与实测一致（`92625d0` 时为 468） |
| 11 | 脏账号越权面 | 见 §1.2 表 | 跨机构读/写/改预算/汇报全部 404；`POST` 落库被迫改为本人+本机构 |
| 12 | 造态入口穷举 | 见 §1.3 表 | 7 条官方路径全部造不出「INTERNAL + R-PARTNER」 |

复现物（只读、只写 `/tmp`）：`/tmp/m2c_r4_wt/backend-django/tests/test_r4_probe.py`（10 例，HEAD 源码）；`/tmp/m2c_r3base`（`92625d0` 源码 + HEAD 测试，用于真红与对照）。

---

## 7. 合并建议

1. **可以合并**：I-1/I-2 门槛已关闭，无 Critical，无新增安全回退。
2. **下个提交必修**（Important-1）：`apps/sysadmin/api.py:343` 的拒绝面收窄为 `R-PARTNER`，同步改文案，并补「院内账号授 R-EXPERT → 200」回归；否则管理端角色页对院内专家永远是 400，且与专家审核流自相矛盾。
3. **可延后**：Minor-1…5 及 m-2/m-3/m-5/m-6/m-7/m-8、I-3（`list_reviews` 无租户）。

## 8. 复审边界

- 未做浏览器端 E2E；前端仅 `vue-tsc` 类型检查 + `UsersView.vue:158` 的调用链静态核对。
- 未连真实 PG（本机 5432 不可用），`makemigrations --check` 在默认库连接告警下仍返回 `No changes detected`；seed 幂等用独立 sqlite 文件验证。
- 未覆盖 svc-ai 与 `scripts/smoke_p3.py`/`smoke_p4.py`（本轮 diff 未触及）。
- 所有结论均以本轮实测为准，未采信提交说明或上轮报告的结论性描述。
