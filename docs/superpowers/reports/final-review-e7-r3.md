# E-7 跨域 body/path id 裸查收口 · 第三轮终审（r3，含 2a9248b 增量）

- 审查对象：`develop` @ `2a9248b`，BASE `1b1b55f`，共 7 个 commit（e2d297a / 91830e1 / d317245 / a17db11 / bd55718 / 9fe262b / 2a9248b）
- 上轮结论：`docs/superpowers/reports/final-review-e7-r2.md` — APPROVED_WITH_MINOR，可推 develop、不可上生产（R2-I1 / R2-I2 未闭环）
- 本轮声明：`9fe262b` 闭环 R2-I1、R2-I2、M2、M3、M5；`2a9248b` 闭环 r2 报告 B 段「创建类接口 body 引用未校验」（R2-B）
- 评审方式：只读。全部测试与探针在 `git archive 2a9248b` 的干净导出树 `/tmp/e7r3-clean2` 内执行；真实仓库本次评审**零写入**（唯一写入是本报告）。

## 0. 审查口径与并发改动说明

评审从 `9fe262b` 开始，期间真实工作树出现过他人未提交的 R2-B 改动（`create_expense` 的 EProject / SysLegalEntity 归属校验、`create_outward` 的 project / budget 校验、`create_loan` 的 project 404、`create_disclosure` 的 output / project 校验及配套用例）。评审中途 HEAD 前进到 `2a9248b`，上述改动即该 commit 的内容。按最终要求，本报告以 `1b1b55f..2a9248b` 的 7 个 commit 为判定对象，`2a9248b` 的增量已独立复验（§B′），不采信提交说明。

为可复现且避免把并发改动算进旧基线，所有命令均在导出树执行：

```bash
git archive 2a9248b | tar -x -C /tmp/e7r3-clean2
cd /tmp/e7r3-clean2/backend-django
```

评审结束时真实仓库 `git status --porcelain backend-django/apps backend-django/tests backend-django/config/casbin` 为空（并发改动已落为 `2a9248b`），确认本 reviewer 未改动真实工作树。

复现材料（均在 `/tmp`，未入仓）：

- `/tmp/e7r3-probes/test_probe_e7r3.py` —— A/B/C/D 探针（11 条）
- `/tmp/e7r3-probes/test_probe_toctou.py` —— B′ 的「不存在则放行 / 软删绕过 / TOCTOU」探针（3 条）
- `/tmp/review-e7-r3-v2.diff` —— `1b1b55f..2a9248b` 全量 diff

```bash
cp /tmp/e7r3-probes/*.py /tmp/e7r3-clean2/backend-django/tests/
cd /tmp/e7r3-clean2/backend-django && .venv/bin/python -m pytest -q tests/test_probe_e7r3.py tests/test_probe_toctou.py -s
# 14 passed；上面 596 的基线是移除探针后的数，加入后 610
```

## VERDICT

**APPROVED_WITH_MINOR** —— 就 `1b1b55f..2a9248b` 这 7 个 commit 而言，R2-I1 / R2-I2 / M2 / M3 / M5 与 R2-B 全部实测闭环，**可以推 develop**；但**不可上生产**：D 项漏网扫出 3 处存量跨租户可写裸查（ethics / project / output），且 `_reject_foreign_ref` 的「不存在则放行 + `deleted=0`」留下可复现的跨租户引用通道（Important）。

> 口径：APPROVED_WITH_MINOR 只针对本期 diff。若把「E-7 跨域裸查收口」的验收标准定义为**全仓清零**，则本报告应读作 **REQUEST_CHANGES**——D-1/D-2/D-3 正是本计划要消灭的漏洞类别，且不在本期 7 个 commit 内。

## 1. 实测数字表

