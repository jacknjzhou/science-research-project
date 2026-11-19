# M1-a 开票管理 + 借款管理 + 差旅费用标准 实施计划

> For agentic workers: REQUIRED SUB-SKILL: Use the **subagent-driven-development** skill to execute this plan (each task = one subagent), or **executing-plans** if running inline.

**日期**: 2026-11-12 · **来源**: docs/reports/2026-11-12-conow-alignment-roadmap.md v1.0 → M1 里程碑 M1-a（A1 开票 / A2 借款 / A3 差旅标准，对齐 CoNow P91/P93/P98/P99）

---

## Goal

为经费域 F 补齐三块 CoNow 对齐能力，全部落在 funding 域内叠加（不动既有表结构语义，只增量加表/加列）：

1. **A1 开票管理**：发票 CRUD + 报销单绑定 + OCR 录入（把前端已调用的 `/invoices/ocr` 从契约 stub 变成真实现）。
2. **A2 借款管理**：借款单全生命周期（填单→提交冻结预算→审批→付款→报销冲销/退款结清），事前关联冻结预算，对齐 CoNow P99「出差→借款→审批」。
3. **A3 差旅费用标准**：员工类别×城市类别二维标准配置 + 报销提交时超标提示（warn-only，对齐 CoNow P98「超标提示/自动流转」）。

完成判据：后端 pytest 全绿（基线 191 → 新增约 35+ 用例）；`design/03-*` 契约三件套更新且与 `frontend/src/api/schema/` 副本一致；前端 typecheck 通过、ExpenseView 的 OCR 调用接通真端点；README 测试数更新为实测值。

## Architecture

- **后端**：Django 5 + django-ninja 单体（backend-django），funding 域文件内叠加：`apps/funding/models.py` 加 3 model，`apps/funding/api.py` 加 ~19 个 endpoint 函数，`apps/funding/mappings.py` 加 3 个 `to_api_*`。路由集中在 `config/api.py`（`api.get/post(...)(funding_api.fn)`）。迁移 0002 一次性增量。
- **AI/OCR**：沿用「AI 仅建议、永不直写业务库」纪律。OCR 解析器放 `core/invoice_ocr.py`（纯规则，text→字段），funding `/invoices/ocr` 优先 `core.llm.chat_json`（`settings.LLM_BASE_URL` 已配时），失败/未配回落规则解析，两者皆不可用降级 HTTP 200 + `confidence:0` 骨架发票（status=DRAFT，人工补录）。svc_ai 增加 `/ai/invoice/ocr` 独立网关端点复用同一解析器（svc_ai 与 funding 不互相 HTTP 调用，与 `ai_invoice_review` 现状一致）。
- **预算联动**：借款复用报销的冻结语义——`FBudgetLine.remaining`（planned+adjusted−frozen−used−released）+ `select_for_update` + 不足 `40902 CODE_CONFLICT_REF`；付款时 frozen→used 结转。
- **前端**：Vue3.4 + TS，无新依赖；契约驱动 mock 自动覆盖新端点（schema 同步后生效），必要时补 curated override。新 LoanView.vue，ExpenseView.vue 加发票面板，FundingConfigView.vue 加差旅标准 tab。

## Tech Stack

- backend-django/.venv（uv 直装：django django-ninja pytest pytest-django fakeredis casbin redis psycopg pyjwt bcrypt pyyaml openpyxl fastapi httpx）
- 测试：`cd backend-django && .venv/bin/python -m pytest tests -q`（**必须在该目录运行**；基线 191 passed）
- 前端：frontend/，验证 = `npm run typecheck`（vue-tsc --noEmit，无 vitest）

## Spec

### 数据模型（migration 0002，全部增量，不改动既有列）

**FInvoice**（db_table=`f_invoice`，对齐 design/03 DDL 既有 F_INVOICE 表定义）：
`id BigAuto / code Char(64) null（INV-年-序） / tenant_id BigInt / status Char(32) default DRAFT（DRAFT/OCR_DONE/CHECKED/BOUND/VOID） / deleted SmallInt default 0 / creator_id BigInt / modifier_id null / created_at auto / updated_at auto / number Char(64) null（发票号码）/ invoice_code Char(32) null（发票代码）/ invoice_type Char(16) default ELECTRONIC（GENERAL/SPECIAL/ELECTRONIC/ITINERARY）/ seller_name/seller_tax_id/buyer_name/buyer_tax_id Char null / amount_excl_tax/tax_amount/total_amount Decimal(18,2) default 0 / issue_date Date null / ocr_confidence Decimal(6,4) null / ocr_raw_json JSON null / check_result Char(16) default PENDING（PASS/FAIL/PENDING）/ is_duplicated Bool default False / expense_id BigInt null / remark TextField null`

