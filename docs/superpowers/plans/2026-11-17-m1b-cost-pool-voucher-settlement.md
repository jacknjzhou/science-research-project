# M1-b（A4 成本池 / A5 凭证同步 / A7 结算单）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通财务核算闭环——凭证同步（下发/回调/报销状态回写）、平行记账分录生成与查询、项目全成本核算（直接+间接分摊）、项目决算（汇总/审批/结余处理）。

**Architecture:** 全部落在 apps/funding 单域内（同 M1-a 模式）：4 个新 Django 模型对应 design/03 已有 DDL；契约 8 条路径+5 schema 已在 yaml 声明，仅缺 POST /cost-pools/calculate（本计划补契约）；分录生成为「事件挂钩」式——在既有 pay/claim/outward-PAID 事务内调用 `_post_accounting_entry` 服务函数，幂等键 (tenant, source_txn_type, source_txn_id, period) 由 DB 唯一索引兜底。

**Tech Stack:** Django 6 ninja + PostgreSQL 15（JSONB 列用 django.db.models.JSONField；tests 用 sqlite :memory:，JSONField 兼容）。

**Spec:** docs/reports/2026-11-12-conow-alignment-roadmap.md :67（M1-b 范围）+ design/03-科研经费管理-F.detail.md :384-417（4.5 平行记账规则、4.7 全成本公式）+ design/03-科研经费管理-F.openapi.yaml :1642-2040（路径）/:2585-2760（schema）。

## Global Constraints

- 租户隔离：所有查询必须带 `tenant_id=d.tenant_id, deleted=0`（domain_from(request) 取 d）。
- 金额一律 Decimal + `_d2()` 入库、`num2()` 出参（Money=string camelCase）；金额无效串 40001（`CODE_BAD_REQUEST`），禁止静默归 0（M2 待办不复刻）。
- 响应键 camelCase（对齐契约）；`ok()` 信封默认 200。
- 状态机只按本文档列出的迁移写守卫，未列状态一律 409 `CODE_CONFLICT`。
- 不改 models/migrations/契约/docs 之外的文件；`git add` 只加明确路径，禁 `add -A`。
- 测试真实走 POST 集成路径（client.post），断言到 DB 行；金额断言用字符串 "8000.00" 形态。
- 迁移命名延续：`python manage.py makemigrations funding`（依赖 0002）；提交前 `makemigrations --check --dry-run` 必须 clean。
- 单号前缀：SET（结算）/ CPL（成本池）/ ACC（分录），用 `code_of(prefix, id)`（mappings.py:56）创建后回填；同步在 design/03-...-F.ddl.sql 尾部备注区登记一行（同 M1-a INV/LOAN 先例，ddl.sql:709 注释区，不动 00-common.sql）。
- 路由注册纪律：静态段先于 `{int:id}` 动态段；动态段必须 ninja 类型化 `{int:id}`；组内顺序注释一行。
- pytest 基线 **237 passed**；每任务结束全量绿。

## Review Focus

1. **凭证回调幂等与伪造**：同一 expenseId 二次回调（已 SUCCESS 再来 SUCCESS/FAILED）不得重复回写/回滚报销状态；回调无 ark_auth 之外的令牌校验按契约 description「系统间回调」仅校验存在性——期望：二次回调返回 200 幂等不产生第二次状态翻转。（Task 3 测试②）
2. **平行记账幂等**：同一 (source_txn_type, source_txn_id, period) 二次触发（如 pay 重放/幂等 200）不得产生第二条分录——期望：update_or_create 语义，回既有 id。（Task 4 测试③）
3. **借贷平衡**：fin_entry_json 的 Σ借=∑贷 由服务函数构造保证；若将来手工构造不平分录须落 SUSPENSE——期望：Task 4 服务函数对传入分录做平衡断言，不平 raise 500 前置校验（ApiError 422 "42200"）。（Task 4 测试④）
4. **决算汇总口径**：income_total=Σ FIncome CLAIMED；expense_total=Σ FExpense (PAID, VOUCHER_SYNCED)；remaining=income−expense，三者同事务快照落库，审批后不可再重算——期望：REJECTED→DRAFT 可重新 create 覆盖汇总（uk_settle_project 1:1 用 update_or_create）。（Task 6 测试①③）
5. **成本池期间唯一**：同 (tenant, project, period) 重复计算须覆盖（update_or_create）而非新建第二行（uk_costpool_period）；LOCKED 状态期间重算须 409——期望：Task 5 测试②⑤。（Task 5）

