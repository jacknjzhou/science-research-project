# E-7 第二轮独立终审报告（r2）

- 仓库/分支：`/Users/jacky/works/science-research-project`，`develop`
- BASE：`1b1b55f`（E-8 部署收口）
- HEAD：`bd55718`（本轮修复）
- 待审范围：`git diff 1b1b55f..bd55718`，5 个 commit：
  `e2d297a`(activity) → `91830e1`(confsec) → `d317245`(funding) → `a17db11`(transform) → `bd55718`(跨域)
- 方法：只读源码 + 独立攻击探针（`/tmp/e7r2probe`，不写入仓库）+ 把四域 `api.py` 回滚到 BASE 跑测试 + 全量回归。
- 唯一写入：本文件。

---

## 0. 结论

**VERDICT: APPROVED_WITH_MINOR**

- **可推送 `develop`：是。** 未发现新的可利用跨租户读写链；`develop...origin/develop [ahead 5]`，5 个 commit 尚未推送。
- **不建议直接上生产。** 两项 Important（R2-I1 存量脏数据静默入账、R2-I2 公开异议通道 PII/状态残留）不影响本次合并，但必须在生产发布前闭环。
- 第一轮 9 条：**7 条已关闭，2 条部分关闭（C4、I5），0 条未关闭**。
- 本轮新增：**Critical 0 / Important 2 / Minor 6**。

> 口径说明：本报告的 Important 指“真实影响、但属存量数据或范围外既有面，生产发布前必须处置”；不阻断 `develop` 合并。若团队规则是 Important 一律 REQUEST_CHANGES，则按团队规则执行；技术事实不变。

---

## 1. 实测数字（本机，2026-11-19）

| 项目 | 命令 | 结果 |
|---|---|---|
| 全量 pytest | `cd backend-django && .venv/bin/python -m pytest -q` | **586 passed, 19 warnings in 46.17s** |
| 迁移检查 | `.venv/bin/python manage.py makemigrations --check --dry-run` | **No changes detected**（仅 PG 连接拒绝的 RuntimeWarning） |
| 契约 diff | `git diff 1b1b55f..bd55718 -- design/ frontend/src/api/schema/` | **0 字节** |
| README 计数 | `grep -n "586" README.md` | 第 **5/29/99** 行均为 586 |
| 测试文件计数 | `pytest --collect-only` | activity **4**、confsec **5**、funding **10**、transform **5**、e7_review_fixes **7** |
| 分支位置 | `git status -sb` | `## develop...origin/develop [ahead 5]` |
| 源码树 | `git status --porcelain apps tests config/casbin` | 空（探针回滚已恢复） |

---

## 2. A 部分：第一轮 9 条逐条复核

### C1 funding 报销链 —— 已关闭（存量残余见 R2-I1）

代码核实：

- `apps/funding/api.py:790-793`：`create_expense` 对 `budget_line_id` 做
  `FBudgetLine.objects.filter(id=line_ref, tenant_id=d.tenant_id, deleted=0).exists()`，否则 404 `预算行不存在`。
- `apps/funding/api.py:859-866`：`submit_expense` 用 `select_for_update().filter(id=..., tenant_id=...)`，`line is None` → 404，冻结不会发生。
- `apps/funding/api.py:925-928`：`_approve_one` 末步实扣的 `update()` 带 `tenant_id`。

攻击链实测（租户 1 令牌，目标租户 2 预算行）：

```text
[C1.create] 404 {'code': 40401, 'message': '预算行不存在'}
[C1.budget.read] 404
[C1.budget.lines] 404
```

- 新链路无法用他租户预算行建单/提交/审批；他租户预算与预算行详情/明细均 404。
- 回归用例：`tests/test_funding_tenant.py::test_cross_tenant_budget_read_and_lines_are_404`、
  `tests/test_e7_review_fixes.py::test_expense_cannot_bind_foreign_budget_line`。
- **残余**：对修复前已存在的跨租户报销单，审批仍返回 200 并把单据置 APPROVED，但预算行 update 命中 0 行（静默 no-op），见 R2-I1。

