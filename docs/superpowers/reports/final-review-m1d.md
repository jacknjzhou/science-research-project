# M1-d 全分支终审报告（B2 看板 / B3 评估 / B4 变更 / B5 指南）

- 评审范围：`b3eec62..69422ff`，9 个 commit
- Review package：`.superpowers/sdd/2026-11-18-m1d-board-evaluation-change-guide/review-b3eec62..69422ff.diff`
- 需求来源：`docs/superpowers/plans/2026-11-18-m1d-board-evaluation-change-guide.md`
- 任务台账：`.superpowers/sdd/2026-11-18-m1d-board-evaluation-change-guide/progress.md`
- 验收基线：`docs/reports/2026-11-12-conow-alignment-roadmap.md`（B2 :73、B3 :78、B4 :77、B5 :50-51）
- 评审方式：只读亲验 + 全量测试/类型检查/契约比对；未修改任何源码或配置

## 结论：REQUEST_CHANGES

B2 看板与 B5 指南的功能主链基本达标，但 B3/B4 的数据正确性，以及看板/变更/指南三处租户隔离问题，构成阻断项。当前不建议合并。

### 合并前必须修复（Critical）

1. **C-1** 变更 `newValue` 不做类型/取值校验，却无条件把变更置为 `EFFECTIVE`：非法预算金额静默不生效、非法日期把 `end_date` 写成 `NULL`、非法 `changeType` 在 PG 上直接 500。涉及 `backend-django/apps/project/api.py:403-408`、`:304-310`、`:347-351`、`:357-372`、`:435-446`。
2. **C-2** 看板与变更生效等新代码沿用无租户过滤的 `_get_project_or_404`：任意租户用户可按 id 读他租户看板；R-MANAGER 可跨租户审批变更并经新的 `_apply_change` 回写项目；中检批文按调用方 project_id 落库。涉及 `backend-django/apps/project/api.py:92-96`、`:157-167`、`:453-454`、`:480`、`:401`、`:1107-1113`。
3. **C-3** 指南评审回写没有租户过滤：N 域任务可发布他租户的指南并通知他租户 R-STAFF。涉及 `backend-django/apps/p/api.py:190-209`（关键行 `:197`）。

修完 C-1/C-2/C-3 后，还需一并处理 I-1/I-2/I-3（见下），否则 B3 的「模板快照」与「批文可见性」仍不成立。

---

## Critical

### C-1 变更输入未校验 → 200 EFFECTIVE 但什么都没改 / 字段被清空

**证据**

- `backend-django/apps/project/api.py:403-408`：只校验 `changeType` 非空、`severity ∈ {GENERAL, MAJOR}`，**没有校验 `changeType` 是否属于 DELAY/BUDGET/MEMBER/TITLE/SCOPE，也没有按类型校验 `newValue`**。
- DDL 明确约束：`design/02-项目过程管理-E.ddl.sql:244-245` `CHECK (change_type IN ('DELAY','BUDGET','MEMBER','TITLE','SCOPE'))`。sqlite 测试库不执行 CHECK，所以测试全绿；PG 上非法类型会变成 500 而不是 40001。
- `apps/project/api.py:300-311` `_change_conflict`：`raw is None` → `False`；`Decimal(str(raw))` 抛 `InvalidOperation/TypeError/ValueError` → `False`。
- `apps/project/api.py:347-351` `DELAY`：`if raw: p.end_date = _parse_date(raw); fields.append("end_date")`；`_parse_date`（`:81-89`）解析失败返回 `None`，于是 `end_date` 被写成 NULL 并 save。
- `apps/project/api.py:357-372` `BUDGET`：`Decimal` 失败 → `target=None` → 跳过写入并 `return None`，**无 40001**。
- `apps/project/api.py:435-446`：无论 `_apply_change` 是否真的改了字段，都执行 `status="EFFECTIVE"`、`approved_at`、`approval_status="APPROVED"`、`approval.log(...)`。
- MAJOR 路径同样：`_advance_change` `:479-504` 冲突检查 False 后，状态推进到 EFFECTIVE 再调用 `_apply_change`，`_apply_change` 无操作也照样落审批日志。

**为什么是问题**

- 违反计划 Global Constraint（`docs/superpowers/plans/2026-11-18-m1d-board-evaluation-change-guide.md:19-20`）「无效金额用 40001 不静默归 0」。
- 数据错误：非法日期清空项目结束日期；非法预算返回 200 且变更单显示 EFFECTIVE；审计日志记录了一次并未发生的变更。
- 这是 B4 的核心写路径，任何上游传参错误都会变成静默数据损坏。

**建议修法**

- 在 `create_change_request` 入口按 `change_type` 校验 payload：`BUDGET` 必须可 `Decimal` 且 ≥ 0；`DELAY` 必须可解析为日期；`MEMBER` 必须是 int 数组；`TITLE` 必须非空；`changeType` 必须在白名单内。失败一律 `ApiError(400, CODE_BAD_REQUEST, ...)`。
- `_apply_change` 返回 `(applied: bool, detail|error)`；只有 `applied` 才允许 `EFFECTIVE` + approval.log；MAJOR 的 `_advance_change` 同样以 apply 结果决定是否推进状态。
- 补 4 个回归测试：非法日期、非法金额、非 dict `newValue`、非法 `changeType`，断言 40001 且项目字段不变。

### C-2 看板/变更生效/批文的项目查找无租户约束（跨租户读与写）

**证据**

