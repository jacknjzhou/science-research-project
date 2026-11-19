# M1-c 拨款·回单识别·开题开户 — A6/A8/B1 实施计划

**日期**：2026-11-17
**分支**：develop（BASE = 1fe6503，M1-b 已推送 origin）
**规划输入**：docs/reports/2026-11-12-conow-alignment-roadmap.md（M1-c = A6 拨款、A8 回单识别、B1 开题开户，跨域联动）
**侦查方式**：lead 现场取证（DDL/契约/models/api/路由/policy/前端 mock 全链核对），事实行号见侦查记录；本文所有行号为 11-17 侦查时点快照，实现者以现场为准。

## Goal

打通财务域最后三块跨域闭环：

1. **A6 拨款**：对 G 外协合同做拨款（转拨单/付款单）——创建前合同额预检（check-contract）、创建拨款单、R-FINANCE 审批与付款，付款落 DISBURSEMENT 平行记账分录。验收：一个开放课题从拨款创建到付款单全链走通。
2. **A8 回单识别**：银行回单文本/文件 → OCR 三级回落（复用 M1-a invoice_ocr 范式）→ 自动生成待确认到账单（FIncome 草稿）→ 人工 claim 确认；bank_flow_no 指纹查重沿用 40903。验收：一张回单文本生成待确认到账单，重复回单被拦截。
3. **B1 开题开户**：项目开题后一键开通核算账号——atomic 创建 FBudget + 按 F_SUBJECT 贯通生成预算行。验收：新项目开户完成即有核算账号可记账。

## 现场基线（侦查结论摘要）

- **A6**：DDL F_DISBURSEMENT 已在（design/03 ddl :592-633，七态 status、contract_amount/disbursed_before/remain_contract_amount 三列、compliance_flags、voucher_status）；**契约已有三端点**（POST /disbursements createDisbursement 带 IdempotencyKey、GET pageDisbursements、POST /disbursements/check-contract :1886→DisbursementCheckResult；schema Disbursement :2671 / DisbursementCreateRequest :2689 / DisbursementStatus :2328）；**运行时零实现**（无 model/handler/policy/路由）；seq 前缀 DISB 已登记（00-common.sql :308-330）。运行时另有 FOutward（models.py:235-259，/outwards 已注册 :254-256）是**预算行级**外拨，与合同级拨款并存不互替；F_OUTWARD 无 DDL（见 Ruling R-1）。
- **A8**：F_INCOME DDL 已含 receipt_no/receipt_date/payer_name/payer_bank/bank_flow_no（条件唯一 uk_f_income_bankflow WHERE deleted=0 AND bank_flow_no IS NOT NULL）/claim_status 四态/match_confidence NUMERIC(6,4)；契约 /incomes POST+GET、/incomes/import-bank-flow :821（body={flows:[BankFlowItem]}→BankFlowImportResult{total,autoMatched,doubtful,unclaimed,elapsedMs}）、/incomes/{incomeId}/claim :851、Income schema :2436；**运行时 import_bank_flow（api.py:520-540）与契约漂移**：裸数组入参、返回 {imported,skipped}、legal_entity_id=1 硬编码、AUTO_MATCHED 无写入路径。回单 OCR 无任何现有 artifact。
- **B1**：E 契约无开题/开户路径；「核算账号」最贴近载体 = FBudget（models.py:40-70，mode 预算制/包干制，project_id+legal_entity_id）+ FBudgetLine（:72-101，remaining=planned+adjusted−frozen−used−released）；FSubject（:11-37，applies_to JSON、parent 树）；EProject（project/models.py:5-38，legal_entity_id default 1、total_budget）。
- **复用面**：_post_accounting_entry（api.py:423-480，幂等五元组、42200 借贷平衡、code_of("ACC")）；outward_action 终审段 :840-872（DISBURSEMENT 分录模板 fin 7701/1002、bud 7501/8001）；invoice_ocr 三级回落范式（api.py:1640-1720，HTTP 200 恒定、OCR_FLOOR 0.85、降级骨架+reasons）；create_outward :777-789（read_json→_money→必填→create→ok）；claim_income :484-516（UNCLAIMED→CLAIMED+mgmt_fee+INCOME 分录）；has_role（core/approval.py:15）；mappings.py 无 disbursement/receipt 序列化器（新增）；policy.csv 839 行，outwards 先例 :504-515。
- **基线**：pytest 268 passed（README 三处仍写 267，本期 Task 8 更正）；M1-b 期次已推送 origin（1fe6503）。

