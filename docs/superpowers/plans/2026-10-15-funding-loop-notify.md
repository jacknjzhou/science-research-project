# 经费闭环(F)真实化 + 通知中心 + 大屏真数据 + LLM 审核 · 实现计划

**规格真源**：`docs/superpowers/specs/2026-10-15-funding-loop-notify-design.md`
**分支**：全程 `develop`，逐任务 commit，逐文件 `git add`，禁止推送。
**sqlc 生成命令**：`cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate`
**测试**：`cd backend-go && ARK_TEST_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable go test -p 1 -count=1 ./...`（-p 1 串行化：多包共享测试库，并行会互踩 fixture）；前端 `cd frontend && npx vue-tsc --noEmit && npm run build`
**TDD 铁律**：每任务先写失败测试（RED）→ 最少实现（GREEN）→ 重构 → commit。无 DB 环境时 DB 测试自动 SKIP（沿用 poolForTest 约定），纯逻辑测必须全绿。

---

## Phase 0 · 基线（T0）
- 确认 docker PG 可用：`docker compose up -d postgres`；`ARK_TEST_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable`
- `cd backend-go && go build ./... && go test ./...` 全绿基线（SKIP 除外）。
- 记录基线输出。

## Phase 1 · 契约追加 + sqlc 基建（T1、T2）

### T1 契约补丁
- 修改 `design/03-科研经费管理-F.openapi.yaml`：追加 `GET /funding/execution`、`GET /funding/warnings`（响应 schema 按 spec §3.1）。
- `cp design/03-科研经费管理-F.openapi.yaml frontend/src/api/schema/`（字节同步铁律）。
- 验证：`diff` 两份一致；openapi yaml 可被后端 Spec 加载（启动无错）。

### T2 sqlc F 基建
- 创建 `backend-go/db/schema/f_schema.sql`：从 `migrations/000001_init.up.sql` 裁剪 F_SUBJECT/F_BUDGET/F_BUDGET_LINE/F_INCOME/F_EXPENSE/F_EXPENSE_APPROVAL/F_INDIRECT_FEE/F_EXPENSE_APPROVAL（原样语句）+ `E_PROJECT`/`sys_user` 最小列（跨域引用仅作类型来源，不 join 建模）。
- 创建 `backend-go/db/query_f/`：`f_subject.sql`、`f_budget.sql`、`f_income.sql`、`f_expense.sql`、`f_approval.sql`、`f_indirect.sql`、`f_exec.sql`。
- 修改 `backend-go/sqlc.yaml`：加 F 生成块（schema: db/schema/f_schema.sql, queries: db/query_f, out: internal/modules/funding/store, package fstore）。
- 生成 + `store/compile_test.go`（空跑编译断言）。
- 创建 `backend-go/testdata/seed_f.sql`（幂等：先 DELETE 本租户 F 行，再插科目字典 8 类、项目 2 个、预算 1 套 3 行、到款 2 笔 1 待认领、报销 1 单 DRAFT、用户 5 人含 R-FINANCE/R-MANAGER/R-LEADER）。
- 验证：sqlc generate 成功、`go build ./...`。

## Phase 2 · F 域 handler 真实化（T3..T7，每任务一个 commit）

### T3 科目字典 + 预算编制/批复/调整
- 文件：`internal/modules/funding/{routes.go,mapper.go,handler.go,budget.go}`。
- 端点：GET /subjects；POST+GET /budgets；GET /budgets/:id；GET /budgets/:id/lines；POST /budgets/:id/submit|approve|adjust。
- 状态机守卫 + approve 时 total_approved/`approved_by/at` 回填、status→EXECUTING；adjust 生成新 version 行（或原行 delta 累加 + version+1，取简单方案：原行 `amount_adjusted` 累加、`total_adjusted` 重算、version+1、status RE_APPROVED→EXECUTING）。
- 测试：`contract_test.go`（mapper NUMERIC→string 形状）+ `handler_test.go`（建预算→提交→批复→调整 全链路，含非法流转 40901）。

### T4 到款登记/列表/认领/批量导入
- 文件：`internal/modules/funding/income.go`。
- 端点：POST+GET /incomes（分页+claim_status/project_id 过滤，narg 铁律）；POST /incomes/:id/claim（UNCLAIMED 守卫、回填 project_id/claimed_by/at，已认领 40901）；POST /incomes/import-bank-flow（数组批量，bank_flow_no 冲突跳过并返回 {imported, skipped}）。
- 测试：handler_test（登记→认领→重复认领拒绝；导入 3 条含 1 重复 → imported=2 skipped=1）。

### T5 报销填单/查重/提交（冻结 + 审批链）
- 文件：`internal/modules/funding/expense.go`。
- 端点：POST+GET /expenses；GET /expenses/:id（含 approval 步骤列表）；POST /expenses/:id/submit。
- submit 事务：状态守卫 DRAFT→SUBMITTED；指纹查重（非 REJECTED/RETURNED 同 hash → 40903）；预算制冻结（FOR UPDATE 校验 remaining≥amount，不足 40902；frozen+=amount, frozen_at=now）；生成审批链（<10 万 1 步 R-MANAGER，≥10 万 2 步 +R-LEADER）；提交后 `submitted_at`。
- 测试：正常提交冻结断言（balance 接口复核）；余额不足 40902；重复指纹 40903；包干制提交不锁行。