| 项目 | 期望 | 实测 |
|---|---|---|
| 全量回归 `pytest -q`（干净 2a9248b） | 596 passed | **596 passed**, 19 warnings, 43.25s |
| 含 14 条独立探针 | — | **610 passed**（596 + 14；探针已从导出树移除，仅存 /tmp） |
| `makemigrations --check --dry-run` | No changes | **No changes detected**（仅 PG 127.0.0.1:5432 连接拒绝 RuntimeWarning） |
| `git diff 1b1b55f..2a9248b -- design/ frontend/src/api/schema/` | 0 | **0 行** |
| README 第 5/29/99 行 | 596 | **596 / 596 / 596** |
| r3 新增用例真红（4 文件回滚 bd55718） | 新增用例失败 | **5 failed, 8 passed**（第 6 条为回归锁，见 §C-3） |
| 2a9248b 新增用例真红（2 文件回滚 9fe262b） | 4 条失败 | **4 failed, 13 passed**（§B′） |
| 迁移 0019 · 空库 | 可跑通 | **720 links, 0 悬空, `indirect-fees GET` ×2** |
| 迁移 0019 · 已 seed 库 | 只删悬空、留目录行 | **721 → 720**，`SysPermission` 目录行保留，GET 行补齐为 2 |
| `purge_stale_policy_rows` 单测 | 有 | **无**（Minor，见 §M-2） |
| `policy.csv` 键卫生 | 行数 = 唯一键 | **754 行 / 720 唯一三元组**，30 个重复键（34 行冗余） |
| `tests/test_phase4_transform.py`（`duration_days:0`） | 全绿 | **7 passed** |

### 逐 commit `--stat`（无夹带）

| commit | 文件 | 变更 |
|---|---|---|
| e2d297a | README + activity/api.py + test_activity_tenant.py | 104+/14- |
| 91830e1 | README + confsec/api.py + test_confsec_tenant.py | 97+/8- |
| d317245 | README + funding/api.py + test_funding_domain.py + test_funding_tenant.py | 202+/29- |
| a17db11 | README + transform/api.py + test_transform_tenant.py | 104+/28- |
| bd55718 | README + confsec/funding/transform api + 0018 + policy.csv + 6 个测试文件 | 243+/31- |
| 9fe262b | README + funding api + 0019 + sysadmin/permissions.py + transform api/mappings + policy.csv + test_e7 | 252+/9- |
| 2a9248b | README + funding/api.py + transform/api.py + test_e7 | 90+/7- |

每个 commit 均为「README 测试数 + 本域实现 + 本域测试」，无脚本、无生成物、无无关格式化。bd55718 跨 3 域但主题一致（E-7 终审补漏）。

## A. R2-I1（存量脏单静默成功）—— 已闭环

### A-1 helper 覆盖全部 4 处

`apps/funding/api.py:257-267`：

```python
def _update_budget_line_or_409(tenant_id: int, line_id: int, **fields) -> None:
    n = FBudgetLine.objects.filter(
        id=line_id, tenant_id=tenant_id, deleted=0).update(**fields)
    if n == 0:
        raise ApiError(409, CODE_CONFLICT, "预算行归属异常，审批已阻断")
```

调用点 4/4：

| 场景 | 位置 |
|---|---|
| 报销终审实扣（frozen→used） | `apps/funding/api.py:959` |
| 报销驳回/退回解冻（frozen→released） | `apps/funding/api.py:979` |
| 借款驳回/退回释放 | `apps/funding/api.py:2349` |
| 借款放款结转（frozen→used） | `apps/funding/api.py:2383` |

静态复核 `FBudgetLine` 的全部写入点：`apps/funding/api.py:222/265/297/310/332/371/384/409/427/774/824/893/1047/1104/1514/2239/2291`。除 `:371`（预算行编辑）、`:409`（调整）、`:427`（删除）是在**已做租户校验的 budget 之下**按 `budget_id` 派生行、并带 `budget_id=bud.id` 条件外，其余写入全部经租户过滤或本 helper；**未发现遗漏的静默 `update()`**。helper 采用单条 UPDATE + 行数判定，天然抵御「读后行被改租户/软删」的竞态，优于先查后写。

### A-2 直接落库脏单复现（4 条路径全 409，回滚彻底）

探针直接 ORM 造「本租户单据 + 他租户 `budget_line_id`」，走真实 HTTP：

```
A2.expense.approve 409 {"code": 40901, "message": "预算行归属异常，审批已阻断"}
A2.expense.reject  409 {"code": 40901, ...}
A2.loan.reject     409 {"code": 40901, ...}
A2.loan.pay        409 {"code": 40901, ...}
A3.outward.final   409 {"code": 40902, "message": "预算行余额不足，外拨无法入账"}
```

每条的落地状态断言（全部通过）：

| 用例 | 单据状态 | 审批链 | `SysApprovalLog` | 他租户预算行 |
|---|---|---|---|---|
| 报销 APPROVE | SUBMITTED（未推进） | `FExpenseApproval` 仍 **PENDING** | **未写入** | frozen/used/released 全不变 |
| 报销 REJECT | SUBMITTED | 仍 PENDING | 未写入 | released 仍 0 |
| 借款 reject | SUBMITTED | — | 无 LOAN 日志 | frozen=400 不变，released=0 |
| 借款 pay | APPROVED | — | 无 log | frozen=400 / used=0 不变 |