---

### Task 1: 4 模型 + 迁移 + DDL 前缀备注

**Files:**
- Modify: `backend-django/apps/funding/models.py`（文件尾追加 4 类）
- Create: `backend-django/apps/funding/migrations/0003_<auto>.py`（makemigrations 生成）
- Modify: `design/03-科研经费管理-F.ddl.sql`（尾部注释区 +1 行前缀登记）
- Modify: `frontend/src/api/schema/03-科研经费管理-F.ddl.sql`（cp 同步）
- Test: `backend-django/tests/test_funding_m1b.py`（新文件，本任务只放模型冒烟）

**Interfaces:**
- Produces: `FCostPool`、`FAccountingEntry`、`FSettlement`、`FVoucherSync`（字段=下方步骤 3 清单，全部 `models.Model` + 既有基类风格：无抽象基类，手写 tenant_id/deleted/creator_id/modifier_id/created_at/updated_at 与 0002 三模型同款）。

- [ ] **Step 1: 写失败测试** `tests/test_funding_m1b.py`：

```python
import pytest
from apps.funding.models import FCostPool, FAccountingEntry, FSettlement, FVoucherSync

@pytest.mark.django_db
def test_m1b_models_crud_smoke():
    cp = FCostPool.objects.create(tenant_id=1, creator_id=1, project_id=1,
        legal_entity_id=1, period="202611", direct_cost="100.00", full_cost="120.00")
    assert cp.status == "DRAFT" and str(cp.direct_cost) == "100.00"
    ae = FAccountingEntry.objects.create(tenant_id=1, creator_id=1, source_txn_id=cp.id,
        source_txn_type="EXPENSE", legal_entity_id=1, period="202611",
        fin_entry_json={"lines": []}, bud_entry_json={"lines": []})
    assert ae.reconcile_status == "UNRECONCILED" and ae.posted_finance is False
    vs = FVoucherSync.objects.create(tenant_id=1, creator_id=1, expense_id=1, finance_system="YONYOU")
    assert vs.sync_status == "PENDING" and vs.retry_count == 0
    st = FSettlement.objects.create(tenant_id=1, creator_id=1, project_id=1, legal_entity_id=1)
    assert st.status == "DRAFT" and st.treatment == "结转"
```

- [ ] **Step 2: 跑红** `pytest tests/test_funding_m1b.py -q` → ImportError/ImportError 级失败。
- [ ] **Step 3: 按 DDL 逐列建模型**（models.py 尾追加，列名 snake_case 对应 DDL）：
  - `FCostPool`: code CHAR64、status(默认 DRAFT, choices DRAFT/CALCULATED/LOCKED/REVERSED)、project_id、legal_entity_id、period CHAR8、direct_cost NUMERIC(18,2) default 0、indirect_alloc_json JSONField null、full_cost NUMERIC(18,2) default 0、basis_rule_id/policy_pack_id BIGINT null + remark；Meta indexes: (tenant_id,status)、project_id。
  - `FAccountingEntry`: code、status(DRAFT/POSTED/SUSPENSE/REVERSED)、source_txn_id、source_txn_type(choices EXPENSE/INCOME/DISBURSEMENT/DEPRECIATION/INDIRECT)、project_id null、legal_entity_id、period CHAR8、fin_entry_json/bud_entry_json JSONField null、posted_finance/posted_budget BooleanField default False、reconcile_status(默认 UNRECONCILED, choices BALANCED/UNRECONCILED/SUSPENSE)、voucher_sync_id/policy_pack_id null + remark；Meta indexes: (tenant_id,status)、(tenant_id,reconcile_status)、project_id。
  - `FSettlement`: code、status(DRAFT/SUBMITTED/AUDITING/APPROVED/REJECTED)、project_id、legal_entity_id、closing_date DateField null、income_total/expense_total/remaining NUMERIC(18,2) default 0、treatment(默认 "结转", choices 结转/收回/留用)、audit_report_url CHAR512 null、approved_by null、approved_at null、score_detail JSONField null + remark；Meta indexes: (tenant_id,status)、project_id。
  - `FVoucherSync`: code、status(默认 PENDING, choices PENDING/SYNCING/SUCCESS/FAILED/MANUAL)、expense_id、finance_system(choices YONYOU/KINGDEE/INSPIRE)、voucher_no CHAR64 null、sync_status(默认 PENDING, choices PENDING/SUCCESS/FAILED)、retry_count SmallIntegerField default 0、payload_json/callback_json JSONField null、sync_at DateTimeField null、error_msg TextField null + remark；Meta indexes: (tenant_id,status)、voucher_no。应用层唯一约束 (tenant, expense, deleted=0) 在 Task 3 handler 用 get-or-create 保证（sqlite 测试库不支持条件唯一索引）。