- `backend-django/apps/project/api.py:92-96` `_get_project_or_404(project_id)` 只过滤 `id` + `deleted=0`，**没有 tenant_id**。该 helper 是 BASE 既有。
- 看板是 **M1-d 全新端点**：`apps/project/api.py:157-167` 没有 `domain_from(request)`，`p = _get_project_or_404(id)` 后用 `p.tenant_id` 查其余域；路由 `backend-django/config/api.py:132`；策略 `backend-django/config/casbin/policy.csv:123` 允许 R-STAFF `GET /api/v1/project/*`。因此租户 A 的 R-STAFF 可按 id 读取租户 B 项目的经费/成员/质量/外包/变更/成果聚合。
- 变更/中检/验收的创建在 BASE 已存在，仍复用同一 helper（`apps/project/api.py:401`、`:275`、`:567`）；M1-d 新增的 `_apply_change` 使变更审批从「改状态」升级为「直接写项目字段」，风险面由此扩大。
- 审批 `_advance_change` `:453-454` 只按 `id` 取变更单、只比较 `row.project_id`；`:480` 取项目也无 tenant。R-MANAGER 可跨租户把变更推进到 EFFECTIVE 并回写 `EProject`。
- 中检批文 `conclude_mid_check` `:1107-1113` 用调用方传入的 `project_id` 取项目并建 `EReport`，`mc` 查询本身也无 tenant。

**为什么是问题**

- 直接违反计划全局约束「所有查询带 tenant_id + deleted=0」（plan `:15-17`）。
- 看板聚合含经费、成员姓名、风险等级，属于跨租户数据泄露；变更/中检写路径会污染他租户项目数据。
- 看板是本次新增的暴露面，变更回写是本次新增的写面，不能以「helper 是旧的」为由整体放过。

**建议修法**

- 新增 `_get_project_in_tenant_or_404(tenant_id, project_id)`（或在 helper 增加必填 tenant 参数），新代码统一使用：`project_board` 先 `d = domain_from(request)`；`create_change_request` / `create_mid_check` / `create_final_accept` 传入 `d.tenant_id`。
- `_advance_change` 的变更单与项目查询都加 `tenant_id=d.tenant_id, deleted=0`；`get_change_versions` 已按 tenant 查变更，可保留。
- `conclude_mid_check` 改为按 `mc.project_id` / `mc.tenant_id` 取项目与建批文（同时解决 I-5）。
- 补双租户测试：A 租户请求 B 的项目 board/变更/审批 → 404，且 B 的数据不变。

### C-3 指南评审回写无 tenant → 跨租户发布

**证据**

- `backend-django/apps/p/api.py:190-209`：`:194` 取 N 任务只按 id + deleted；`:197` `PGuideline.objects.filter(id=t.target_id, deleted=0).first()` **没有 tenant_id**；`:202-207` 将 DRAFT 改为 PUBLISHED；`:208` 按 `g.tenant_id` 通知该租户 R-STAFF。
- 上游 `backend-django/apps/expertreview/api.py:222-238` `create_review` 只校验 `biz_type`/`title`，`target_id`/`project_id` 可任意填；`:375-388` `conclude_review` 先把任务置 CONCLUDED，再经 `_conclude_writeback` `:407-410` 调用上述单一写者。

**为什么是问题**

- 租户 A 的评审任务只要 `target_id` 指向租户 B 的指南，就能绕过 B 的 R-MANAGER 发布动作，直接把 B 的指南置为 PUBLISHED 并向 B 的 R-STAFF 推送；这是跨租户写 + 越权状态机推进。
- 「N 域单一写者」在租户维度没有闭环，B5 的发布权限模型被绕过。

**建议修法**

- `conclude_guide_review` 改查 `PGuideline.objects.filter(id=t.target_id, tenant_id=t.tenant_id, deleted=0)`；理想情况下 `create_review` 也校验 `target_id` 属于 `d.tenant_id`。
- 补测试：租户 1 的任务 target 指向租户 2 的 DRAFT 指南，conclude 后指南仍为 DRAFT，且无通知。

---

## Important

### I-1 B3 模板 sections 未预置进中检 `score_detail`，验收也无快照；验收测试被削弱

**证据**

- `backend-django/apps/project/api.py:273-289` `create_mid_check` 只写 `check_round/check_date/plan_id/template_id/expert_ids`，**没有写 `score_detail`**；`_resolve_template_id` `:586-605` 只返回 id，不返回模板对象。
- `backend-django/tests/test_project_domain.py:581-608` 三个用例只断言 `mc.template_id` 与 `check_round`，**没有断言 `score_detail == 模板 sections`**。
- `backend-django/apps/project/api.py:565-576` `create_final_accept` 只写 `template_id`；`EFinalAccept` 模型（`apps/project/models.py:242-247`）没有 score_detail 列，模板 sections 未落任何快照。
- 计划 Task 4 Step 1 的验收语句明确要求：`create_mid_check` 带 `templateId` → `template_id` 命中 **且 `score_detail == 模板 sections`**；Task 4 还要求验收侧「仅落 sections 快照」。

**为什么是问题**

- 模板后续被编辑/禁用后，这次中检/验收实际依据的评分章节无法还原，B3「一套模板配置支撑两种评估」只剩一个 id 引用。
- 测试只覆盖了绑定，没有覆盖快照，属于验收条件被削弱而非单纯缺测试。

**建议修法**

