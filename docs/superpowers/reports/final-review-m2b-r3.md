# M2-b 开放课题全流程 · 第三轮终审（r3）

- 评审对象：`e573c19..231c6a5`（2 commits：`e7906cb` 修复 + `231c6a5` 回归用例），HEAD `231c6a5`
- 仓库：`/Users/jacky/works/science-research-project`（Django + django-ninja + Vue3）
- 评审方式：只读源码 + 真实 HTTP（`django.test.Client` + 真实 JWT + 真实 casbin + 真实迁移 sqlite 库）+ 空库 `migrate`/`seed_demo` + 独立攻击链探针；未改动任何源码
- 前序：r1 `docs/superpowers/reports/final-review-m2b.md`（4 Critical + 4 Important）、r2 `docs/superpowers/reports/final-review-m2b-r2.md`（1 Critical + 5 Important + 9 Minor，判 REQUEST_CHANGES）

## 1. Verdict

**REQUEST_CHANGES**

- r2 的唯一 Critical（R2-C-1 任务书跨机构）**已关闭**，R2-I-2 / I-3 / I-5 已关闭。
- 但 **R2-I-1 仅部分关闭**：新建混合角色账号的入口已拦死，**存量混合角色账号仍在运行期获得并集权限**（`/expenses`、`/staff`、`/output`、`/budgets` 全 200，`/apply/ai/draft` 仍返回院内项目引用），r2 明确要求确认的“真实越权面已不可达”未达成。
- **R2-I-4 仅部分关闭**：`pi_user_id=999999` 已 400，但 PI 校验只查“存在且同租户”，**不查 ACTIVE、不查是否外部身份**；一个合法的停用账号或外部账号仍可被写成院内申报 PI，随后 `submit → decide → 生成任务书` 全部 200，而 PI 永远无法签署（停用者登录 403；外部 PI 看不到任务书 404；管理员签 PI 403），且**没有任何改派 PI 的接口**，申报永久卡死。该链条已用真实 HTTP 端到端复现。
- 新增 2 条 Important（N-1、N-2，即上述两个未闭合面的具体化）+ 5 条 Minor；无新增 Critical。

## 2. 逐条复核表

