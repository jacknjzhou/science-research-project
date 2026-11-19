# M2-c 终审 · 第三轮复审报告（r3）

- **复审范围**：`git diff b825029..9ee0e3a`（1 commit，`fix(m2c): 终审 r2——机构副本与应价回执补收件人、黑名单不可自助洗白、院内专家按院内口径、跨租户不投递`），外加期间新增的 `92625d0`（`perf(org_scope): 账号机构/来源按请求缓存`，仅性能自查用）。
- **判定基准**：`HEAD = 92625d0`（复审结束时 `git log` 确认未再前进；`git diff 92625d0..HEAD -- backend-django frontend` 为空）。
- **复审方法**：只读源码 + 纯净副本上跑真实端点（Django `Client` + 真实 `mail.outbox`/DB 断言）+ 源码回退真红实验。独立副本 `/tmp/m2c_r3_wt` 由 `git archive 92625d0` 生成，symlink `backend-django/.venv`，仓库工作区未做任何源码改动。
- **上轮报告**：`docs/superpowers/reports/final-review-m2c-r2.md`（285 行，REQUEST_CHANGES）。

---

## 0. Verdict

**REQUEST_CHANGES**

> **合并门槛（一句话）**：上轮 N-1/N-2/N-3/N-4 四条阻断点确实全部关闭、抽样真红且全量绿灯，但 `9ee0e3a` 在修 N-4 时把 P 域判据从"按角色 fail-closed"换成"按 `user_source`"，**引入一条新的越权回归**——`user_source=INTERNAL` 且仅持 `R-PARTNER` 的账号（可由官方管理端两步造出）在 P 域被当院内，跨机构读/写他人申报并伪造 `pi_user_id`/`applicant_org_id`（实测 HEAD 200+落库、`b825029` 同场景 404+强制本人/本机构）；修掉这一条（判据或 `assign_role` 校验二选一）+ 补 1 条用管理端 API 造态的回归测试，即可合并。

无 Critical。Important 3 条（1 条为本轮新引入的回归、1 条为 N-4 未跨域统一、1 条为上轮 N-5 遗留）。

---

## 1. 上轮 4 条阻断点逐条结论

| 编号 | 上轮问题 | 本轮结论 | 关键证据（我亲自跑） |
|---|---|---|---|
| N-1 | 黑名单专家可自助"重新申请"把 `BLACKLIST` 刷回 `CANDIDATE` | **已关闭** | `POST /api/v1/portal/expert-apply`（`R-EXPERT`，已有 BLACKLIST 档案）→ **403**，体 `{"code":40301,"message":"该账号已被列入专家黑名单，不接受自助申请"}`；`NExpert` 行仍 `status=BLACKLIST`、`remark='学术不端'` 未被改写 |
| N-2 | 外部 PI 的机构邮箱拿不到决议副本 | **已关闭** | 外部申报（PI=`pi-n2@example.com`，机构 contact=`org-n2@example.com`）`:decide` → 200，outbox **2 封**，收件人集合 `{'org-n2@example.com','pi-n2@example.com'}`；院内无机构申报同端点 → 200、outbox **0 封**（不误发） |
| N-3 | 应价回执发给了采购发起人，供应商侧收不到 | **已关闭** | `POST /api/v1/portal/supplier/inquiries/{id}:quote` → 200，outbox **3 封**，收件人集合 `{'buyer-n3@example.com','s1@example.com','s2@example.com'}`；同机构 `DISABLED` 的 `s3@example.com` **未收到**（停用账号被过滤） |
| N-4 | 院内 `R-EXPERT` 在 P 域被当外部，被自己的申报挡在门外 | **已关闭（限 P 域）** | 院内专家（`user_source=INTERNAL`，`R-STAFF+R-EXPERT`）：`GET /api/v1/apply/applications` → **200 + 空集**（旧码 403）；`POST /api/v1/apply/applications` `pi_user_id=999999` → **400 "申报负责人不存在"**、`pi_user_id=自己` → **200**。⚠️ 只修了 P 域，E 域仍按外部处理，见 I-2 |

四条均为**真实端点实测**，不是读代码推断；结论"已关闭"仅指上轮描述的行为，**不覆盖** N-4 改判据带来的新回归（见 I-1）。

### 1.1 真红抽样（6 组，回退源码后跑对应用例）