- 模板存在且请求未显式传 `score_detail` 时，写入 `{"sections": tpl.sections, "scoreRubric": tpl.score_rubric}`；请求显式传值时保留调用方值（与计划措辞一致）。
- 验收侧若坚持不加列，可把快照放进 `output_summary`（如 `templateSections`），但契约需同步；更干净的是给 `E_FINAL_ACCEPT` 补 JSON 列并迁移。
- 把 `tests/test_project_domain.py:581` 的断言补成 `mc.score_detail["sections"] == tpl.sections`，并新增验收快照断言。

### I-2 契约新增的 `templateId` / `approvalDocId` 完全没有出参

**证据**

- `backend-django/apps/project/mappings.py:84-93` `to_api_mid_check` 返回 `template_id`、`report_id`，**没有 `approval_doc_id`**，且整体是 snake_case。
- `backend-django/apps/project/mappings.py:121-130` `to_api_final_accept` **既没有 `template_id` 也没有 `approval_doc_id`**。
- 契约明确声明：`design/02-项目过程管理-E.openapi.yaml:1098` `templateId`、`:1103` `approvalDocId`；`:1180` `templateId`、`:1181` `approvalDocId`。
- 计划 Global Constraint（plan `:16`）要求「响应键全 camelCase（前端消费契约键）」；同批的 `to_api_eval_template`（`mappings.py:133-142`）和 `to_api_change_version`（`:109-118`）已经 camelCase，说明这是可做到的。

**为什么是问题**

- 前端按契约读 `data.templateId` / `data.approvalDocId` 会得到 `undefined`；中检/验收落定后，批文 id 在 API 上不可见，B3 的「批文回填」只剩数据库内部状态。
- 契约与实现直接矛盾，且契约副本会被前端 mock/类型使用（`frontend/src/api/schema/02-...E.openapi.yaml` 与 design 一致）。

**建议修法**

- 两个映射补 `templateId`、`approvalDocId`；同时把这两个响应对象的键统一成 camelCase（至少新增字段必须是 camelCase）。
- 在 `tests/test_project_domain.py:628` / `:611` 增加响应 JSON 断言，防止只测 DB。

### I-3 批文/变更多条写路径无事务；批文幂等无唯一约束

**证据**

- 计划 Task 5 Step 3 要求「批文创建与 report_id 回填同 atomic」。
- `backend-django/apps/project/api.py:1103-1116`：`mc.save` → `_issue_report`（内部 create + 二次 save code）→ `mc.save(approval_doc_id)`，三次独立写，**无 `transaction.atomic`**。
- `_issue_report` `:1077-1093`：先 `filter(...).first()` 复用，再 `create`，再 `code_of` 二次 save；**无 `select_for_update`、无 DB 唯一约束**。并发 conclude 可各插一份。
- `create_change_request` `:410-446`：建变更、建版本、apply、改状态、写日志多写无事务；`_advance_change` `:489-504` 先把状态 update 成 EFFECTIVE，再 `_apply_change`，apply 抛错会留下「状态已生效、项目未改」。
- `_sync_change_budget`（`:378-399`）在 `p.save` 之后执行；若它失败，项目总额已变、F 预算未同步，且变更单仍非 EFFECTIVE。

**为什么是问题**

- 部分失败会留下不可自愈的不一致（例如批文行已建但 code 为空，重试命中旧行后不会补 code；变更单 EFFECTIVE 但项目字段未回写）。
- 与 Task 5 的明确要求不符；并发重复签发也破坏「一次评估一批文」。

**建议修法**

- `conclude_mid_check` / `conclude_final_accept` 用 `transaction.atomic()` 包住「结论 + 批文 + approval_doc_id」；`_issue_report` 内 `select_for_update` 锁中检/验收行，或加唯一部分索引 `(tenant_id, doc_type, mid_check_id)` / `(tenant_id, doc_type, final_accept_id)`。
- `create_change_request` 与 `_advance_change` 用 `transaction.atomic()`；`_advance_change` 先 apply 成功再推进状态（或用 `select_for_update` 锁变更单）。
- `_issue_report` 复用旧行时若 `code` 为空，补一次 `code_of`。

### I-4 `create_eval_template` 不校验 `status` 枚举，非法值 200 入库

**证据**

- `backend-django/apps/project/api.py:641-645`：`status=body.get("status") or "ACTIVE"`，**没有白名单校验**；`_EVAL_TEMPLATE_STATUSES = ("ACTIVE","DISABLED")` 在 `:583` 已定义，`update_eval_template` `:671-674` 有校验，create 没有。
- 契约 `design/02-项目过程管理-E.openapi.yaml:1293` 明确 `status` enum `[ACTIVE, DISABLED]`。

**为什么是问题**

- 违反全局约束「无效枚举用 40001」；写入 `FOO` 后该模板永远无法被 `_resolve_template_id` 选中（要求 ACTIVE），但接口返回 200，前端无法解释。
- create/update 校验不一致，属于容易漏的契约缺口。

**建议修法**

- create 分支加 `if status not in _EVAL_TEMPLATE_STATUSES: raise ApiError(400, CODE_BAD_REQUEST, ...)`，并补一条 40001 测试。

### I-5 批文幂等键含调用方 `project_id`，结论写回也信任调用方 project_id

**证据**

- `backend-django/apps/project/api.py:1077-1082`：幂等查询条件是 `tenant_id + project_id + doc_type + mid_check_id/final_accept_id`。
- `conclude_mid_check` `:1107-1113` 用调用方传入的 `project_id` 取项目并建批文，而不是 `mc.project_id`；`conclude_final_accept` `:1136-1141` 用的是 `fa.project_id`（正确）。
- `mc` 查询本身（`:1100`）只有 id + deleted，没有 tenant。