## Global Constraints（全任务强制）

1. 所有查询带 tenant_id + deleted=0；跨租户资源一律 40401（CODE_NOT_FOUND 族）。
2. 金额 Decimal 全程（_money 入 / num2 出），Money=string；无效金额串 → 40001，禁止静默归 0。
3. 响应键 camelCase、逐字段对齐契约 schema；分页响应沿用 page_args 先例。
4. 单号 code_of 前缀：拨款 DISB（已登记）、到账 INC（已登记）、分录 ACC（已登记）；不新增前缀。
5. 路由 {int:id} 类型化、静态路径先于动态注册、注册处留注释。
6. pytest 基线 268，TDD 红→绿，测试走真实 POST 集成路径（禁 stub pass-on-broken）；每任务只 stage 明确文件，禁 add -A，禁动 docs/。
7. 契约改动：design/03-科研经费管理-F.openapi.yaml 与 frontend/src/api/schema/03-…yaml 双份 cp 后 cmp 逐字节一致 + safe_load 过。
8. 已裁定事项不重开（见 Preflight Rulings）；歧义取保守解释标 CONCERN 不停等。

## Preflight Rulings（裁定，实现者照办）

- **R-1** F_OUTWARD 无 DDL：本期不补 DDL（运行时自有表，先在代码；M2 做 DDL↔运行时同步专项时统一处理）。
- **R-2** CoNow 拨款五阶段（方案→计划→清单→转拨单→付款单）以 F_DISBURSEMENT.status 单表流转表达：DRAFT(方案)/SUBMITTED(计划)/APPROVED(清单确认)/PAID(付款单)；不新建三张阶段表（契约与 DDL 均单表，M2 需拆表再立期次）。
- **R-3** create_disbursement 落 SUBMITTED（契约无草稿端点；对齐 M1-b settlement 直接落 AUDITING 先例）；DRAFT 枚举保留不产生。
- **R-4** 拨款审批**不实扣 FBudgetLine**（F_DISBURSEMENT 无预算列；合同额余额即闸门，check-contract 承担）。outward 的预算实扣路径不受影响。
- **R-5** action（approve/pay）handler 内 has_role 强制 R-FINANCE，R-ADMIN 不代行（对齐 M1-a loans pay Ruling 8：放款类操作不代行）；非授权 40301。
- **R-6** 回单 OCR 元数据（reasons/warnings/引擎路径）落 FIncome.remark（序列化 JSON 前缀 "ocr:"）；不加新列（F_INCOME 无 ocr_raw_json 列，避免迁移膨胀）。
- **R-7** import-bank-flow 对齐契约：入参 {flows:[...]}、返回 BankFlowImportResult 五键；autoMatched/doubtful 固定 0（规则引擎 M2）；legal_entity_id 维持 1 + 注释留档（认领时点 claim_income 已按项目归口）。
- **R-8** open-account 幂等：项目已有非 CLOSED FBudget → 40901；预算行 = applies_to 包含 "F" 的 ACTIVE FSubject 逐行（amount_planned=0）；无命中科目 → 只建账号不建行；团队组建不在本期（member_ids 由 E 域管理，CONCERN 留档）。
- **R-9** B1 契约补丁落 03-F（funding 域拥有 FBudget），路径 POST /projects/{projectId}/open-account——E 域路由是单数 /project/*，复数 /projects/* 不冲突。
- **R-10** Idempotency-Key header 经 core/idempotency 处理（redis 缺失时静默放行=现状缺陷行为，维持；core/idempotency 修复已列 M2 专项）。

## Review Focus（终审五项）

1. **check-contract 聚合口径**：disbursed_before = Σ FDisbursement.amount ∈ {APPROVED, PAID, VOUCHER_SYNCED}（REJECTED/RETURNED/DRAFT/SUBMITTED 不计）；canDisburse 数学正确；超额时 create 拒绝路径与 check 返回值一致性。
2. **回单 OCR 降级语义**：三级回落 HTTP 200 恒定、降级骨架可创建、reasons 落 remark、bank_flow_no 命中 uk_f_income_bankflow → 40903 拦截、无 flow_no 可创建。
3. **import-bank-flow 三方一致**：契约信封 {flows} ↔ handler ↔ 测试 ↔（如前端发）mock，全按 BankFlowImportResult 五键；旧 {imported,skipped} 断言全部更新。
4. **open-account 幂等与贯通**：重复开户 40901、行生成按 applies_to "F"、FBudget+FBudgetLine 同 atomic、total_approved 快照自洽（total_approved 与 Σlines 不强制相等——行额为 0 占位）。
5. **DISBURSEMENT 分录幂等**：_post_accounting_entry 键 (tenant, "DISBURSEMENT", d.id, period) 与 outward 分录（txn=o.id）并存不冲突；pay 幂等重放不重复落分录。

---

## Task 1: FDisbursement 模型 + 迁移 0004

**Files**：backend-django/apps/funding/models.py（追加 FDisbursement）、backend-django/apps/funding/migrations/0004_fdisbursement.py（新）、backend-django/tests/test_funding_m1c.py（新，模型冒烟）
**Interfaces**：`class FDisbursement(models.Model)`，db_table="f_disbursement"，字段逐列对齐 DDL F_DISBURSEMENT（:592-633）：code CharField(32)、status（七态 default DRAFT）、contract_id BIGINT、outsource_unit_id CharField(256)、project_id BIGINT、legal_entity_id BIGINT、security_level（四态）、phase（预付/进度/尾款 CharField(8)）、amount Decimal(18,2)、approval_chain JSONField default list、invoice_url CharField(512) null、voucher_status（PENDING/SUCCESS/FAILED/MANUAL default PENDING）、contract_amount/disbursed_before/remain_contract_amount Decimal(18,2)（预检快照）、compliance_flags JSONField default list、policy_pack_id CharField(64) null + 基础列（tenant_id/deleted/creator_id/modifier_id/created_at/updated_at/remark，对齐 sibling）。
**Steps**：
1. 读 DDL F_DISBURSEMENT 全列+索引，逐列映射（枚举逐字、注释同步）；条件唯一/条件索引不在 Meta 建（sqlite 测试库限制，应用层保证——M1-b Task 1 先例）。
2. migrations/0004；`makemigrations --check` clean。
3. 模型冒烟测试 ×1（create + 默认值 + db_table 断言）→ 红→绿。
4. 验证：pytest 全绿（268→269）；DDL 本体不改（表已存在），前端 DDL 副本无需同步。
**Commit**：`feat(funding): M1-c FDisbursement 模型与迁移 0004（A6 合同级拨款）`

## Task 2: policy.csv 端点策略放行

**Files**：backend-django/config/casbin/policy.csv、backend-django/tests/test_rbac.py
**Interfaces**：新策略行（keyMatch2 语义）：
- R-FINANCE：/disbursements GET+POST、/disbursements/*/action POST、/disbursements/check-contract POST、/incomes/ocr-receipt POST、/projects/*/open-account POST（约 7 行）
- R-MANAGER：/disbursements GET+POST、/disbursements/check-contract POST、/incomes/ocr-receipt POST、/projects/*/open-account POST（约 5 行）
- R-LEADER：/disbursements GET、/incomes/ocr-receipt POST、/projects/*/open-account POST（约 3 行，对齐 outwards :504-515 先例角色面）
**Steps**：
1. 先跑 casbin key_match2 实测（M1-b Task 2 先例）：裸 POST 不覆盖 /disbursements/*/action 与 /disbursements/check-contract → 显式行；check-contract 是字面静态段注意不被 {id} 通配歧义。
2. 列对齐公式 `"p, "+(role+",").ljust(11)+(path+",").ljust(38)+action`（M1-b 实测公式，含 role 逗号）。
3. test_rbac 追加用例（每角色×端点命中/未命中）→ 红→绿。
4. pytest 全绿。
**Commit**：`feat(rbac): 拨款/回单识别/核算开户端点策略放行（A6/A8/B1）`

