# M1-d 第四轮终审（r4）

- 仓库：`/Users/jacky/works/science-research-project`，分支 `develop`
- 范围：`b3eec62..HEAD`（16 个提交，HEAD `72ee658`）；初审基于 15 提交的 `dabfdff`，`72ee658` 为按 r4 意见的补丁（仅 `tests/test_project_domain.py`），复核见第六节
- 基准：`docs/superpowers/reports/final-review-m1d-r3.md`
- 性质：只读复审（除本报告外未修改仓库内任何文件、未提交 git；探针脚本均写在 `/tmp`）

## 结论

**APPROVED** —— 初审（`dabfdff`）发现的两条阻断项已由 `72ee658` 关闭并复核（第六节）：

1. **Important-2 已真修**：用例改 `@pytest.mark.django_db(transaction=True)` 后不再被测试级 atomic 包裹；在 `transaction=True` 下重放「修复前序列」（不包 atomic）实测 `in_atomic_block == False`，即去掉 `conclude_final_accept` 的 atomic 时 `assert seen == [True]` 会失败——用例现能真抓缺陷。
2. **Important-4 已补齐**：中检/验收建单响应断言 `approvalDocId is None`（键存在性），conclude 回写后再断言 `to_api_final_accept(fa)["approvalDocId"] == fa.approval_doc_id`。

生产代码（MEMBER 强制审批、预算上下界、批处理 id、空回写守卫）正确，346 测试/迁移/类型/契约全绿，未发现新的运行时缺陷；剩余仅 `fields = []` 死赋值与 OpenAPI 描述漂移两项 Minor（后者已记 ledger 排期 M2）。

## 一、r3 意见逐条状态

| 项 | 状态 | 证据（file:line） |
|---|---|---|
| **Important-1** MEMBER 移出 GENERAL、强制 MAJOR | **已落地** | `backend-django/apps/project/api.py:314`（`_CHANGE_GENERAL_TYPES = ("DELAY", "BUDGET", "TITLE")`）；`:363-367` 文案改为「成员/范围变更须以重大变更（severity=MAJOR）提交，经审批后生效」，与实现一致（当前仅 MEMBER/SCOPE 会命中）；前端注释同步 `frontend/src/views/ProjectView.vue:330-332`（`severityLocked` 仍锁 MEMBER/SCOPE）；用例 `backend-django/tests/test_project_domain.py:1094-1109`（GENERAL→400/40001，MAJOR→200 SUBMITTED） |
| **Important-2** N-1 spy 用例要能在修复前失败 | **已达成（`72ee658` 真修）** | 用例 `tests/test_project_domain.py:1016-1040`：`@pytest.mark.django_db(transaction=True)`（`:1016`）去掉测试级 atomic 包裹，spy 断言 `seen == [True]`（`:1040`）；`transaction=True` 下重放修复前序列实测 `[False]`，会失败（第六节） |
| **Important-3** 预算金额上下界 / 亚分精度 | **已落地** | `api.py:334-349`（`is_finite` + `<= 1e15` + `target == target.quantize(Decimal("0.01"))`，`quantize` 在 `try` 内）；用例 `tests/test_project_domain.py:1075-1091`（1e100/0.001/1e-30/1e16 → 400/40001，123456.78 放行）。边界与空格实测见第二节 |
| **Important-4** 断言 camelCase 契约键 `templateId`/`approvalDocId` | **已达成（`72ee658` 补齐）** | `templateId`：`tests/test_project_domain.py:978`、`:998`；`approvalDocId`：`:980`（中检建单）、`:1001`（验收建单）断言键存在且为 `None`，`:1046` 断言 conclude 回写后 `to_api_final_accept(fa)["approvalDocId"] == fa.approval_doc_id`。双写实现：`apps/project/mappings.py:92-93`、`:131-132` |
| **Minor-1** 删 BUDGET 分支恒真 `if fields:` | **已落地** | `api.py:444-445`：改为无条件 `p.save(update_fields=fields + ["updated_at"])` 后 `return`；此时 `fields == ["total_budget"]`，行为与修复前等价（其后的 `fields = []` 是无害死赋值，不算缺陷） |
| **Minor-5** 一般备案空回写守卫 | **已落地，且不误伤三条合法路径** | `api.py:522-524` `if not adjusted: raise 40001`，与审批路径 `api.py:590-593` 同口径。DELAY/BUDGET/TITLE 经 `_validate_change`（`:327-349`）后 `_apply_change`（`:417-451`）必产生非空 `applied`，合法输入不会误杀；该守卫对现有类型不可达，属防御代码 |
| **Minor-6** `approve_change_batch` 校验 ids 元素 int | **已落地** | `api.py:645-646`（`isinstance(i, int) and not isinstance(i, bool)`）；逐条 `try/except ApiError`（`:659-663`）未被破坏 |
| 新增 `test_m1d_member_change_requires_major` | **已落地且有效** | `tests/test_project_domain.py:1094-1109`；修复前 GENERAL+MEMBER 会 200/EFFECTIVE，该用例会失败，是真回归 |