在 `/tmp/m2c_r3_wt` 内用 `git show b825029:<file> > <file>` 覆盖，跑单例，再恢复并 `cmp` 校验（全部 `cmp ok`）。

| # | 回退文件 → `b825029` | 用例 | 真红证据 |
|---|---|---|---|
| 1 | `backend-django/apps/expertreview/portal.py` | `test_r2_blacklisted_expert_cannot_reapply` | `assert 200 == 403`（旧码把 BLACKLIST 刷成 CANDIDATE） |
| 2 | `backend-django/apps/notify/email.py` | `test_r2_notify_user_skips_cross_tenant_uid` | `assert <SysNotification: …(1)> is None`（旧码写孤儿站内信） |
| 3 | `backend-django/apps/p/api.py` | `test_c1_decide_application_notifies_pi_by_email` | `assert 'org-pi@example.com' in {'pi-ext@example.com'}`（缺机构副本） |
| 4 | `backend-django/apps/procure/portal.py` | `test_c1_quote_receipt_notifies_purchaser` | `assert 1 >= 2`（只发采购发起人） |
| 5 | `backend-django/apps/p/api.py`（`core/org_scope.py` 保持 HEAD） | `test_r2_internal_expert_is_not_external_in_apply_domain` | `assert 403 == 200`（旧码把院内专家当外部） |
| 6 | `backend-django/core/org_scope.py` | 同上 | `ImportError: cannot import name 'is_external_account'` —— 弱红（模块级耦合，只能证明"接线"不能证明"行为"）；第 5 组才是行为红 |

`test_m2c_review_fixes.py` 现 **19 例**（`--collect-only` 实测 19）。第 5 组说明该用例确实钉住了行为；第 6 组说明它同时硬依赖新函数名，属可接受的耦合。

---

## 2. 新发现问题

### Critical

无。

### Important

#### I-1（**本轮引入的回归**）`INTERNAL + R-PARTNER` 账号在 P 域被当院内：跨机构读/写 + 伪造 PI/机构

- **位置**：`backend-django/core/org_scope.py:88-99`（`is_external_account`）、`backend-django/apps/p/api.py:293`（`external = is_external_account(d)`）、`backend-django/apps/p/api.py:367-380`（`_app_scoped_or_404`，docstring 仍写"外部身份（含混合角色，fail-closed）"）
- **机制**：新判据只看 `sys_user.user_source`：`INTERNAL` 一律按院内。于是"账号来源院内、角色集只有外部角色"的脏数据走内部分支 → `list_applications`/`_app_scoped_or_404` 不再按 `applicant_org_id` 收口，`create_application` 也不再把 PI/机构强制成本人/本机构。
- **可达路径（全程官方 API，无需碰库）**：
  1. `POST /api/v1/admin/users {"roles": [], "org_id": <APPROVED 机构>}` → **200**，返回 `user_source=INTERNAL`（`create_user` 只在 `roles` 含外部角色码时才强制 `EXTERNAL`，空 `roles` 落默认 `INTERNAL`，`backend-django/apps/sysadmin/api.py:216-219`）；
  2. `POST /api/v1/admin/users/{id}/roles {"role_id": <R-PARTNER>}` → **200**（`_assert_role_consistency` 只校验"与其他角色共存"，无其他角色即放行，`backend-django/apps/sysadmin/api.py:142-168`）；
  3. `/api/v1/auth/login` → token `roles=['R-PARTNER']`，DB 行 `user_source=INTERNAL, org_id=1`。
- **实测对照（同场景同用例，仅换源码版本）**：

| 场景（账号：`user_source=INTERNAL`，`org_id=A`，token `R-PARTNER`） | HEAD `92625d0` | `b825029`（旧判据 fail-closed） |
|---|---|---|
| `GET /apply/applications` | **200**，`ids=[1]`（B 机构申报可见） | **200**，`ids=[]` |
| `GET /apply/applications/{B机构申报}` | **200**（跨机构正文） | **404** |
| `POST /apply/applications` body 伪 `pi_user_id=<他人>`、`applicant_org_id=<B>` | **200**，落库 **pi=2(他人)、org=2(B 机构)** | **200**，落库 pi=3(自己)、org=1(本机构) |
| `POST /apply/applications/{B机构草稿}/budget` | **200**（跨机构改预算） | 未测（读已被 404 挡住） |

  同一路径用管理端两步造出的账号复测：`list ids=[2,1]`（租户内全部申报）、两条他人申报 `GET 200/200`、`POST` 落库 `pi=<受害人>`、`org=<B 机构>`、`applicant_type=INTERNAL`。