**FLoan**（db_table=`f_loan`，新建，DDL 追加到 design/03）：
`id / code Char(64) null（LOAN-年-序）/ tenant_id / status Char(32) default DRAFT（DRAFT/SUBMITTED/APPROVED/REJECTED/RETURNED/PAID/CLOSED）/ deleted / creator_id / modifier_id / created_at / updated_at / remark / project_id BigInt / budget_line_id BigInt null / legal_entity_id BigInt / applicant_user_id BigInt / amount Decimal(18,2) / reason TextField null / write_off_amount Decimal(18,2) default 0 / refunded_amount Decimal(18,2) default 0 / submitted_at/frozen_at/paid_at DateTime null`
状态机：DRAFT →(submit) SUBMITTED →(approve) APPROVED｜REJECTED｜RETURNED →(pay) PAID →(write-off 或 refund 补齐) CLOSED。

**FTravelStandard**（db_table=`f_travel_standard`，新建，DDL 追加）：
`id / tenant_id / name Char(64) / staff_category Char(32)（员工类别，如 院领导/中层管理/普通员工/外聘专家）/ city_tier Char(32)（城市类别，如 一类/二类/三类 或城市名）/ accommodation_cap/meals_cap/transport_cap Decimal(18,2) / effective_from Date / effective_to Date null / status Char(16) default ACTIVE（ACTIVE/DISABLED）/ deleted / creator_id / created_at / updated_at / remark`
唯一性：同 (tenant_id, staff_category, city_tier) 仅一条 ACTIVE（应用层校验 40901）。

**FExpense 加列**：`related_loan_id BigInt null`（关联借款，冲销溯源）、`travel_over_limit Bool default False`、`travel_staff_category Char(32) null`、`travel_city_tier Char(32) null`（差旅匹配元数据，随填单提交）。

### 端点（全部挂 tags=["funding"]，auth=ark_auth，注册进 config/api.py funding 段；**静态路径必须先于 {id} 动态路径注册**，避免 `[^/]+` 吞噬 → 405）

发票 A1：
- `POST /invoices` — 手工新建。必填 total_amount>0、number；status=DRAFT；code=code_of("INV", id)；`is_duplicated` = 同租户存在其他非 VOID 且 (number, total_amount, issue_date) 全等的发票（标记不拦截，报销提交时才由指纹 40903 硬拦）。
- `GET /invoices?expenseId=&status=&page=&size=` — page_args 分页，deleted=0。
- `GET /invoices/{id}` / `PUT /invoices/{id}` — 仅 DRAFT/OCR_DONE 可改（BOUND/CHECKED/VOID → 40901）。
- `POST /invoices/{id}/void` — BOUND 状态 → 40901；其余 → VOID。
- `POST /invoices/{id}/bind` body {expenseId} — 发票须 DRAFT/OCR_DONE/CHECKED；expense 存在且未 PAID；事务内 expense.invoice_ids（JSON list）append、invoice.expense_id 设置、status→BOUND。
- `POST /invoices/ocr` body {fileUrl?, text?, expenseContext?} — 见 OCR 流程。

