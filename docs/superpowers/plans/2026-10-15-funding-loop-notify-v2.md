# 功能完备化 · 详细实施计划 v2（经费闭环 + 通用底座 + 成果/项目/知产增强）

> **取代** `2026-10-15-funding-loop-notify.md`（v1，Phase 0-5 内容并入本文件）。
> **规格真源**：`docs/superpowers/specs/2026-10-15-funding-loop-notify-design.md`（含 v2 需求蒸馏附录 A-H）。
> **需求来源**：docs/ 下 4 份易普拉格 Word 手册（管理员 179p / 秘书 73p+2020 版 / 人员 71p+21p）、2 份 PDF（南林 2025 / 通用 2013）、14 张竞品功能图 —— 已全部蒸馏入 spec v2 附录。
> **分支**：全程 `develop`，逐任务 commit、逐文件 `git add`，禁止推送。
> **TDD 铁律**：每任务先失败测试（RED）→ 最少实现（GREEN）→ 重构 → commit。DB 测试无环境自动 SKIP。
> **sqlc**：`cd backend-go && /tmp/sqlc generate`（v1.27.0 预编译二进制；如丢失重下 `sqlc_1.27.0_Darwin_arm64`）。
> **测试命令**：`cd backend-go && ARK_TEST_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable go test -count=1 ./...`；前端 `cd frontend && npx vue-tsc --noEmit && npm run build`。

---

## 当前状态（2026-10-15 晚 · 更新）

| 项 | 状态 |
|---|---|
| T0-T7（基建 + F 域闭环） | ✅ 全绿并 commit（e713a10/07ba5ca/ba535a3） |
| T8-T10（通知中心 + LLM + 大屏） | ✅ 全绿并 commit（7a22484/12c1410/ab8a0fc/9fe528c）；docker 端到端冒烟通过：staff 建报销→提交→manager 收 TODO 通知→APPROVE→staff 收结果→已读闭环 |
| T11-T12（前端对接 + 全量验证） | ✅ 已 commit（955a7c9）：App 铃铛轮询+收件箱面板、ExpenseView 真契约（EXECUTING 预算驱动 + snake_case payload）、BigscreenView alerts 适配；vue-tsc+build 全绿；headless Chrome 冒烟 4/4 PASS |
| P4（T13-T15 Excel 底座/外拨结转/科目预警） | ✅ 已 commit（a214a6a，含 T13-T15 漏交 store 生成物补提） |
| P5（T16-T18 成果治理） | ✅ 已 commit（a214a6a） |
| P6（T19 两级审核 / T20 任务中心） | ✅ 已 commit（ca6df95 / 1cc0d44） |
| P7（T21 分类预警 / T22 PDF 解析） | ✅ 已 commit（f8f1edf；模板渲染遗漏补提 e64cee3） |
| P8（T23 三维监控 / T24 画像真数据） | ✅ 已 commit（a2f1f0d） |
| P9（T25 申报计划+形式审查） | ✅ 已 commit（dc441fc）：时间窗守卫/两级审批/to-project 幂等/auto-stop |
| **T13-T25 全量回归** | ✅ 31+ 包 `-p 1` 全绿（ARK_TEST_DATABASE_URL 测试库，migration 已至 version 12） |

