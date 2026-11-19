# M1-d 第三轮终审（r3）

- 仓库：`/Users/jacky/works/science-research-project`，分支 `develop`
- 范围：`b3eec62..HEAD`（14 个提交，HEAD `e55b81f`），相对 r2 的 HEAD `4eef2e5` 新增 `efe006a`、`e55b81f`
- 基准：`docs/superpowers/reports/final-review-m1d-r2.md`
- 性质：只读复审（本轮除本报告外未修改任何文件、未提交 git）

## 结论

**APPROVED_WITH_MINOR** —— r2 的阻断项 N-1 已真修（事务/行锁按 PG 语义推演 + 实测可证），N-2..N-6、N-8..N-10 均已落地，测试/迁移/类型/契约全部通过；剩余为「测试抓不到该缺陷」「预算指数溢出 500」以及若干契约/UI 一致性问题，不构成合并阻断。

## 一、上轮意见逐条状态

| 项 | 状态 | 证据（file:line） |
|---|---|---|
| **N-1** `conclude_final_accept` 无事务/无锁却调 `_issue_report` 的 `select_for_update`（PG 半提交） | **已修（真修，见第二节）** | `backend-django/apps/project/api.py:1267`（`with transaction.atomic()`）、`:1268-1270`（`EFinalAccept.objects.select_for_update()`）、`:1282-1289`（同事务内签发+回填）；批文侧锁仍在 `api.py:1219` |
| **N-2** SCOPE 审批后 EFFECTIVE 零改动 | 已修 | `api.py:351-354`（两种 severity 一律 40001）；用例 `tests/test_project_domain.py:891-898` |
| **N-3** MEMBER 空 payload 零改动生效 | 已修 | `api.py:344-350`（非空 list + 元素 int）；审批复检 `api.py:565-567`；用例 `test_project_domain.py:880-882` |
| **N-4** BUDGET Infinity 放行 / NaN 抛 `InvalidOperation` 500 | 已修（原两项）；残余同类见 Important-3 | `api.py:333-343`（`is_finite()` + `except (InvalidOperation, TypeError, ValueError)` → 40001）；用例 `:877-879` |
| **N-5** 批处理遇坏数据整批 400、前序已提交 | 已修 | `api.py:650-654`（逐条 `try/except ApiError`，记 `ok:false` 继续）；行查询带 tenant `:643-645`；用例 `test_project_domain.py:1034` |
| **N-6** `get_change_versions` 裸查项目 | 已修 | `api.py:605`（`_get_project_or_404_tenant(id, d.tenant_id)`） |
| **N-7** EReport 无唯一约束 / 复用时 `code` 不回填 | **未修（既有技术债，非本期引入）** | `apps/project/models.py:348-356`（无 `unique_together`/`UniqueConstraint`）；`api.py:1219-1226`（命中旧行直接 `return old.id`，不回填 `code`） |
| **N-8** 结论取项目未带 tenant / `project_id` 死参 | 已修（死参仍在，Minor） | `api.py:1280`（`tenant_id=fa.tenant_id`）；`conclude_mid_check` 签名 `api.py:1233` 的 `project_id` 仍为死参（`:1244` 起以 `mc.project_id` 为准） |
| **N-9** sections 形状三方不一致 | 已修 | `design/02-项目过程管理-E.ddl.sql:309-313`（`{key,label,weight,desc}`）；`api.py:698-716`（docstring 如实写 `{"items":[...]}`）；openapi `:1262-1281` 一致 |
| **N-10** memberIds 元素类型未校验 | 已修 | `api.py:349-350`；用例 `:882`（`["abc"]` → 40001） |
| **C-1** 变更输入强校验 | 已修 | 同 N-2/N-3/N-4/N-10；校验在建单前 `api.py:485`，无半成品（用例 `:873` 断言 `count()==0`） |
| **C-2** 租户隔离 | 已修 | `api.py:100/564/605/643/1280` |
| **C-3** 指南回写租户 | 已修（未变更） | `backend-django/apps/p/api.py:197-198` |
| **I-1** 中检 `score_detail`/模板快照与 plan 字面不符 | **部分修** | 实现：`api.py:698-716`；但 docstring 声称「偏差已记 ledger Ruling」，仓库 `docs/` 下无任何 ledger/ruling 记录（`ls docs/superpowers` 仅 plans/reports/specs），plan `2026-11-18-m1d-board-evaluation-change-guide.md:117` 仍写 `score_detail == 模板 sections` → 声称无法核验 |
| **I-2** 评估单序列化字段（契约 camelCase） | **部分修（实现已修，用例断言错键）** | 实现双写：`apps/project/mappings.py:90-91`（`approval_doc_id`+`approvalDocId`、`templateId`）、`:130-131`（`template_id`+`templateId`、`approvalDocId`）；但用例 `tests/test_project_domain.py:977`（注释「I-2：序列化器可见」）与 `:995-996`（注释写「验收响应带 templateId」）断言的都是 `data["template_id"]`，契约键仍无用例 |
| **I-3** 事务与行锁 | 已修 | N-1 同证据；`conclude_mid_check` `api.py:1236-1237` |
| **I-4** 模板 status 枚举 | 已修（未变更） | `test_m1d_eval_template_status_validated`（`tests/test_project_domain.py:982`） |
| **I-5** 批文幂等键 | 部分修（同 N-7，技术债） | `api.py:1212-1226` |