借款 A2：
- `POST /loans`（DRAFT，code_of("LOAN")）/ `GET /loans?status=&projectId=&page=` / `GET /loans/{id}`
- `POST /loans/{id}/submit` — 仿 submit_expense 事务链（apps/funding/api.py:528 模板）：select_for_update 取单（须 DRAFT）→ 预算制+budget_line_id 时 FBudgetLine select_for_update，`line.remaining < amount` → ApiError(409, CODE_CONFLICT_REF, "预算可支余额不足")；否则 `line.amount_frozen += amount` → frozen_at=now → status=SUBMITTED → 审批链 steps（下）→ `_notify_role(tenant, steps[0], "LOAN_APPROVAL", f"待审批：借款单 {code}", body, f"loan/{id}")`。
- `POST /loans/{id}/approve` body {action: approve|reject|return, comment?} — 逐 step 校验 `approval.has_role(roles, step)`，action=approve 走下一步或终审→APPROVED；reject→REJECTED；return→RETURNED（RETURNED 可改后重新 submit，预算行冻结释放：amount_frozen -= amount）。每次 `approval.log(tenant_id, "LOAN", id, step, actor, role, action, comment)`。REJECTED 同样释放冻结。
- `POST /loans/{id}/pay`（R-FINANCE）— SUBMITTED→? 否，仅 APPROVED→PAID：`amount_frozen -= amount; amount_used += amount; paid_at=now`。
- `POST /loans/{id}/write-off` body {expenseId} — expense 须 APPROVED 且 related_loan_id==本单；冲销额 = expense.amount ≤ amount − write_off_amount（超出 40902）；write_off_amount += expense.amount；write_off_amount + refunded_amount == amount → CLOSED。
- `POST /loans/{id}/refund` body {amount} — 仅 PAID；amount ≤ amount − write_off_amount − refunded_amount（超出 40901）；refunded_amount += amount；补齐 → CLOSED。

审批链（与 submit_expense 完全一致）：`steps = ["R-MANAGER", "R-FINANCE"]`，`amount >= 100000` 或 `approval.twostep_enabled()` 时在 R-MANAGER 前插 "R-LEADER"。

差旅标准 A3：
- `GET /travel-standards?status=&page=` / `POST` / `PUT /{id}` / `DELETE /{id}`（软删 deleted=1）。
- `GET /travel-standards/match?staffCategory=&cityTier=&date=`（date 缺省今天）— 命中 ACTIVE 且 effective_from ≤ date ≤ (effective_to 或 ∞)；无命中 → 40401「无匹配差旅标准」。
- **超标检查（warn-only）**：submit_expense 内，`expense_type=="TRAVEL"` 且 travel_staff_category/travel_city_tier 齐备时查 match；命中且 `amount > accommodation_cap + meals_cap + transport_cap` → `e.travel_over_limit=True`，submit 响应与 to_api_expense 增加 `travelOverLimit` 布尔；无匹配/无元数据 → 不拦不禁，仅无标记。**不引入硬拦截**（CoNow P98 语义为提示）。

### OCR 流程（/invoices/ocr）

1. `settings.LLM_BASE_URL` 已配 → `core.llm.chat_json(system, text)`（system 提示只输出 JSON 字段对象：invoiceType/number/invoiceCode/sellerName/sellerTaxId/buyerName/buyerTaxId/amountExclTax/taxAmount/totalAmount/issueDate）→ 失败落步骤 2。
2. `text` 非空 → `core/invoice_ocr.py: parse_invoice_text(text) -> (fields: dict, confidence: float)`（纯规则：增值税发票正则抽 号码/代码/日期/金额/税额/购销方名称与税号；金额自洽校验 |total−(excl+tax)|≤0.01，通过加 confidence，否则 reasons 记「金额自洽校验未通过」）。
3. 两者皆不可用（无 LLM、无 text，仅 fileUrl）→ 降级：HTTP 200 返回骨架 Invoice `{status:"DRAFT", ocr_confidence:0, ocr_raw_json:{"reasons":["ocr-engine-unavailable"]}, check_result:"PENDING", ...空字段}`，remark 提示人工补录 —— 对齐 AI 降级契约（HTTP 200 + 显式低置信 + reasons，不 5xx）。
4. 解析成功且 confidence ≥ 0.85 → status=OCR_DONE，否则 DRAFT；`is_duplicated` 同手工新建规则；响应体 = Invoice + `ocrWarnings: string[]`。
5. svc_ai 增加 `POST /ai/invoice/ocr` req {fileUrl?, text?} → `{fields, confidence, warnings, reasons[]}`：内部直接调 `core/invoice_ocr.py`（无 text → `{fields:{}, confidence:0, reasons:["ocr-engine-unavailable"]}` HTTP 200）。**AI 产出仅建议，不写业务库**（svc_ai 不 import Django models）。

### Casbin（config/casbin/policy.csv，行格式与现文件逐空格对齐）