## 二、关键验证（含反例实测）

### 1. Important-2 的 spy 用例为什么抓不到缺陷

pytest-django 对 `django_db` 用例使用 Django `TestCase` 语义，每个用例整体包在一个 atomic 里。用项目自身配置实测（`/tmp/test_probe_atomic_r4.py`）：

```
PROBE in_atomic_block= True autocommit= False has_select_for_update= False
1 passed
```

再把「修复前」的 `conclude_final_accept` 调用序列原样重放（先 `fa.save()`，再直接调 `_issue_report`，**不包 atomic**；与 `git show 4eef2e5:backend-django/apps/project/api.py:1232` 起的旧实现同构，而当时 `_issue_report` 已有 `select_for_update`，缺陷窗口真实存在），跑 r4 的断言（`/tmp/test_probe_pre_fix_r4.py`）：

```
PRE-FIX PROBE seen= [True] report_id= 1
1 passed
```

即：**删掉 `conclude_final_accept` 的 `with transaction.atomic()`，`assert seen == [True]` 仍然通过**。用例 docstring 第 1016 行「修复前（无 atomic）为 False」与事实不符。修复方式（已实测）：

```
@pytest.mark.django_db(transaction=True)
→ PROBE_TXN in_atomic_block= False autocommit= True
```

把该用例标成 `transaction=True`（`seed_auth` 仍可用）后，测试体不再被外层 atomic 包裹，spy 才能区分修复前后。

### 2. 预算边界/空格是否误杀（`_validate_change` 直调 + 真实 HTTP）

直调结果：**放行** `"1e15"`、`"1000000000000000"`、`"100000.00"`、`" 1234.50 "`、`"1234.5"`、`"0.01"`、`"999999999999999.99"`、`1234.5`、`1e15`；**拒绝** `"1e16"`、`"1e100"`、`"0.001"`、`"1e-30"`、`"1.005"`（40001「两位小数且不超过 1e15」）、负数（40001「须为正数」）、`NaN`/`Infinity`/`None`/`True`（40001「合法的 totalBudget」）。

真实 HTTP（GENERAL 备案，走完校验+回写，`/tmp/test_boundary_r4.py`）：

| totalBudget | 结果 | 落库 |
|---|---|---|
| `"1e15"` | 200 EFFECTIVE | `1000000000000000.00` |
| `" 1234.50 "` | 200 EFFECTIVE | `1234.50` |
| `"100000.00"` | 200 EFFECTIVE | `100000.00` |

结论：**不会误杀**题述边界/正常值/含空格值。仅一处注释不严谨：`api.py:341` 称「与 DecimalField(18,2) 对齐」，而 `models.py:27` 的 `DecimalField(max_digits=18, decimal_places=2)` 上限约 `1e16-0.01`，代码取 `1e15` 更保守（业务上无实际影响，不阻断）。

### 3. 空回写守卫是否误伤 DELAY/BUDGET/TITLE

不会。TITLE 校验用 `str(...).strip()` 拒绝所有 falsy 标题（`0`/`[]`/`False` 都被 `or ""` 归一后拒绝），DELAY 要求 `_parse_date` 成功，BUDGET 要求有限且两位小数；三者到 `_apply_change` 都必然非空。该守卫在当前校验下不可达，纯防御。

## 三、新发现问题（初审基于 `dabfdff`；Important-1/2 已在 `72ee658` 关闭，见第六节）

### Critical

- 无。

### Important

1. **N-1 回归用例仍恒真（唯一阻断项）**：`tests/test_project_domain.py:1012-1035`。pytest-django 测试级 atomic 使 `connection.in_atomic_block` 恒 `True`，用例无法在「无 `transaction.atomic()`」的实现上失败（实测见第二节），且 docstring `:1016` 的因果关系写反。建议：给该用例加 `@pytest.mark.django_db(transaction=True)`（或改用 `TransactionTestCase` 语义），保留现有 spy 断言；`seed_auth` 依赖的 `db` 会随 `transaction=True` 切到事务型 fixture，实测可用。
2. **`approvalDocId` 仍无契约键断言（Important-4 的另一半）**：`mappings.py:92` 与 `:132` 已双写，但 `tests/` 中无任何 `approvalDocId` 断言；把该键从序列化器删掉，346 测试仍会全绿。建议在 `tests/test_project_domain.py:978`/`:998` 同处补 `data["approvalDocId"]`（含「conclude 后回填」场景更好）。

### Minor