### C2 funding 外拨链 —— 已关闭

- `apps/funding/api.py:1005-1008`：`create_outward` 的 `budget_line_id` 租户校验，404。
- `apps/funding/api.py:1062-1066`：终审实扣 `FBudgetLine.objects.filter(id=o.budget_line_id, tenant_id=d.tenant_id, ...)`。
- 探针：新单 create 404；对“修复前已存在的外拨单指向他租户预算行”，终审返回
  `409 {'code': 40902, 'message': '预算行余额不足，外拨无法入账'}`，单据保持 `PENDING`，他租户行 `used=0.00`。
  这是 fail-closed，不会静默成功（错误文案可后续优化）。
- 用例：`test_outward_cannot_bind_foreign_budget_line`、`test_funding_tenant.py` 外拨相关断言。

### C3 funding 借款链 —— 已关闭（存量残余见 R2-I1）

- `apps/funding/api.py:2195-2198`：`create_loan` 的 `budget_line_id`（含 `budgetLineId`）租户校验，404。
- `apps/funding/api.py:2247-2251`：`submit_loan` 冻结，`select_for_update + tenant_id`，`line is None` → 404。
- `apps/funding/api.py:2305-2308`：`approve_loan` 驳回/退回释放，带 `tenant_id`。
- `apps/funding/api.py:2338-2341`：`pay_loan` 冻结转实扣，带 `tenant_id`。
- 探针：新单 create 404；存量脏数据 reject/pay 的静默 no-op 见 R2-I1。

### C4 transform 公示异议 —— 部分关闭（跨租户处置已关闭；公开通道残留）

- `apps/transform/api.py:642-649`：`handle_objection` 已改为
  `TPublicity.objects.filter(deal_id=dealId, tenant_id=dom.tenant_id, deleted=0)`。
- 探针：租户 1 的 R-MANAGER 对他租户 dealId 处置 →
  `[C4.handle.foreign] http=404 {'code': 40401, 'message': '公示不存在'}`；对方 deal 仍 `PUBLICIZED`、publicity 仍 `PUBLISHED`。
  **第一轮“跨租户终止交易”攻击链已断。**
- 但公开通道仍有两个面（详见 R2-I2）：
  - `apps/transform/api.py:577-583` `get_publicity` 匿名可读，`to_api_publicity`（`apps/transform/mappings.py:243-256`）原样返回 `objections`，含 `contact`/`submitter`。实测：
    `[Pub.contact] http=200 contact=13800000000`。
  - `apps/transform/api.py:613-637` `submit_objection` 仅按 `deal_id` 取最新公示，**没有 tenant、没有状态、没有公示期校验**，直接 `objection_open=True; status="OBJECTION_PENDING"`。实测对 `status=COMPLETED`、交易 `TERMINATED`、公示期已过 5 天的公示提交：
    `[Pub.submit.after.completed] http=200 pub=OBJECTION_PENDING open=True deal=TERMINATED`；
    对 `TERMINATED` 公示同样返回 `200 {'objection_id': 'OBJ1-1'}`。
- **关于“公示期外不接受异议”回退的取舍**：可接受，但只应视为“本次范围控制”，不应视为问题已解决。
  - 阻塞用例 `tests/test_phase4_transform.py:229-248` 用 `duration_days: 0`（发布即满期），把“期满后仍可提异议”固化成了事实规格；设计 `design/05-科技成果转化-T.detail.md §4.8` 与 OpenAPI 只写公开/匿名通道，未写窗口限制，因此加窗口守卫会改变既有语义，回退合理。
  - 但**状态守卫**（只允许 `PUBLISHED`/`OBJECTION_PENDING` 的公示接收异议）不会破坏该用例（该用例公示状态正是 `PUBLISHED`），可以单独补；同时公开 GET 应脱敏 `contact`。
- 结论：C4 的**跨租户管理动作**已关闭；**公开面**保留为 Important 残余（R2-I2），不计入“未关闭”。

