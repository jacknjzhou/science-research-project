# M1-d 实施计划：B2 项目八要素看板 / B3 统一评估 / B4 变更版本化 / B5 指南征集

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 roadmap M1-d 四条验收线——项目八要素聚合看板、统一项目评估（模板配置→发起→评审→批文）、变更重大/一般分流与版本快照+预算联动、指南征集发布/关闭+专家论证评审入库推送。

**Architecture:** 全部落在既有 E 域（apps/project）与 P 域（apps/p），零新业务表仅两张（E_EVAL_TEMPLATE/E_CHANGE_VERSION）+E_CHANGE_REQUEST 加 severity 列；B2 为纯聚合只读端点（复用 funding `_execution_of`）；B3 复用 N 域评审链（单一写者纪律）；B4 沿 `_advance_change` 扩展；B5 沿 PGuideline 加动作端点。契约补丁随功能任务走（02-E / 01-P 双份 yaml cp 同步）。

**Tech Stack:** Django 5 + django-ninja、PostgreSQL 15（测试 sqlite :memory:）、Vue 3.4 + TS、Casbin policy.csv、pytest 310 基线。

**Spec:** docs/reports/2026-11-12-conow-alignment-roadmap.md（B2 :73 / B3 :78 / B4 :77 / B5 :50-51）+ docs/superpowers/plans/ 前三期次计划先例（键名/错误码/测试风格）。

## Global Constraints