- GET×4 角色（R-STAFF/R-MANAGER/R-LEADER/R-FINANCE）：`/api/v1/invoices`、`/api/v1/invoices/*`、`/api/v1/loans`、`/api/v1/loans/*`、`/api/v1/travel-standards`、`/api/v1/travel-standards/*`
- POST：R-MANAGER + R-FINANCE → `/api/v1/invoices`、`/api/v1/invoices/*`（bind/void/ocr 是 POST 子路径）、`/api/v1/loans`、`/api/v1/loans/*`
- PUT：R-FINANCE + R-MANAGER → `/api/v1/invoices/*`、`/api/v1/travel-standards/*`；POST `/api/v1/travel-standards` 两角色；DELETE `/api/v1/travel-standards/*` R-FINANCE
- 决策说明：写权限对齐 expenses 现状（R-STAFF 只读；如需放开员工提交借款，后续单独改策略，本计划不扩）。

### 契约同步（唯一真源 + 副本，两处逐字节一致）

- `design/03-科研经费管理-F.openapi.yaml`：新增 Invoice/Loan/TravelStandard schema 与 13 条路径（/invoices、/invoices/{id}、/invoices/{id}/bind、/invoices/{id}/void、/invoices/ocr【已有 :880，补全描述】、/loans、/loans/{id}、/loans/{id}/submit、/loans/{id}/approve、/loans/{id}/pay、/loans/{id}/write-off、/loans/{id}/refund、/travel-standards、/travel-standards/{id}、/travel-standards/match）。
- `design/03-科研经费管理-F.ddl.sql`：追加 F_LOAN、F_TRAVEL_STANDARD 两表（F_INVOICE 已存在不动）。
- `design/03-科研经费管理-F.detail.md`：读现有最大功能编号后顺延，新增「借款管理」「差旅费用标准」两个功能块，并在 F-08 发票OCR 块补 CRUD 端点引用。
- 完成后 `cp design/03-科研经费管理-F.openapi.yaml frontend/src/api/schema/` 同步副本（mock 生成器自动覆盖新端点）。

### Global Constraints（跨任务红线）

1. 响应一律 `core/httpx.ok(request, data)` / `ApiError(status, code, msg)`；错误码沿用：40001 参数、40401 不存在、40901 冲突、40902 预算余额不足、40903 指纹查重。
2. 金额 Decimal(18,2)，出参一律 `mappings.num2()`；时间出参 `fmt_ts()`（RFC3339）；新 code 走 `code_of("INV"|"LOAN", id)` → `f"{prefix}-{yyyy}-{id:06d}"`。
3. 所有查询带 `tenant_id` + `deleted=0`；写操作事务包裹；预算行更新必须 `select_for_update`。
4. AI 永不直写业务库：OCR/LLM 产出仅作为建议字段落入发票草稿，confidence<0.85 必须 DRAFT 人工确认。
5. 金额、冻结、释放计算不得引入浮点（Decimal 运算）。
6. 既有 191 测试不得回归；`fingerprint_hash` 唯一约束与 40903 行为不动。
7. 前端不新增 npm 依赖；UI 沿用 ExpenseView/FundingConfigView 既有模式（api/list + toNum + 现有样式类）。
8. 迁移只增不改不删；生成后肉眼检查 0002 文件再提交。
9. 提交信息风格：`feat(funding): 中文标题——细节`（对齐 git log 既有风格）；每任务一 commit。
10. 契约三件套改完必须 cp 同步到 frontend/src/api/schema/（双份契约是已知债务，本计划内保持一致）。

## Review Focus

- **预算冻结/释放正确性**：submit/approve-reject/pay/refund 各路径对 `amount_frozen/amount_used` 的增减是否收支相抵；并发下 select_for_update 是否覆盖所有余额变更点。
- **40903 回归**：发票 is_duplicated 逻辑不得影响 FExpense 指纹查重既有路径。
- **审批链一致性**：借款 steps 与 submit_expense 的两步/两级规则逐行对照（≥100000 + APPROVAL_TWOSTEP 双条件）。
- **OCR 降级契约形状**：无 LLM 无 text 时必须 HTTP 200 + confidence 0 + reasons，绝不 5xx；svc_ai 端点不得 import Django models。
- **契约 yaml 与前端副本逐字节一致**（diff 验证）；静态路由先于动态路由注册。
- **casbin 行格式**：与现文件空格对齐风格一致，避免 csv 解析歧义。

---

## Task 1: Models + Migration 0002