### I1 `TEnterpartner` 查询租户 —— 已关闭

- `apps/transform/api.py:296-301`：`TEnterpartner.objects.filter(id=deal.enterpartner_id, tenant_id=dom.tenant_id, deleted=0)`；`None` → `404 合作企业不存在`。
- 其余入口也已租户化：`apps/transform/api.py:381-384`（信用代码查重）、`:408`（列表）、`:936`（AI 机会）。
- 用例：`tests/test_e7_review_fixes.py::test_deal_rejects_foreign_enterpartner`（BASE 上红，现绿）。
- 说明：`if ep is not None:` 已成为死代码（Minor M6）。

### I2 confsec 审计日志 `tenantId` —— 已关闭

- `apps/confsec/api.py:641-648`：`_sec_log(dom.tenant_id, ...)`，注释明确“忽略 body.tenantId”。
- 用例：`test_sec_log_ignores_body_tenant`：body 传 `tenantId=2`，断言 `XSecLog(tenant_id=2)` 数量不变、租户 1 至少新增 1 条。
- 代码层不存在第二条 body 控制归属的写链；读链 `apps/confsec/api.py:672` 也按 `dom.tenant_id`。

### I3 `delete_subject` 存在性预言机 —— 已关闭

- `apps/funding/api.py:212-228`：先按 `id + tenant_id + deleted=0` 取科目，`None` → 404；再做下级/预算引用检查（均带 tenant），最后软删。
- 探针三种他租户形态全部 404：
  `[I3.parent] 404`、`[I3.leaf] 404`、`[I3.used] 404`；
  本租户父科目仍 409：
  `[I3.own.parent] 409 {'code': 40902, 'message': '存在下级科目，禁止删除'}`。
- 用例：`test_delete_subject_foreign_id_is_opaque_404`（覆盖“他租户父+子”，未覆盖 leaf/used；探针已补证）。

### I4 假绿用例 + 悬空 policy —— 已关闭（DB 残留见 M2）

- `tests/test_transform_tenant.py:43-49` 已删除不存在的 `GET /disclosure/{id}` 断言，改为 `POST /disclosure/{id}/submit`，并写明“无详情路由，GET 断言会是 stub 假绿”。
- 路由核实：`backend-django/config/api.py:648-651` 只有
  `GET /disclosure`、`POST /disclosure`、`POST /disclosure/{id}/submit`、`POST /disclosure/{id}/valuation`；
  无 detail GET，因此删除 `GET /api/v1/disclosure/*` 两行不影响真实路由鉴权。
- `config/casbin/policy.csv:603-609` 仍保留列表/提交/估值行；删除的只是通配 detail 行。
- 残余：`0018` 的 resync 只增不删，旧 DB 中这两行仍可能存在（M2）。

### I5 `/indirect-fees/calculate` policy —— 部分关闭

- 已补：`config/casbin/policy.csv:923-925`
  ```
  p, R-MANAGER, /api/v1/indirect-fees/calculate, POST
  p, R-FINANCE, /api/v1/indirect-fees/calculate, POST
  ```
- 迁移：`apps/sysadmin/migrations/0018_resync_permissions_e7.py` 调用 `sync_permissions_from_csv`，依赖 `0017`。
- 测试：`tests/test_funding_tenant.py::test_indirect_fee_rejects_foreign_project` 的令牌已改为 `FIN = ["R-MANAGER","R-FINANCE"]`；但该用例只断言 `in (400, 404)`，没有断言“有权限”（403 也会被排除，故能间接证明放行），也没有分角色。
- 探针（POST）：
  `[I5.R-MANAGER] 200`、`[I5.R-FINANCE] 200`、`[I5.R-STAFF] 403 无权限`。
- **遗漏**：同一路径还有 `GET /indirect-fees/calculate`（`config/api.py:319-321`，`page_indirect_fees`），设计 `design/03-科研经费管理-F.detail.md:487` 记的是 `POST ... · GET`，但 policy 只补了 POST。实测：
  `R-MANAGER 403`、`R-FINANCE 403`、`R-ADMIN 200`。
  属 fail-closed、无提权风险，但业务角色仍打不开该 GET（M3）。