## Task 3: A6 拨款后端——三端点 + action 契约补丁

**Files**：backend-django/apps/funding/api.py、backend-django/apps/funding/mappings.py、backend-django/config/api.py、design/03-科研经费管理-F.openapi.yaml、frontend/src/api/schema/03-…yaml（cp 副本）、backend-django/tests/test_funding_m1c.py
**Interfaces**：
- `create_disbursement(request)` POST /disbursements：Idempotency-Key header 经 core/idempotency（R-10）；read_json→_money(amount) 40001；必填集对齐 DisbursementCreateRequest :2689（contractId/outsourceUnitId/projectId/amount/phase）；GContract tenant 校验 40401；预检内联（同 check 逻辑）：amount > remain → 422 RuleRejected（错误码族对齐契约该路径声明，实现者核对契约 422 示例后落码）；创建 status=SUBMITTED（R-3）、code_of("DISB")、快照三列（contract_amount/disbursed_before/remain_contract_amount）；幂等：同 (tenant,contract_id,phase) 已有非 REJECTED/RETURNED 单 → 40901。
- `page_disbursements(request)` GET /disbursements：contractId/projectId/status 过滤 + 分页（对齐 pageIncomes 先例）。
- `check_disbursement_contract(request)` POST /disbursements/check-contract：body {contractId,amount}；disbursed_before=Σ amount ∈ {APPROVED,PAID,VOUCHER_SYNCED}（Review Focus 1）；返回 DisbursementCheckResult 全键（contractAmount/disbursedBefore/remainContractAmount/canDisburse/complianceFlags/ruleHits——flags/hits 本期 []）。
- `disbursement_action(request, id:int)` POST /disbursements/{int:id}/action（**契约补丁新增**）：body {action:"approve"|"pay"}；R-5 强制 R-FINANCE 40301；approve：SUBMITTED→APPROVED，approval_chain JSONB 追加 {userId,action,at}；pay：APPROVED→PAID + paid_at + `_post_accounting_entry(tenant, user, "DISBURSEMENT", d.id, project_id, legal_entity_id, period=当月, fin=[{"subject":"7701","direction":"debit",...},{"subject":"1002","direction":"credit",...}], bud=[{"subject":"7501","direction":"debit"...},{"subject":"8001","direction":"credit"...}])`（模板对齐 outward_action :856-868）；非对应状态 → 40901；pay 幂等重放 40901（分录幂等键兜底 Review Focus 5）。
- mappings：`to_api_disbursement(o)`（Disbursement :2671 全键 camelCase、Money=string）。
- 路由 config/api.py：静态 check-contract、action 依序注册于动态路径之前，注释纪律。
**Steps**：TDD——create 40001/40401/40901/超额 422/check-contract 数学（含 REJECTED 不计）/approve·pay 状态机+40301+分录落库断言/pay 重放幂等。契约补丁：/disbursements/{id}/action + DisbursementActionRequest schema + 双份 cp cmp + safe_load。
**Commit**：`feat(funding): 合同级拨款——预检/创建/审批付款+DISBURSEMENT 分录（A6）`