- **Files**: `backend-django/apps/funding/models.py`（追加 FInvoice/FLoan/FTravelStandard，FExpense 加 4 列）；`backend-django/apps/funding/migrations/0002_*.py`（自动生成）
- **Interfaces**（后续任务依赖的最终签名）:
  - `class FInvoice(models.Model)` — Meta.db_table="f_invoice"
  - `class FLoan(models.Model)` — Meta.db_table="f_loan"；`@property remaining_for_writeoff` = amount − write_off_amount − refunded_amount
  - `class FTravelStandard(models.Model)` — Meta.db_table="f_travel_standard"；`@property total_cap` = accommodation_cap + meals_cap + transport_cap
  - `FExpense.related_loan_id: BigIntegerField(null=True)`、`FExpense.travel_over_limit: BooleanField(default=False)`、`FExpense.travel_staff_category: CharField(32, null=True)`、`FExpense.travel_city_tier: CharField(32, null=True)`
- **Steps**:
  1. 在 models.py 按 Spec 追加三个 model 与 FExpense 四列（风格对齐 FExpense:131：BigAutoField/tenant_id/deleted/creator_id/created_at/updated_at + Meta.db_table + 注释行）。
  2. `cd backend-django && .venv/bin/python manage.py makemigrations funding`（若 settings 需要环境变量，按 .env 缺省补；生成 0002）。
  3. 打开 0002 文件肉眼核对：仅 AddField/CreateModel，无 Alter/Rm。
  4. `cd backend-django && .venv/bin/python -m pytest tests -q` → 191 passed（结构变更不破坏既有测试）。
  5. Commit: `feat(funding): F 域新增 FInvoice/FLoan/FTravelStandard 模型与迁移 0002（A1/A2/A3 表结构）`

## Task 2: Casbin 策略行

- **Files**: `backend-django/config/casbin/policy.csv`（funding 段附近追加 ~20 行）
- **Steps**:
  1. 按 Spec 的 Casbin 小节追加行，格式逐空格对齐现有行（参考 `p, R-FINANCE, /api/v1/expenses,                     POST` 的列对齐）。
  2. `grep -c "invoices\|loans\|travel-standards" config/casbin/policy.csv` 核对行数与角色覆盖。
  3. `cd backend-django && .venv/bin/python -m pytest tests/test_rbac.py -q` 全绿。
  4. Commit: `feat(rbac): 开票/借款/差旅标准端点策略放行（A1-A3 写权限对齐 expenses 现状）`

## Task 3: 契约三件套 + 前端副本

- **Files**: `design/03-科研经费管理-F.openapi.yaml`、`design/03-科研经费管理-F.ddl.sql`、`design/03-科研经费管理-F.detail.md`、`frontend/src/api/schema/03-科研经费管理-F.openapi.yaml`（cp 副本）
- **Steps**:
  1. 读 03-F.detail.md 找最大功能编号（已知 F-08/F-15 存在），新编号顺延。
  2. openapi.yaml 增 3 个 component schema + 13 条路径（Spec 列表；request/response 形状对齐既有 path 的写法：ApiResponse 包裹 + allOf）。
  3. ddl.sql 追加 F_LOAN/F_TRAVEL_STANDARD（列与本计划 Spec 的 model 一一对应，含 uk/索引注释风格对齐既有表）。
  4. detail.md 追加两个功能块（编号顺延、状态 P0、对齐 CoNow P98/P99 引用），F-08 块补「/invoices CRUD + bind/void 见 M1-a」一行。
  5. `cp design/03-科研经费管理-F.openapi.yaml frontend/src/api/schema/03-科研经费管理-F.openapi.yaml`；`diff` 两文件确认逐字节一致。
  6. Commit: `feat(contract): 03-F 契约补 /invoices /loans /travel-standards 三组路径与 DDL/detail（A1-A3）`

## Task 4: mappings 出参函数

- **Files**: `backend-django/apps/funding/mappings.py`
- **Interfaces**:
  - `to_api_invoice(i: FInvoice) -> dict` — id/code/status/number/invoice_code/invoice_type/seller_name/seller_tax_id/buyer_name/buyer_tax_id/amount_excl_tax/tax_amount/total_amount(均 num2)/issue_date(ISO date str)/ocr_confidence(num2)/check_result/is_duplicated/expense_id/created_at(fmt_ts)
  - `to_api_loan(l: FLoan) -> dict` — id/code/status/project_id/budget_line_id/applicant_user_id/amount/write_off_amount/refunded_amount/remaining_for_writeoff(均 num2)/reason/submitted_at/frozen_at/paid_at/created_at(fmt_ts)
  - `to_api_travel_standard(t: FTravelStandard) -> dict` — id/name/staff_category/city_tier/three caps(num2)/effective_from/effective_to/status/remark