**为什么是问题**

- 同一个 `mid_check_id` 若被第二次以不同 `project_id` 调用，幂等条件不命中，会再签一份批文；N 域任务携带错 project_id 时，批文会挂到别的项目，甚至跨租户。
- 这与 C-2 同源，但即使补了端点租户校验，函数内部仍应自洽。

**建议修法**

- `conclude_mid_check` 改从 `mc.project_id` 取项目、写批文；`_issue_report` 幂等查询去掉 `project_id`（或改为 `tenant_id+doc_type+mid_check_id`），并校验 `mc.tenant_id` 与调用上下文一致。

---

## Minor

### M-1 动态路由未使用 `{int:id}`，契约路径参数名与后端不一致

- `backend-django/config/api.py:132` `/project/{id}/board`、`:146` `/project/{id}/change-request/{change_id}/versions`；计划 Task 6 写的是 `{int:id}`。`backend-django/apps/funding/api.py:338` 有 `{int:id}` 先例。
- 契约 `design/02-...E.openapi.yaml` 的 versions 路径参数写作 `{changeId}`，后端是 `{change_id}`；URL 语义不受影响，但代码生成/文档会出现两个名字。
- 现状靠 handler 注解 `id: int` 完成转换，非法 id 会走 ninja 校验错误而非 404。建议新路由统一 `{int:id}`，契约参数名与后端一致。

### M-2 `to_api_change_request` 仍是 snake_case，与 02-E 契约 camelCase 不一致

- `backend-django/apps/project/mappings.py:96-106` 返回 `project_id/change_type/old_value/new_value/conflict_flag/snapshot_ref`。
- 契约 `EChangeRequest` 使用 `projectId/changeType/...`。这是 BASE 既有风格，M1-d 新增的 `severity` 也沿用了 snake；目前没有前端消费变更详情，故列 Minor。若后续做变更列表 UI，会直接踩契约键。

### M-3 `E_CHANGE_VERSION` 索引 DDL 与模型列数不一致

- DDL `design/02-项目过程管理-E.ddl.sql:290`：`idx_e_chgver_change(tenant_id, change_id, version_no)` 三列。
- 模型 `backend-django/apps/project/models.py:198-200`：同名索引只含 `["tenant_id", "change"]` 两列。功能不受影响，但设计文档与迁移产物不一致，建议二选一对齐。

### M-4 种子指南是 DRAFT，计划 Task 9 期望一条 PUBLISHED 的演示指南

- `backend-django/apps/sysadmin/management/commands/seed_demo.py:1032-1038` 建 `GL-DEMO-2026-02` 为 DRAFT；计划 Task 9 写的是 `BUD-GUIDE-DEMO-0001` PUBLISHED + publish_at。
- 既有 `GL-DEMO-2026-01` 在 `:269` 已是 PUBLISHED，B5 演示仍可走通；但「发布动作」的演示数据不如计划直观。建议把新种子改为 PUBLISHED，或明确演示脚本先调 publish。

### M-5 前端 schema 目录没有 02-E DDL 副本

- `frontend/src/api/schema/` 只有 `03-科研经费管理-F.ddl.sql`，没有 02-E DDL。计划 Task 1 要求复制；实现者 progress 记为「从未存在」。不影响运行，但前后端契约资产不对称。

### M-6 `BoardFund` 把两个执行率声明为 string，契约/后端是 number

- `frontend/src/views/ProjectView.vue:244-247` `execRateByBudget: string; execRateByIncome: string`；契约 `design/02-...E.openapi.yaml:1310-1311` 是 `number`；后端 `_execution_of` 返回 float。
- 运行时 `pct()` 走 `toNum` 不会崩，但类型是假的；mock `frontend/src/api/mock/overrides/project.ts:144` 返回 `'0.3750'` 字符串，进一步固化了错误类型。建议类型改 `number`，mock 同步返回数字。

### M-7 中检未通过（CORRECT/TERMINATE）也签发批文，与 DDL 注释「通过时签发」措辞不一致

- `backend-django/apps/project/api.py:1103-1116` 对任意 conclusion 都调 `_issue_report`；DDL 注释 `design/02-...E.ddl.sql:214`、`:499` 写「结论通过时签发」。
- 评审 brief 只硬性要求「仅 FINAL_ACCEPT=APPROVED 才签」，实现满足该条；中检是否只对 CONTINUE 签发需产品确认。若确认只对通过签发，加 `if conclusion not in ("CONTINUE","PASS"): return` 并补测试。

### M-8 变更单接受客户端传入 `code`，可绕过 CHG 单号序列

- `backend-django/apps/project/api.py:411` `code=body.get("code")`，仅当为空才 `code_of("CHG", r.id)`（`:417-419`）。客户端可写任意/重复 code，破坏单号唯一性与审计。建议忽略 body.code，统一 `code_of`；确需导入时走单独入口并校验。

### M-9 看板成员只接受 int 数组元素，字符串 id 被静默丢弃

- `backend-django/apps/project/api.py:183` `[m for m in (p.member_ids or []) if isinstance(m, int)]`。若历史数据/导入写的是字符串 id，成员卡会少人且无提示。成果侧已专门处理 int/str（`:141-154`），成员侧建议同样兼容或至少记录告警。

---

## Review Focus 五项结论

### 1) 看板八要素口径：基本通过，租户范围不通过