`FExpenseApproval` 保持 PENDING、`approval.log` 未落库，说明 409 抛在 `transaction.atomic` 内且**原子回滚彻底**，没有「状态已变、金额未动」的半截写入。

### A-3 外拨终审仍 fail-closed

`apps/funding/api.py:1104-1110` 仍为 `select_for_update().filter(id=..., tenant_id=..., deleted=0)`，取不到行或余额不足 → `40902`。实测：单据保持 PENDING，`first_approved_by` 仍 `None`，他租户行 used=0。

## B. R2-I2（公示 PII + 异议状态守卫）—— 已闭环（2 项残余观察）

### B-1 匿名 GET 已掩码

- `apps/transform/api.py:577-584`：`get_publicity` 改调 `to_api_publicity_public(p)`
- `apps/transform/mappings.py:243-276`：`_mask_name`（首字 + `*`，`max(1, len-1)`）、`_mask_contact`（`len>=7` → 前 3 + `****` + 后 4；`len>4` → 前 2 + `****` + 后 2；否则全 `*`；非 `str`/空 → `None`）
- `to_api_publicity` 字段面固定为 `id/deal_id/status/publish_*/duration_days/url/summary_json/objection_open/objections`，无额外 PII 字段

实测原始响应（未经过任何前端处理）：

```
submitter "欧阳修远" → "欧***"      contact "13812345678"       → "138****5678"
submitter "张三"     → "张*"        contact "110101199001011234" → "110****1234"
submitter "李"       → "李*"        contact null                 → null
```

断言「完整手机号 / 18 位身份证串 / 全名均不出现在原始响应体中」通过。

**残余 1（Important）**：`handle_result` 原样返回（实测 `"已处理"`）。字段本身是管理员填写的处置说明，非自动采集 PII，但属公开面无约束自由文本，存在人工写入手机号/姓名的通道。建议公开面只回 `handle_status`，或对 `handle_result` 套同一 `_mask_contact` 数字段规则。

### B-2 异议状态守卫（不误伤正常提交）

`apps/transform/api.py:614-622`：

```python
if p.status not in ("PUBLISHED", "OBJECTION_PENDING"):
    raise ApiError(409, CODE_CONFLICT, "公示已结束，不再受理异议")
```

| 公示状态 | 结果 | 副作用 |
|---|---|---|
| COMPLETED | **409** | 异议数不变、状态不变 |
| TERMINATED | **409** | 同上 |
| PUBLISHED | **200** | 转 OBJECTION_PENDING，追加 1 条 |
| OBJECTION_PENDING | **200** | 直接追加 1 条，状态不变 |

不过度收紧的验证：`tests/test_phase4_transform.py`（含两处 `duration_days: 0` 用例）**7 passed**；全量 596 passed 亦覆盖。

**残余 2（Minor）**：若构造 `deal.status=TERMINATED` 而 `publicity.status=PUBLISHED` 的存量脏态，匿名 POST 仍 200 并把公示翻回 `OBJECTION_PENDING`（实测 `[B2.deal_terminated_pub_published] 200`）。当前代码中 deal 置 TERMINATED 的唯一路径是 `handle_objection` SUSTAINED，且同事务把公示置 TERMINATED，故正常流程不可达，只是缺乏兜底。建议守卫同时判 `p.deal.status == "TERMINATED"`。

### B-3 掩码函数健壮性

`None` / `""` / `12345`（非 str）/ `"1"` / `"1234"` / `"12345"` / `" 13800000000 "` 全部按预期返回，无 `IndexError`、无异常。

## B′. R2-B（创建类接口 body 引用）—— 2a9248b 增量，已闭环但留 Important

### B′-1 实现与覆盖

`apps/funding/api.py:241-254`：

```python
def _reject_foreign_ref(model, obj_id, tenant_id: int, label: str) -> None:
    if obj_id in (None, "", 0, "0"):
        return
    try:
        oid = int(obj_id)
    except (TypeError, ValueError):
        raise ApiError(400, CODE_BAD_REQUEST, f"{label} id 非法")
    if model.objects.filter(id=oid, deleted=0).exclude(tenant_id=tenant_id).exists():
        raise ApiError(404, CODE_NOT_FOUND, f"{label}不存在")
```