- **Steps**:
  1. 仿 `to_api_expense`（mappings.py，num2/fmt_ts 现成）实现三个函数。
  2. `.venv/bin/python -m pytest tests -q` → 191 passed（纯增量）。
  3. Commit: `feat(funding): Invoice/Loan/TravelStandard 契约出参映射（num2/fmt_ts 对齐 PRD 2.6）`

## Task 5: 差旅标准 CRUD + match（TDD）

- **Files**: `backend-django/tests/test_funding_m1a.py`（新建）、`backend-django/apps/funding/api.py`、`backend-django/config/api.py`（注册）
- **Interfaces**:
  - funding_api 函数：`list_travel_standards(request)`、`create_travel_standard(request)`、`update_travel_standard(request, id: int)`、`delete_travel_standard(request, id: int)`、`match_travel_standard(request)`
  - `_match_travel_standard(tenant_id: int, staff_category: str, city_tier: str, on: date) -> FTravelStandard | None`（内部复用函数，Task 7 也用）
- **Steps**:
  1. 新建 tests/test_funding_m1a.py：文件头 docstring「M1-a：差旅标准/开票/借款（A1-A3）」；复用 conftest 的 bearer/seed_auth 与 test_funding_domain 的工厂风格（本文件内定义 `_standard(**kw)`）。
  2. 写失败测试：①R-FINANCE POST /travel-standards 201 语义 ok 且响应含 num2 金额；②同 (staffCategory, cityTier) 重复 ACTIVE → 40901；③PUT 改 cap、DELETE 后列表不可见；④match 命中/过期不命中/无命中 40401。
  3. 跑 `.venv/bin/python -m pytest tests/test_funding_m1a.py -q` 确认全红（404/not found）。
  4. 实现 api.py 五个函数（read_json 校验、40901 应用层唯一、软删、match 按 effective 区间）+ config/api.py 注册（**/travel-standards/match 注册在 /travel-standards/{id} 之前**）。
  5. 测试转绿；`pytest tests -q` 全量 191+新 全绿。
  6. Commit: `feat(funding): 差旅费用标准 CRUD+match——员工类别×城市类别二维配置（A3）`

## Task 6: 发票 CRUD + bind/void + is_duplicated（TDD）

- **Files**: `backend-django/tests/test_funding_m1a.py`、`backend-django/apps/funding/api.py`、`backend-django/config/api.py`
- **Interfaces**:
  - `list_invoices(request)`、`create_invoice(request)`、`get_invoice(request, id: int)`、`update_invoice(request, id: int)`、`void_invoice(request, id: int)`、`bind_invoice(request, id: int)`
  - `_invoice_duplicated(tenant_id: int, number: str, total: Decimal, issue_date, exclude_id: int | None) -> bool`
- **Steps**:
  1. 写失败测试：①手工建票 code=INV-年-序、status=DRAFT；②同号同额同日期第二张 → is_duplicated=true（仍创建）；③PUT 仅 DRAFT/OCR_DONE 可改（BOUND→40901）；④bind 到 expense 后 expense.invoice_ids 含该 id、发票 status=BOUND；⑤void BOUND 票 → 40901、void DRAFT 票 → VOID；⑥列表按 expenseId/status 过滤。
  2. 跑确认全红。
  3. 实现六函数 + `_invoice_duplicated`；注册路由 `/invoices`、`/invoices/{id}`、`/invoices/{id}/bind`、`/invoices/{id}/void`（**本任务不注册 /invoices/ocr**）。
  4. 转绿 + 全量回归。
  5. Commit: `feat(funding): 发票 CRUD+绑定/作废+同号同额同日期重复标记（A1，40903 硬拦不受影响）`

## Task 7: OCR（core 解析器 + funding 端点 + svc_ai 网关）（TDD）