| 项 | 结论 | 关键证据（文件:行号 / 实跑） |
|---|---|---|
| R2-C-1 任务书生成机构收口 | **PASS** | `apps/p/api.py:928-943` 新增 `_locked_scoped_app_or_404`（`select_for_update` + tenant + `is_external_only` 时机构相等），`:959` 使用；`:1004` decide 同口径。探针：混合账号（orgB）→ orgA 申报 `404`、`PTaskBook` 计数 0；已有任务书跨机构仍 `404`；纯 R-PARTNER `403`；院内 R-MANAGER `200`；混合账号→本机构 `200`。 |
| R2-I-1 角色一致性双向校验 | **FAIL（部分关闭）** | 新入口全部按预期：给 R-PARTNER 追加 R-STAFF `400`（`sysadmin/api.py:304-322`，角色表未被污染仍为 `['R-PARTNER']`）；`create_user` EXTERNAL+R-STAFF `400`（`:180-183`）；R-PARTNER 无 org `400`；正常运维 staff+R-MANAGER / finance+R-AUDITOR / manager+R-FINANCE / staff+R-LEADER 全 `200`。**但**存量混合账号读 `/api/v1/expenses`、`/staff`、`/output`、`/budgets` 全 `200`，`/apply/ai/draft` 返回 `[{'project_code':'PRJ-5','title':'r3院内申报'},{'project_code':'PRJ-3','title':'r3机构A申报'}]`；登录/发 token 处无混合角色拒绝（`core/auth/api.py:47-48` 只管 ACTIVE），`ai_draft` 引用查询无机构过滤（`apps/p/api.py:600-604`）。 |
| R2-I-2 progress-report 契约入参 | **PASS** | `apps/project/api.py:283-300` `_pick` 双读。按契约 `{period,reportType,progressPercent,contentRich,nextPlan}` 提交 → `200`，落库 `('SELF',55,'进展','下一步','问题',[1,2])`；snake_case → `200`；`progressPercent=0` → `0`（未被默认值掩盖）；出参同时含 camelCase/snake_case 键。附 3 个 Minor（见 N-3）。 |
| R2-I-3 空机构写入 | **PASS** | `apps/p/api.py:295-297`（申报）、`:797-799`（建议）。空机构 R-PARTNER 建申报 `403` 且 `PApplication` 计数 5→5；建建议 `403` 且 `org_id IS NULL` 计数不变。 |
| R2-I-4 PI 校验 | **FAIL（部分关闭）** | `apps/p/api.py:299-308` 仅 `SysUser.filter(id, tenant_id, deleted=0).exists()`。`pi=999999` → `400`，`pi="abc"` → `400`，正常 PI → `200`；**但** `pi=DISABLED` 账号 → `200`，院内申报 `pi=R-PARTNER 外部账号` → `200`。两条链路 `submit=200 / decide=200 / generate=200`，停用 PI 登录 `403`（`core/auth/api.py:47-48`），任务书 PI 签署 `403`（`apps/p/api.py:1066`），外部 PI 读任务书 `404`（`apps/p/api.py:915-926`），且 `config/api.py` 无任何改派 PI 路由。 |
| R2-I-5 UserRequest 契约 | **PASS** | `design/12-用户与权限-U.openapi.yaml:1079-1093` 已含 `org_id`(nullable int64) 与 `user_source`(enum INTERNAL/EXTERNAL)；`cmp` 与 `frontend/src/api/schema/12-...yaml` 完全一致；`yaml.safe_load` 后 `UserRequest.properties` 含两项。Minor：`UserUpdateRequest:1094-1103` 仍无 `org_id/user_source`，且 `update_user`（`sysadmin/api.py:219-239`）不接受 `org_id`，账号创建后机构不可改。 |
| Minor：PENDING 机构挂账号 | **PASS** | R-PARTNER + PENDING org `400`（`sysadmin/api.py:156-157`，实测 `org.audit` 前置）。 |
| Minor：`org_id="abc"` | **PASS** | `400`（`sysadmin/api.py:172-178`），不再 500。 |
| Minor：decide comment | **PASS** | `apps/p/api.py:1002-1010`；`remark` 落库且出参返回 `同意资助，额度 30 万`；超长按契约 `maxLength:512` 截断（契约 `design/01:658`）。 |
| Minor：`outputSummaryText` 幻影键 | **PASS** | `apps/project/mappings.py:129` 起已无该键；`grep -rn outputSummaryText backend-django frontend/src design` 无命中；final-accept `200`，响应无 `outputSummaryText`、有 `outputSummary`。 |
| Minor：陈旧/重复注释 | **FAIL（非阻塞）** | `apps/p/api.py:74-78` 仍写“除 R-PARTNER 外没有任何其它角色…fail-open 给内部”，实现已是 fail-closed；`:336-338` 仍有重复的 `_TERMINABLE` 注释。 |

## 3. 新发现问题

### N-1（Important）PI 只校验“存在”，未校验“可用/身份”，叠加无改派接口 → 申报永久死锁

- 位置：`backend-django/apps/p/api.py:299-308`（校验）、`:1032-1075`（签署，`:1066` 要求 `d.user_id == a.pi_user_id`）、`backend-django/config/api.py:101-121`（无 application update / change-pi 路由）、`backend-django/apps/sysadmin/api.py:219-239`（`update_user` 可随意把 PI 置 DISABLED）。
- 复现（真实 HTTP，空库 + seed，探针 `/tmp/m2b_r3_probe7.py`）：
  1. `POST /api/v1/admin/users` 建 `p7pi`（R-STAFF，ACTIVE）→ 200；
  2. `POST /api/v1/apply/applications {"title":"p7离任PI申报","project_type":"ZIGE","pi_user_id":<p7pi>}` → 200；
  3. `PUT /api/v1/admin/users/<p7pi> {"status":"DISABLED"}` → 200（模拟离职/停用）；
  4. `POST /api/v1/auth/login` → **403**（`账号已停用或锁定`）；
  5. `POST /apply/applications/<id>/submit` → 200；`:decide {"decision":"PUBLISHED"}` → 200；`POST /apply/task-books` → 200；
  6. 管理员 `POST /apply/task-books/<tb>:sign {"role":"PI"}` → **403**（`仅申报负责人本人可签署 PI`）；停用者无法登录；无接口可换 PI → **永久卡死**。