应用点 4/4：

| 创建接口 | 校验对象 | 位置 |
|---|---|---|
| `create_expense` | EProject + SysLegalEntity | `apps/funding/api.py:816-817` |
| `create_outward` | EProject + FBudget | `apps/funding/api.py:1039-1043` |
| `create_loan` | EProject | `apps/funding/api.py:2234` |
| `create_disclosure` | ROutput + EProject（内联同逻辑） | `apps/transform/api.py:158-167` |

新增 4 条用例在 `9fe262b` 上回滚 `apps/funding/api.py` + `apps/transform/api.py` 后：

```
FAILED tests/test_e7_review_fixes.py::test_create_expense_rejects_foreign_project
FAILED tests/test_e7_review_fixes.py::test_create_outward_rejects_foreign_project
FAILED tests/test_e7_review_fixes.py::test_create_loan_rejects_foreign_project
FAILED tests/test_e7_review_fixes.py::test_create_disclosure_rejects_foreign_output
4 failed, 13 passed
```

恢复后 md5 与 `2a9248b` blob 一致（funding api `480f4eee5a2f6ec5f79846f5a86cf663`），真红成立。

### B′-2 「不存在则放行」的判定：可接受，但不是无风险

我按最坏路径实测了三组（探针在 /tmp，未入库）：

```
$ pytest -q tests/test_probe_toctou.py -s
[A.nonexistent] status=200 project_id=999999
[B.soft_deleted_foreign] project=1 status=200
[C.get] 200 title_leak=False | submit=200 approve=200 | status=APPROVED acct=True acct.project_id=999998
3 passed in 2.69s
```

即：`project_id=999999`（不存在）建单 200；他租户项目 `deleted=1` 后建单仍 200；以 `project_id=999998`（不存在）建单后由租户 2 占用该 id，单据仍可提交、审批，最终 `FAccountingEntry(tenant=1).project_id=999998`。`GET` 响应不含项目标题（`title_leak=False`），故不构成读泄露。

判定：

1. **写入侧未被突破**：审批链只按 `budget_line_id` 定位并写预算行，已全部带 `tenant_id`；`_post_accounting_entry`（`apps/funding/api.py:480-505`）直接接收 `project_id`、不反查 EProject；`to_api_expense`（`apps/funding/mappings.py:105-125`）与 `get_expense`（`apps/funding/api.py:864-872`）不 join 项目。故**没有**改到他租户行、也没有借响应面读到项目内容，不判 Critical。
2. **但留下两类可复现问题**：(a) 孤儿单据与孤儿会计分录被正常受理；(b) 一旦 id 被他人占用，本租户单据/分录就长期指向他租户项目（跨租户引用），财务按项目的汇总会出现错误的归属；(c) **软删绕过**更直接——`deleted=0` 使「存在但已软删」的他租户对象逃过校验，与 helper 注释「对象存在且属于他租户时一律 404」自相矛盾，且 id 顺序可枚举。
3. 结论：作为兼容历史数据的取舍**可以接受**，但应显式列为已知限制并补两道闸：校验改为 `model.objects.filter(id=oid).exclude(tenant_id=tenant_id).exists()`（不带 `deleted=0`，堵软删绕过）；对新建单据增加「引用 id 超过当前表 max(id) 即 400」或定期数据质量扫描（孤儿 `project_id` 报表）。判 **Important（I-1）**，不阻塞 develop，但属于生产前应修。

### B′-3 顺带发现

`create_outward`/`create_loan`/`create_disclosure` 对 `budget_id`/`budget_line_id`/`output_id` 仍直接 `int(...)`（如 `apps/funding/api.py:823`、`:1042`、`:2238`，`apps/transform/api.py:158`），非数字串会抛 `ValueError` → 500，而非 helper 的 400。属 Minor（M-4）。

## C. M2 / M3 / M5 —— 已闭环

### C-1 M2：purge 只删悬空指派

`apps/sysadmin/permissions.py:64-92`：`keep` 只收 CSV 的 `(obj, act)`，遍历 `SysRolePermission.select_related("permission")`，凡 `(obj,act)` 不在 keep 即删 link；**不删 `SysPermission` 目录行**。迁移 `0019_purge_stale_policy_e7.py` 依赖 0018，先 purge 再 sync。

实测三种库：