## Task 4: A8 回单 OCR——三级回落生成到账草稿

**Files**：backend-django/core/receipt_ocr.py（新）、backend-django/apps/funding/api.py、backend-django/config/api.py、design/03 yaml + 副本、backend-django/tests/test_receipt_ocr.py（新）、backend-django/tests/test_funding_m1c.py
**Interfaces**：
- `parse_receipt_text(text) -> (fields: dict, confidence: float, warnings: list[str])`：标签族——付款人（付款人/付款户名）、金额（￥/金额/人民币）、日期（年月日/ISO）、流水号（流水号/交易流水/凭证号）、用途（摘要/用途）；加权置信度合计 1.00（仿 invoice_ocr :15-：number/total 主导、金额自洽无则不罚）；空文本 → ({}, 0.0, ["receipt-text-empty：…"])。结构镜像 core/invoice_ocr.py，**不 import Django**。
- `ocr_receipt(request)` POST /incomes/ocr-receipt（**契约补丁新增**）：body {fileUrl?, text?}；三级回落（LLM prompt 换回单字段→规则→降级），HTTP 200 恒定、OCR_FLOOR=0.85（≥0.85 可创建，<0.85 创建 claim_status=UNCLAIMED 且 match_confidence=conf——均创建，置信度仅记录）；识别 bank_flow_no → 查重 (tenant,flow_no,deleted=0) 命中 → **40903**（R-6/Review Focus 2，对齐 uk_f_income_bankflow）；未识别 → 不带 flow_no 创建；创建 FIncome（claim_status=UNCLAIMED、match_confidence=conf、code_of("INC")、receipt_no/receipt_date/payer_name/purpose_text 回填）；OCR reasons/warnings 落 remark（"ocr:"+JSON，R-6）。
- 契约补丁：POST /incomes/ocr-receipt（IncomeOcrRequest required []）+ IncomeOcrResponse = Income allOf + ocrWarnings: [string]（镜像 InvoiceOcrResponse :2939 结构）；双份 cp cmp + safe_load。
**Steps**：TDD——parser 标签族/空文本/置信度边界；handler 降级 HTTP 200、40903 拦截、无 flow_no 创建、remark 审计、claim_income 后续确认联通（复用 :484 先例）。
**Commit**：`feat(funding): 银行回单 OCR——三级回落生成到账草稿+流水号 40903 查重（A8/F-15）`