- 另一条链（探针 `/tmp/m2b_r3_probe.py` E 段）：院内申报 `pi=R-PARTNER(orgA)` → 200，`submit/decide/generate` 全 200，外部 PI `POST /task-books/<tb>:sign` → **404**（`_task_book_visible` 因 `applicant_org_id is None` 拒绝），管理员签 PI → 403。
- 修法（最小集）：
  1. `create_application` 院内分支把 `status="ACTIVE"` 加入查询（并建议校验 `employment_status` 非 RESIGNED/RETIRED），否则 400；
  2. 院内申报拒绝持有 `R-PARTNER` 的用户作 PI（join `SysUserRole`），或明确产品允许则同步放开 `_task_book_visible` 的外部 PI 可见性；
  3. 增加 `POST /apply/applications/{id}:change-pi`（仅 R-MANAGER/R-LEADER，PI 未签或任务书未生成时可改），同步更新 `content_snapshot.pi_user_id`；
  4. 回归用例：DISABLED PI → 400；外部 PI 院内申报 → 400；改派后新 PI 可签 → 200。

### N-2（Important）存量混合角色账号的并集越权未收口

- 位置：`backend-django/core/org_scope.py:26-34`（按角色判定外部，混合即外部）、`backend-django/apps/p/api.py:600-604`（ai/draft 引用无机构过滤）、`backend-django/core/auth/api.py:28-60`（登录只查 ACTIVE，不查角色组合）。本轮 diff 未改 `policy.csv`、未改 auth 中间件、未改 references 查询。
- 复现（真实 HTTP，探针 `/tmp/m2b_r3_probe.py` B 段；账号 `r3mixed`=R-PARTNER+R-STAFF，orgB）：`GET /api/v1/expenses` → 200、`/api/v1/staff` → 200、`/api/v1/output` → 200、`/api/v1/budgets` → 200；`POST /api/v1/apply/ai/draft` → 200，`references=[{'project_code':'PRJ-5','title':'r3院内申报'},{'project_code':'PRJ-3','title':'r3机构A申报'}]`（跨机构/院内标题泄露）。纯 R-PARTNER 对四端点均 403，说明并集确实来自 R-STAFF。
- 修复对比：新建入口已能拦住（`sysadmin/api.py:304-322` 每次用 `existing+[new]` 校验），但**已存在的混合账号仍可登录并拿到并集**。若线上/测试库曾用旧版本 API 造过混合账号，风险仍在。
- 修法：
  1. 登录/刷新 token 时若 `R-PARTNER` 与任一内部角色并存 → 403（或签发前剔除内部角色），并给一次性数据审计/清理命令；
  2. `ai_draft` 的 `references` 对外部身份按 `applicant_org_id == current_org_id(d)` 过滤（或直接只返回本机构/空列表）；
  3. 回归用例用 ORM 造存量混合账号，断言四端点 403 或仅本机构数据、references 不含院内项目。

### N-3（Minor）progress-report 入参无类型/枚举/范围校验

- 位置：`backend-django/apps/project/api.py:289-301`。
- 实测：`progressPercent:"abc"` → **500**（`ValueError: Field 'progress_percent' expected a number but got 'abc'`）；`progressPercent:150`、`-5` → 200 且越界落库；`period:123` → 200 且落库字符串 `"123"`；契约 `design/02:1096-1106` 要求 `period/reportType` 枚举、`progressPercent` 0..100。
- 修法：`int()` 包 try/except → 400；范围 0..100；枚举校验（注意与前端现有自由文本 `period`、种子数据 `2026-Q3` 的兼容，需同步 M-9）。