| 场景 | 命令 | 结果 |
|---|---|---|
| 空库全量迁移 | `manage.py migrate --settings=probe_settings` | **720 links**，悬空 `disclosure GET` = 0，`indirect-fees GET` = 2 |
| 已 seed 库（迁移到 0018 后注入悬空 link） | `migrate sysadmin 0018` → 注入 → `migrate sysadmin 0019` | 721 → **720**，悬空 link 删除，`SysPermission` 目录行**仍为 1**，GET 行补齐为 2 |
| 单测内动态注入悬空 link | 调 `purge_stale_policy_rows()` | `deleted 1, before 722, after 721`；合法 link 保留；全量 purge `deleted 0, keep 720, db 720, missing 0` |

结论：只删 CSV 中已不存在的 `(obj,act)` 指派，不动现有规则，也不清权限目录；空库/存量库均可执行。

**提示（Important）**：`apps/sysadmin/api.py:601-637` 允许管理端运行期 grants/revokes。迁移里的 purge 会把「挂在 CSV 已删 `(obj,act)` 上的运行期授权」一并删除。方向正确（悬空权限），但属一次性数据变更，建议在迁移里输出删除条数与 `(role,obj,act)` 清单，便于回溯。

### C-2 M3：GET /indirect-fees/calculate 策略补齐

- `config/casbin/policy.csv:924-927` 已含 `R-MANAGER` / `R-FINANCE` 的 GET 与 POST
- `config/api.py:316-320` 同时注册 POST/GET → `funding_api`
- `design/03-科研经费管理-F.detail.md:487` 记 `POST /indirect-fees/calculate · GET`，与实现一致

实测：`{'R-MANAGER': 200, 'R-FINANCE': 200, 'R-STAFF': 403}`——既补上财务口径，也没把 GET 放开给普通科研人员。

### C-3 M5 与「新测试真红」验证

将 4 个文件回滚到 `bd55718` 后跑 `tests/test_e7_review_fixes.py`：

```
FAILED test_legacy_expense_with_foreign_line_is_blocked_on_approve
FAILED test_legacy_loan_with_foreign_line_is_blocked_on_pay
FAILED test_public_publicity_masks_objector_pii
FAILED test_public_objection_rejected_on_closed_publicity
FAILED test_indirect_fee_calculate_get_allowed_for_finance
5 failed, 8 passed in 2.96s
```

覆盖文件已用备份恢复，`md5` 与 `9fe262b` blob 逐一比对一致，导出树无残留。

**必须说明的细节**：第 6 条 `test_legacy_expense_with_foreign_line_cannot_be_submitted` 在 `bd55718` 上**是绿的**。原因是「提交时点校验悬空/他租户预算行」的代码在 r2 之前就存在，M5 的缺口是**测试覆盖**而非实现。因此它是回归锁而不是「真红」用例，`9fe262b` 对 M5 的闭环是「补上覆盖」，属实，但不能宣称「新增用例全部由红转绿」。

**M2 没有对应的单元测试**（仅靠迁移与手工探针验证），属 Minor（M-2）。

## D. 漏网再扫 —— 发现 3 处存量跨租户可写裸查（Critical）

扫描口径：`apps/*/api.py` 中 `objects.filter(id=` / `objects.get(id=` / `select_for_update()`，逐条判断「id 是否来自 path/body」「是否带 tenant_id」「后续是否写入」。共 189 处命中，绝大多数已带租户或经父对象派生。以下 3 处**实测可跨租户写入**，2a9248b 未触及这些文件，结论与 9fe262b 相同。

### D-1 ethics：案卷 helper 无租户，12 个写接口全部可跨租户

`apps/ethics/api.py:81-85`：

```python
def _get_case_or_404(cid: int) -> CEthicsCase:
    c = CEthicsCase.objects.filter(id=cid, deleted=0).first()
    if c is None:
        raise ApiError(404, CODE_NOT_FOUND, "伦理案卷不存在")
    return c
```

调用它的写接口：`:155`（submit）、`:174`（ai-prescreen）、`:191`（formal-check）、`:212`（assign）、`:234`（opinion）、`:266`（meeting check-in）、`:295`（meeting vote）、`:316`（letter）、`:358`（amendment）、`:407`（ae-report）、`:446`（annual-review）、`:467`，另有 `decide_amendment`（`:424`）直接 `CAmendment.objects.filter(id=id, deleted=0)` 后写状态。**全部无 `tenant_id` 条件**。

复现（`bearer(1, ["R-STAFF"], tenant_id=1)` 打 tenant 2 的案卷）：