## 二、N-1 是否真修（本轮判定核心）

**结论：真修，且按 PG 语义成立。**

1. 缺陷机制（Django 源码）：`backend-django/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py:839-848`：
   `if self.query.select_for_update and features.has_select_for_update:` → `if self.connection.get_autocommit() and features.supports_transactions: raise TransactionManagementError("select_for_update cannot be used outside of a transaction.")`。
   修复前 `conclude_final_accept` 无 `atomic`（`git show efe006a` 删除的旧实现可见），视图层以 autocommit 运行 → PG 上必抛，而 `fa.status/accept_at` 已先 `save()`，即 r2 所述半提交。
2. 修复后 `api.py:1267-1289`：整体 `transaction.atomic()`，`EFinalAccept` 先 `select_for_update()`；`_issue_report`（`api.py:1219` 的锁）与状态写入、`approval_doc_id` 回填在**同一事务**内。
3. 实测（`/tmp/probe_r3.py`，内存 sqlite，迁移后）：
   - **A** 拟 `connection.features.has_select_for_update=True`，autocommit 下直接调 `_issue_report` → `TransactionManagementError: select_for_update cannot be used outside of a transaction.`（旧缺陷可复现）。
   - **B** 同特性下调 `conclude_final_accept(fa.id,"APPROVED")` → `OperationalError: near "FOR": syntax error`。该错来自 `api.py:1268` 的锁查询本身（sqlite 不支持 `FOR UPDATE`，属模拟限制），说明**已过 autocommit 闸门、SQL 是在事务内下发的**；失败后 `fa.status=APPLIED, accept_at=None, approval_doc_id=None, reports=0`，半提交消失。
   - **C** 特性复原、spy `_issue_report`：`in_atomic_block=True, autocommit=False`；把 `_issue_report` 换成抛 `RuntimeError` 并预置 `fa.status=APPLIED` → 异常后 `fa.status=APPLIED, accept_at=None, approval_doc_id=None, reports=0`（整体回滚）。
4. 注意：`tests/test_project_domain.py:1009` 的新用例抓不到该缺陷（见「测试有效性」）。

## 三、新发现问题

### Critical
- 无。

### Important

1. **MEMBER 变更默认 severity=GENERAL 现在提交即生效（本轮行为变更，无用例/文档/前端同步）**
   `api.py:313`（`_CHANGE_GENERAL_TYPES` 新增 `MEMBER`）+ `api.py:481`（缺省 `GENERAL`）+ `api.py:359-361`。`R-STAFF`（`config/casbin/policy.csv:127` 允许 POST change-request）不带 `severity` 提交 `{"changeType":"MEMBER","newValue":{"memberIds":[...]}}` 会直接改 `EProject.member_ids`，不经 R-MANAGER/R-LEADER（审批权限见 `policy.csv:132/140`）。而修复前同类请求返回 **400**（`git show efe006a` 删除的旧代码：`_CHANGE_GENERAL_TYPES = ("DELAY", "BUDGET", "TITLE")`，旧错误文案「成员/范围变更须以重大变更（severity=MAJOR）提交，经审批后生效」，旧注释「MEMBER/SCOPE 生效需人员或任务书口径（M2），一律走重大变更审批留痕」）；前端也仍按「成员/范围变更仅支持重大审批」锁定 MAJOR（`frontend/src/views/ProjectView.vue:330-331`、`:706`），其代码注释还写着「后端 40001」。
   影响：`member_ids` 参与「参与项目」判定（`api.py:1070-1076`），属人员名单完整性/审批口径问题（非鉴权越权，租户/角色仍由 casbin 控制）。
   建议：确认口径。若非有意，把 `MEMBER` 移出 `_CHANGE_GENERAL_TYPES`（与 SCOPE 一样在 `create_change_request` 强制 MAJOR，1 行）；若有意，改 `ProjectView.vue:706` 文案并补一条 `GENERAL`+`MEMBER` 用例。本项与 plan P-5/P-7 字面并不冲突，故不判为合并阻断，但**需要一句明确结论**。