- [ ] **Step 4: 跑绿** `pytest tests/test_funding_m1b.py -q` + `makemigrations --check --dry-run` 生成 0003 后须 clean。
- [ ] **Step 5: DDL 尾注 + 提交**：design/03 ddl 尾部注释区加一行「M1-b 单号前缀 SET/CPL/ACC 需在 00-common.sql seq_prefix_registry 补登记（owner=F，v1.2）」；cp 到前端副本；`makemigrations --check` clean + 全量 237+1 绿。提交：
  `feat(funding): M1-b 四模型 FCostPool/FAccountingEntry/FSettlement/FVoucherSync 与迁移 0003（A4/A5/A7 表结构）`

### Task 2: policy.csv 策略行

**Files:**
- Modify: `backend-django/config/casbin/policy.csv`（F 块尾追加，对齐列公式 `"p, "+role.ljust(11)+(path+",").ljust(38)+action`）
- Test: `backend-django/tests/test_rbac.py`（追加用例）

**Interfaces:**
- Produces: 11 行策略——vouchers/sync POST、vouchers/sync-callback POST（R-FINANCE）；settlements POST、settlements/* GET、settlements/*/approve POST（R-FINANCE 全部，approve 另授 R-LEADER）；cost-pools GET、cost-pools/* GET、cost-pools/calculate POST（R-MANAGER GET+POST、R-FINANCE GET+POST、R-LEADER GET）；accounting-entries GET、accounting-entries/* GET（R-MANAGER/R-FINANCE/R-LEADER GET）。裸路径+/* 成对（keyMatch2 铁律）。

- [ ] **Step 1: 写失败测试**（仿 test_rbac.py 既有形态）：断言 11 行 (role,path,action) 在 policy.csv 中存在且成对。
- [ ] **Step 2: 跑红** → **Step 3: 追加 11 行**（R-FINANCE 7 行、R-MANAGER 4 行 GET×3+cost-pools POST、R-LEADER 3 行 GET）→ **Step 4: 跑绿** `pytest tests/test_rbac.py -q`。
- [ ] **Step 5: 提交** `feat(rbac): 凭证同步/决算/成本池/平行记账端点策略放行（A4/A5/A7）`

### Task 3: 凭证同步 push + callback + 报销状态回写

**Files:**
- Modify: `backend-django/apps/funding/api.py`（追加 push_voucher、voucher_callback + `_voucher_sync_of` helper）
- Modify: `backend-django/config/api.py`（注册 2 路由，组注释「静态段无动态冲突」）
- Test: `backend-django/tests/test_funding_m1b.py`

**Interfaces:**
- Consumes: FVoucherSync（Task 1）、FExpense.status 可写 "VOUCHER_SYNCED"（models.py:135 注释约定）、`ok()`/`domain_from`/`read_json`/`ApiError`。
- Produces: `push_voucher(request)`、`voucher_callback(request)`；`_voucher_sync_of(tenant_id, expense_id) -> FVoucherSync|None`（Task 5 复用查 voucher_sync_id）。

语义（契约 :1642-1697 + VoucherSync/VoucherCallbackRequest schema）：
- **pushVoucher** POST /vouchers/sync：body `{expenseId, financeSystem?}`；expenseId 缺→40001；报销单不存在/跨租户→40401；已有非 MANUAL 记录→返回既有记录（幂等重推，200）；否则创建 FVoucherSync(status=SYNCING, financeSystem 缺省 "YONYOU", payload_json={expense 摘要}) 并返回 VoucherSync 契约键（id/expenseId/financeSystem/voucherNo null/syncStatus/retryCount/errorMsg null/syncAt null）。**不做真实外部调用**（M2 接财务网关），落 payload 即视为受理。
- **voucherCallback** POST /vouchers/sync-callback：body `{expenseId, result, voucherNo?, financeSystem?, detail?}`；无记录→40401；记录已 SUCCESS→200 幂等返回不重复翻转；result=SUCCESS→sync_status=SUCCESS、voucher_no 回填、sync_at=now、payload 记 callback_json，且同事务把 expense.status: PAID→VOUCHER_SYNCED（其余状态不动）；result=FAILED→sync_status=FAILED、retry_count+1、error_msg=detail 摘要、retry_count>3→status=MANUAL（报销状态不动）。

- [ ] **Step 1: 写失败测试**：①push 新建返回 syncStatus=SYNCING+payload 含 expenseId ②push 幂等重推返回同 id ③callback SUCCESS→DB 行 sync_status=SUCCESS+voucher_no+expense.status=VOUCHER_SYNCED ④callback 二次 SUCCESS 幂等（expense.status 不变仍 VOUCHER_SYNCED）⑤callback FAILED×4→retry_count=4+status=MANUAL。
- [ ] **Step 2: 跑红** → **Step 3: 实现**（pay 后的报销 fixture 复用 test_funding_m1a.py 的 `_expense_paid` 风格 helper，本文件内重建）→ **Step 4: 跑绿** 全量。
- [ ] **Step 5: 提交** `feat(funding): 凭证同步下发/回调——状态机+报销 VOUCHER_SYNCED 回写（A5/F-11）`

### Task 4: 平行记账分录服务 + 事件挂钩

**Files:**
- Modify: `backend-django/apps/funding/api.py`（追加 `_post_accounting_entry` 服务函数；在 pay_expense、claim 动作（FIncome 认领 handler）、outward 终审 PAID 三处事务内挂钩）
- Test: `backend-django/tests/test_funding_m1b.py`

**Interfaces:**
- Consumes: FAccountingEntry（Task 1）；pay_expense（api.py pay handler，冻结转实扣后）、income claim handler（api.py 认领分支）、outward_action PAID 分支（api.py:708-756 先例）。
- Produces: `_post_accounting_entry(tenant_id, user_id, source_txn_type, source_txn_id, project_id, legal_entity_id, period, fin_lines, bud_lines) -> FAccountingEntry`——幂等（update_or_create on (tenant, type, txn_id, period)）、平衡校验（fin_lines Σdebit==Σcredit 否则 raise ApiError(422,"42200","借贷不平")）、落库后 posted_finance/posted_budget=True、reconcile_status="BALANCED"。

分录模板（detail 4.5 + 政府会计制度简化科目，M2 可配制度包）：
- EXPENSE（pay 时）：fin=[借 5001 业务活动费用 amount / 贷 1002 银行存款 amount]；bud=[借 7201 事业支出 amount / 贷 8001 资金结存 amount]。period=pay 时点 `%Y%m`。
- INCOME（claim 时）：fin=[借 1002 银行存款 / 贷 4601 非同级财政拨款收入]；bud=[借 8001 资金结存 / 贷 8201 预算收入]。period=claim 时点。
- DISBURSEMENT（outward PAID 时）：fin=[借 7701 对外拨付款 / 贷 1002]；bud=[借 7501 对外拨付预算 / 贷 8001]。period=PAID 时点。
- 金额用源单 amount；source_txn_id=源单 id；project/legal_entity 从源单取。

- [ ] **Step 1: 写失败测试**：①PAID 一笔报销后出现 EXPENSE 分录，fin_entry_json 两行借贷等额、posted 双 True、BALANCED ②INCOME 认领后出现 INCOME 分录 ③同一报销 pay 幂等重放（再次调用 pay 返回 409）后分录仍 1 条（直接二次调 `_post_accounting_entry` 同参数断言同 id）④构造 fin_lines 借 100/贷 90 → ApiError 42200。
- [ ] **Step 2: 跑红** → **Step 3: 实现服务函数+三处挂钩**（挂钩放各事务内 `approval.log` 旁；income claim handler 名以现场为准 grep "CLAIMED"）→ **Step 4: 跑绿**（全量 237+N；test_funding_domain 22 不得回归）。
- [ ] **Step 5: 提交** `feat(funding): 平行记账双分录生成——pay/claim/outward-PAID 事件挂钩+幂等键（F-21/4.5）`

### Task 5: 分录与成本池查询端点 + 成本池计算

**Files:**
- Modify: `backend-django/apps/funding/api.py`（追加 page_accounting_entries、get_accounting_entry、page_cost_pools、get_cost_pool、calculate_cost_pool + `_calc_cost_pool` helper）
- Modify: `backend-django/config/api.py`（注册 5 路由：cost-pools 组静态 calculate 先于 {int:projectId}）
- Modify: `design/03-科研经费管理-F.openapi.yaml` + `frontend/src/api/schema/03-...yaml`（契约补丁：POST /cost-pools/calculate，operationId calculateCostPool，body required [projectId, period]，schema CostPoolCalcRequest；详见步骤 3）
- Test: `backend-django/tests/test_funding_m1b.py`

**Interfaces:**
- Consumes: `_post_accounting_entry`（Task 4）、`_sum_expense`（api.py:837）、FCostPool/FAccountingEntry（Task 1）、`page_args`（既有分页 helper）。
- Produces: `page_accounting_entries(request)`（query: page/size/sourceTxnType/reconcileStatus/projectId）、`get_accounting_entry(request, id)`（40401）、`page_cost_pools(request)`（projectId/period/status 过滤）、`get_cost_pool(request, project_id)`（query period 必填，无行→40401）、`calculate_cost_pool(request)`。

语义：
- **page/get 分录**（契约 :1731/:1789）：按租户+deleted 过滤；响应键=AccountingEntry schema（camelCase：sourceTxnId/sourceTxnType/finEntry/budEntry/postedFinance/postedBudget/reconcileStatus/voucherSyncId/policyPackId；voucherSyncId 用 `_voucher_sync_of` 按 source_txn_id=expense_id 查）。
- **calculateCostPool**（契约补丁 + detail 4.7）：body `{projectId, period}`；period 格式 YYYYMM（regex ^\d{6}$ 否则 40001）；direct_cost=Σ FExpense (PAID, VOUCHER_SYNCED) + Σ FOutward PAID（period 按源单时点归属，M1-b 简化：不看单据时点、整项目累计，period 仅作池标识）；indirect 项取该租户 FIndirectFee 同 period indirect_amount 记一条 {type:"管理费", basis:"indirect_fee:<id>", amount}；full_cost=direct+Σindirect；update_or_create on (tenant, project, period)——**已有行 status=LOCKED→40901 拒绝重算**；新建 status=CALCULATED；响应=CostPool schema 全键（indirectAlloc 数组、code=code_of("CPL")）。
- **pageCostPools/getCostPool**（契约 :1909/:1940）：getCostPool period query 必填缺→40001、无行→40401；响应含 status 键（schema CostPool 未含 status，补契约 schema 一并加 status 行，枚举同 DDL）。

- [ ] **Step 1: 写失败测试**：①PAID 报销+计提后 calculate→fullCost=direct+indirect、indirectAlloc 数组 1 项、status CALCULATED、code CPL-前缀 ②同 period 重算覆盖同 id（幂等）③LOCKED 后重算 40901 ④getCostPool 缺 period 40001、无行 40401 ⑤pageAccountingEntries sourceTxnType=EXPENSE 过滤命中 1 条+voucherSyncId null ⑥getAccountingEntry 404。
- [ ] **Step 2: 跑红** → **Step 3: 实现+契约补丁**（yaml：/cost-pools/calculate 路径块插在 /cost-pools 之前（静态先注册）、CostPoolCalcRequest schema 插在 CostPool 前、CostPool 加 status 键；cp 副本 diff 空；safe_load 双过）→ **Step 4: 跑绿**+`test_contract_full_coverage` 绿。
- [ ] **Step 5: 提交** `feat(funding): 全成本核算计算/查询+平行记账查询端点——契约补 /cost-pools/calculate（A4/F-20/F-21）`

### Task 6: 结算单 create/get/approve

**Files:**
- Modify: `backend-django/apps/funding/api.py`（追加 create_settlement、get_settlement、approve_settlement + `_settlement_totals` helper）
- Modify: `backend-django/config/api.py`（注册 3 路由：getSettlement {int:projectId} 与 approve {int:settlementId}——两动态段无同名前缀冲突，按契约顺序注册并注释）
- Test: `backend-django/tests/test_funding_m1b.py`

**Interfaces:**
- Consumes: FSettlement（Task 1）、`_sum_claimed_income`/`_sum_expense`（api.py:830/:837）、FOutward PAID 累计（不计入 expense_total——外拨是对外转出非项目支出，detail 4.6 口径；报告中单列 disbursementTotal 备查键）。
- Produces: `create_settlement(request)`、`get_settlement(request, project_id)`、`approve_settlement(request, settlement_id)`。

语义（契约 :1745-1817 + Settlement schema）：
- **createSettlement** POST /settlements：body `{projectId, closingDate}` 必填（缺→40001）；项目不存在→40401；已有行（uk_settle_project 1:1）：status∈(APPROVED)→40901 不可重算，其余（DRAFT/SUBMITTED/AUDITING/REJECTED）→覆盖更新汇总；汇总快照 income_total/expense_total/remaining 落库+score_detail={明细 JSON}；status=DRAFT；code=code_of("SET")；响应=Settlement schema（camelCase 全键）。
- **getSettlement** GET /settlements/{projectId}：无行→40401。
- **approveSettlement** POST /settlements/{settlementId}/approve：body `{action, treatment?, comment?}`；action∉(APPROVE,REJECT)→40001；仅 AUDITING→可审（SUBMITTED→AUDITING 由谁触发？——**裁定：create 直接落 AUDITING**（简化：决算发起即进入审计复核，无独立 SUBMIT 端点，契约也未定义），DRAFT 仅作为 REJECTED 后重开态）；APPROVE→status=APPROVED+approved_by/approved_at+treatment 缺省沿用现值（传入则覆盖，枚举外 40001）；REJECT→status=REJECTED；非 AUDITING 状态→40901。

- [ ] **Step 1: 写失败测试**：①create（1 income 1000 CLAIMED+1 expense 300 PAID）→incomeTotal "1000.00"/expenseTotal "300.00"/remaining "700.00"/status AUDITING ②重复 create 覆盖同 id+汇总更新 ③APPROVED 后再 create→40901 ④approve APPROVE+treatment 留用→status APPROVED+approvedBy 非 null ⑤REJECT→REJECTED 后再 create 可重开 ⑥DRAFT 下 approve→40901。
- [ ] **Step 2: 跑红** → **Step 3: 实现**（审批记 approval.log(tenant,"SETTLEMENT",id,1,user,role,action,comment)）→ **Step 4: 跑绿**。
- [ ] **Step 5: 提交** `feat(funding): 项目决算发起/查询/审批——汇总快照+结余处理（A7/F-13）`

### Task 7: 前端三面板 + mock 契约对齐

**Files:**
- Create: `frontend/src/views/FundingSettleView.vue`（决算：发起表单 projectId+closingDate、汇总卡、审批按钮 APPROVE/REJECT+treatment 下拉）
- Create: `frontend/src/views/FundingCostPoolView.vue`（成本池：period 输入+计算按钮+direct/indirect/full 卡+indirectAlloc 表）
- Modify: `frontend/src/views/ExpenseView.vue`（详情区加「凭证同步」块：push 按钮+syncStatus 徽标，读 /vouchers/sync 返回）
- Modify: `frontend/src/router/index.ts`（/funding/settle、/funding/cost-pool 两路由，meta.roles ['R-MANAGER','R-FINANCE','R-LEADER']）
- Modify: `frontend/src/App.vue`（nav 两项）
- Modify: `frontend/src/api/mock/overrides/auth.ts`（PAGE_GRANTS 两行+ROLE_CAPS 对应 caps）
- Test: `frontend/scripts/task-m1b-smoke.mjs`（仿 task11-smoke.mjs，HTTP 探针即可）

**Interfaces:**
- Consumes: 后端 8+1 端点（Task 3/5/6）；契约 schema 副本（camelCase、Money=string）。
- Produces: 可手工演示的三面板；mock 模式下 auth.can 全通过。

- [ ] **Step 1: 写组件**（响应键严格 camelCase：closingDate/incomeTotal/expenseTotal/remaining/treatment/auditReportUrl/status；directCost/indirectAlloc/fullCost/basisRuleId；syncStatus/retryCount/voucherNo）。
- [ ] **Step 2: 验证** `npx vue-tsc --noEmit` 0 errors + 后端全量绿；mock 冒烟脚本 exit 0。
- [ ] **Step 3: 提交** `feat(fe): 决算/成本池视图+报销凭证同步面板——契约驱动对齐 M1-b`

### Task 8: seed 演示数据 + README + 验收

**Files:**
- Modify: `backend-django/apps/sysadmin/management/commands/seed_demo.py`（追加 1 FVoucherSync SUCCESS+2 FAccountingEntry EXPENSE/INCOME+1 FCostPool CALCULATED+1 FSettlement APPROVED，幂等键与 M1-a 同款 get_or_create）
- Modify: `README.md`（测试计数→实测 N，三处）
- Test: `backend-django/tests/test_seed_demo_idempotent.py` 不回归

- [ ] **Step 1: seed 追加**（金额与 M1-a seed 台账自洽：BUDL-DEMO-001 amount_used 不再变动——分录不动预算行）→ **Step 2: 幂等两遍**（单进程脚本，文件库 /tmp，pass2 全零）→ **Step 3: 全量 pytest 实测 N+README 更新三处**（grep 154/188/237 旧值）→ **Step 4: 提交** `chore(seed+readme): M1-b 演示数据 + 测试数更新为实测 N`

## Self-Review 结论（写计划时已过一遍）

1. **Spec 覆盖**：契约 8 路径→Task 3（2）/Task 5（5 含补丁）/Task 6（3 中 get/approve/create）✓；detail 4.5→Task 4、4.7→Task 5 ✓；roadmap M1-b 三特性→A4=Task 5、A5=Task 3+4、A7=Task 6 ✓。
2. **已裁定项**（实现者勿重开）：create 直接落 AUDITING（无 SUBMIT 端点，Task 6）；成本池 direct 整项目累计不看单据时点（Task 5，M2 再精细化）；凭证推送不接真实财务系统（Task 3，M2）；DEPRECIATION/INDIRECT 分录类型 M1-b 不生成（A-12 资产折旧属后续期次）；分录科目模板硬编码（M2 制度包化）。
3. **类型一致**：`_post_accounting_entry(tenant_id, user_id, source_txn_type, source_txn_id, project_id, legal_entity_id, period, fin_lines, bud_lines)` 全计划唯一签名；`_voucher_sync_of(tenant_id, expense_id)` Task 3 定义 Task 5 消费 ✓。
4. **Review Focus 5 项**各归 Task 3①③⑤ / Task 4②④ / Task 6①③ / Task 5②③⑤ ✓。
