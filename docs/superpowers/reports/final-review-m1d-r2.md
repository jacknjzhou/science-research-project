# M1-d 修复复审（Round 2）

- 复审对象：`b3eec62..4eef2e5`（M1-d 全部 12 个提交；主修复 `36e6d6a`，补租户 `d435e1d`，README 校准 `4eef2e5`）
- 上一次结论：REQUEST_CHANGES（3 Critical + 5 Important），见 `docs/superpowers/reports/final-review-m1d.md`
- 复审方式：逐条读实现与测试（不以 commit message 为据）+ 3 条验收命令 + 一次性探针复现（探针只写 /tmp，不改仓库）
- 环境：HEAD `4eef2e5`，Django 5.2.19，Python 3.13，本地无 PostgreSQL 实例（5432 拒连）

## 结论

**REQUEST_CHANGES**

上轮 C-1（主路径）、C-2、C-3、I-1（快照部分）、I-4、I-5（中检路径）确实修到位，冲突回退标记也能真正落库。但：

1. **I-3 的修复在 PostgreSQL 上引入必然 500（新 Critical 回归）**：`_issue_report` 新增的 `select_for_update()` 被 `conclude_final_accept` 在**无事务**的情况下调用，Django 在 autocommit 下直接抛 `TransactionManagementError`。结题验收「通过即签批文」这条 B3 主链路在 PG 上 100% 失败，且失败前 `fa.status` 已提交，留下「验收已通过、无批文」的脏状态。SQLite 因 `has_select_for_update=False` 把该锁静默降级，所以 342 个测试全绿掩盖了它。
2. **C-1 仍有旁路**：`changeType=SCOPE`（以及 `MEMBER` 空 payload）能通过校验并走到 `EFFECTIVE`，但 `_apply_change` 没有任何回写分支，审批日志却记为「已生效」——与上轮 C-1 的缺陷同类，只是入口从「不校验」变成了「校验不管内容」。

## 实测数字