- 经费复用 `_execution_of`，未重算：`apps/project/api.py:162-170` 延迟 import，`apps/funding/api.py:1413-1426` 统一「预算批复/到账/已用/冻结/结余 + 两率」，金额全部 `num2` 字符串。**通过**。
- 进度用 `EMilestone.status=ACHIEVED` / `ETask.status=COMPLETED`：`apps/project/api.py:173-180`。**通过**。
- 成员：`:182-187` 返回 `{userId,name}`，查无此人 `name=None`（契约 nullable）；未过滤 `SysUser.deleted/status`，但已删除用户仍可能显示姓名。**基本通过**（M-9）。
- 质量：`:190-199` 取 `p.health_score/p.risk_level` + 最新 `EHealthHistory`（模型无 deleted 字段，`apps/project/models.py:377-387`）。**通过**。
- 外包：`:202-205` `GContract` 按 tenant+project+deleted 聚合，金额 `_num2`。**通过**。
- 变更：`:208-213` 按状态计数，tenant+project+deleted。**通过**。
- 成果：`:141-154` 对 `ROutput.project_ids` 同时匹配 int 与 `str(int)`，测试 `tests/test_project_domain.py:469` 覆盖。**通过**。
- 金额 string：测试 `:417` 断言 Money 字符串；`:486` 覆盖成员与 404。**通过**。
- **不通过点**：`project_board` 没有请求租户校验（C-2），可跨租户读；前端执行率类型写错（M-6）。

### 2) 评估模板 scene 校验与中检/验收绑定：部分通过

- `_resolve_template_id` `apps/project/api.py:586-605`：`templateId/template_id` 双读、非整数 40001、查询带 tenant+deleted+ACTIVE、不存在/跨租户 40401、scene 不符 40001。**通过**。
- CRUD：`list/create/update/delete` `:615-688` 均带 tenant+deleted；软删；list 支持 scene/status 过滤；路由静态段先于 `{id}`（`config/api.py:116-128`，测试 `:573`）。**通过**。
- 绑定：`create_mid_check :281-288`、`create_final_accept :569-575` 均落 `template_id`；测试 `:581`、`:611`。**通过**。
- **不通过点**：模板 sections 未预置进中检 `score_detail`，验收无 sections 快照，测试未断言（I-1）；响应不出 `templateId/approvalDocId`（I-2）；create 不校验 status 枚举（I-4）。

### 3) 批文签发幂等与通知：部分通过

- 幂等：`_issue_report :1069-1094` 按 tenant+project+doc_type+mid/final id 复用旧行；测试 `:648` 断言重复 conclude 只有 1 份。**通过（单线程）**。
- 仅 FINAL_ACCEPT=APPROVED 才签：`conclude_final_accept :1130-1134` 提前 return；测试 `:663`。**通过**。
- 通知失败不阻断：`_notify_role` 内部 `try/except`（`:1055-1066`），调用点再包一层（`:1117-1121`、`:1146-1150`）；测试 `:676`。**通过**。
- 批文内容：title 含项目名 + 「中期检查批文/结题验收批文」，conclusion+score_detail 落 `EReport`，`approval_doc_id` 回填。**通过**。
- **不通过点**：无事务、幂等无唯一约束（I-3）；`conclude_mid_check` 用调用方 project_id 且 mc 查询无 tenant（I-5/C-2）；响应不出 `approvalDocId`（I-2）。

### 4) 变更分流/冲突/回写/预算联动：部分通过

- 默认 GENERAL、提交即 EFFECTIVE + 单条 approval.log：`create_change_request :406-446`；测试 `:705`。**通过**。
- MAJOR 走两级审批（受 `twostep_enabled` 控制）：`_advance_change :456-477`；测试 `:726`。**通过**。
- 冲突先于 approval.log 与状态推进：GENERAL `:428-433`、MAJOR `:479-487`；`conflict_flag=1` + `ROLLED_BACK` + 409；测试 `:755` 覆盖两条路径。**通过**。
- BUDGET 联动：`_sync_change_budget :378-399` 调 `FBudget.total_approved` 与首条 `FBudgetLine.amount_adjusted`，返回 `budgetAdjustment` 写版本快照；测试 `:786` 断言项目 120000 / 预算 120000 / delta 20000。**通过**。
- EFFECTIVE 回写四类字段：`_apply_change :342-372` TITLE/DELAY/MEMBER/BUDGET。**通过（合法输入）**。
- 版本：提交即落 `EChangeVersion`，`version_no` 自增，`snapshot_ref=E_CHANGE_VERSION#id`，versions 端点 camelCase（`:512-524`，`mappings.py:109-118`）；测试 `:812`。**通过**。
- **不通过点**：非法输入静默生效/清空（C-1）；非原子（I-3）；跨租户（C-2）；响应 snake_case（M-2）；客户端可传 code（M-8）。

### 5) 指南 publish/close 与 GUIDE 评审入库：状态机通过，租户隔离不通过

- `publish_guideline :158-173`：DRAFT→PUBLISHED + `publish_at` + R-STAFF 通知；PUBLISHED→200 幂等且不重复通知；CLOSED→409。测试 `tests/test_p_domain.py:191`、`:206`。**通过**。
- `close_guideline :176-187`：PUBLISHED→CLOSED；CLOSED→200 幂等；非 PUBLISHED→409。测试 `:212`。**通过**。
- 路由顺序：`config/api.py:70-75` 的 `{id}:publish` / `{id}:close` 注册在 `:76` `{id}` 之前；契约 01-P 双份一致。**通过**。
- GUIDE 单一写者：`expertreview/api.py:407-410` 延迟 import `conclude_guide_review`，N 域不直接 UPDATE P；测试 `:260` AST 检查无顶层 `apps.p` import。**通过**。
- 通知：publish `:171-172`、评审入库 `:208-209` 均推 R-STAFF。**通过**。
- **不通过点**：`conclude_guide_review` 无 tenant（C-3）；`create_review` 不校验 target（C-3 上游）。