- **Files**: `backend-django/core/invoice_ocr.py`（新建）、`backend-django/tests/test_invoice_ocr.py`（新建）、`backend-django/apps/funding/api.py`、`backend-django/config/api.py`、`backend-django/svc_ai/main.py`、`backend-django/tests/test_svc_ai.py`
- **Interfaces**:
  - `core.invoice_ocr.parse_invoice_text(text: str) -> tuple[dict, float, list[str]]` — (fields, confidence, warnings)；fields 键 camelCase：invoiceType/number/invoiceCode/sellerName/sellerTaxId/buyerName/buyerTaxId/amountExclTax/taxAmount/totalAmount/issueDate(YYYY-MM-DD)
  - funding_api `invoice_ocr(request)` — 注册 `POST /invoices/ocr`（在 /invoices/{id} 之前）
  - svc_ai `POST /ai/invoice/ocr` req `{fileUrl?: str, text?: str}` → `{fields, confidence, warnings, reasons[]}`（HTTP 200 恒定，不 import Django models）
- **Steps**:
  1. 写 core 失败测试：增值税样例文本（含 发票号码/发票代码/开票日期/价税合计/税额/购销方）→ 字段全抽出；金额自洽（total=excl+tax）→ confidence ≥0.85；不一致 → warnings 含「金额自洽」字样且 confidence <0.85；空文本 → ({}，0，warnings)。
  2. 跑红 → 实现 parse_invoice_text（正则规则，无三方依赖）→ 绿。
  3. 写 funding 失败测试：①无 LLM 无 text → HTTP 200，data.status="DRAFT"、ocr_confidence="0"、ocr_raw_json.reasons=["ocr-engine-unavailable"]；②给 text（@override_settings(LLM_BASE_URL=None)）→ 规则解析落库，confidence≥0.85 → status="OCR_DONE"，is_duplicated 生效；③LLM_BASE_URL 配置但 chat_json 抛异常 → 回落规则解析（monkeypatch core.llm.chat_json raise）。
  4. 跑红 → 实现 invoice_ocr（Spec OCR 流程 1-4；chat_json 的 system prompt 按 ai_invoice_review:1027 风格）→ 注册路由 → 绿。
  5. svc_ai/main.py 加 /ai/invoice/ocr（复用 core.invoice_ocr；FastAPI pydantic req model 对齐 ExpenseReviewRequest 风格）+ test_svc_ai.py 用例（有 text 解析 / 无 text 降级）。
  6. 全量 `pytest tests -q` 绿；Commit: `feat(funding): 发票 OCR 真实现——LLM→规则→降级三级回落 + svc_ai /ai/invoice/ocr 网关（A1/F-08）`

## Task 8: submit_expense 差旅超标提示接线（TDD）

- **Files**: `backend-django/tests/test_funding_m1a.py`、`backend-django/apps/funding/api.py`（submit_expense ~528 段 + create_expense payload）、`backend-django/apps/funding/mappings.py`
- **Interfaces**: to_api_expense 增加 `travelOverLimit: bool` 键；create_expense payload 增可选 `travelStaffCategory`/`travelCityTier`/`relatedLoanId`
- **Steps**:
  1. 写失败测试：①TRAVEL 报销 + 匹配标准 + amount>total_cap → 提交成功、响应 travelOverLimit=true、DB travel_over_limit=True；②amount≤cap → false；③无匹配标准 → 提交成功且 false；④非 TRAVEL 类型 → 不查标准；⑤payload 带 relatedLoanId → FExpense.related_loan_id 落库。
  2. 跑红 → 实现：create_expense 存三字段；submit_expense 事务内（预算冻结成功后）TRAVEL 分支调 `_match_travel_standard`；mappings 补键 → 绿 + 全量回归（重点 test_funding_domain 40903/冻结用例不动）。
  3. Commit: `feat(funding): 差旅报销超标提示接线——warn-only travelOverLimit（A3/P98）`

## Task 9: 借款全生命周期（TDD）

- **Files**: `backend-django/tests/test_funding_m1a.py`、`backend-django/apps/funding/api.py`、`backend-django/config/api.py`
- **Interfaces**:
  - `create_loan(request)`、`list_loans(request)`、`get_loan(request, id: int)`、`submit_loan(request, id: int)`、`approve_loan(request, id: int)`、`pay_loan(request, id: int)`、`write_off_loan(request, id: int)`、`refund_loan(request, id: int)`
  - 复用：`core.approval`（twostep_enabled/has_role/log）、`_notify_role`（api.py:111）、`_fingerprint` 不涉及