**遗留事项**（后续可另开任务）：
- ~~契约同步：T13-T25 新端点尚未写入 design/*.openapi.yaml~~ ✅ 已完成（f7ee0a6）：7 份契约补齐 40+ 端点，pyyaml 语法 + $ref 校验 ALL PASS。
- T25 CreateApplication 的 sqlc 坑：`COALESCE($4,0)` 会推断成 `Column4 interface{}`，须全命名参数 `sqlc.arg('apply_amount')::numeric`。

**冒烟踩坑沉淀**（冒烟/联调必读）：
- 种子账号：admin/Admin@123456、manager/Manager@123456、staff/Staff@123456。
- POST /budgets、/expenses 均必填 `legal_entity_id`；budget `mode` 枚举为中文 `预算制`/`包干制`；`expense_type` 为英文枚举 EQUIPMENT/MATERIAL/TRAVEL/MEETING/LABOR/EXPERT/OTHER。
- `sys_legal_entity` 种子为空，status 枚举带中文后缀（`ACTIVE=正常`）；冒烟前需插一条法人。
- `uk_budget_project_ver` 唯一：同项目重复建预算 50002，冒烟复用 EXECUTING 预算。
- **列表端点统一返回 `{list,total,page,size}` 分页结构**（/subjects、/budgets/:id/lines、/expenses、/notifications 均如此），前端必须取 `.list`——本轮前端 bug 根因。
- 前端 headless 冒烟脚本：/tmp/fe-smoke.cjs（playwright + chromium-1228 executablePath）。


---

## 历史状态存档（2026-10-15 晚首轮）

| 项 | 状态 |
|---|---|
| T0 基线 | ✅ 全绿 |
| T1 契约追加（/funding/execution、/funding/warnings） | ✅ 已 commit（222082d） |
| T2 sqlc F 基建 | 🟡 代码已写完：f_schema.sql（8 表）、db/query_f/*（7 文件）、sqlc.yaml F 块、fstore 生成、funding 模块 12 文件、`go build` 绿 |
| T2-T3 测试 | 🔴 handler_test/loop_test 红：①seed_f.sql 的 E_PROJECT(9001) 与其它 seed 冲突 ②submit 后批复查询返回 DRAFT ③policy.csv 未加 F 域路由规则 |
| 未提交 | f_schema/query_f/funding 模块/seed_f/sqlc.yaml 全部未 commit |

---

## Phase 1 · F 域经费闭环收尾（T2..T7，对应 v1，此处列阻塞与验收）

### T2 基建收尾（当前焦点）
1. 修 `testdata/seed_f.sql`：E_PROJECT 改 id=91001/91002 或 `ON CONFLICT (id) DO UPDATE`；确认与 seed_e/seed_r 无 F 表主键冲突。
2. `internal/platform/auth/policy.csv` 追加 F 路由规则（subjects/budgets/incomes/expenses/approval/execution/warnings/indirect-fees/expense/ai-invoice-review × 各角色）。
3. 测试库应用：后端启动自动跑迁移；测试库手动 psql 确认 schema 一致。
4. 验收：`go test ./internal/modules/funding/` 全绿 → commit（f_schema + query_f + sqlc.yaml + funding 模块 + seed）。

### T3 预算链路 / T4 到款认领 / T5 报销提交 / T6 审批 / T7 执行率预警
- 端点与验收同 v1（v1 文件 Phase 2 节，此处不重复）。要点：
  - T5 指纹查重 40903、冻结 40902；T6 两步链、越权 40301、跳步 40901；T7 执行率 string 精度、DEADLINE_RISK 读 E_PROJECT。
- **新增**（来自竞品蒸馏 B 组）：`GET /budgets/:id` 响应中带「科目进度」（每 line 的 approved/used/frozen/remaining）——为 P8 三维监控打基础。

**Phase 1 出口标准**：funding 域 20+ 端点真数据、测试全绿、docker compose 冒烟通过（建预算→批复→到款→认领→报销→两步审批→执行率→预警）。

---

## Phase 2 · 通知中心 + LLM + 大屏（T8..T10，对应 v1 Phase 3）

- T8 通知中心：migration 000003 `sys_notification`（id/tenant_id/user_id/role_key/type/title/body/biz_ref/read_at/created_at）；notify 模块（POST /notifications 内部、GET /notifications、GET /notifications/unread-count、POST /notifications/:id/read、POST /notifications/read-all）；funding 触达点接线（审批待办、认领审核、预警）。
- T9 LLM：platform/llm client（NewAPI OpenAI 兼容，env：ARK_LLM_BASE_URL/KEY/MODEL/TIMEOUT）；aireview 降级链路；confidence<0.85 强制 REVIEW。
- T10 大屏：dataops GET /dashboard/funding 真 SQL 聚合。

**扩展（spec F 组）**：通知类型扩展 `type: TODO|MESSAGE|WARNING|ANNOUNCE`，为 P6 任务中心与站内消息预留；GET /notifications 支持 type 过滤。

---

## Phase 3 · 前端对接 + 全量验证（T11、T12，对应 v1 Phase 4-5）

- ExpenseView 真端点、App 铃铛轮询、BigscreenView 真聚合；`vue-tsc && build` 全绿；headless Chrome 冒烟 + 端到端验收脚本（登录→全经费链路→断言）。
- commit + 更新 memory。

---

## Phase 4 · 通用底座：导入导出 + 科目/外拨/结转（新增，spec B/F 组）

### T13 Excel 导入导出底座
- 依赖：纯 Go，无新表（导入日志除外）。
- migration 000004：`sys_import_log(id, tenant_id, module, row_count, success_count, fail_count, operator_id, snapshot jsonb, created_at)` —— snapshot 存原始行，支持撤销（删除该批导入的业务行）。
- 新建 `internal/modules/dataio/`：
  - `POST /dataio/import?module=funding.income|project.e|output.r`：multipart Excel（用 `github.com/xuri/excelize/v2`）→ 模板校验 → 逐行调对应模块的批量导入（复用 T4 import-bank-flow 模式）→ 写导入日志 → 返回 {imported, skipped, errors[]}。
  - `GET /dataio/template?module=...`：返回 xlsx 模板（表头 + 示例行 + 校验说明 sheet）。
  - `GET /dataio/imports?module=&from=&to=`：导入日志列表。
  - `POST /dataio/imports/:id/undo`：按 snapshot 撤销（仅当业务行未被引用，如认领行已入账则拒绝）。
  - `POST /dataio/export?module=...&fields[]=...&order[]=...`：接受字段选择与顺序（spec「选择性导出」），流式 xlsx。
- 测试：模板生成/导入往返（生成模板→填两行→导入→断言入库→撤销→断言清空）；错误行收集（1 错 1 成功 → imported=1, errors 长度 1）。
- Casbin：导入导出仅 R-MANAGER/R-LEADER。

### T14 经费外拨 + 结转 + 预算追加
- migration 000005：`F_OUTWARD(id, tenant_id, project_id, amount, to_unit, reason, status DRAFT/PENDING/APPROVED/REJECTED, approved_by/at, created_at)`；`F_CARRYOVER(id, tenant_id, project_id, fiscal_year, amount, status, created_at)`；`F_BUDGET` 加 `pending_delta NUMERIC`（追加审批中金额）。
- sqlc：追加 query_f/f_outward.sql、f_carryover.sql、f_budget.sql（新增 upsert 语句）；重生成 fstore。
- funding/outward.go：POST /outwards（自动带出项目信息）→ POST /outwards/:id/approve（两级：R-MANAGER→R-LEADER，复用 P6 审批服务）→ APPROVED 后从 F_BUDGET_LINE remaining 扣减。
- funding/carryover.go：POST /carryovers（结题项目守卫：E_PROJECT.status=COMPLETED）→ approve 后生成下年度 F_INCOME(CARRYOVER) 行。
- funding/budget.go 扩展：POST /budgets/:id/append {lines:[{line_id,delta,reason}]}（pending_delta+=，approve 后 total_approved+=、version+1）。
- 契约：03-F.openapi.yaml 追加 6 个 operation + 字节同步前端。
- 测试：外拨两级审批、结转守卫（未结题 40901）、追加审批前后 remaining 断言。

### T15 支出科目管理 + 经费预警配置
- F_SUBJECT 已有表（type=EXPENSE 支出科目）→ 扩展多级：F_SUBJECT 加 `parent_id BIGINT`。
- migration 000006：`F_WARN_CONFIG(tenant_id, project_category_id, threshold_pct, level, channel, cron_expr, template, enabled)`。
- 端点：POST/PUT/DELETE /subjects/:id（多级守卫：有子级或被预算引用禁删）、GET /subjects/tree；GET/POST/PUT /funding/warn-configs。
- 测试：树形 CRUD、删除守卫、配置生效于 T18 预警扫描。

---

## Phase 5 · 成果治理增强（spec D/E 组）

### T16 期刊源库 + 刊物级别 + 转载登记
- migration 000007：`R_JOURNAL_SOURCE(id, tenant_id, name, issn, level_code, year_from, year_to, deleted)`；`R_JOURNAL_LEVEL(id, tenant_id, code, name, paper_type, indexed, deleted)`；`R_JOURNAL_LEVEL_SOURCE(level_id, source_id)`；`R_PAPER_REPRINT(paper_id, name, type, reprint_date, remark)`；`R_PAPER` 加 `level_code TEXT`（冗余快照）。
- 端点（output 模块）：GET/POST/PUT /journal-levels、/journal-sources（年度过滤）、POST /journal-levels/:id/sources（多对多）；POST /papers/:id/reprints；GET /journal-levels/resolve?name=&year=（按名称+年度匹配返回级别，未命中 200+null）。
- 论文新增链路：POST /papers 时若传 journal_name+publish_date → 服务端 resolve → 写 level_code（可显式覆盖）。
- 测试：匹配优先级（精确名 > 别名 > null）、年度窗口过滤、转载 CRUD。

### T17 网推成果认领 + 去重
- migration 000008：`R_PUSH_ITEM(id, tenant_id, type PAPER/PATENT, source_db, title, authors jsonb, year, raw_doi, status PUSHED/IMPORTED/IGNORED, pushed_at, dedup_key TEXT)`。
- 端点：GET /push-items?status=（分页）；POST /push-items/:id/import（先查重：dedup_key 精确命中 → 40905 附 existing_id；相似 = 标题 trigram 相似度 >0.85 → 200 + {similar:[...]} 需 force=true 才导入）；POST /push-items/:id/ignore。
- 测试：精确重复拒绝、相似确认后 force 导入、忽略幂等。

### T18 专利生命周期 + 年费预警
- migration 000009：`R_PATENT` 加 `stage PRE_APPLY/APPLIED/PUBLISHED/GRANTED/TRANSFERRED`、`annual_fee_due DATE`、`agency_id BIGINT`；新表 `R_PATENT_FEE(patent_id, year, amount, paid_at, status)`；`R_AGENCY(id, tenant_id, name, contact)`。
- 端点：POST /patents/:id/stage（阶段流转守卫）；POST /patents/:id/fees（登记年费）；GET /patents/:id/fees；GET/POST /agencies。
- 预警：通知中心扫描任务（P6 的 cron 基座）：`annual_fee_due - now < 30d` → 通知第一发明人（WARNING）；已过期未缴（CRITICAL）。
- 测试：阶段守卫（PRE_APPLY→APPLIED 合法、PRE_APPLY→GRANTED 40901）、预警扫描产生正确通知。

---

## Phase 6 · 通用两级审核 + 批量审核 + 任务中心（spec A/F 组）

### T19 通用两级审核服务
- 新建 `internal/platform/approval/`（不是模块，是服务库）：
  - `type TwoStep struct { FirstRole, SecondRole string }`；`Submit(tx, bizType, bizID, submitter)`、`Act(tx, bizType, bizID, actor, action, comment)`。
  - 状态复用各业务表 status；审核动作写 `sys_approval_log(biz_type, biz_id, step, actor_id, action, comment, acted_at)`（migration 000010）。
  - 锁规则接口：`Editable(status, role) bool`（学校通过→全员锁；学院通过→提交人锁）。
- 先接入 2 个域验证：E 变更/中检/结题 approve 升级为两级可配（env `ARK_APPROVAL_TWOSTEP=off` 默认关，行为不变）；F 认领审核（T4 claim 后加 PENDING，秘书审→科研处审→入账）。
- 批量端点：POST /expenses/approval-batch、POST /projects/approve-batch {ids:[], action, comment}（逐条事务、逐条结果 {id, ok, err}）。
- 测试：两级链路、锁规则矩阵（4 角色 × 5 状态）、批量部分失败。

### T20 任务中心 + 站内消息
- 通知中心扩展：GET /tasks（聚合：我的待办 = 未读 TODO 通知 + 我名下 PENDING 单据）；GET /tasks/summary（今日待办计数）。
- 站内消息：sys_notification type=MESSAGE；POST /messages {to_user_ids[], title, body}（点对点，接收人从用户接口选择）；GET /messages（收件箱，type=MESSAGE 过滤）；业务咨询 = to 固定角色 R-MANAGER 的消息。
- 前端：App 铃铛面板分「待办/消息/预警」三 tab；DashView 加「今日待办」卡。
- 测试：聚合正确性（A 提交报销 → B 的 /tasks 出现该单；B 审批后消失）。

---

## Phase 7 · 中检/结项日期范围预警 + LLM PDF 解析（spec C/F 组）

### T21 项目分类管理 + 日期范围预警
- migration 000011：`E_PROJECT_CATEGORY(id, tenant_id, name, code, level, budget_template jsonb, mgmt_fee_pct NUMERIC, midcheck_from/to DATE NULL, closing_from/to DATE NULL)`；E_PROJECT 加 `category_id`。
- 端点：CRUD /project-categories；E 立项时选分类。
- 预警（P6 cron 基座）：扫描 E_PROJECT（EXECUTING）× 分类窗口 → 进入中检窗口前 15 天发 MIDCHECK_DUE 预警给负责人；结项同理 CLOSING_DUE。
- 管理费：T4 认领入账时按分类 mgmt_fee_pct 自动计算（F_INCOME 加 mgmt_fee 列，migration 000012）。
- 测试：窗口边界预警、管理费计算精度（DECIMAL(18,2)）。

### T22 LLM PDF 任务书解析
- platform/llm 扩展：`ExtractJSON(ctx, kind, fileBytes)` —— NewAPI 多模态（文件走 base64 或先 pdfplumber 提文本，取简单方案：Go 端用 `github.com/ledongthuc/pdf` 抽文本 → 拼 prompt）。
- 端点：POST /projects/extract-taskbook（multipart pdf）→ {project_name, pi, members[], budget_lines[], period} 置信度 <0.85 降级返回 raw_text+提示人工录入。
- 立项页「PDF 导入」按钮：解析结果回填表单（不直接落库，人工确认后提交）。
- 测试：fake LLM 返回样例 JSON → 字段映射断言；LLM 超时降级。

---

## Phase 8 · 执行三维监控 + 大屏/画像真数据 + 预警配置生效（spec B 组）

### T23 执行进度三维监控
- GET /funding/execution?dim=project|college|subject：
  - project：现 T7 聚合；college：按 E_PROJECT.college 分组聚合；subject：按 F_BUDGET_LINE.subject_id 分组（approved/used/frozen/remaining/执行率）。
- 大屏「一图一舱三预警」：dashboard/funding 响应加 `by_college[]`、`by_subject[]`。
- 测试：三维聚合数值断言（seed 场景手工算例）。

### T24 画像真数据 + 预警配置生效
- GET /portrait/:userId：项目数/经费（执行率）/成果数/考核分，全部真 SQL（复用各模块查询）。
- T15 warn-config 接入 T18/T21 扫描：channel=cron 时按配置模板渲染消息。
- 测试：画像字段非零断言（seed 有数据）、模板渲染。

---

## Phase 9 · 申报计划 + 形式审查（spec C 组，收尾扩展）

### T25 申报计划
- migration 000013：`E_APPLY_PLAN(id, tenant_id, name, category_id, source, start_at, end_at, need_review bool, guide_file_id, status DRAFT/OPEN/STOPPED, created_at)`；`E_APPLICATION(id, plan_id, project_name, apply_amount, applicant_id, attachment_ids, status SUBMITTED/COLLEGE_PASSED/COLLEGE_REJECTED/SCHOOL_PASSED/SCHOOL_REJECTED)`。
- 端点：CRUD /apply-plans（R-MANAGER）；POST /apply-plans/:id/start|stop（start 校验时间窗）；POST /apply-plans/:id/applications（仅 OPEN 且 now∈[start,end]）；GET /apply-plans/:id/applications（形式审查视图：申请人「主持+参与」项目摘要子查询）；POST /applications/:id/approve（两级，P6 服务）。
- 到期自动停止：P6 cron 扫描 `end_at < now AND status=OPEN → STOPPED`。
- 通过后转立项：POST /applications/:id/to-project（生成 E_PROJECT 草稿）。
- 测试：时间窗外提交 40901、自动停止、to-project 幂等。

---

## 依赖关系

```
P1(F闭环) ─→ P2(通知/LLM/大屏) ─→ P3(前端+验证)
      │                                │
      ├─→ P4(导入导出/外拨/结转) ──┐   │
      ├─→ P5(期刊/网推/专利)      ├──→ P8(三维监控/画像)
      └─→ P6(两级审核/任务中心) ──┘
P6 ─→ P7(日期预警/PDF解析)
P6 ─→ P9(申报计划)
```

P4/P5/P6 可并行（各自独立 migration 序号按合并顺序重排）。

## 验收总标准（全部 Phase 完成）
1. `go test ./...` 全绿（含 -race）；`vue-tsc && build` 全绿。
2. docker compose 冒烟：申报→立项→预算→到款→认领（两级审）→报销→两步审批→执行率（三维）→预警（中检/结项/年费）→通知/任务中心→大屏→导入导出→PDF 解析。
3. 契约同步铁律：每个新端点先入 03-F/02-E/06-R.openapi.yaml 再实现，字节同步 frontend。
4. 每任务独立 commit，消息格式 `feat(<域>): <内容>`。

## 风险与裁剪预案
- **excelize/ledongthuc/pdf 新依赖**：go.mod 已有 gin/pgx，新增两个纯 Go 库风险低；若 PDF 文本抽取质量差，P7 的 T22 降级为「仅支持文本版 PDF + 明确报错」。
- **两级审核改造影响面**：默认 env 开关关闭，先在 F 认领单域验证，E 域灰度。
- **工期裁剪顺序**（若需收缩）：P9 → P7/T22 → P5/T17 → P8/T24 依次可延后，核心闭环（P1-P4+P6）不可裁。