---

## 全局约束逐条核对

| 约束 | 证据 | 结论 |
|---|---|---|
| 所有查询带 `tenant_id` + `deleted=0` | 看板各域 `apps/project/api.py:173-213`、模板 CRUD `:615-688`、versions `:512-524`、publish/close `apps/p/api.py:151-187` 均带；`_get_project_or_404:92-96`、`_advance_change:453-454`、`conclude_guide_review:197` 不带 | **不通过**（C-2/C-3）；其余新查询通过 |
| 金额 Decimal 运算、Money 以 string 出参（`num2`） | 看板经费复用 `_execution_of`（`apps/funding/api.py:1413-1426`）；外包 `_num2`（`apps/project/api.py:205`）；`_change_snapshot` 用 `str`（`:314-320`） | **通过**（看板/预算执行）；但 `to_api_change_request` 的 `new_value` 原样透出，客户端传数字时响应就是数字，不受 `num2` 约束（仅快照语义，可接受但需知悉） |
| 无效金额/枚举用 40001，不静默归 0 | `_change_conflict:307-310` 失败返回 False；`_apply_change:360-363` 失败跳过；`create_eval_template:644` 不校验 status | **不通过**（C-1、I-4） |
| `{int:id}` 类型化动态路由 + 静态段先于动态段 | 静态顺序：`config/api.py:116-132`；动态仍用 `{id}`/`{change_id}`；`apps/funding/api.py:338` 有 `{int:id}` 先例 | **部分**：顺序通过，类型化未采用（M-1），靠 handler 注解 int 转换 |
| 单号统一用 `code_of` | CHG `apps/project/api.py:418`、RPT `:1092`；`design/00-common.sql:332-333` 注册 RPT/CHG | **通过**；但变更允许 body 传 `code`（M-8） |

---

## 套件与工具链实测

### pytest

```text
$ cd backend-django && .venv/bin/python -m pytest -q
336 passed, 7 warnings in 12.65s
```

- 基线 310，计划 Task 9 目标 336，实测 336。
- README 三处计数已同步：`README.md:5`、`:29`、`:73`。

### 前端类型检查

```text
$ cd frontend && ./node_modules/.bin/vue-tsc --noEmit
(无输出，exit=0)
```

- 未使用 `pnpm exec vue-tsc`（本机 esbuild ignored-builds 会报错），按评审要求直调 `./node_modules/.bin`。

### 迁移一致性

```text
$ cd backend-django && ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/fr_m1d.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected
```

### 契约副本逐字节比对（16 对）

```text
SAME 01-项目申报与立项-P.openapi.yaml
SAME 02-项目过程管理-E.openapi.yaml
SAME 03-科研经费管理-F.openapi.yaml
DIFF 04-科研成果管理-R.openapi.yaml
SAME 05-科技成果转化-T.openapi.yaml
SAME 06-科研诚信与伦理-C.openapi.yaml
SAME 07-人员与团队-S.openapi.yaml
DIFF 08-数据分析与决策-D.openapi.yaml
SAME 09-采购与合同管理-G.openapi.yaml
SAME 10-资产与耗材管理-A.openapi.yaml
SAME 11-涉密管理与多法人治理-X.openapi.yaml
DIFF 12-用户与权限-U.openapi.yaml
SAME 13-学术活动管理-V.openapi.yaml
DIFF 14-科研绩效评价-M.openapi.yaml
SAME 15-专家与评审管理-N.openapi.yaml
SAME 16-科研档案管理-O.openapi.yaml
```

- M1-d 涉及的 01-P、02-E 均 `SAME`；4 个 DIFF 均为 M1-d 未触碰的既有偏差。
- `02-E` 中的 `/project/{id}/board`、`/project/eval-templates*`、versions，`01-P` 中的 `:publish`/`:close` 双份一致。

### YAML 可解析性

```text
$ backend-django/.venv/bin/python -c "import glob,yaml; ..."
files=32 bad=[]
```

- `design/*.yaml` 16 个 + `frontend/src/api/schema/*.yaml` 16 个，全部 `safe_load` 为 dict。

### 种子幂等（文件库，非 :memory:）

```text
$ ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/fr_m1d.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate
$ ... manage.py seed_demo   # 第 1 次：打印各表新增/更新计数
$ ... manage.py seed_demo   # 第 2 次及复查
seed_demo 完成（幂等）：
```

- 第 2 次起无任何计数（全部为 0），无新增/更新；`get_or_create` + 显式 key 生效。
- 种子覆盖：两个评估模板（MID_CHECK/FINAL_ACCEPT 各 3 sections，`seed_demo.py:947-975`）、`EChangeVersion` v1 + `snapshot_ref`（`:986-995`）、MAJOR 变更（`:996-999`）、MID_CHECK 批文（`:1016-1029`）、`GL-DEMO-2026-02` DRAFT 指南（`:1032-1038`）。

### git 状态