- 结论：POST 链已关闭；GET 未覆盖，故 I5 记“部分关闭”。

---

## 3. B 部分：漏网扫描

扫描方式：对四域 `api.py` 的 `filter/get/exclude(...id=...)`、`select_for_update()` 全量 grep，再逐个看上下文是否已经过租户化对象派生。

### 3.1 仍“裸 id”但可接受的查询

| file:line | 查询 | 判断 |
|---|---|---|
| `backend-django/apps/activity/api.py:171-172` | 参与人/评审按 `activity_id=id` | 可接受：前面 `_get_activity_or_404(d.tenant_id, id)` |
| `backend-django/apps/activity/api.py:348` | 参与人列表按 `activity_id=id` | 可接受：同上 |
| `backend-django/apps/activity/api.py:369` | `filter(id=pid, activity_id=id).delete()` | 可接受：父活动已租户校验，且二次限定 `activity_id` |
| `backend-django/apps/confsec/api.py:685` | `qs.filter(object_type=..., object_id=...)` | 可接受：`qs` 已由 `XSecLog.objects.filter(tenant_id=...)` 收口 |
| `backend-django/apps/funding/api.py:279,301` | 预算行按 `budget_id` | 可接受：`budget` 先经 `_get_budget_or_404(tenant_id, ...)` |
| `backend-django/apps/funding/api.py:340,378` | `filter(id=line_id, budget_id=bud.id)` | 可接受：`bud.id` 来自租户校验后的预算 |
| `backend-django/apps/funding/api.py:443` | `EProjectCategory.filter(id=p.category_id)` | 可接受：`p` 是按 `tenant_id` 取的项目；分类是全局字典 |
| `backend-django/apps/funding/api.py:891,1094,1280` | `Model.objects.get(id=id)` 回读 | 可接受：同一事务内 `id` 已经过租户校验并更新 |
| `backend-django/apps/funding/api.py:907` | `FExpenseApproval.filter(id=step.id)` | 可接受：`step` 由租户校验后的报销单派生 |
| `backend-django/apps/funding/api.py:1075` | `EProject.filter(id=o.project_id, deleted=0)` | **有风险但非读取泄露**：外拨记账取项目法人；`o.project_id` 可能是他租户 id（M1） |
| `backend-django/apps/funding/api.py:2313,2342,2379,2386,2410,2417` | `FLoan.filter(id=loan.id)` 更新 | 可接受：`loan` 已经 `tenant_id` 取到；`id` 同源 |
| `backend-django/apps/funding/api.py:1511,1685,1834` | 列表按 `project_id` / `exclude(id=...)` | 可接受：基础 qs 已 `tenant_id` 过滤 |
| `backend-django/apps/transform/api.py:580,615` | `TPublicity.filter(deal_id=dealId)` | **按设计公开**；但带来 R2-I2，不能算“安全裸查” |
| `backend-django/apps/transform/api.py:986` | `exclude(id=deal.id)` | 可接受：基础 qs 已租户过滤，仅排除自身 |

### 3.2 真正的“未校验 body 引用”（不是 `filter(id=)` 裸查，但同类）

| file:line | 字段 | 实测/影响 |
|---|---|---|
| `backend-django/apps/funding/api.py:762-800` | `create_expense` 的 `project_id`、`legal_entity_id` | 未校验租户；写入后可指向他租户项目（不泄露数据） |
| `backend-django/apps/funding/api.py:996-1010` | `create_outward` 的 `project_id`、`budget_id` | 探针：`[Minor.outward.foreign_project] 200`；终审 `:1075` 会读他租户项目的 `legal_entity_id` 入账 |
| `backend-django/apps/funding/api.py:2177-2204` | `create_loan` 的 `project_id` | 探针：`[Minor.loan.foreign_project] 200`；仅用于 `legal_entity` fallback（取不到则 1） |
| `backend-django/apps/funding/api.py:274-277` | `create_budget` 的 `subject_id` | 未校验科目租户 |
| `backend-django/apps/transform/api.py:148-170` | `create_disclosure` 的 `output_id`、`project_id` | 未校验；可写入他租户引用 |