```
D.ethics.get    200 {"code": 0, "data": {"id": 1, "code": "ETH-X-000001", "status": "DRAFT", ...}}
D.ethics.submit 200 {"code": 0, "data": {"id": 1, "status": "FORMAL_CHECK", ...}}
D.ethics.after  FORMAL_CHECK
```

即：租户 1 的普通科研人员可读、可提交（进而可走审批/签发批件）租户 2 的伦理案卷。`policy.csv:649-657` 对 `R-STAFF` 开放 `/api/v1/ethics/*/submit` 等，攻击面不是理论值。

修法：helper 增参 `tenant_id`，`filter(id=cid, tenant_id=tenant_id, deleted=0)`，12 个调用点传入 `dom.tenant_id`；`decide_amendment` 改 `CAmendment.objects.filter(id=id, case__tenant_id=dom.tenant_id, deleted=0)`。

### D-2 project：任务更新跨租户

`apps/project/api.py:95` 的 `_get_project_or_404(project_id)` 无租户过滤（`:1463` 还有一份同名重复定义，同样无租户）；`:243-255`：

```python
def update_task(request, id, task_id):
    _get_project_or_404(id)
    ...
    task = ETask.objects.filter(id=task_id, project_id=id, deleted=0).first()
    task.status = status
```

两个 id 都来自 path，均无租户条件。复现（tenant 2 的项目+任务，tenant 1 的 `R-STAFF`）：

```
D.project.update_task 200 {"code": 0, "data": {"id": 1, "tenant_id": 2, "status": "DONE", ...}}
D.project.task.after DONE
```

`policy.csv:124` 对 `R-STAFF` 开放 `PUT /api/v1/project/*/tasks/*`。同文件 `:1008` `attach_project_category` 也是 `EProject.objects.filter(id=id, deleted=0).update(category_id=...)`，无租户。

修法：helper 改为 `_get_project_or_404(project_id, tenant_id)` 并删掉重复定义；`attach_project_category` 加 `tenant_id=d.tenant_id`；对 `ETask/EMilestone/...` 等子对象统一经已租户校验的 project 派生。

### D-3 output：批量认领按 body id 跨租户写

`apps/output/api.py:223-250`：

```python
for it in items:
    oid = (it or {}).get("output_id")
    o = ROutput.objects.filter(id=oid, deleted=0).first() if oid else None
    ...
    o.claim_status = claim_status
    o.status = status
    o.is_claimed = is_claimed
    o.save(...)
    RClaimRecord.objects.create(tenant_id=d.tenant_id, ..., output_id=o.id, ...)
```

body 里的 `output_id` 无租户过滤，写入的 `RClaimRecord` 却记到当前租户——等于把他人成果「认领」到自己名下。复现（tenant 1 `R-STAFF` 认领 tenant 2 成果）：

```
D.output.claim 200 {"code": 0, "data": {"results": [{"output_id": 1, "success": true, "new_status": "CLAIMED"}]}}
D.output.after CLAIMED CLAIMED True
```

`policy.csv:154` 对 `R-STAFF` 开放 `POST /api/v1/output/claim`。同文件 `:93` `_get_output_or_404`、`:293` `conclude_output_eval`（N 域回写）、`:480` `ROutput.objects.get(id=id)` 亦无租户；其中 `conclude_output_eval` 是内部单一写者，风险低于前两者，但建议一并加 `tenant_id` 可选参数。

修法：`_process_claim` 的查询改 `filter(id=oid, tenant_id=d.tenant_id, deleted=0)`，未命中计入 `success:false` 而不是静默跳过租户校验。

### D-4 其余静态候选（未逐一探针，供后续排期）

| 位置 | 形态 | 判断 |
|---|---|---|
| `apps/archive/api.py:53/60/496` | `_get_doc_or_404` / `_get_archive_or_404` / `_set_borrow_status` 无租户 | 写路径受 `R-ADMIN` 策略约束（`policy.csv:261-263`），仍建议收口 |
| `apps/asset/api.py:78/647` | `_get_asset_or_404`、凭证明细按 body `depreciationId` 写 `voucher_id` | `R-FINANCE` 策略约束，跨租户可写，建议收口 |
| `apps/dataops/api.py:73` | `EProject.objects.filter(id=b.project_id)` 无租户 | 只读聚合，仅泄露部门 id 到热力图键；存量脏 budget 才能触发（Minor，M-5） |
| `apps/p/api.py:239/633/688/719` | 评审任务按 id 直查 | 任务→指南/申请均带 `tenant_id` 派生（`:243` 有注释），风险较低；`:633` body `task_id` 建议补租户 |
| `apps/expertreview`、`apps/performance` | 已带 `tenant_id` 或经 scheme/专家父对象派生 | 本轮未发现问题 |