- 所有 ORM 查询带 `tenant_id=d.tenant_id` 且 `deleted=0`（软删域约定）。
- 金额一律 `Decimal` 运算、`num2()` 序列化为 Money=string；响应键全 camelCase（前端消费契约键）。
- 无效金额串 40001 拒绝（`_money_strict` 口径，禁静默归 0）；缺必填字段 400 `CODE_BAD_REQUEST`。
- 动态路由一律 `{int:id}` 类型化；静态/动作路由先于动态注册（config/api.py 注释纪律，M1-a 教训）。
- pytest 基线 **310 passed**；每任务真实 POST 集成路径测试（TDD 红→绿）。
- 契约改 design/*.yaml 后必须 `cp` 到 frontend/src/api/schema/ 且 diff 逐字节一致 + 双份 safe_load 通过。
- 评审写入纪律：N 域（expertreview）NEVER 直接 UPDATE E_/P_ 表，只调单一写者函数（先例 conclude_mid_check project/api.py:645）。
- 已裁定事项不重开：bind 幂等放行、200-vs-201 ok() 信封、OCR 三级回落 HTTP 200、pay R-FINANCE handler 内 enforce、TOCTOU 应用层校验接受（M1-a/b/c ledger）。
- 提交纪律：只 stage 明确路径文件，禁 `add -A`，不动 docs/（本计划文件除外）、不动 README 计数（Task 9 统一收口）。

## Preflight Rulings（P-1 ~ P-10，与计划正文冲突时以本节为准）

- **P-1** B2 契约新路径 `GET /project/{id}/board`（operationId `getProjectBoard`，tag `Board`）补 02-E 双份 yaml；schema `ProjectBoard` 八键。
- **P-2** board 八要素口径：fund=`_execution_of(tenant_id, project_id)` 原样嵌入（延迟 import 防）；progress={milestonesTotal,milestonesDone,tasksTotal,tasksDone}；members=[{userId,name}]（EProject.member_ids × SysUser，查无此人仅 id）；quality={healthScore,riskLevel,lastCheckAt}（EProject+EHealthHistory 最新一条，无则 null）；outsource={contracts,amountTotal}（GContract tenant+project_id+deleted=0 计数+Sum(amount) num2）；changes={total,byStatus}（EChangeRequest 按 status 计数）；outputs={total}（ROutput.project_ids JSON 包含该 id，tenant+deleted=0 全量 Python 过滤）。
- **P-3** 评估模板 scene 枚举 `MID_CHECK|FINAL_ACCEPT`；同名不唯一（不建唯一约束）；发起中检/验收时 `templateId` 可选：存在→落 `EMidCheck.template_id`（EFinalAccept 无 template_id 列，仅落 sections 快照），并把模板 sections JSON 预置进 `score_detail`（请求未显式给 score_detail 时）。
- **P-4** 批文生成：`conclude_mid_check` / `conclude_final_accept` 成功后创建一条 EReport（标题「中期检查批文」/「项目验收批文」，content 汇总 conclusion+score_detail JSON 文本）并回填 `report_id`；EReport 字段以 models.py 现状为准，不适配处标 CONCERN 上报，不停等。
- **P-5** 变更分流：`severity` 入参 MAJOR|GENERAL（缺省 GENERAL，DDL/模型 default GENERAL）。GENERAL=内部备案：submit 后直接 EFFECTIVE（写 approval.log 单步）；MAJOR=主管审批：沿既有 `_advance_change` 两级链（R-MANAGER→R-LEADER，尊重 twostep 开关）。
- **P-6** conflict：changeType=BUDGET 且 newValue.totalBudget < EProject.spent_amount → `conflict_flag=1`；此时 decision=APPROVED → 409 `CODE_CONFLICT` + 状态 ROLLED_BACK，不生效。
- **P-7** EFFECTIVE 回写映射：DELAY→`end_date=newValue.endDate`；TITLE→`title`；MEMBER→`member_ids=newValue.memberIds`（JSON 原样）；BUDGET→`total_budget=newValue.totalBudget` + 该项目活跃 FBudget（非 CLOSED 最新一条）`total_approved` 同步差额、首条 FBudgetLine `amount_adjusted` 增量；「预算调剂单」以 E_CHANGE_VERSION.snapshot.budgetAdjustment JSON 承载（F 域调整单据表 M1-b 未建，M2 接）。
- **P-8** 版本快照：submit 时写一行 EChangeVersion（snapshot=变更前 EProject 对应字段 JSON + version_no 自增 per change）；`GET /project/{id}/change-request/{changeId}/versions` 返回快照列表；变更 code 回填 `code_of("CHG", id)`（若 00-common.sql seq_prefix_registry 已有变更前缀则跟随其值，implementer 现场确认，CONCERN 上报）。
- **P-9** B5 动作端点：`POST /apply/guidelines/{id}:publish`（DRAFT→PUBLISHED + publish_at + `_notify_role(tenant, "R-STAFF", ...)` 广播征集通知）与 `POST /apply/guidelines/{id}:close`（PUBLISHED→CLOSED）；重复调用幂等 200；契约补 01-P 双份 yaml（沿 :713 `:publish` 冒号动作风格）。R-MANAGER 才可写。
- **P-10** B5 论证评审：`create_review` biz_type=`GUIDE`、target_id=guidelineId（N 域无枚举校验，任意串可建，不需改 N）；conclude 流程经 `_conclude_writeback` 新增 GUIDE 分支 → 延迟 import 调 `p/api.py` 单一写者 `conclude_guide_review(n_task_id)`：评审结论通过（conclusion PASS/APPROVED 语义，按 N 域 conclude 传参现状适配）→ guideline DRAFT→PUBLISHED（入库发布+推送）；不通过→保持 DRAFT。外部填报打通留 M2。

## Review Focus（终审与各任务评审重点）

1. **board 八键金额全 string**：任何一处漏 `num2()` 都会把数字类型漏给前端破坏 Money=string 契约（测试：断言每个金额键 isinstance str，Task 3）。
2. **GENERAL 备案绕过审批链**：EFFECTIVE 必须先过 conflict 检查再落 approval.log，顺序反了会把冲突变更备案生效（测试：conflict GENERAL 变更 submit→409/ROLLED_BACK，Task 6）。
3. **ROutput.project_ids JSON 元素类型混存**（int vs str id）：Python 过滤必须兼容两种类型（测试：project_ids 存 str 时 board 仍计数，Task 3）。
4. **N conclude 单一写者**：GUIDE 分支若在 expertreview 内直接 UPDATE PGuideline 即违纪（评审 grep 检查 + 测试经 conclude_guide_review 间接生效，Task 7）。
5. **`:publish`/`:close` 动作路由与 `{int:id}` 详情路由注册顺序**：动作路由必须先注册，否则被动态段吞掉（测试：POST :publish 经真实路由命中，Task 7）。

---

### Task 1: E 域模型三件套——EEvalTemplate / EChangeVersion / severity 列 + 迁移 0002 + DDL/detail

**Files:**
- Modify: `backend-django/apps/project/models.py`（EChangeRequest 后追加两模型；EChangeRequest 加 severity 列）
- Create: `backend-django/apps/project/migrations/0002_eevaltemplate_echangeversion_severity.py`
- Modify: `design/02-项目过程管理-E.ddl.sql`（E_EVAL_TEMPLATE / E_CHANGE_VERSION CREATE TABLE；E_CHANGE_REQUEST 补 severity 列）
- Modify: `design/02-项目过程管理-E.detail.md`（功能行 + 3.x 两表节 + severity 说明）
- Copy: `frontend/src/api/schema/02-项目过程管理-E.ddl.sql`（cp 后 cmp 逐字节一致）
- Test: `backend-django/tests/test_project_domain.py`（追加冒烟用例）

**Interfaces:**
- Produces: `EEvalTemplate`（fields: name Char(128)、scene Char(16) default MID_CHECK、sections JSON default list、score_rubric JSON、status Char(16) default ACTIVE、deleted/tenant/creator/时间戳；db_table `e_eval_template`）、`EChangeVersion`（change FK EChangeRequest PROTECT、version_no PositiveIntegerField、snapshot JSON、creator_id；db_table `e_change_version`）、`EChangeRequest.severity` Char(8) default GENERAL。
- 后续 Task 4/5/6/7 直接按这些名字消费。

- [ ] **Step 1: 写冒烟测试**（EEvalTemplate/EChangeVersion 可建可查、severity default GENERAL；断言 db_table 与字段名）
- [ ] **Step 2: 红** `pytest backend-django/tests/test_project_domain.py -k m1d_model -v` → FAIL (ImportError/AttributeError)
- [ ] **Step 3: 实现** models 两模型+severity 列（DDL 02-E 为权威：列名/枚举逐字对齐；条件唯一不进 Meta，普通索引进 Meta——M1-b Task 1 先例）
- [ ] **Step 4: 迁移** `makemigrations project` → 0002；`makemigrations --check` clean
- [ ] **Step 5: 绿** + 全量 `pytest` ≥311 passed
- [ ] **Step 6: DDL/detail/副本** 三处同步+cmp+safe_load（.ddl.sql 无 YAML，cmp 即可）
- [ ] **Step 7: Commit** `feat(project): M1-d EEvalTemplate/EChangeVersion 模型与 severity 列、迁移 0002+DDL/detail（B3/B4 表结构）`

### Task 2: policy 放行——board/eval-templates/change-versions/guideline 动作

**Files:**
- Modify: `backend-django/config/casbin/policy.csv`（project 域 :131-138 附近 + apply 域 guideline 段）
- Modify: `backend-django/tests/test_rbac.py`（+2 用例：行存在 + keyMatch2 覆盖矩阵，含负面断言——规避 :354 恒真教训）

**Interfaces:**
- Produces: 显式行 `GET /project/*/board`（R-MANAGER/R-LEADER/R-FINANCE）、`/project/eval-templates*` POST/GET/PUT/DELETE（R-MANAGER 写、R-LEADER/R-FINANCE GET）、`GET /project/*/change-request/*/versions`（R-MANAGER/R-LEADER/R-FINANCE）、`POST /apply/guidelines/*:publish` 与 `*:close`（R-MANAGER）。
- 写前 casbin keyMatch2 实测：冒号动作路径 `*:publish` 是否被裸 POST `/apply/guidelines` 覆盖——不覆盖则显式行（M1-b Task 2 Ruling 先例）；列对齐公式 `"p, "+(role+",").ljust(11)+(path+",").ljust(38)+action`。

- [ ] **Step 1: 红测试**（断言新行存在 + Enforcer 探针：R-MANAGER POST :publish 200 路、R-STAFF 拒）
- [ ] **Step 2: 红** → FAIL
- [ ] **Step 3: 加行**（keyMatch2 写前实测裁定显式/通配）
- [ ] **Step 4: 绿** test_rbac 全过 + 全量 ≥313 passed
- [ ] **Step 5: Commit** `feat(rbac): M1-d 看板/评估模板/变更版本/指南发布端点策略放行（B2/B3/B4/B5）`

### Task 3: B2 看板——聚合端点 + 契约补丁

**Files:**
- Modify: `backend-django/apps/project/api.py`（新增 `project_board(request, id: int)` + `_board_outputs(tenant_id, project_id)` helper）
- Modify: `backend-django/config/api.py`（注册 `GET /project/{id}/board`，紧跟既有 project 组）
- Modify: `design/02-项目过程管理-E.openapi.yaml` + 前端副本（board 路径 + ProjectBoard schema，P-1/P-2 口径）
- Test: `backend-django/tests/test_project_domain.py`

**Interfaces:**
- Consumes: `_execution_of(tenant_id, project_id)`（apps/funding/api.py:1413，**函数内延迟 import**）；`to_api_*` 无需新序列化器（board 返回手拼 dict）。
- Produces: 响应 data 八键 `fund/progress/members/quality/outsource/changes/outputs`（七键——fund 内含 execRate 两率；键名 camelCase，金额全 num2 string）。

- [ ] **Step 1: 红测试**：八键齐全且金额键 isinstance str（fund.budgetApproved 等）；ROutput.project_ids 存 str id 时 outputs.total 仍计数（Review Focus 3）；project 不存在→40401
- [ ] **Step 2: 红** → FAIL
- [ ] **Step 3: 实现**（P-2 口径逐键；跨 app import 一律函数内延迟 import）
- [ ] **Step 4: 绿** + 全量
- [ ] **Step 5: 契约补丁** 双 yaml cmp+safe_load
- [ ] **Step 6: Commit** `feat(project): 项目八要素看板——经费/进度/人员/质量/外包/变更/成果聚合（B2）`

### Task 4: B3 评估模板 CRUD + 中检/验收接模板

**Files:**
- Modify: `backend-django/apps/project/api.py`（`list/create/update/delete_eval_template` 四 handler + `create_mid_check`/`create_final_accept` 接 templateId）
- Modify: `backend-django/config/api.py`（`/project/eval-templates` 组）
- Modify: `design/02-*.openapi.yaml` 双份（EvalTemplate schema + 路径组：GET 分页 / POST / PUT /{id} / DELETE /{id} 软删）
- Test: `backend-django/tests/test_project_domain.py`

**Interfaces:**
- Consumes: Task 1 EEvalTemplate；既有 `create_mid_check`（project/api.py:169）/`create_final_accept`（:280）。
- Produces: `to_api_eval_template`（camelCase：id/name/scene/sections/scoreRubric/status/…）；EMidCheck.template_id 落值；score_detail 预置 sections（P-3）。

- [ ] **Step 1: 红测试**：CRUD 四操作经真实路由；create_mid_check 带 templateId → EMidCheck.template_id 命中 + score_detail == 模板 sections；templateId 不存在→40401；不带 templateId → 行为与现状一致（回归）
- [ ] **Step 2: 红** → FAIL
- [ ] **Step 3: 实现**（create/update 无同名唯一约束；delete 软删 deleted=1）
- [ ] **Step 4: 绿** + 全量
- [ ] **Step 5: 契约补丁** 双份 cmp+safe_load
- [ ] **Step 6: Commit** `feat(project): 统一评估模板 CRUD+中检/验收接模板与填报快照（B3）`

### Task 5: B3 conclude 批文生成 + 通知

**Files:**
- Modify: `backend-django/apps/project/api.py`（`conclude_mid_check` :645 / `conclude_final_accept` :656 尾部追加批文+通知）
- Test: `backend-django/tests/test_project_domain.py`

**Interfaces:**
- Consumes: 既有 conclude 两写者；`_notify_role` 范式（funding/api.py:122-137，E 域自建同款或延迟 import——implementer 选一，CONCERN 记录）。
- Produces: conclude 成功后 EReport 批文行 + `report_id` 回填（P-4）。

- [ ] **Step 1: 红测试**：conclude 后 EMidCheck.report_id 非空且 EReport 行存在（标题含「批文」）；重复 conclude 幂等不重复建批文；通知异常不阻断（monkeypatch _notify_role raise → conclude 仍 200）
- [ ] **Step 2: 红** → FAIL
- [ ] **Step 3: 实现**（批文创建与 report_id 回填同 atomic）
- [ ] **Step 4: 绿** + 全量
- [ ] **Step 5: Commit** `feat(project): 评估结论批文生成与通知回填（B3）`

### Task 6: B4 变更分流 + conflict + 生效回写 + 版本快照 + 预算联动

**Files:**
- Modify: `backend-django/apps/project/api.py`（`create_change_request` :185、`_advance_change` :202、新增 `get_change_versions(request, id: int, change_id: int)`）
- Modify: `backend-django/config/api.py`（`GET /project/{int:id}/change-request/{int:change_id}/versions`，先于既有 change 动态动作路由）
- Modify: `design/02-*.openapi.yaml` 双份（EChangeRequestCreate.severity、EChangeVersion schema、versions 路径）
- Test: `backend-django/tests/test_project_domain.py`

**Interfaces:**
- Consumes: Task 1 EChangeVersion/severity；FBudget/FBudgetLine（apps/funding.models，ORM 直改，P-7）。
- Produces: severity 入参；GENERAL submit→EFFECTIVE+approval.log；MAJOR 沿两级；conflict 409+ROLLED_BACK；EFFECTIVE 回写映射（P-7）；versions 列表响应 `[{versionNo, snapshot, createdAt}]` camelCase。

- [ ] **Step 1: 红测试**：①GENERAL：submit→status EFFECTIVE+approval.log 一条+EProject.title 已回写 ②MAJOR：submit→APPROVING（两级链不变）③conflict：BUDGET newValue.totalBudget<spent→submit 后 conflict_flag=1、decision APPROVED→409+ROLLED_BACK（Review Focus 2）④BUDGET 无冲突 EFFECTIVE→EProject.total_budget+FBudget.total_approved 同步+snapshot.budgetAdjustment 存在 ⑤TITLE EFFECTIVE→title 回写；versions 端点返回快照行数=submit 次数 ⑥变更 code 回填 CHG-年-序
- [ ] **Step 2: 红** → FAIL（六组）
- [ ] **Step 3: 实现**（P-5/P-6/P-7/P-8 逐条；conflict 检查先于 approval.log 与 EFFECTIVE）
- [ ] **Step 4: 绿** + 全量（test_project_domain 既有 12 用例零回归）
- [ ] **Step 5: 契约补丁** 双份 cmp+safe_load
- [ ] **Step 6: Commit** `feat(project): 变更重大/一般分流+冲突回退+生效回写与版本快照、预算联动（B4）`

### Task 7: B5 指南 publish/close + GUIDE 论证评审入库

**Files:**
- Modify: `backend-django/apps/p/api.py`（`publish_guideline`/`close_guideline`/`conclude_guide_review(n_task_id)`）
- Modify: `backend-django/apps/expertreview/api.py`（`_conclude_writeback` :390 加 GUIDE 分支，**延迟 import p.api**）
- Modify: `backend-django/config/api.py`（`:publish`/`:close` 动作路由注册在 guidelines 动态详情之前）
- Modify: `design/01-项目申报与立项-P.openapi.yaml` 双份（两动作路径 + 409/404 响应）
- Test: `backend-django/tests/test_apply_domain.py`（若文件名不同以现实现场为准；新增用例放 P 域测试文件）

**Interfaces:**
- Consumes: PGuideline（p/models.py:9-33）、`_notify_role`、N 域 conclude 流程（biz_type=GUIDE 由测试直接 create_review 构造）。
- Produces: publish→PUBLISHED+publish_at+R-STAFF 通知；close→CLOSED；GUIDE conclude 通过→DRAFT→PUBLISHED（P-10）。

- [ ] **Step 1: 红测试**：①R-MANAGER publish DRAFT→200 PUBLISHED+publish_at 非空+SysNotification 有 R-STAFF 用户行；重复 publish 幂等 200 ②close PUBLISHED→CLOSED；DRAFT close→40901 ③N 域 create_review(biz_type=GUIDE,target_id=gid)→专家打分→conclude 通过→guideline PUBLISHED（入库发布）；不通过→仍 DRAFT ④expertreview/api.py 顶层无 `from apps.p` import（grep 断言延迟 import）
- [ ] **Step 2: 红** → FAIL
- [ ] **Step 3: 实现**（P-9/P-10；动作路由先注册——Review Focus 5）
- [ ] **Step 4: 绿** + 全量
- [ ] **Step 5: 契约补丁** 双份 cmp+safe_load
- [ ] **Step 6: Commit** `feat(apply): 指南征集发布/关闭+专家论证评审入库推送（B5）`

### Task 8: 前端——看板 tab + 指南发布/关闭 + mock 对齐

**Files:**
- Modify: `frontend/src/views/ProjectView.vue`（新增「看板」tab：八要素卡片，fund 卡片复用既有 fund tab 数据风格，各要素「直达」链接到对应已有页面/tab）
- Modify: `frontend/src/views/GuideView.vue`（PUBLISHED/CLOSED 状态徽标 + R-MANAGER 可见发布/关闭按钮，消费 `:publish`/`:close`）
- Modify: `frontend/src/api/mock/overrides/project.ts`、`guide.ts`（board 聚合 + publish/close mock）
- Modify: `frontend/src/api/mock/overrides/auth.ts`（PAGE_GRANTS/ROLE_CAPS 镜像 Task 2 policy 行——board 无新页则仅 caps）
- Test: `frontend/scripts/` 冒烟脚本按需（非强制）

**Interfaces:**
- Consumes: GET /project/{id}/board（ProjectBoard 八键）、POST :publish/:close、契约 schema 副本（双 yaml 已同步）。

- [ ] **Step 1: 实现** 三视图+mock（契约键逐一对照 02-E/01-P yaml，camelCase/Money=string）
- [ ] **Step 2: typecheck** `pnpm -C frontend exec vue-tsc --noEmit` → 0 errors
- [ ] **Step 3: 回归** `pytest` 全量数字不降
- [ ] **Step 4: Commit** `feat(fe): 项目看板 tab+指南发布/关闭——契约驱动 mock 对齐 M1-d`

### Task 9: seed + README 收口

**Files:**
- Modify: `backend-django/scripts/seed_demo.py`（M1-d 段：EEvalTemplate 1 条 MID_CHECK sections 三节；EChangeVersion 1 条挂既有变更；PGuideline BUD-GUIDE-DEMO-0001 PUBLISHED publish_at；code 经 code_of 回填；幂等键沿用业务键）
- Modify: `README.md`（三处测试计数 → 实测 N）

**Interfaces:**
- Consumes: Task 1/7 模型；seed 幂等单进程文件库两遍法（M1-b/c 先例：test settings sqlite :memory: 两进程隔离坑，必须单进程脚本跑两遍）。

- [ ] **Step 1: 实现** seed 段（只增不改 M1-a/b/c 种子）
- [ ] **Step 2: 幂等验证** 单进程两遍 → pass2 全零
- [ ] **Step 3: 全量绿** + README 计数三处=实测 N
- [ ] **Step 4: Commit** `chore(seed+readme): M1-d 演示数据 + 测试数更新为实测 N`