- **为什么算回归**：`b825029` 的 `is_external_only` 明确 fail-closed，并在 docstring 里记录了 M2-b I2 的攻击面（`backend-django/core/org_scope.py:102-113`："混合角色…可伪造 pi_user_id / applicant_org_id（实测 200）"）。`9ee0e3a` 换判据后，这个攻击面对 `user_source=INTERNAL` 的账号重新成立，而 `_app_scoped_or_404` 的 docstring（`apps/p/api.py:372`）还写着 fail-closed，属**文档与行为相反**，后续评审会被误导。
- **影响面**：仓库演示数据**未**暴露（`seed_demo` 里 `partner`/`expert_ext` 均 `EXTERNAL`，实测 6 个种子账号 `user_source` 正确）；需要管理员先造出"院内来源 + 仅外部角色"的账号。该账号仍过不了 `R-MANAGER` 系 Casbin（`decide/change-pi` 双重校验），所以危害是**同租户内跨机构数据面 + 冒名申报**，不是全租户管理权。
- **建议修法（二选一，建议都做）**：
  1. 判据加"院内角色"条件：`src == "INTERNAL"` 且角色集**不含任何院内角色**时仍按外部（fail-closed）；含院内角色（如 `R-STAFF`）才走院内——N-4 的院内专家场景仍成立；
  2. `assign_role` 对 `user.user_source != "EXTERNAL"` 且新角色 ∈ 外部角色码时直接 400（与 `create_user` 的强制 `EXTERNAL` 对称），从源头消灭该状态。
- **必须补的测试**：用 `POST /admin/users` + `POST /admin/users/{id}/roles` 造态，断言该 token 在 P 域 `GET 他人申报 == 404`、`POST` 落库 `pi==自己`、`org==本机构`。

#### I-2 N-4 只修了 P 域：院内专家在 E 域仍被当外部，作为 PI 无法提交阶段汇报（404）

- **位置**：`backend-django/apps/project/api.py:55`（`from core.org_scope import current_org_id, is_external_only`）、`:279`、`:346`、`:755`、`:783`
- **实测**（院内专家 `user_source=INTERNAL`、`R-STAFF+R-EXPERT`）：
  - `GET /api/v1/project/mine` → **200**，`ids=[1]`（作为 PI 能看到项目）；
  - `POST /api/v1/project/1/progress-report` → **404 `{"code":40401,"message":"项目不存在"}`**（走 `_partner_project_or_404`，`current_org_id=None` 必 404）；
  - 同一账号在 P 域 `GET /apply/applications` → 200，**同一身份两套口径**。
- **影响**：院内专家（PI）无法提交/查看阶段汇报，功能面直接断；错误码是 404 而非 403，排查成本高。方向上是"更严"（不泄数据），但与本轮 N-4 的修复目标自相矛盾。
- **建议**：判据按 I-1 修好后，把 `apps/project/api.py` 的 5 处 `is_external_only` 一并换成 `is_external_account`，并在 `test_m2c_review_fixes.py` 增加"院内专家 PI 提交阶段汇报 200"的用例。

#### I-3（上轮 N-5 遗留，不计本轮门槛）N 域评审任务列表仍无租户过滤

- **位置**：`backend-django/apps/expertreview/api.py:227`（`list_reviews`：`NReviewTask.objects.filter(deleted=0)`，无 `tenant_id`）
- **说明**：上轮已认定为既有遗留、不计门槛；本轮确认**仍未修**（`GET /api/v1/reviews` 在 A 租户可见 B 租户任务标题/biz_type）。同一函数的 `_get_task_or_404`（`:66-71`）已按租户收口，仅列表遗漏。
- **建议**：`filter(tenant_id=d.tenant_id, deleted=0)`；顺手把 `_notify_invitees` 的 `NExpert` 查询补租户（见 m-2）。