**有意保留的公开通道（判断依据）**：

- `GET /api/v1/publicity/{dealId}`、`POST /api/v1/publicity/{dealId}/objection`：匿名可访问是产品需求（公示异议），PII 已在输出层掩码 + 状态守卫，保留合理。
- `/portal/*`、`/register/*`：对外开放的申报/注册入口，不依赖登录租户，鉴权在各自业务内完成。
- `GET /api/v1/ethics/letter/{letterNo}`：按编号验证批件真伪，只回验证结论不回内容（`config/api.py:702` 注释明确），保留合理。

## E. 回归与卫生 —— 通过

```bash
cd /tmp/e7r3-clean2/backend-django
.venv/bin/python -m pytest -q                                  # 596 passed, 19 warnings in 43.25s
.venv/bin/python manage.py makemigrations --check --dry-run    # No changes detected
git diff 1b1b55f..2a9248b -- design/ frontend/src/api/schema/   # 0 行
sed -n '5p;29p;99p' README.md                                  # 596 / 596 / 596
```

- **回归**：596 passed（r2 基线 586 → r3 前 592 → 2a9248b 596，增量与新增用例数一致：9fe262b +6、2a9248b +4）。
- **迁移**：`No changes detected`；唯一警告是 PG `127.0.0.1:5432` 连接拒绝的 RuntimeWarning（test settings 用 sqlite 内存库），与代码无关。
- **契约**：`design/` 与 `frontend/src/api/schema/` 零 diff，公开面字段未变（掩码在输出层做，不改 schema）。
- **README**：第 5/29/99 行均为 596。
- **逐 commit**：见 §1 表，均为「README 测试数 + 本域实现 + 本域测试」，无脚本、无生成物、无无关格式化，无夹带。
- **工作树**：评审期间出现的并发改动已确认为 `2a9248b` 的内容；评审结束时 `git status --porcelain backend-django/apps backend-django/tests backend-django/config/casbin` 为空，本 reviewer 零写入真实仓库。

## 问题清单

### Critical

**D-1 伦理案卷跨租户读/写（存量，非本期引入）**
- 位置：`apps/ethics/api.py:81-85`（及 12 个写接口、`:424`）
- 复现：`pytest -q tests/test_probe_e7r3.py -s -k test_d_ethics`；tenant-1 `R-STAFF` 对 tenant-2 案卷 GET 200 / POST `/ethics/{id}/submit` 200，状态 DRAFT→FORMAL_CHECK
- 修复：helper 增 `tenant_id` 过滤并更新 12 个调用点；修正案按 `case__tenant_id` 过滤

**D-2 项目任务跨租户更新（存量）**
- 位置：`apps/project/api.py:95`、`:243-255`、`:1008`、`:1463`
- 复现：`-k test_d_project`；tenant-1 `R-STAFF` PUT `/project/{tenant2}/tasks/{tenant2}` → 200，任务 DOING→DONE
- 修复：helper 增租户参数、删除重复定义；子对象统一经已租户校验的 project 派生

**D-3 成果认领按 body id 跨租户写（存量）**
- 位置：`apps/output/api.py:235`
- 复现：`-k test_d_output`；tenant-1 `R-STAFF` POST `/output/claim` 携带 tenant-2 的 `output_id` → 200，成果变 CLAIMED 且生成租户 1 的认领记录
- 修复：查询加 `tenant_id=d.tenant_id`

### Important

**I-1 `_reject_foreign_ref` 的「不存在则放行 + deleted=0」留下跨租户引用/软删绕过（2a9248b 新增）**
- 位置：`apps/funding/api.py:241-254`；同口径 `apps/transform/api.py:158-167`
- 复现：`pytest -q tests/test_probe_toctou.py -s`
- 复现 A（孤儿→跨租户引用）：tenant-1 用 `project_id=999998`（不存在）建报销 → 200；tenant-2 随后创建 `id=999998` 项目；该报销 submit → 200、approval → 200，`FAccountingEntry(tenant=1).project_id=999998`
- 复现 B（软删绕过）：tenant-2 项目 `deleted=1`，tenant-1 `POST /expenses` 携带其 id → **200**（`filter(deleted=0)` 使其逃过校验）
- 影响：不改他租户行，但造成孤儿单据/分录与长期跨租户引用；软删对象可被稳定枚举并引用
- 修复：校验去掉 `deleted=0`（`filter(id=oid).exclude(tenant_id=tenant_id).exists()`）；新建单据增加 id 上界检查或孤儿数据质量扫描；在 helper docstring 写明「引用存在性不保证」