- **Steps**:
  1. 写失败测试（覆盖 Spec 全状态机）：
     ①create DRAFT + code LOAN-年-序；②submit 预算制冻结（line.amount_frozen 增、40902 分支：remaining 不足）；③approve 链：steps 顺序断言（amount<100000 → [R-MANAGER, R-FINANCE]；≥100000 或 override_settings(APPROVAL_TWOSTEP on) → 前插 R-LEADER）；用错误角色 approve → 40301；reject → REJECTED 且 amount_frozen 回落；return → RETURNED 且冻结释放；④pay：frozen→used 结转、paid_at 落、非 APPROVED → 40901；⑤write-off：expense APPROVED + related_loan_id 匹配 → write_off_amount 累加、补齐 → CLOSED；expense 未 APPROVED → 40901；超 remaining → 40902；⑥refund：超额 40901、补齐 → CLOSED。
  2. 跑红 → 实现八函数（submit 事务链逐行仿 submit_expense:528-566；审批仿 approval_action 既有实现——**先读它再写**）→ 注册路由 → 绿 + 全量回归。
  3. Commit: `feat(funding): 借款全生命周期——提交冻结/两级审批/付款/冲销退款结清（A2/P99）`

## Task 10: seed_demo + README 测试数

- **Files**: `backend-django/apps/sysadmin/management/commands/seed_demo.py`、`README.md`（backend-django/README.md 若测试数在别处则改对应处）
- **Steps**:
  1. seed_demo funding 段（:189 起）追加：2 条 FTravelStandard（一类城市×普通员工、二类×中层）、1 条 FInvoice（DRAFT）、1 条 FLoan（PAID + write_off 部分）——风格对齐既有 `Model.objects.get_or_create(..., defaults={...})`。
  2. 全量 pytest 记录实测总数 N；把 README 里 154/188 旧数改为 N（grep 定位）。
  3. Commit: `chore(seed+readme): M1-a 演示数据 + 测试数更新为实测 N`

## Task 11: 前端（借款视图 + 发票面板 + 差旅标准 tab + 路由导航）

- **Files**: `frontend/src/views/LoanView.vue`（新建）、`frontend/src/views/ExpenseView.vue`（发票面板）、`frontend/src/views/FundingConfigView.vue`（差旅 tab）、`frontend/src/router/index.ts`、导航注册文件（先 grep 侧边栏 nav 定义，与 /expense 模式一致）、`frontend/src/api/mock/overrides/loan.ts`（按需）
- **Steps**:
  1. 读 ExpenseView.vue 全文 + FundingConfigView.vue 全文，确认 OcrInvoice 接口形状与 api/list 用法；若 OcrInvoice 字段与新契约 Invoice 不一致，就地修正为契约字段（camelCase，num2 金额为 string）。
  2. LoanView.vue：列表（api.list /loans）+ 新建对话框（project/budgetLine/amount/reason）+ submit/approve/pay/write-off/refund 操作列 + 状态徽标；样式复用 ExpenseView 既有 class。
  3. ExpenseView.vue 发票面板：报销详情抽 invoice 列表（GET /invoices?expenseId=）+ OCR 按钮（已有 :104 调用，接真响应：成功后刷新列表）+ bind 下拉。
  4. FundingConfigView.vue 加「差旅标准」tab：CRUD 表单（staffCategory/cityTier/三 cap/effective 区间）。
  5. router/index.ts 注册 `/loan`（meta.roles ['R-MANAGER','R-FINANCE']）与差旅 tab 入口（funding-config 页内，无需新路由）；nav 加 LoanView 入口（对齐 /expense 注册模式）。
  6. mock：契约同步后自动生成；跑 dev mock 模式冒烟（任一列表非空即可），不足处补 overrides/loan.ts。
  7. `npm run typecheck` 通过；Commit: `feat(fe): 借款管理视图+发票面板+差旅标准配置——契约驱动 mock 对齐 M1-a`

## Task 12: 全量验收

- **Steps**:
  1. `cd backend-django && .venv/bin/python -m pytest tests -q` 全绿（记录 N）。
  2. `git status` 干净；`git log --oneline` 复核 11 条提交风格统一。
  3. 对照 Review Focus 五项逐条自查（预算收支相抵/40903 回归/审批链/OCR 降级/契约 diff）。
  4. 汇报：新增端点清单、测试 191→N、遗留项（如需放开 R-STAFF 提交借款的策略变更）。