| 命令 | 结果 |
|---|---|
| `cd backend-django && .venv/bin/python -m pytest -q` | `342 passed, 7 warnings in 13.18s`（real 0m13.596s），exit 0 |
| `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | exit 0，stdout 0 行（未用 `pnpm exec`） |
| `cd backend-django && .venv/bin/python manage.py makemigrations --check --dry-run` | `No changes detected`，exit 0（有 PG 连接拒绝的 RuntimeWarning，不影响判定） |

342 = 336 基线 + 6 新增；`README.md:5/:29/:73` 已同步为 342。

## 逐条核验

### C-1 变更输入强校验 —— 部分修（Important 残留）

已修部分：

- 建单前校验：`backend-django/apps/project/api.py:316 _validate_change`，覆盖 `changeType` 枚举（:321-323）、`newValue` 必须是对象（:324）、TITLE 非空（:326-328）、DELAY 必带合法 `endDate`（:329-332 `_parse_date`）、BUDGET 为正数（:333-340）、MEMBER 必须是数组（:341-344）；`:347 _check_general_applicable` 只允许 DELAY/BUDGET/TITLE 走 GENERAL。调用点在 `create_change_request`（:458）里、建单（:475）之前（:469）。
- 审批生效前复检：`_advance_change`（:516）在 `:549-551` 对 `to_status == "EFFECTIVE"` 再跑一次 `_validate_change(row.change_type, row.new_value)`。探针：ORM 造 `change_type="DATE"` 的 MAJOR/SUBMITTED 旧数据后调 `_advance_change`，抛 `ApiError: changeType 须为 DELAY/BUDGET/MEMBER/TITLE/SCOPE`，状态未推进。
- **冲突回退标记确实落库**（上轮重点怀疑项，已排除）：冲突分支 `apps/project/api.py:494-498`（`r.conflict_flag=1; r.status="ROLLED_BACK"; r.save(...); raise ApiError(409...)`）位于建单事务 `:474-487` **之外**；`config/settings/base.py:73-81` 未开 `ATOMIC_REQUESTS`（默认 False）；`core/ninja.py:23-24` 的 `ApiError` 处理器返回响应、不再向上抛。既有用例 `tests/test_project_domain.py:762` 在 409 之后直接查库断言 `conflict_flag == 1`、`status == "ROLLED_BACK"`，实测通过。

未修部分（见「新发现」N-2/N-3/N-4）：

- `_validate_change` 对 SCOPE 无任何内容校验，`_apply_change`（:393-437）也没有 SCOPE 分支，但 `_advance_change:561-563` 无条件把状态推进为 EFFECTIVE。
- MEMBER 允许 `memberIds is None`（:341-344 的 `if ids is not None and ...`），空 payload 同样 EFFECTIVE 而无变化。
- BUDGET 只做 `Decimal(str(raw))` 与 `<= 0` 比较，`"Infinity"` 放行、`"NaN"` 在比较处抛 `InvalidOperation`。

### C-2 租户隔离 —— 已修（余 1 处不一致，无泄露）

- 新增 `apps/project/api.py:100 _get_project_or_404_tenant(project_id, tenant_id)`。
- 覆盖面：看板 `project_board:175-176`（先取 `d = domain_from(request)`）；建单 `create_change_request:460`；中检建单 `create_mid_check:285`、验收建单 `create_final_accept:638`（后两处由 `d435e1d` 补）；审批 `_advance_change` 的变更单查询 `:519-521` 带 `tenant_id=d.tenant_id, deleted=0`，项目查询 `:548` 带 tenant，状态 update `:561-563` 同样带 tenant；批文签发 `_issue_report:1183` 按 `tenant_id` 过滤，中检取项目 `:1214` 带 `tenant_id=mc.tenant_id`。
- 跨租户用例 `tests/test_project_domain.py:895 test_m1d_board_and_change_tenant_isolated` 覆盖看板/建单/审批，断言 404 且 `cr.status` 仍 SUBMITTED、`p.title` 未变；`d435e1d` 之后中检/验收建单也走同一 helper（用例未单独覆盖这两条，属测试缺口而非功能缺失）。
- 余量（Minor）：`get_change_versions:586` 仍用裸 `_get_project_or_404(id)`；紧随其后的变更单查询 `:588-590` 带 `tenant_id=d.tenant_id`，跨租户仍是 404，无数据泄露，仅风格不一致。

### C-3 指南回写租户 —— 已修

`apps/p/api.py:197-198`：`PGuideline.objects.filter(id=t.target_id, tenant_id=t.tenant_id, deleted=0)`。用例 `tests/test_p_domain.py:277 test_m1d_guide_conclude_tenant_isolated` 造 tenant2 的 DRAFT 指南 + tenant1 任务 PASS，断言仍 DRAFT。

### I-1 中检预填 score_detail / 模板快照 —— 部分修

已修：

- `create_mid_check:291-295` 用 `_template_bundle`（:660-668，返回 `{"templateId","scene","sections"}`）+ `_prefill_score_detail`（:671-686）；请求显式带 `scoreDetail` 时保留调用方值。
- `EMidCheck.template_snapshot`（`apps/project/models.py:136`）与 `EFinalAccept.template_snapshot`（:247）均为 `JSONField(null=True)`；迁移 `apps/project/migrations/0005_m1d_eval_template_snapshot.py`（依赖 `0004_ereport`，两个 AddField）与 `design/02-项目过程管理-E.ddl.sql:209/:346` 的 JSONB 列、`:354` 的 COMMENT 同步；`makemigrations --check` 无待生成变更。
- 用例 `tests/test_project_domain.py:957` 断言 snapshot 含 2 个 sections、`score_detail["items"]` 的 key 顺序为 `["progress","finance"]`、`score` 全为 None，并在改模板 sections 后重查快照仍为 2 条。

未修（Important，规格偏差）：

- 计划 `docs/superpowers/plans/2026-11-18-m1d-board-evaluation-change-guide.md:117` 的验收语句是 `score_detail == 模板 sections`；实现返回的是 `{"items":[{key,label,weight,score:null}]}`，丢了 `desc`/`required` 等原始字段，形状不等于 sections。`_prefill_score_detail:672` 的 docstring 自己写着「score_detail==sections」，与实现不符。用例按实现形状断言，等于把偏差固化。
- 计划说「不带 templateId → 行为与现状一致」，实现为 `score_detail=None`，符合；此点无问题。

### I-2 序列化字段 —— 部分修（Important）

- `apps/project/mappings.py:92` 给 `to_api_mid_check` 加了 `"approval_doc_id": r.approval_doc_id`；`:130` 给 `to_api_final_accept` 加了 `"template_id"`、`"approval_doc_id"`。字段值确实可见。
- 但键名是 snake_case，而契约 `design/02-项目过程管理-E.openapi.yaml:1092-1104`（EMidCheck）与 `:1172-1186`（EFinalAccept）全量 camelCase（`templateId`、`approvalDocId`，无 snake 别名）。前端按契约读 `d.templateId` 会拿到 undefined；目前 `frontend/src` 下 grep 无消费者，属潜伏问题。新增用例 `tests/test_project_domain.py:971`、`:1007` 断言的正是 `template_id`，把错误键名写进了回归网。

### I-3 事务与行锁 —— 部分修（Critical 回归）

已修：

- 建单 + 版本：`create_change_request:474-487` `transaction.atomic()`。
- 生效 + 流水：`_advance_change:560-579` 原子块内做条件 update + `_apply_change` + `approval.log`。
- 中检批文 + 回填：`conclude_mid_check:1204-1226` 整体 atomic，`:1205` `select_for_update` 锁中检行。

未修（新 Critical，见 N-1）：`conclude_final_accept:1232` 既没有 `atomic()`，也没有锁 `EFinalAccept` 行；`:1246` 调用的 `_issue_report:1188` 却有 `select_for_update()`。

### I-4 模板 status 枚举 —— 已修

`apps/project/api.py:744-745` 校验 `status in ("ACTIVE","DISABLED")`；用例 `tests/test_project_domain.py:1004` 断言 400/40001。

### I-5 批文幂等键 —— 已修（中检路径）

- `_issue_report:1183-1187` 的幂等查询已去掉调用方 `project_id`，键为 `(tenant_id, doc_type, mid_check_id|final_accept_id)`；`:1188` 加了 `select_for_update`。
- `conclude_mid_check:1213-1214` 改用 `mc.project_id`、并按 `mc.tenant_id` 查项目，`project_id` 形参已成死参（Minor 清理项）。
- 用例 `tests/test_project_domain.py:918` 用 p2 重复 conclude，断言仍只有 1 份批文且 `project_id == p1.id`。
- 残留：无 DB 唯一约束兜底（仅靠行锁，锁又被 N-1 打破）；复用旧行时 `code` 为空不回填。

## 新发现

### Critical

**N-1 `conclude_final_accept` 在 PostgreSQL 上必然抛 `TransactionManagementError`，且留下半提交状态（`36e6d6a` 引入的回归）**

- `apps/project/api.py:1232-1256`：函数无 `transaction.atomic()`，`:1240` 先 `fa.save(update_fields=["status", ...])`（autocommit 立即提交），`:1246` 再调 `_issue_report`，后者 `:1188` 执行 `qs.select_for_update().first()`。
- Django `django/db/models/sql/compiler.py:838-847`：`if self.query.select_for_update and features.has_select_for_update: if self.connection.get_autocommit() and features.supports_transactions: raise TransactionManagementError("select_for_update cannot be used outside of a transaction.")`。PostgreSQL 的 `has_select_for_update=True`，请求路径 autocommit=True → 必抛。
- 复现（把 sqlite 的 `connection.features.has_select_for_update` 置 True 模拟 PG）：`conclude_final_accept(fa.id, "APPROVED")` → `TransactionManagementError`；且 `fa.status` 已是 `APPROVED`、`approval_doc_id` 仍为 None、`EReport` 未新增（半提交）。
- 触发链路是真实业务路径：`apps/expertreview/api.py:375 conclude_review` → `:388 _conclude_writeback` → `:404 conclude_final_accept(target_id, status)`（`biz_type=FINAL_ACCEPT` 且结论 PASS）。注意 `conclude_review:387` 已先把评审任务置 CONCLUDED 并提交，因此线上表现是「任务已结、验收状态已通过、批文没生成、接口 500」。
- 为什么测试没抓到：SQLite 的 `has_select_for_update=False`，Django 直接把该锁当 no-op，342 个用例全绿；本机无 PG 实例，`makemigrations` 只报 5432 拒连。
- 最小修法：把 `conclude_final_accept` 整体包进 `transaction.atomic()` 并 `EFinalAccept.objects.select_for_update().filter(id=..., deleted=0).first()`（与 `conclude_mid_check:1204-1205` 对齐）。已验证：`atomic()` 内调用不再抛编译期异常（sqlite 上会因 `FOR UPDATE` 语法报错，属模拟限制；PG 上合法）。

### Important

**N-2 SCOPE 变更审批后「生效」但项目零改动**

- `apps/project/api.py:393-437 _apply_change` 只处理 TITLE/DELAY/BUDGET（MEMBER 也只写入选定分支），没有 SCOPE 分支，函数恒返回 None；`_advance_change:561-563` 仍把状态更新为 EFFECTIVE，`:576` 照常写 `approval.log(... "APPROVE" ...)`。
- 探针：`change_type="SCOPE", new_value={"foo":1}`，审批后 `status == "EFFECTIVE"`、`p.title` 未变。变更单与审批日志共同宣称「范围已变更」，实际无任何落点。
- 建议：SCOPE 在 M2 落地前应拒单（或生效时只允许 `NOTE`/`PENDING_SCOPE` 状态），至少不能置 EFFECTIVE。

**N-3 MEMBER 空 payload 同样「无内容生效」，且新测试把它固化为预期**

- `_validate_change:341-344` 允许 `memberIds` 缺省；`_apply_change` 在无 ids 时不动 `member_ids`。
- 探针：`member_ids=[1,2]` 的项目，MEMBER MAJOR + `new_value={}` 审批后 `status=EFFECTIVE`、`member_ids` 仍 `[1,2]`。
- `tests/test_project_domain.py:879-888` 反而断言 MEMBER/SCOPE 的 MAJOR + 空 `newValue` 返回 200——把「空变更生效」写成期望，后续修复要改测试。

**N-4 BUDGET 非有限数在生效阶段 500**

- `_validate_change:333-340` 只 `Decimal(str(raw))` + `target <= 0`。探针：`"Infinity"` 通过校验（`Decimal('Infinity') > 0`），`"NaN"` 在 `target <= 0` 处抛 `InvalidOperation`（未捕获 → 500），`"Infinity"` 到 `_apply_change` 的 `.quantize()` 也抛 `InvalidOperation`。
- 因 `_advance_change` 的 atomic 会回滚，无脏数据；但违反 plan「非法输入 40001」的约束。建议补 `target.is_finite()`。

**N-5 批量审批遇坏数据整批 400，但前序条目已各自提交**

- `approve_change_batch:610`（循环 `:622-633`）内 `_advance_change` 现在可能抛 `ApiError`（N-2/N-4 同源：`_validate_change`），循环无 try → 整个请求 400，而已完成的条目已提交，调用方无法从响应判断哪些成功。
- 触发条件：修复前入库的旧格式变更单（如 `new_value` 用 `subject` 而非 `totalBudget`）在批量通过时命中复检。

### Minor

- **N-6** `get_change_versions:586` 仍用裸 `_get_project_or_404(id)`；后续变更单查询带 tenant，无泄露，仅不一致。
- **N-7** `EReport` 仍无 `(tenant_id, doc_type, mid_check_id)` / `(…, final_accept_id)` 唯一约束；`_issue_report:1188` 的行锁在「行不存在」时没有互斥力，并发重复签发只能靠 `conclude_mid_check` 锁中检行兜住，结题验收路径连这层都没有（叠加 N-1）。复用旧行时 `code` 为空不回填（`_issue_report:1196-1197` 只在新建时赋值）。
- **N-8** `conclude_final_accept:1244` 取项目未带 `tenant_id` 过滤（`project_id` 来自评估单本身，跨租户风险低）；`conclude_mid_check` 的 `project_id` 形参已无用途。
- **N-9** 契约/DDL/实现三方对 sections 元素形状不一致：`design/02-项目过程管理-E.openapi.yaml:1270` 写 `{key,label,weight,desc}`，`design/02-项目过程管理-E.ddl.sql:312` 注释写 `{key,title,weight,required}`，实现按 `label` 取值。
- **N-10** `_validate_change` 未校验 `memberIds` 元素类型（`["alice"]` 会被写入 `member_ids`，看板侧过滤掉后成员静默消失）。

## 测试有效性

6 个新增用例都能抓到修复前的缺陷（逐条对照过修复前实现，非恒真）：

| 用例 | 修复前必失败的原因 |
|---|---|
| `test_m1d_change_invalid_input_rejected`（`tests/test_project_domain.py:849`） | 修复前无 `_validate_change`，DATE/BOGUS/负预算均能落单（7 种非法输入 + 断言 0 条变更单） |
| `test_m1d_board_and_change_tenant_isolated`（:895） | 修复前看板/建单按裸 id 查询，返回 200 并回写 |
| `test_m1d_report_signing_uses_eval_row_tenant`（:918） | 修复前幂等键含调用方 `project_id`，换 p2 会签第二份 |
| `test_m1d_eval_template_prefill_and_snapshot`（:957） | 修复前无 `template_snapshot` 字段、不预填 `score_detail` |
| `test_m1d_eval_template_status_validated`（:1004） | 修复前 `create_eval_template` 不校验 status，返回 200 |
| `test_m1d_guide_conclude_tenant_isolated`（`tests/test_p_domain.py:277`） | 修复前 `PGuideline.objects.filter(id=...)` 裸查，会把 tenant2 的指南置 PUBLISHED |

既有测试的改动是合理的、不是削弱：`tests/test_project_domain.py:64` 把 `change_type` 从 DATE 改为 DELAY（DATE 本就不在 `design/02-项目过程管理-E.ddl.sql:244-245` 的枚举里，旧用例是错的）；`:99-101` 的 two-step BUDGET 补 `new_value={"totalBudget": "120000.00"}` 是新增校验后的必要输入，并新增 `:137` 的 `str(p.total_budget) == "120000.00"` 断言，属加强。

测试缺口（正是本轮漏掉 N-1/N-2/N-4 的原因）：

1. 没有 PG 语义测试：`select_for_update` 在 autocommit 下的行为在 SQLite 上被静默降级，建议 CI 增加 PostgreSQL service + 一条 `conclude_final_accept` 的正向用例。
2. 没有「审批阶段拒绝历史脏数据」的用例（探针证明功能本身有效，但无回归网）。
3. 没有 SCOPE/MEMBER 空内容的负向用例（现有用例反向固化了允许行为）。
4. 没有 BUDGET NaN/Infinity 用例。

## 可合并性

**当前不可合并。** N-1 是 PG 生产环境上的确定性故障，且会造成「验收已通过、批文缺失」的脏数据；建议先做以下最小修复再复审：

1. `conclude_final_accept` 包 `transaction.atomic()` + `select_for_update` 锁 `EFinalAccept` 行（对齐 `conclude_mid_check`）。
2. SCOPE（以及 MEMBER 空 ids）在 `M2` 落地前拒绝置 EFFECTIVE；同步修正 `tests/test_project_domain.py:879-888` 的期望。
3. I-2 键名改为契约的 camelCase（或双写），并同步 `to_api_*` 用例断言。
4. `score_detail` 预填形状对齐计划（直接 `sections`）或更新计划文本；`_prefill_score_detail` docstring 与实现对齐。
5. `_validate_change` 补 `Decimal.is_finite()`；`approve_change_batch` 捕获 `ApiError` 逐条记 `err`。