### Minor

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| m-1 | `backend-django/apps/notify/email.py:89-103` | 跨租户 uid 写孤儿站内信 | **已修**（实测跨租户 → `None`、通知 delta 0、邮件 0；同租户 `email=NULL` 仍写站内信、不发信，符合预期） |
| m-2 | `backend-django/apps/expertreview/api.py:312-327` | `_notify_invitees` 取 `NExpert` 无 tenant；`:298-308` 的 `set_mid_check_experts` 也无租户收敛 | **仍在**（孤儿信已被 m-1 兜住，但跨租户 expert→user_id 仍会被写进本院项目的 mid-check 专家集合） |
| m-3 | `backend-django/tests/test_m2c_review_fixes.py:52-53`、`:91-92` | C-1 四例中"邀请评审""发标"两例仍只断言 `len(outbox)`/subject，不校验 `to` | **部分关闭**（quote `:145-149`、decide `:180-182` 已断言收件人；另两例仍不能发现"发错人/多发别机构"，也正是 m-8 逃过测试的原因） |
| m-4 | `frontend/src/App.vue:216` | 侧栏 expert-apply 带 `R-STAFF` 死链 | **已修**（现 `['R-PARTNER','R-EXPERT']`，与 `router/index.ts` 一致） |
| m-5 | `frontend/src/api/mock/overrides/auth.ts:32-121` | `W(['GET'])` 等通配使 mock 权限宽于 policy | **仍在**（未加"演示口径"注释） |
| m-6 | `backend-django/apps/notify/email.py:76-84` | `notify_user` 无 `channel` 形参、返回 `SysNotification` 而非 `int`，与计划书 `:522-572` 漂移 | **仍在** |
| m-7 | `backend-django/apps/procure/portal.py:157,175`、`backend-django/apps/procure/api.py:344`、`backend-django/apps/expertreview/api.py:322`、`backend-django/apps/expertreview/portal.py:122` | 通知 `typ="TODO"`（共 5 处，比上轮多 1 处：专家申请通知） | **仍在**（不影响投递；前端按 typ 过滤会落"其他"） |
| m-8 | `backend-django/apps/procure/api.py:326-350` | 发标只找机构下 ACTIVE 账号邮箱，机构只有 `contact_email` 时 0 封 | **仍在**（实测：给"有 `contact_email`、无账号"的机构发标 → 200、`outbox=0`） |
| m-9 | `backend-django/tests/test_m2c_review_fixes.py:313-345` | I-4 缺 BLACKLIST 负例 | **实质关闭**（新的 `test_r2_blacklisted_expert_cannot_reapply` 在 portal 层覆盖了 BLACKLIST→403；`test_p_m2b` 的 I-4 本身仍未补） |
| m-10 | `backend-django/apps/expertreview/portal.py:91-94` | `reject_reason = None` 死赋值 | **已修**为 `remark = None` |
| m-11 | `backend-django/apps/expertreview/portal.py:91-94` | 复用档案复位时清空 `remark`（`NExpert.remark` 是唯一审核意见字段，模型无独立审核表，`apps/expertreview/models.py:10-44`），SUSPENDED/CANDIDATE 复审后上一条驳回理由永久丢失 | **新**（建议把旧值写入 remark 前缀或加审核日志表；本轮实测 `remark='材料不全'` → `None`） |
| m-12 | `backend-django/apps/p/api.py:372-373` | `_app_scoped_or_404` docstring 仍称"外部身份（含混合角色，fail-closed）"，与 I-1 行为相反 | **新**（改判据后必须同步） |
| m-13 | `backend-django/core/org_scope.py:47-70` | 每请求固定多 1 条 `sys_user(id, org_id, user_source)` 查询，且与鉴权阶段那条 `sys_user(status,deleted)` 查同一行、未合并 | **新（可接受）**：实测 `GET /apply/applications` 6 条 SQL（旧码 5 条），第二次请求 4 条（旧码 3 条）；同请求 12 次判定仍只 1 条（`92625d0` 缓存生效） |
| m-14 | `backend-django/apps/p/api.py:1038-1066` | 机构副本不去重：机构 `contact_email` 与 PI 邮箱相同时会收到两封 | **新（低危）** |

---

## 3. 我亲自跑的验证与数字