```text
$ git log --oneline b3eec62..69422ff
69422ff chore(seed+readme): M1-d 演示数据（评估模板/批文/变更版本/待发布指南）+ 测试数更新为实测 336
b0ad7d7 feat(fe): 项目八要素看板 tab + 变更严重程度分流 + 指南发布/关闭——契约驱动 mock 对齐 M1-d
924e6c6 feat(apply): 指南征集发布/关闭+专家论证评审入库推送（B5）
e9320f8 feat(project): 变更重大/一般分流+冲突回退+生效回写与版本快照、预算联动（B4）
0e09460 feat(project): 评估结论批文生成与通知回填（B3）
1f0c299 feat(project): 统一评估模板 CRUD + 中检/验收绑模板（B3）+ 契约/DDL 补 templateId
0534c1c feat(project): 项目八要素看板聚合端点（B2）+ 02-E 契约补 /project/{id}/board
2d4125b feat(rbac): M1-d 统一评估模板写维护策略放行（B3）
76a650a feat(project): M1-d EEvalTemplate/EChangeVersion 模型与 severity 列、迁移 0002+DDL/detail（B3/B4 表结构）
```

```text
$ git status --porcelain
 M docs/.DS_Store
 D docs/IMG_1355.jpeg
 D docs/IMG_1357.jpeg
 D docs/IMG_1358.jpeg
 D docs/scienceResearch2.png
 D docs/spm3.png
 D docs/spm5.png
 D docs/spm9.png
?? backend-django/uv.lock
?? docs/img/
?? docs/reports/.DS_Store
?? docs/reports/2026-11-12-conow-alignment-roadmap.md
?? docs/superpowers/plans/2026-11-12-m1a-invoice-loan-travel.md
?? docs/superpowers/plans/2026-11-17-m1b-cost-pool-voucher-settlement.md
?? docs/superpowers/plans/2026-11-17-m1c-disbursement-receipt-opening.md
?? docs/superpowers/plans/2026-11-18-m1d-board-evaluation-change-guide.md
?? dump.rdb
?? frontend/pnpm-lock.yaml
?? frontend/pnpm-workspace.yaml
?? scripts/ocr_jxa.js
?? scripts/ocr_screenshots.swift
```

- 以上均为 BASE 前既有脏文件/未跟踪文件（docs 图片移动、roadmap、历史 plan、ocr 脚本、锁文件），**不是 M1-d 残留**。
- 本报告新增 `docs/superpowers/reports/final-review-m1d.md`（未跟踪），除此之外本次评审未写任何文件。

---

## 跨任务集成缝隙

### 看板 → 各域

- 只读聚合，不写任何域；经费经 `_execution_of` 延迟 import，避免 E→F 顶层循环依赖；成果经 `ROutput.project_ids` 的 int/str 兼容；外包经 `GContract`；质量经 `EHealthHistory`；变更经 `EChangeRequest`。
- 缝隙 1：**租户**。board 用 `p.tenant_id` 而非请求 tenant，跨租户可读（C-2）。
- 缝隙 2：**预算状态口径**。`_sync_change_budget` 选 `exclude(status="CLOSED")` 的最新 FBudget（含 DRAFT/SUBMITTED），而看板 `_sum_budget_approved` 只统计 EXECUTING/ADJUSTING/RE_APPROVED/CLOSED。若项目只有 DRAFT 预算，变更把 `EProject.total_budget` 与 DRAFT `FBudget.total_approved` 都调了，看板经费仍显示 0，直到预算进入 EXECUTING。该选取与 F 域开户逻辑（`apps/funding/api.py:704` 同样 exclude CLOSED）一致，属于既有口径，但会让「变更生效后看板立即变」在 DRAFT 预算项目上不成立；建议在验收说明中明确，或让看板口径与 F 域展示口径统一。

### 变更生效 → F 域预算

- 按 P-7 允许 E 域直接 ORM 调 F 行，不生成 F 域正式调剂单（F 单据表 M2 补），`budgetAdjustment` 只落 `E_CHANGE_VERSION.snapshot`。
- 缝隙 3：**无 FBudget 的项目**。`_sync_change_budget` 返回 `budget=None`，`create_change_request` 仍置 EFFECTIVE；项目总额变了，F 预算与看板经费都没变。建议无活跃预算时返回 409（或明确「仅项目台账变更，不联动 F」并写进契约）。
- `_sync_change_budget` 只调首条 `FBudgetLine.amount_adjusted`，不调 `total_adjusted/pending_delta`；与 P-7 一致，但多行预算项目会只落一行。后续做 F 域正式单据时需补分摊规则。

### 中检结论 → 批文 → 通知

- N `_conclude_writeback` → `conclude_mid_check` → `EReport` + `mc.approval_doc_id` + R-MANAGER 通知；FINAL_ACCEPT 走 status_map，仅 APPROVED 签发。
- 缝隙 4：**可见性**。`to_api_mid_check` 返回 `report_id`（恒 null，因为批文用 `approval_doc_id`）而不返回 `approvalDocId`；前端/外部无法从 API 拿到批文 id（I-2）。
- 缝隙 5：**原子性**。结论、批文、回填三次写无事务；通知失败虽不阻断，但 DB 失败会留下半成品（I-3）。

### 指南发布 → 通知 → 申报入口

- publish 置 PUBLISHED + `publish_at` + R-STAFF 通知；申报入口按 `PGuideline.status` 取指南。
- 缝隙 6：`list_guidelines`（`backend-django/apps/p/api.py:58-63`）默认不限制 status，只在传参时过滤；如果申报向导未显式传 `status=PUBLISHED`，DRAFT 指南会出现在可选列表。前端 `GuideView` 只拉 PUBLISHED/CLOSED，但申报页不在本次 diff 内，建议确认申报入口的过滤条件。
- 发布/关闭没有「申报自动开启/截止」联动，外部填报按计划留到 M2，符合范围。