### N-4（Minor）`user_source=EXTERNAL` + 空角色可两步绕过“外部账号不能持有内部角色”

- 位置：`backend-django/apps/sysadmin/api.py:180-183`（`any(...)` 对空角色为 False）、`:304-322`（assign_role 不查 `user_source`）。
- 实测：`POST /admin/users {"user_source":"EXTERNAL","roles":[],"org_id":1}` → 200；再 `POST /admin/users/<id>/roles {"role_id":R-STAFF}` → **200**，最终 `user_source=EXTERNAL, roles=['R-STAFF']`。因 `user_source` 目前不参与鉴权（仅落库/展示），影响限于身份标签不一致；但该不变量可被两步绕过。
- 修法：`assign_role` 中若 `u.user_source=="EXTERNAL"` 且新角色 != R-PARTNER → 400；或 `create_user` 对 EXTERNAL 源要求 roles 非空且只含 R-PARTNER。

### N-5（Minor）非 R-PARTNER 账号仍可绑 PENDING/不存在机构

- 位置：`backend-django/apps/sysadmin/api.py:131-158`（`_assert_role_consistency` 对无 R-PARTNER 直接 return）、`:160-205`。
- 实测：`roles=["R-STAFF"], org_id=<PENDING org>` → **200**；`org_id=99999` → **200** 且 `org_id=99999` 落库。r2 M-2 的“99999 → 200”部分未闭合。
- 修法：对所有 `org_id` 统一做同租户 + `deleted=0` 校验（是否要求 APPROVED 可按产品定），非法值 400。

### N-6（Minor）r2 既有 Minor 仍开放

- **M-8**：`config/casbin/policy.csv:15-16` 给 R-STAFF 全量 `/api/v1/apply/* POST`，纯 R-STAFF 对任意机构申报 `POST /apply/task-books` 实测 **200**（任务书生成仍无角色限制）。
- **M-3**：`apps/p/api.py:962-967` `exist` 分支先于状态检查；对 `status=REJECTED` 且已有任务书的申报再次生成，实测 **200** 返回旧任务书（终止后孤儿任务书仍可用）。
- **M-9**：`period` 自由文本仍被接受（`2026Q1`/`123`），与契约枚举不一致。
- **陈旧注释**：`apps/p/api.py:74-78`（fail-open 描述与实现相反）、`:336-338`（重复 `_TERMINABLE`）。
- 以上均为非阻塞，但建议随下轮一并清理。

### N-7（Minor）`_pick` 空串语义与 progressPercent 默认值

- `apps/project/api.py:283-287`：camel 键为空串 `""` 时不回落 snake（只有 `None` 才回落），实测 `{"reportType":"","report_type":"SELF"}` → **400**；若前端会发空串，应把 `""` 视为缺省。
- `:297` `progress_percent=_pick(...,0) or 0`：`0` 与“未传”落库同为 0，语义上无法区分；对汇报场景可接受，但建议显式 `None → 0` 并允许区分。

## 4. Review Focus 五项判定

| # | 焦点 | 判定 | 依据 |
|---|---|---|---|
| ① | 任务书生成是否走机构作用域 | **PASS** | `_locked_scoped_app_or_404` 统一租户+机构；混合账号跨机构 404 且不落库；院内正常 200。 |
| ② | 一申报一项目/一任务书 | **PASS** | 本轮未改立项/建项目路径；任务书仍按 `application_id` 幂等。 |
| ③ | P 域 body 的 pi/org 覆盖 | **PASS（有保留）** | 外部身份 `pi=self`、`applicant_org_id=current_org_id` 仍强制覆盖；院内 PI 新增存在性校验，但未校验 ACTIVE/身份（见 N-1）。 |
| ④ | 签署后不可再变更 | **PASS** | 本轮未触碰签署状态机；r2 已验证非 PUBLISHED/DECIDED 409、已签终止 409，本轮回归全绿。 |
| ⑤ | 混合角色并集权限 | **FAIL** | 新建入口已拦，但存量混合账号四端点 200 + ai/draft 跨机构引用（N-2）。 |