**I-2 公示 `handle_result` 自由文本未脱敏**
- 位置：`apps/transform/mappings.py`（`to_api_publicity_public` 只掩码 `submitter`/`contact`）
- 证据：匿名 GET 返回 `"handle_result": "已处理"` 原值；该字段由管理员自由填写
- 修复：公开面不回该字段，或对数字串（≥7 位）套 `_mask_contact`

**I-3 迁移 0019 会删除运行期自定义授权**
- 位置：`apps/sysadmin/permissions.py:64-92` + `apps/sysadmin/api.py:601-637`
- 证据：purge 以 CSV `(obj,act)` 为唯一真源，管理端在运行期授予的、CSV 中不存在的权限会被一并清掉（实测悬空 link 删除 1 条）
- 修复：迁移内打印删除条数与 `(role,obj,act)` 清单；或限定只清「CSV 中不存在的 (obj,act) 且无 audit 引用」的 link

### Minor

**M-1 `policy.csv` 重复键**：754 条 p 行 / 720 唯一三元组，30 个重复键（34 行冗余），如 `tasks/* GET` 四角色各 3 条、`ethics/* GET/POST` 各 2 条。`get_or_create` 幂等，功能无影响，建议去重并加「policy 行唯一」CI 校验。

**M-2 `purge_stale_policy_rows` 无单测**：仅靠迁移与手工探针覆盖，建议补「造悬空 link → 调用 → 断言行数/目录行保留」用例。

**M-3 公示脏态兜底缺失**：`deal=TERMINATED` + `publicity=PUBLISHED` 时匿名异议仍 200 并翻转状态。建议守卫加 `p.deal.status` 判断。

**M-4 创建接口的 id 解析会 500**：`create_outward`/`create_loan`/`create_disclosure` 对 `budget_id`/`output_id` 直接 `int(...)`（`apps/funding/api.py:1046`、`:2241`，`apps/transform/api.py:158`），非数字串抛 `ValueError` → 500。建议统一走 `_reject_foreign_ref` 的 try/except 400。

**M-5 `dataops` 聚合裸读项目**：`apps/dataops/api.py:73` `EProject.objects.filter(id=b.project_id).first()` 无租户，存量脏 budget 可把他租户 `department_id` 带进热力图键。建议加 `tenant_id=d.tenant_id`。

## 结论

`2a9248b` 的 7 个 commit 对 r2 的全部意见是**真闭环**：预算行写入收敛到「零行命中即 409」的单条 UPDATE，四条脏单路径实测 409 且状态、审批链、日志、他租户金额全部无副作用；公示输出层掩码与异议状态守卫生效且未误伤 `duration_days:0`；purge 在空库与存量库上都只删悬空指派；GET 试算策略与设计文档一致；创建类接口的 4 条 body 引用用例在旧 HEAD 上 4 红、在新 HEAD 上全绿。因此**可以推 develop**。

但**不能上生产**，最关键的三条发现是：

1. **D 项扫出 3 处存量跨租户可写裸查**——ethics 案卷（12 个写接口）、project 任务更新、output 批量认领，均由 path/body id 直接定位、无 `tenant_id` 过滤，且对 `R-STAFF` 开放；实测 tenant-1 令牌可改 tenant-2 数据。这正是 E-7 要消灭的漏洞类别，必须在生产前单独立项收口。
2. **创建类接口的引用校验只挡「存在且活跃的他租户对象」**——`deleted=0` 使软删对象可被直接引用（实测 200），「不存在则放行」又让单据可先建后指向他租户项目，最终审批生成的会计分录带着他租户 `project_id` 长期留存。写侧未破防，但引用完整性已破，应作为生产前必修项。
3. **公示与权限迁移各留一条窄通道**——`handle_result` 自由文本原样公开；0019 的 purge 会静默删除管理端运行期自定义授权，缺可观测性。

就本期 diff 本身：**APPROVED_WITH_MINOR**；若验收口径是「E-7 全仓裸查清零」，则本报告应读作 **REQUEST_CHANGES**，阻塞项为 D-1/D-2/D-3。