## Task 5: A8 import-bank-flow 契约对齐

**Files**：backend-django/apps/funding/api.py、backend-django/tests/test_funding_m1c.py（及旧测试断言更新）
**Interfaces**：重写 import_bank_flow（api.py:520-540）：入参 {"flows":[{bankFlowNo,amount,...}]}（BankFlowItem required [bankFlowNo,amount]）；逐条：金额 _money 无效 → 40001 整体拒绝（事务回滚，先例优先）；(tenant,flow_no,deleted=0) 幂等 skip；新建 claim_status=UNCLAIMED；返回 BankFlowImportResult{total,autoMatched:0,doubtful:0,unclaimed:实际新建数,elapsedMs}（R-7）；legal_entity_id=1 维持+注释。
**Steps**：TDD——信封/五键计数/幂等 skip/无效金额 40001/旧断言全部更新（Review Focus 3）。
**Commit**：`feat(funding): import-bank-flow 对齐契约信封与 BankFlowImportResult（A8）`

## Task 6: B1 开题开户

**Files**：backend-django/apps/funding/api.py、backend-django/config/api.py、design/03 yaml + 副本、backend-django/tests/test_funding_m1c.py
**Interfaces**：
- `open_project_account(request, project_id:int)` POST /projects/{int:project_id}/open-account（**契约补丁新增**）：EProject tenant 校验 40401（import apps.project.models）；已有非 CLOSED FBudget(project_id) → 40901（R-8）；atomic：FBudget.create(mode="预算制"、total_approved=project.total_budget or Decimal("0.00")、legal_entity_id=project.legal_entity_id or 1、status 对齐 create_budget :230 先例落法)；行 = FSubject(tenant, deleted=0, status=ACTIVE, applies_to 含 "F") 逐行 FBudgetLine(amount_planned=0，subject_id 贯通)；无命中 → 仅建账号；返回 OpenAccountResult{budgetId, budgetCode, lines:[{id, subjectId, subjectName}]}（新 schema）。
- 契约补丁 03-F：POST /projects/{projectId}/open-account + OpenAccountResult；路由 {int:project_id} 类型化；双份 cp cmp。
**Steps**：TDD——40401/40901 幂等/行生成（applies_to 命中与空命中）/total_approved 快照/租户隔离/重复调用不重复建行（Review Focus 4）。
**Commit**：`feat(funding): 项目一键开通核算账号——FBudget+科目行贯通（B1）`

## Task 7: 前端——拨款/回单/开户三视图