### T6 审批动作 + 余额
- 文件：`internal/modules/funding/approval.go`；GET /budget-lines/:lineId/balance。
- POST /expenses/:id/approval {action: APPROVE|REJECT|RETURN, comment}：当前 PENDING 步校验（角色匹配 R-MANAGER/R-LEADER/R-FINANCE， acted 记录）；中间步 APPROVE→下一步；末步 APPROVE→APPROVED（frozen-=, used+=, paid 留 PAID 动作后续）；REJECT/RETURN→解冻（frozen-=, released+=）。多步未到末步不可跳步（40901）。
- 测试：两步单（10 万+）：第一步批准→状态 HUMAN_REVIEW；第二步批准→APPROVED 且 used+=amount frozen-=amount；驳回→REJECTED 且解冻；越权角色 40301；跳步 40901。

### T7 执行率 + 预警 + 间接费计提
- 文件：`internal/modules/funding/execution.go`。
- GET /funding/execution?project_id=（聚合 F_BUDGET/F_BUDGET_LINE/F_INCOME/F_EXPENSE）；GET /funding/warnings（扫描 + WARN/CRITICAL/DEADLINE_RISK，DEADLINE_RISK 读 E_PROJECT 结题窗口）；POST /indirect-fees/calculate {project_id, rate?}（默认 20%，>30% 拒 40904，同 project 幂等更新）+ GET /indirect-fees?project_id=。
- 测试：seed 场景执行率数值断言（string 精度）；预警分级断言；计提幂等。

## Phase 3 · 通知中心 + LLM + 大屏（T8..T10）

### T8 通知中心
- 创建 `backend-go/migrations/000003_sys_notification.up.sql` + `.down.sql`（对测试库手动 psql 应用）。
- 创建 `backend-go/db/schema/nf_schema.sql`（sys_notification 单表）+ `backend-go/db/query_nf/notification.sql` + sqlc 块（out: internal/modules/notify/store, package nfstore）。
- `internal/modules/notify/{routes.go,handler.go,mapper.go}` + `Notifier` 接口（供 funding 注入）。
- funding 各触达点接线（T4/T5/T6/T7 内 best-effort 调用；无 Notifier 时跳过）。
- 测试：notify handler_test（推送→未读数→已读→read-all）；funding 触达断言（提交报销后审批角色收 1 条）。
- Casbin：policy.csv 追加全角色通知读写行。

### T9 LLM 审核端点
- 创建 `backend-go/internal/platform/llm/client.go` + `client_test.go`（httptest 假 NewAPI：正常 JSON / 超时 / 非 JSON → 降级）。
- `internal/modules/funding/aireview.go`：POST /expense/ai-invoice-review（契约已有）；`funding.NewHandler(pool, notifier, llm)`；llm nil 或不可用 → `{verdict:REVIEW, confidence:0, available:false}`；confidence<0.85 强制 REVIEW。
- config.go 加 LLM 四 env；router.go 注入；docker-compose.yml backend env 加 ARK_LLM_*。
- 测试：fake llm PASS 建议；降级路径；<0.85 强制 REVIEW。

### T10 大屏经费真聚合
- 创建 `backend-go/internal/modules/dataops/{routes.go,handler.go}`：GET /dashboard/funding 真 SQL（fstore 复用查询）。
- router 注册；policy.csv 只读放开。
- 测试：handler_test 聚合数值断言。

## Phase 4 · 前端对接（T11）

### T11 前端
- `frontend/src/views/ExpenseView.vue`：列表接 GET /expenses（分页/状态过滤）；填单 POST /expenses + submit；审批动作 POST approval；执行率条 GET /funding/execution；移除 mock-only 分支保留兜底。
- `frontend/src/App.vue`：铃铛接 GET /notifications/unread-count（60s 轮询）+ 下拉面板 GET /notifications + POST :id/read。
- `frontend/src/views/BigscreenView.vue`：经费总览卡接 GET /dashboard/funding，失败回退现有数据。
- 验证：`npx vue-tsc --noEmit && npm run build`。

## Phase 5 · 收尾验证（T12）
- `cd backend-go && ARK_TEST_DATABASE_URL=... go test -race -count=1 ./...` 全绿。
- 手动 `psql` 应用 000003 到测试库（迁移由后端启动自动跑，测试库手动补）。
- `docker compose up -d --build` 冒烟：healthz → admin 登录 → 建/批预算 → 登记到款 → 认领 → 填报销 → 提交 → 两步审批 → 执行率=used/income 断言 → warnings → notifications → dashboard/funding。
- `curl http://127.0.0.1:8080/` 页面渲染（复用 headless Chrome 冒烟）。
- 汇总报告 + 更新 memory。