结论：**FBudgetLine 层没有真正的裸查漏网**；预算行的创建/冻结/实扣/释放/结转全部带 `tenant_id`（或经租户校验的预算派生）。剩余是“创建时引用他租户 id”的数据卫生问题（M1），不是跨租户读/写漏洞。

---

## 4. Critical / Important / Minor

### Critical

无。

### Important

#### R2-I1 存量跨租户预算引用在审批/放款时“静默成功”

- 位置：
  - `backend-django/apps/funding/api.py:925-928`（报销末步实扣 `update()` 不检查行数）
  - `backend-django/apps/funding/api.py:930-950`（即使预算 update 0 行，仍记会计凭证）
  - `backend-django/apps/funding/api.py:952-953`（单据照常置 APPROVED/REJECTED）
  - `backend-django/apps/funding/api.py:2305-2308`（借款驳回释放）
  - `backend-django/apps/funding/api.py:2338-2341`（借款放款结转）
- 复现（探针直接构造“修复前已存在”的脏数据）：

```text
[C1.legacy.approve] http=200 expense=APPROVED line2 frozen=500.00 used=0.00
[C3.legacy.reject]  http=200 loan=REJECTED line2 frozen=400.00 released=0.00
[C3.legacy.pay]     http=200 loan=PAID     line2 frozen=400.00 used=0.00
```

- 影响：漏洞窗口期（修复前）已创建的跨租户报销/借款，修复后仍能被审批/驳回/放款；单据状态正常推进，但受害租户的预算不扣减/不释放，形成账实不一致和永久冻结。**新数据无法再进入该状态**（create/submit 已 404），所以不是新攻击面，是存量数据处置问题。
- 修复建议（二选一或都做）：
  1. 代码层：把三处 `update()` 改为接收返回值，`n == 0` 时在 `transaction.atomic()` 内 `raise ApiError(409, CODE_CONFLICT, "预算行归属异常，拒绝记账")`，让单据状态回滚；不要静默继续。
  2. 数据层：发布前跑一次性审计（管理命令或迁移），扫描
     `FExpense/FLoan/FOutward` 的 `budget_line_id` 与 `FBudgetLine.tenant_id` 不一致的记录，输出清单并人工修正/解冻；确认结果为 0 再上线。
- 备注：外拨终审已 fail-closed（409），不需要同样的状态回滚修复。

#### R2-I2 公开异议通道：匿名读取联系人 + 无状态守卫

- 位置：
  - `backend-django/apps/transform/api.py:577-583`（公开 GET）
  - `backend-django/apps/transform/mappings.py:243-256`（`to_api_publicity` 原样输出 `objections`）
  - `backend-django/apps/transform/api.py:613-637`（公开 POST，无 tenant/状态/窗口校验）
- 复现：

```text
[Pub.contact] http=200 contact=13800000000
[Pub.submit.after.completed] http=200 pub=OBJECTION_PENDING open=True deal=TERMINATED
[C4.public.terminated] http=200 {'objection_id': 'OBJ1-1'} status_after=OBJECTION_PENDING open=True n=1
```

- 影响：
  1. 匿名访问者可读取异议人手机号（PII）；设计写的是“脱敏对外摘要”，与实现矛盾。
  2. 任何人可对已 COMPLETED/TERMINATED 的公示继续提异议，把公示状态改回 `OBJECTION_PENDING`、`objection_open=True`，并无限追加异议（存储/审计污染、阻断后续执行语义）。