1. **契约描述随本轮行为变更漂移**：`design/02-项目过程管理-E.openapi.yaml:1116-1120` 仍写 `severity`「GENERAL=一般变更（内部备案，提交即生效）」，未说明 MEMBER 已被排除；`ChangeType` 枚举（`:941-943`）仍含 MEMBER/SCOPE。按契约发 `MEMBER`+缺省 GENERAL 的客户端会得到 40001。仅文档/契约问题（r3 Minor-2 的同类延续，本轮 MEMBER 变更使其多一处），不阻断。
2. `api.py:445` 的 `fields = []` 在 `return` 前已无作用，可随下次清理删除（不影响行为）。

## 四、实测数字（本轮亲跑）

| 命令 | 结果 |
|---|---|
| `cd backend-django && .venv/bin/python -m pytest -q` | `346 passed, 7 warnings in 12.29s`，exit 0（real 0m12.63s；`72ee658` 复核实测；初审 `dabfdff` 为 12.99s） |
| `cd backend-django && .venv/bin/python manage.py makemigrations --check --dry-run` | `No changes detected`，exit 0（仅 PG 拒连 `RuntimeWarning`，环境无 5432） |
| `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | exit 0，无输出（real 0m2.637s） |
| `cmp design/02-项目过程管理-E.openapi.yaml frontend/src/api/schema/02-项目过程管理-E.openapi.yaml` | 一致，exit 0 |
| `cmp design/01-项目申报与立项-P.openapi.yaml frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml` | 一致，exit 0 |
| `git log --oneline b3eec62..HEAD` | 16 条（HEAD `72ee658`；初审时 15 条、HEAD `dabfdff`） |
| `git status --porcelain` | 仅 `docs/` 既有改动/未跟踪（含三份旧 plan、本报告目录、`docs/img/`、roadmap）与 BASE 前既有未跟踪（`backend-django/uv.lock`、`dump.rdb`、`frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml`、`scripts/ocr_jxa.js`、`scripts/ocr_screenshots.swift`），**无源码残留** |
| README | `README.md:5/29/73` 均为 346，与实测一致 |

说明：初审时 346 全绿**不能**证明 N-1 有回归保护（失效用例也在其中通过）；`72ee658` 后该用例已能在修复前失败（第六节反证），346 全绿才具备回归含义。

## 五、可合并性

**可以合并。** `72ee658` 已把两条阻断项真正关闭：N-1 用例改 `transaction=True` 后能在「无 atomic」实现上失败（反证实测 `[False]`），`approvalDocId` 三处断言覆盖建单与回写；全量 346 测试、迁移、`vue-tsc`、契约 cmp 均通过，未误伤其它用例，无源码残留。剩余两项 Minor（`fields = []` 死赋值、OpenAPI 描述漂移）不影响行为，后者已记 ledger 排期 M2。

## 六、`72ee658` 复核（两条阻断项）

提交 `72ee658 test(project): N-1 回归用例改事务型（transaction=True）并补 approvalDocId 断言（M1-d r4 意见）`，仅改 `backend-django/tests/test_project_domain.py`（+10/−3），无生产代码改动。

### 1. Important-2：用例现在真能抓缺陷

- 改动：`tests/test_project_domain.py:1016` 增加 `@pytest.mark.django_db(transaction=True)`，签名去掉 `seed_auth`（`:1017` 变为 `(monkeypatch)`），docstring `:1014-1015` 的因果表述改为「去掉 atomic 时这里变成 False」。
- 独立反证：在 `transaction=True` 下重放修复前序列（先 `fa.save()` 再直调 `_issue_report`，**不包 atomic**），`/tmp/test_probe_pre_fix_r4b.py` 实测 `seen = [False]`，即用例的 `assert seen == [True]`（`:1040`）会失败；修复后实现下 `seen = [True]`，用例通过。
- 结论：不再是恒真用例，能区分「有/无 `transaction.atomic()`」。

### 2. Important-4：`approvalDocId` 断言已补齐

- `tests/test_project_domain.py:980`（中检建单响应）与 `:1001`（验收建单响应）各断言 `data["approvalDocId"] is None`——键缺失即 KeyError。
- `tests/test_project_domain.py:1046` 在 conclude 回写、`refresh_from_db` 后断言 `to_api_final_accept(fa)["approvalDocId"] == fa.approval_doc_id`，覆盖「签批后回填」路径。
- `templateId` 断言（`:978`/`:998`）未受影响。

### 3. 未误伤其它用例

- `pytest -q tests/test_project_domain.py -k "conclude_works_without_caller_transaction or eval_template_prefill"` → 2 passed。
- 全量 `346 passed, 7 warnings in 12.29s`，exit 0；`transaction=True` 用例结束后 flush，未污染后续用例。
- `git status --porcelain` 与初审一致：仅 `docs/` 改动/未跟踪与 BASE 前既有未跟踪文件，无源码残留；`git log` 为 16 条。