### 前端 tab → 契约路径/字段名

- 看板：`ProjectView.vue:259-264` GET `/project/${id}/board`，字段 `fund/progress/members/quality/outsource/changes/outputs` 与 02-E ProjectBoard 一致；金额按字符串展示；执行率经 `toPct` ×100，但 TS 类型写成 string（M-6）。
- 指南：`GuideView.vue:42-63` 调 `POST /apply/guidelines/${id}:publish|close`；按钮用 `auth.can('/apply/guidelines/0:publish POST')`，由 `/api/v1/apply/* POST` 通配放行；列表使用后端 snake_case `publish_at`，与 `to_api_guideline` 一致（01-P 契约本身也是 snake，无冲突）。
- mock：`frontend/src/api/schema/index.ts` 的模板匹配支持段内 `{id}:publish`，override key 能命中；`overrides/project.ts:144` 的 board 金额/执行率是字符串，契约是 number（M-6）。
- 模板配置：本次没有前端页面，B3 只能走 API/种子；计划 Task 8 只要求看板与指南，故不算缺口，但「一套模板配置」在 UI 上尚不可操作。

### 契约与 DDL 一致性

- 01-P / 02-E 双份逐字节一致；32 个 yaml 可解析；`makemigrations --check` 干净。
- `00-common.sql:332-333` 已注册 `RPT`（评估批文，E，v1.2）与 `CHG`（项目变更，E，v1.2）；`code_of` 在 `apps/funding/mappings.py:57`。
- DDL `E_MID_CHECK:208-216` 的 `template_id/report_id/approval_doc_id`、`E_FINAL_ACCEPT:344-345` 的 `template_id/approval_doc_id`、`E_REPORT`（`:473-502`）与模型/迁移一致。
- 唯一不一致：`E_CHANGE_VERSION` 索引列数（M-3）；以及 `frontend/src/api/schema` 缺 02-E DDL 副本（M-5，非运行问题）。

---

## 已裁定事项核对（未重开）

| 裁定 | 实现 | 结论 |
|---|---|---|
| 批文绑定位用新列 `approval_doc_id`，不用 `report_id` | `models.py:245-246`、迁移 0004、`_issue_report` 回填 `approval_doc_id` | 一致 |
| `severity` 缺省 GENERAL（提交即生效） | `api.py:406`、`models.py:172`、DDL `:256-257` | 一致 |
| E 域模型 `db_table` 大写 | `E_EVAL_TEMPLATE`/`E_CHANGE_VERSION`/`E_REPORT` | 一致 |
| 只加 3 行 policy，其余由既有通配覆盖 | `policy.csv:135-137` 仅 eval-templates 三行 | 一致 |
| 指南 `:publish`/`:close` 冒号动作风格 | `config/api.py:70-75` | 一致 |
| GUIDE 评审走 N 域延迟 import 单一写者 | `expertreview/api.py:407-410` | 一致 |

已确认的既有缺口（按指示不立新 finding，仅记录）：R-STAFF 也持 `apply/* POST|PUT`（`policy.csv:15-17`，M2 收窄）；MEMBER 变更向导只发意向不发 memberIds；回单/导入幂等竞窗无 DB 唯一约束；`legal_entity_id` 兜底 1。

---

## merge-readiness 判断

**不可合并。** 理由：

1. C-1 会让 B4 的写路径在非法输入下产生「假生效 / 字段被清空 / 审计日志失真」，属于数据正确性问题。
2. C-2 使 B2 看板与 B4 变更写路径跨租户可达，属于租户隔离与越权写。
3. C-3 使 B5 的指南发布可被跨租户评审任务触发，绕过本租户 R-MANAGER。
4. I-1 使 B3 的模板快照验收条件不成立（计划 Task 4 Step 1 明确断言 `score_detail == sections`，测试未覆盖）。
5. I-2 使契约声明的 `templateId/approvalDocId` 在 API 上不可见，前端按契约取值为 undefined。
6. I-3 与 Task 5 Step 3 的 atomic 要求不符，且并发可重复签发批文。

**建议的合并门槛**：

- 修 C-1/C-2/C-3，补双租户与非法输入的回归测试。
- 修 I-1（prefill + 验收快照 + 测试断言）、I-2（响应字段）、I-3（atomic + 唯一约束/锁）、I-4（status 枚举）。
- 修完后重跑：`pytest -q`（应 ≥ 336 + 新增）、`./node_modules/.bin/vue-tsc --noEmit`、双份 yaml `cmp`/`safe_load`、种子两遍幂等。
- 若采纳「验收 sections 快照」新增列，需要新迁移并更新 02-E DDL + yaml + frontend 副本；若不改列，至少把快照写入 `output_summary` 并在契约中说明。
- C-2 的修法会触及 `_get_project_or_404` 的既有调用面，建议新增 tenant 版 helper 而不是直接改旧签名，避免把 M1-a/b/c 的端点一起改出回归。

**范围外但建议跟进**：申报入口是否默认过滤 PUBLISHED 指南（seam 6）；变更详情响应 camelCase（M-2）；`E_CHANGE_VERSION` 索引列数（M-3）；无 FBudget 项目的预算变更语义（seam 3）。

---

*本报告为只读评审产物；除本文件外未修改仓库任何文件。*