## 5. 独立实跑数字

| 检查 | 命令（工作目录） | 结果 |
|---|---|---|
| 全量测试 | `backend-django $ .venv/bin/python -m pytest -q` | **409 passed, 7 warnings in 19.16s**（7 条为既有 `PytestReturnNotNoneWarning`） |
| 迁移漂移 | `backend-django $ .venv/bin/python manage.py makemigrations --check --dry-run` | **No changes detected**，exit 0（stderr 仅既有 PG 5432 连接警告） |
| 前端类型 | `frontend $ ./node_modules/.bin/vue-tsc --noEmit` | **exit 0**，无输出 |
| 契约副本 | `cmp -s design/<f> frontend/src/api/schema/<f>` ×3 | 01/02/12 全部 **IDENTICAL** |
| 契约解析 | `yaml.safe_load` | paths：01=**40**、02=**26**、12=**27**；schemas：36/33/22；`UserRequest.props` 含 `org_id,user_source` |
| 空库建库+种子 | 删库 → `migrate` → `seed_demo` ×2 | 第 1 遍：legal +2，staff +11，p +6，project +17，funding +23，output +7，expert +6，activity +4，archive +6，performance +6，transform +13，ethics +5，procure +8，asset +9，confsec +7，notify +5，partner +5，users +4，dicts +5，items +26，grants +78；第 2 遍：`seed_demo 完成（幂等）：`（全 0） |
| 新 5 条用例真红 | `git archive e573c19` → 覆盖 HEAD `tests/test_p_m2b.py` → `pytest tests/test_p_m2b.py -k r2` | 旧码 **5 failed, 20 deselected in 2.10s**；HEAD **5 passed, 20 deselected in 1.91s** |
| 自建攻击探针 | `/tmp/m2b_r3_probe.py`（46 断言） | **44 PASS / 2 FAIL**；其中 1 条是我探针用 GET 打只注册 POST 的路由得到 405（修正后未认证 POST 实测 **401**），真实未闭合项为 N-1 死锁链；另有 5 条 `[残留]` 记录项（混合账号并集、staff 跨机构任务书、DISABLED PI、外部 PI、EXTERNAL 空角色）均为真实缺陷证据 |
| 补充探针 | `/tmp/m2b_r3_probe2..7.py` | 正常运维组合 200×4；EXTERNAL+空角色再授 R-STAFF 200；内部账号绑 PENDING/99999 机构 200；staff camel/snake 汇报 200；manager 汇报 403（policy 既有，非本轮回归）；decide 长 comment 截断 512；REJECTED+已有任务书 200；停用 PI 全链路见 N-1 |

工作区：本轮**未改任何源码**；`git diff -- backend-django frontend/src design` 为空。`git status` 仍显示评审前既存的 `docs/` 二进制删改与未跟踪文件（与本轮代码无关），我全程只写 `/tmp` 与本报告。

## 6. 合并门槛结论

**不满足合并门槛（NOT MERGEABLE）**。

关闭情况：R2-C-1 关闭；R2-I-2 / I-3 / I-5 关闭；R2-I-1、R2-I-4 仅部分关闭。

下轮必须完成（阻塞项）：

1. **N-1**：PI 校验补 `ACTIVE`（并建议拒绝外部身份作院内 PI）；补 PI 改派接口或在任务书生成前允许管理员改 `pi_user_id`；补对应用例。当前停用 PI 会让“开放课题全流程”在任务书签署环节永久卡死，且无产品内修复路径。
2. **N-2**：对存量混合角色账号做登录/token 层拒绝或一次性数据清理；`ai_draft.references` 按机构收口；补存量混合账号用例。

可随下轮或合并后跟进（非阻塞）：N-3 ~ N-7（入参校验、两步绕过、org 校验、M-8/M-3/M-9、陈旧注释、`_pick` 空串）。

在上述两项 Important 关闭前，建议维持 REQUEST_CHANGES；若产品明确接受“存量混合账号由运维手工清理 + PI 停用走 DB 修复”的风险，需在合并记录中显式登记风险与 owner，否则不应合并。