2. **N-1 的回归用例在 sqlite 上恒真，抓不到 PG 语义**
   `tests/test_project_domain.py:1009-1032`：只断言 `status/accept_at/approval_doc_id/EReport` 成对落地与幂等。实测 sqlite `connection.features.has_select_for_update == False`，autocommit 下直接调 `_issue_report` 也成功返回（`in_atomic_block=False`），因此修复前代码同样能通过该用例。用例 docstring 自己也承认这一点，但命名（`works_without_caller_transaction`）会给人「已回归」的错觉。
   建议：在用例里 monkeypatch `apps.project.api._issue_report` 为探针，断言被调用时 `connection.in_atomic_block is True`（sqlite 可跑、修复前必失败）；或引入 PG 测试库跑一条 `has_select_for_update=True` 的语义用例。

3. **BUDGET 有限的超大指数仍 500，且亚分金额落库为 0.00（N-4 同类残余）**
   `api.py:435-436` 的 `quantize` 不在 `try` 内（`try` 只包 `Decimal(str(raw))`，`:429-433`）。实测：`totalBudget="1e100"` → `_validate_change` **通过**（`is_finite()` 为真），`_apply_change` 抛未捕获的 `decimal.InvalidOperation` → 500；`"0.001"`、`"1e-30"` 通过「须为正数」校验后被 `quantize(Decimal("0.01"))` 落成 `0.00`，项目总预算变成 0 而校验声称正数。
   影响：前者是 500（发生在 `atomic` 内会回滚，无脏数据）；后者是数据质量（0 元预算）。
   建议：校验处对 `target` 做上下界（如 `0 < target <= 1e12`，或按域内 `DecimalField(max_digits=18, decimal_places=2)` 的精度）并复用同一 `quantize` 结果；`_apply_change` 里把 `quantize` 也包进 `except InvalidOperation`。

4. **I-2 的修复没有对应契约键断言**
   `mappings.py:130-131` 已双写，但 `test_project_domain.py:977` 与 `:995-996` 断言的是 `template_id`，后者注释却写「验收响应带 templateId」。删除 `templateId` 不会有用例失败，前端 `undefined` 的问题仍可能回归。
   建议：把两处断言改/加为 `data["templateId"]` 与 `data["approvalDocId"]`（保留 snake 断言亦可）。

### Minor

1. `_apply_change` BUDGET 分支 `if fields:` 恒真死代码（`api.py:438-439`），逻辑写在分支内且随后 `return`；建议删掉该 `if`/`fields=[]` 或改为 `p.save(update_fields=["total_budget","updated_at"])`，避免后续维护误读。
2. 契约仍允许 SCOPE：`design/02-项目过程管理-E.openapi.yaml:941-943` `ChangeType` 枚举含 `SCOPE`，而实现一律 400（`api.py:351-354`）。属契约漂移（本轮未改 yaml），建议在枚举/描述标注「M2 任务书版本化」。
3. 前端 SCOPE 卡仍可填可提交（`frontend/src/views/ProjectView.vue:311`、`:339`、`:371-372`），提交必 400；建议在 `severityLocked`/提交按钮上禁用（SUPPORT 提示已加 `:747`）。
4. docstring 声称「偏差已记 ledger Ruling」（`api.py:704-706`）在仓库内无法核验（`docs/` 无 ledger/ruling 文件），建议补一条 Ruling 记录或改掉这句话（与上表 I-1 同源）。
5. `create_change_request` 的 GENERAL 分支缺 `if not adjusted: raise`，与 `_advance_change`（`api.py:584-586`）不一致（`api.py:516-528`）。目前经 `_validate_change` 不可达，属防御一致性建议：把两条路径合并到同一 helper。
6. `approve_change_batch` 对 `ids` 元素类型不校验：`ids=[{"a":1}]` 会在 `filter(id=cid)` 抛 `ValueError` → 500（`api.py:643`）。属既有问题（修复前同样是 `filter(id=cid)`），建议加 `isinstance(cid, int)`。
7. `conclude_mid_check(mid_check_id, project_id, ...)` 的 `project_id` 已是死参（`api.py:1233`），建议删参或改名 `_project_id` 以免误用。
8. TITLE 回写静默截断到 256（`api.py:414`），而校验未限长（`api.py:326-328`）；超长标题会导致项目值≠变更单 `newValue`。属既有行为（本期未引入），建议校验处直接限长 40001。

### 既有技术债（非本期引入，明确不计入阻断）