**Files**：frontend/src/views/FundingDisburseView.vue（新）、frontend/src/views/FundingIncomeView.vue（新，若无既有 incomes 页面；实现者先勘测 router/views，若有则并入）、既有项目视图加「开通核算账号」入口、frontend/src/router、frontend/src/App.vue（nav）、frontend/src/api/mock/overrides/auth.ts（PAGE_GRANTS+ROLE_CAPS 镜像 Task 2 policy）、frontend/src/api/schema/03-…yaml（Task 3/4/6 已 cp）
**Interfaces**：
- FundingDisburseView：列表（contractId/status 过滤）+ 新建抽屉（先调 check-contract 展示预检面板再提交）+ approve/pay 操作列（仅 R-FINANCE 显示，40301 时按钮隐藏）。
- FundingIncomeView：到账列表（claimStatus 过滤）+ 回单识别（text 粘贴/文件 URL → /incomes/ocr-receipt → 成功刷新 + ocrWarnings 展示）+ import-bank-flow（flows JSON 粘贴）+ claim 操作（对齐契约 CONFIRM/MANUAL/DOUBTFUL）。
- 开户入口：项目列表/详情「开通核算账号」按钮 → POST open-account → 成功提示 budgetCode；40901 幂等提示已开通。
- router meta.roles 对齐 Task 2 矩阵；mock ROLE_CAPS/PAGE_GRANTS 逐行镜像 policy.csv；契约 schema 副本已由后端任务同步。
**Steps**：实现 → vue-tsc 0 errors → pytest 后端零漂移 → （可选）smoke 脚本仿 task-m1b-smoke.mjs。
**Commit**：`feat(fe): 拨款管理/到账认领与回单识别/核算开户——契约驱动 mock 对齐 M1-c`

## Task 8: seed 演示数据 + README 收口

**Files**：backend-django/management/commands/seed_demo.py（或现有 seed 位置）、README.md、backend-django/tests/test_seed_demo_idempotent.py（不动，跑绿即可）
**Interfaces**：追加 M1-c 段（幂等 key 均按业务唯一键）：1 条 GContract（横向/外协 ACTIVE amount=300000 挂既有演示项目）+ 1 条 FDisbursement（SUBMITTED→由 seed 直接落 APPROVED，amount=80000，快照三列自洽）+ 1 条 FIncome（UNCLAIMED、bank_flow_no=DEMO 流水、match_confidence=null）+ 1 条 B1 演示（新建开放课题 EProject 或复用既有项目 seed 直接造 FBudget+applies_to "F" 科目行——不经 handler，保持 seed 直写先例）；code 经 code_of 回填（DISB/INC/BUD）；README 三处计数 → 实测 N。
**Steps**：单进程文件库幂等两遍（M1-b 踩坑：test settings sqlite :memory: 两进程隔离，禁 manage.py migrate+seed 两进程）；pass2 全零；pytest 全绿；vue-tsc 0。
**Commit**：`chore(seed+readme): M1-c 演示数据（拨款/回单/开户） + 测试数更新为实测 N`

## 终审

全分支 review package（BASE 1fe6503 → HEAD）→ 独立评审（Review Focus 五项 + Global Constraints + 跨任务集成缝隙：check-contract↔create 口径同源、OCR→claim 链、open-account 与 create_budget 并存、DISBURSEMENT 分录与 outward 分录共存）→ 修复循环 → finishing-a-development-branch（推送 develop）。

---

## 计划自审（writing-plans 五项）

1. **[是否从所有对话获取了所有信息？]** 侦查三轮取证（b37/b43-b45）覆盖 DDL/契约/models/api/路由/policy/mappings/前端 mock；实现者另有 brief 现场复核兜底。
2. **[是否完全准确？]** 行号系 11-17 快照；Task 指令均写「以现场为准」，brief 抽取时复核。
3. **[是否有所有模糊之处都已用裁定解决？]** 10 条 Ruling 覆盖：F_OUTWARD 无 DDL、五阶段单表化、create 落 SUBMITTED、不实扣预算行、R-FINANCE 强制、remark 审计、import 计数口径、开户幂等与行口径、契约补丁落位、Idempotency 缺陷行为维持。
4. **[是否写了验证步骤？]** 每任务 Steps 含 TDD 红→绿与全量 pytest；契约任务含 cp cmp + safe_load；Task 8 含幂等两遍；终审含 Review Focus 五项。
5. **[每个 task 的理由是什么？]** T1 表结构→T2 权限→T3/T4/T5/T6 四个垂直切片（各自可独立评审）→T7 前端消费全部新端点→T8 演示数据与文档收口；顺序保证每个任务只依赖已完成先例。

## 执行交接

- 执行模式：**Subagent-driven**（SDD）——workspace `.superpowers/sdd/2026-11-17-m1c-disbursement-receipt-opening/`，ledger（progress.md）+ task-brief 抽取 + 实现/评审双代理循环 + 终审，同 M1-a/M1-b 流程。
- 本计划经用户批准后开工；批准方式以用户回复为准（「子智能体驱动」即 SDD 启动）。