- 说明：这是既有公开通道行为，不是 E-7 引入；但 C4 第一轮已点到公开 GET，且本次修复只收口了管理动作。
- 修复建议：
  - 公开序列化脱敏：`get_publicity` 使用单独的 public 视图，剥离/掩码 `contact`、`submitter`（管理端仍可看全量）。
  - 状态守卫：`submit_objection` 仅允许 `p.status in ("PUBLISHED", "OBJECTION_PENDING")`；这不会破坏 `test_phase4_transform.py::test_publicity_objection_block_and_release`（该用例公示状态是 `PUBLISHED`）。
  - 公示期守卫可另行评估；若加，需先把上述用例的 `duration_days: 0` 改为有效窗口 + 时间控制，否则会再次“破坏既有用例”。

### Minor

- **M1 创建接口未校验他租户 body 引用**：`apps/funding/api.py:762-800`（project/legal_entity）、`:996-1010`（project/budget）、`:2177-2204`（project）、`:274-277`（subject）、`apps/transform/api.py:148-170`（output/project）。影响是数据卫生/记账维度污染（外拨终审会读他租户项目的法人），不构成跨租户读取。建议统一加 `EProject`/`EOutput`/`FSubject` 的租户存在性校验，404 语义与预算行一致。
- **M2 `0018` 只增不删，旧 policy 行残留**：`apps/sysadmin/permissions.py:24-63` 只 `get_or_create`；`0018_resync_permissions_e7.py` 不会删除 BASE 时代的两行 `GET /api/v1/disclosure/*`。它们对当前不存在路由无影响，但会给未来新增的 detail GET 预授权。建议加一个删除精确行的数据迁移，或让 resync 支持 prune。
- **M3 I5 的 GET 未补 policy**：`config/api.py:319-321` 有 `GET /indirect-fees/calculate`，`policy.csv:923-925` 只有 POST；实测业务角色 403。若该 GET 仍在使用，补 `R-MANAGER`/`R-FINANCE` 的 GET 行；若已废弃，删路由并同步契约。
- **M4 测试覆盖偏窄/断言偏松**：
  - `tests/test_e7_review_fixes.py` 的 C1/C2/C3 只覆盖“建单 404”，没有覆盖“存量脏数据 submit/approve/release/pay 不得静默成功”（R2-I1 正是这条链）。
  - `test_funding_tenant.py:50,71,87` 用 `in (404, 409)`，409 可能掩盖“租户过滤缺失但状态机兜底”；建议确认后收紧为 404。
  - `test_funding_tenant.py:78-90` 末尾断言 `e.status != "PAID"` 是空断言（报销单没有 PAID 状态）。
  - `test_delete_subject_foreign_id_is_opaque_404` 只覆盖父+子形态；建议补 leaf/used。
- **M5 `test_funding_m1a.py` 的改动是语义收敛，不是掩盖回归**：旧用例“建单成功→提交 404”现在变成“建单即 404”，与新的 create 校验一致；但删掉了 submit 时点的悬空行覆盖。建议保留新断言的同时，另加一条直接落库的悬空/他租户行 + 本租户令牌 submit → 404，锁住 R2-I1 涉及的提交路径。
- **M6 死代码/卫生**：`apps/transform/api.py:302-305` 的 `if ep is not None:` 在 404 之后已不可达；工作区仍有与本任务无关的 `docs/.DS_Store`、删除图片、未跟踪 plans/reports 等（未进入 5 个 commit，属既有脏树）。`README` 的“`develop` 已推送”在 `bd55718` 推送前是陈旧描述，推送后即真。

---

## 5. 测试真实性（红/绿验证）

### 5.1 方法

在 `backend-django/` 下对四域 `api.py` 做“备份 → `git show 1b1b55f:./apps/<app>/api.py` 覆盖 → 跑测试 → 备份恢复”，不用 `git checkout --`：

```bash
cd backend-django
for a in activity confsec funding transform; do
  cp apps/$a/api.py /tmp/$a.api.py.bak
  git show 1b1b55f:./apps/$a/api.py > apps/$a/api.py
done
.venv/bin/python -m pytest -q tests/test_e7_review_fixes.py
.venv/bin/python -m pytest -q tests/test_activity_tenant.py tests/test_confsec_tenant.py \
  tests/test_funding_tenant.py tests/test_transform_tenant.py
for a in activity confsec funding transform; do cp /tmp/$a.api.py.bak apps/$a/api.py; done
```