- **N-7 残**：`EReport` 无 `(tenant_id, doc_type, mid_check_id/final_accept_id)` 唯一约束，`_issue_report` 命中旧行不回填 `code`（`models.py:348-356`、`api.py:1219-1226`）。本轮 `conclude_final_accept`/`conclude_mid_check` 已分别锁父表行（`api.py:1268`、`:1237`），**两个在库调用方**的并发重复签发窗口已被收窄；DB 层仍缺最后一道防线。
- **`_advance_change` 未锁项目行**：`p` 在 `atomic` 外读取（`api.py:564`），两个并发 APPROVE 可在同一 `p` 快照上各自 `_apply_change`，预算/成员回写存在丢失更新；`_sync_change_budget` 亦会重复记账。属既有并发缺陷（r2 未列），建议 M2 前补 `select_for_update()`。
- **跨模块半提交**：`apps/expertreview/api.py:373-386` 先 `save(t.status="CONCLUDED")`（无事务）再调 `_conclude_writeback`（`:388-410`），批文/回写失败时评审单已终结。r2 已提及，本轮未修。

## 四、测试有效性

| 用例 | 能否抓到对应缺陷 | 说明 |
|---|---|---|
| `test_m1d_change_invalid_input_rejected`（`tests/test_project_domain.py:848-905`） | **能** | Infinity/NaN/负预算/空 memberIds/非 int 元素/SCOPE 两档此前分别会被放行或 500，现在断言 400+40001，且 `:870` 断言无半成品变更单；不是恒真断言 |
| `test_m1d_change_batch_isolates_bad_rows`（`:1034`） | **能（部分）** | 修复前 SCOPE 会直接 EFFECTIVE，`ok` 会是 2 且 `bad.ok` 为 True → 断言失败；但**未断言**坏行仍为 `SUBMITTED`/未写 `approved_at`，也没覆盖「`_apply_change` 返回空 → 40001」这条新防线（当前经 `_validate_change` 不可达） |
| `test_m1d_conclude_works_without_caller_transaction`（`:1009`） | **不能** | 见 Important-2，sqlite 静默降级，修复前后都通过 |
| `test_m1d_eval_template_prefill_and_snapshot`（`:955-996`） | 部分 | 形状断言 `{"items":[...]}` 与 docstring 一致；但 I-2 的 camelCase 键只断言了 snake 键（`:977`、`:996`） |
| 缺失 | — | 无 GENERAL+MEMBER 正向/负向用例；无 BUDGET 精度（`0.001`/`1e100`）用例；无 PG 语义用例；无「项目行并发锁」用例（技术债） |

另：seed 幂等无需单独手跑——`tests/test_sysadmin.py:338 test_seed_demo_idempotent` 连续两次 `seed_demo` 已在本次 344 全绿中通过。

## 五、实测数字（本轮亲跑）

| 命令 | 结果 |
|---|---|
| `cd backend-django && .venv/bin/python -m pytest -q` | `344 passed, 7 warnings in 13.69s`，exit 0（real 0m14.1s） |
| `cd backend-django && .venv/bin/python manage.py makemigrations --check --dry-run` | `No changes detected`，exit 0（仅 PG 拒连 `RuntimeWarning`，环境无 5432） |
| `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | exit 0，无输出（real 0m2.7s） |
| `cmp design/02-项目过程管理-E.openapi.yaml frontend/src/api/schema/02-项目过程管理-E.openapi.yaml` | 一致（exit 0） |
| `cmp design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml` | 一致（exit 0） |
| `git log --oneline b3eec62..HEAD` | 恰 14 条（`e55b81f, efe006a, 4eef2e5, d435e1d, 36e6d6a, 69422ff, b0ad7d7, 924e6c6, e9320f8, 0e09460, 1f0c299, 0534c1c, 2d4125b, 76a650a`） |
| `git status --porcelain` | 仅 `docs/` 既有改动与本报告新增 + BASE 前既有未跟踪（`backend-django/uv.lock`、`dump.rdb`、`frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml`、`scripts/ocr_*`），**无本轮源码残留** |
| README 测试数 | `README.md:5/29/73` 均为 344，与实际一致 |

N-1 语义探针见第二节（同一探针文件 `/tmp/probe_r3.py`、`/tmp/probe_r3b.py`，均在临时内存库运行，未写仓库）。

## 六、可合并性

N-1 阻断项已按 PG 语义真正修复（事务+父行锁+回滚实测），其余 r2 意见均已落地或降级为既有技术债；剩余为测试有效性、预算精度与契约/UI 一致性小项，**可以合并**，建议合并前用 1 行确认 MEMBER 是否应允许 GENERAL 即时生效，并把 `test_m1d_conclude_works_without_caller_transaction` 改成断言 `in_atomic_block` 的真回归用例。