| # | 验证项 | 命令 | 结果 |
|---|---|---|---|
| 1 | 后端全量 | `cd backend-django && .venv/bin/python -m pytest -q` | **468 passed, 5 warnings in 18.39s**（`--collect-only` = 468 tests；与 README/声称一致） |
| 2 | 新增回归文件 | `pytest tests/test_m2c_review_fixes.py --collect-only -q` | **19 tests**（上轮 16） |
| 3 | 真红抽样 | 见 §1.1 | 6 组全部红；5 组为断言红、1 组为 ImportError；恢复后 `cmp` 全 ok |
| 4 | 前端类型 | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | **exit 0，无输出** |
| 5 | 迁移漂移 | `python manage.py makemigrations --check --dry-run` | **No changes detected**（exit 0） |
| 6 | seed 幂等 | `ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2c_r3_seed.sqlite`：`migrate` → `seed_demo` ×2 | 两遍后 **141 张表**行数逐表 `diff` 为空；账号 `user_source`：`partner`/`expert_ext` = `EXTERNAL`，其余 4 个院内账号 = `INTERNAL` |
| 7 | 契约双份 | `cmp design/<f>.openapi.yaml frontend/src/api/schema/<f>.openapi.yaml`（16 对） | **13 SAME / 3 DIFF**；DIFF 仍为 `04-科研成果管理-R`、`08-数据分析与决策-D`、`14-科研绩效评价-M`（与 r2 基线同，非本轮引入）；**09-G、15-N 均 SAME** |
| 8 | README 计数 | `grep -n 468 README.md` | 3 处（`:5`、`:29`、`:73`）均为 **468**，与实测一致；`9ee0e3a` 已把 465→468 同步 |
| 9 | 端点清单 | `git diff --stat b825029..9ee0e3a` | 9 文件 +204/−30；**未改 `config/api.py`** → 无新端点/schema，契约无需更新 |
| 10 | 性能（第三问） | 同一请求内 4 轮 × (`is_external_account`+`current_org_id`+`user_source_of`) | **1 条 SQL**（缓存生效，`92625d0` 有效） |
| 11 | 查询增量 | `GET /apply/applications`（5 条申报，`R-STAFF`） | HEAD：首请求 **6** 条、复用后 **4** 条；`b825029`：**5** / **3** → 净 **+1 SELECT/请求** |
| 12 | 虚拟令牌（第三问） | `Domain(user_id=0, roles=['R-PARTNER'])` / 无角色 | `is_external_account` 与 `is_external_only` **完全一致**（True/True、False/False）→ 行为未变 |
| 13 | I-1 越权（第四问） | 见 §2 I-1 对照表 | HEAD 跨机构 200 + 伪造落库；`b825029` 404 + 强制本人/本机构 |
| 14 | 越权面（第四问） | 同上账号 `:decide` / `:change-pi` | 仍 403（`apps/p/api.py:1013,1084` 的 `is_external_account or not has_role` 双闸），**未**扩大到管理动作 |

复现脚本（只读、只写 `/tmp`）：`/tmp/m2cprobe_r3/test_r3_probe.py`（N-1..N-4 + 性能 + notify）、`test_mix2.py`（管理端造态 + 越权）、`test_mixbase.py`（HEAD vs `b825029` 对照）、`test_qcount.py`（查询数）、`test_edomain.py`（E 域口径）；运行方式 `cd /tmp/m2c_r3_wt/backend-django && .venv/bin/python -m pytest -q <file> --ds=config.settings.test -s`。

---

## 4. 合并前必须做的两件事

1. **修 I-1**：`core/org_scope.py::is_external_account` 增加"仅持外部角色时 fail-closed"，或（并且）在 `apps/sysadmin/api.py::assign_role` 拒绝给 `user_source != EXTERNAL` 的账号授予 `R-PARTNER`；同步更正 `apps/p/api.py:372` 的 docstring。
2. **补 1 条回归测试**：用 `POST /admin/users`（`roles=[]` + `org_id`）+ `POST /admin/users/{id}/roles`（`R-PARTNER`）造态，断言 P 域跨机构 `GET=404`、`POST` 落库 `pi=自己`、`org=本机构`。建议同时补 I-2 的 E 域用例（院内专家 PI 提交阶段汇报 200）。

修完这两项后，其余 Minor 可留到下个迭代；本轮不需要再动 N-1/N-2/N-3/N-4 的既有修复。

---

## 5. 复审边界

- 未做浏览器端 E2E，前端仅 `vue-tsc` 类型检查 + 侧栏角色表静态核对。
- 未连真实 PG（环境 5432 不可用），`makemigrations --check` 在回退 sqlite 默认库下完成；seed 幂等用独立 sqlite 文件验证。
- 未覆盖 svc-ai 微服务与 smoke_p3/p4 脚本（本轮 diff 未触及）。
- 本轮未修改任何源码，只新增本报告；所有实验脚本与临时库均在 `/tmp`。