### 5.2 结果

| 运行 | 结果 |
|---|---|
| 新文件 7 例 vs BASE 源码 | **7 failed in 3.00s**（7 条全部真红） |
| 四个租户文件 24 例 vs BASE 源码 | **23 failed, 1 passed in 3.22s** |
| 当前源码五文件 31 例 | **31 passed in 3.07s** |
| 全量当前源码 | **586 passed, 19 warnings in 46.17s** |

唯一在 BASE 上仍通过的是 `test_related_loan_and_expense_id_reject_foreign`（该路径在 BASE 已有租户过滤），合理。

### 5.3 用例数与真实性判断

- activity 4 / confsec 5 / funding 10 / transform 5，与第一轮报告一致；新增 7 例。
- 7 例新测试确实覆盖了本轮 4 个 Critical + 3 个 Important 的**入口**，且在 BASE 上全红，非假绿。
- 不足：C1–C3 只覆盖 create，没有覆盖存量数据的 approve/release/pay；I3 只覆盖一种形态；I5 未分角色断言。这不影响“修复对新增数据有效”的结论，但让 R2-I1 这类存量路径缺少回归锁。

---

## 6. 交付卫生

### 6.1 commit 内容

| commit | 文件 | 判断 |
|---|---|---|
| `e2d297a` | README + activity/api.py + test_activity_tenant.py | 仅 activity 域，干净 |
| `91830e1` | README + confsec/api.py + test_confsec_tenant.py | 仅 confsec 域，干净 |
| `d317245` | README + funding/api.py + test_funding_domain.py + test_funding_tenant.py | 仅 funding 域，干净 |
| `a17db11` | README + transform/api.py + test_transform_tenant.py | 仅 transform 域，干净 |
| `bd55718` | README + confsec 4 行 + funding 52 行 + 0018 + transform 12 行 + policy 5 行 + 4 个测试文件 | 跨域修复，均为相关文件 |

未发现夹带无关业务改动。README 在每个 commit 里同步累计测试数，最终 586 与实测一致。

### 6.2 契约与迁移

- `design/` 与 `frontend/src/api/schema/` diff 为 0：本轮没有路由/字段/错误码变更，只有校验语义（404）与 Casbin 策略变化，空 diff 合理。
- 但 `GET /indirect-fees/calculate` 的权限缺口（M3）不属于 OpenAPI 能表达的内容，不能靠“契约 diff 为空”证明权限完整。
- `makemigrations --check --dry-run` 为 No changes，`0018` 已落盘。

### 6.3 `test_funding_m1a.py` 改动判断

**合理，不是掩盖回归。** 旧用例把“悬空 `budget_line_id`”拖到 submit 才 404；新实现于 create 即 404，属于更早失败的语义收敛，且旧用例的跨租户 submit 覆盖已由 `test_funding_tenant.py` 承担。唯一代价是 submit 时点的悬空行路径失去显式用例，建议按 M5 补一条存量数据的回归。

### 6.4 可推送性

- `develop` 领先 `origin/develop` 5 个 commit，工作区源码干净。
- **可以推送 `develop`**：不引入新的跨租户可利用链，586 全绿，迁移无 drift。
- **生产发布门**：先完成 R2-I1 的存量审计/行数守卫与 R2-I2 的公开脱敏/状态守卫；否则不要把本提交直接当生产版本。

---

## 7. 最终结论

```text
VERDICT: APPROVED_WITH_MINOR

E-7 目标（activity/confsec/funding/transform 的 body/path id 跨租户隔离）：
- 新增链路：已达成，未发现可用跨租户读写。
- 第一轮 9 条：7 关闭、2 部分（C4 公开面、I5 GET）。
- 可推送 develop：是。
- 可直接发布生产：否，先闭环 R2-I1 / R2-I2。
```
