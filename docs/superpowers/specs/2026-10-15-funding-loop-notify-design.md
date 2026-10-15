# 经费闭环(F)真实化 + 通知中心 + 大屏真数据 + LLM 审核 · 设计规格

**日期**：2026-10-15 · **状态**：已与主人确认（策略 A：经费闭环纵深；LLM 接 NewAPI 网关）
**需求来源**：`docs/易普拉格科研管理系统V系列-功能文档.md`（§2.3 经费管理、§2.4 科研财务协同、§3.2 大模型赋能、§3.3 大数据应用）、`docs/一体化科研管理平台-CoNow-AOP-功能文档.md`（预算与财务闭环、数据中台）

---

## 1. 背景与差距

backend-go 已有 8 个域真实现（P/E/R/V/M/N/O/sysadmin），**F 经费域 100% passthrough 假数据**；执行率由前端自算；无通知/预警机制；大屏（BigscreenView）消费 passthrough；零 LLM 代码。本轮对标竞品补齐「到款→认领→入账→预算→报销→审批→执行率→预警→大屏」闭环。

## 2. 范围（本轮做 / 不做）

**做**：
1. F 域核心链路真实化（14 个既有契约端点 + 2 个新增契约端点）
2. 通知中心底座（新表 + notify 模块 + funding 业务触达点）
3. 执行率聚合 API + 经费预警 API（竞品"三预警"的确定性部分）
4. D 域 `/dashboard/funding` 真聚合（大屏经费卡接真数据）
5. LLM 发票/报销智能审核（NewAPI OpenAI 兼容接口，仅建议不决策）
6. 前端：ExpenseView 真实对接、App.vue 通知铃铛接真、BigscreenView 经费卡接真

**不做**（留后续迭代）：F-11 凭证同步外部财务系统、F-13 决算结转、F-20 全成本分摊、F-21 平行记账、F-22 外拨、发票 OCR 影像识别（本轮 AI 审核走结构化字段）、C/G/A/T/S/X 域真实化、移动端。

## 3. 关键设计决策

### 3.1 F 域模块（backend-go/internal/modules/funding）
- 复刻 activity/performance 垂直切片模式：`db/schema/f_schema.sql`（从 000001 裁剪）+ `db/query_f/*.sql` → sqlc 生成 `store`（package `fstore`）→ `mapper.go/handler.go/routes.go`。
- 路由前缀沿用既有契约裸路径：`/subjects` `/budgets` `/incomes` `/expenses` `/expense` `/budget-lines` `/indirect-fees`（openapi 已定义，当前走 passthrough，注册后真 handler 接管）。
- **状态机**（守卫在 handler，非法流转 40901）：
  - 预算 `F_BUDGET`：DRAFT→SUBMITTED→UNDER_REVIEW→APPROVED→EXECUTING；调整走 ADJUSTING→RE_APPROVED（version+1）
  - 到款 `F_INCOME.claim_status`：UNCLAIMED→CLAIMED（认领回填 project_id）；IMPORT 批量命中已有 bank_flow_no 幂等跳过
  - 报销 `F_EXPENSE`：DRAFT→SUBMITTED→HUMAN_REVIEW→APPROVED/REJECTED/RETURNED；AI_REVIEW 可选跳过
- **F-10 预算冻结/扣减**（本地事务，`SELECT ... FOR UPDATE` 行锁）：
  - 提交报销：`remaining ≥ amount` 校验（不足 40902）→ `amount_frozen += amount`
  - 审批通过（末步）：`amount_frozen -= amount; amount_used += amount`
  - 驳回/退回：`amount_frozen -= amount; amount_released += amount`
  - 包干制（submit_mode=包干制）不锁科目行，校验预算总额 remaining
- **三重指纹查重**（PRD 11）：`fingerprint_hash = sha256(no|amount|date)`，同租户内存在非 REJECTED/RETURNED 同指纹单 → 40903 拒绝
- **审批链生成**（F-09 简化规则路由）：`amount < 100000` 一步 `[R-MANAGER]`；`≥ 100000` 两步 `[R-MANAGER, R-LEADER]`；落 `F_EXPENSE_APPROVAL(step_order, role, status=PENDING)`；审批人按角色匹配 Casbin 用户（MVP：任何持该角色用户可审，记 acted user）
- **费用提取**（竞品强调）：`POST /indirect-fees/calculate {project_id, rate?}` → 按项目 CLAIMED 入账总额×间接费率（默认 20%，上限校验 30%）落 `F_INDIRECT_FEE`，同 project+rate 幂等
- **执行率**：`GET /funding/execution?project_id=` → `{budget_approved, income_total, used, frozen, remaining, exec_rate_by_income, exec_rate_by_budget}`（NUMERIC → string，两口径）
- **预警**（惰性计算不落库）：`GET /funding/warnings` 扫描 EXECUTING 项目 → `WARN`（执行率≥80%）、`CRITICAL`（≥100%）、`DEADLINE_RISK`（E_PROJECT 结题窗口 30 天内且执行率<100%）

### 3.2 通知中心（新模块 notify）
- 新迁移 `000003_sys_notification.up/down.sql`：`sys_notification(id, tenant_id, user_id, type, title, content, biz_ref, read_at, created_at)` + 索引 `(tenant_id, user_id, read_at)`
- `internal/modules/notify`：`GET /notifications?only_unread=`、`GET /notifications/unread-count`、`POST /notifications/:id/read`、`POST /notifications/read-all`（Casbin：全角色可读写本人通知）
- `Notifier` 接口（`Push(ctx, userID, type, title, content, bizRef)`）由 router 注入 funding handler；funding 事务提交后 best-effort 推送（失败仅日志，不回滚业务）
- 触达点：到款登记/导入→项目 PI（待认领）；报销提交→当前步审批角色；审批通过/驳回/退回→报销人；执行率预警查询到 CRITICAL→PI（去重：同 biz_ref 未读不重复推）

### 3.3 LLM 智能审核（platform/llm + NewAPI）
- `internal/platform/llm/client.go`：OpenAI 兼容 `POST {base}/chat/completions`；env `ARK_LLM_BASE_URL`（默认 `http://10.26.8.43:3002/v1`）、`ARK_LLM_API_KEY`、`ARK_LLM_MODEL`（默认 `gpt-4o-mini` 占位，部署侧可改）、超时 15s；网络/解析失败返回 `ErrUnavailable`
- `POST /expense/ai-invoice-review {expense_id}`：组装单据结构化上下文（金额/类别/事由/指纹/科目余额/执行率）→ system prompt 要求严格 JSON `{verdict: PASS|REVIEW|REJECT, confidence: 0..1, reasons: []}` → 解析失败/超时降级 `{verdict: REVIEW, confidence: 0, available: false}`；`confidence < 0.85` 强制 REVIEW（PRD 2.4：AI 仅建议、永不直写业务）
- 结果**不落 F_EXPENSE**（MVP 只读建议），前端在审批页展示；`ai_suggestion` JSONB 列留待后续落库

### 3.4 D 域大屏真数据（新模块 dataops，最小集）
- `internal/modules/dataops`：`GET /dashboard/funding` → 真 SQL 聚合 F/E 表：`{income_total, expense_total, exec_rate_avg, by_status 分布, top_projects[5]}`；Casbin 只读角色全放开；其余 `/dashboard/*`、`/dash/*` 继续 passthrough

### 3.5 前端
- `ExpenseView`：列表/填单/提交/审批动作接真端点；执行率条读 `/funding/execution`；OCR 演示按钮保留但标注"演示"
- `App.vue` 铃铛：未读数轮询（60s）+ 下拉最近 10 条 + 点击已读
- `BigscreenView`：经费总览卡接 `/dashboard/funding`，失败回退现有 passthrough 数据展示

## 4. 兼容性承诺
- 契约改动仅**追加** operation（`/funding/execution`、`/funding/warnings`），不改既有定义；`cp` 同步 frontend schema 副本
- 未实现的 F 契约操作继续 passthrough 兜底，全站无死链
- 新表仅增量迁移 000003，不动 000001（gen.go 生成物零漂移，`gen_test.go` 保持绿）
- mock 模式（VITE_USE_MOCK≠false）行为不变，新增端点在 mock 侧走既有 generator 兜底

## 5. 测试策略
- fstore/mapper 契约形测（无 DB）；handler DB 集成测（`ARK_TEST_DATABASE_URL`，seed_f.sql 幂等）；llm client 用 httptest 假服务测成功/降级两路；notify 独立集成测；前端 `vue-tsc --noEmit` + `npm run build`
- 验收端到端：docker compose up --build 后 admin 登录 → 建预算→批复→登记到款→认领→填报销→提交（冻结）→审批（实扣）→执行率/预警/通知/大屏全链路 curl 断言

## 6. 风险
- sqlc 对 F 表 NUMERIC/JSONB 生成类型需逐列核对（沿用列级 override 经验）
- NewAPI 不可达时 AI 端点必须降级不阻塞（测试覆盖）
- `/subjects` 等裸路径若与其他域未来契约冲突，迁移成本 = 路由前缀改动（记录在案）

---

# v2 附录 · 原始资料需求蒸馏（2026-10-15 增补）

来源：`docs/` 下 4 份旧版 Word 手册（易普拉格管理员/科研秘书/科研人员手册 2020-2022）、2 份 PDF（南林大 2025 定制版 + 通用版 2013）、14 张竞品功能图。以下为设计参考的需求清单，按「对当前实现的映射」组织。

## A. 通用审核体系（两级状态机 + 批量审核）
- 状态机：`已提交 → 学院通过/学院不通过 → 学校通过/学校不通过`；退回修改后自动回「已提交」。
- 锁规则：学校通过后秘书不可改；学院通过后本人不可改；仅 `不通过/已提交` 状态可编辑。
- 批量审核：列表勾选 + 批量通过/退回 + 审核意见。
- 当前映射：F_EXPENSE_APPROVAL 是单据内多步链；E 域变更/中检/结题已有单级 approve。→ 新增通用 `approval` 服务（两级可配）+ 各域复用。

## B. 经费域补充需求（竞品手册一致性最高的域）
- 批量到账导入：Excel（项目编号+金额）批量入账；银行流水批量导入（已有 import-bank-flow）。
- 认领两级审核：负责人认领 → 秘书审 → 科研处审 → 入账；未审可改，通过后打印入账通知单。
- 经费外拨：新增外拨记录 + 审核（自动带出项目信息）。
- 经费结转：结题后剩余经费结转。
- 预算补录/追加：人员发起 → 审核 → 自动更新项目预算。
- 工作量分割 / 绩效分割：到账经费按成员分割登记（负责人可登记，他人只读）。
- 支出科目管理：多级科目 CRUD。
- 预借票据：新增（带出项目/到账）→ 审核 → 打印。
- 执行进度三维监控：学院进度 / 项目进度 / 科目进度。
- 经费预警可配：按项目分类配置预警消息格式/发送方式/时间。

## C. 项目域补充需求
- 项目分类管理：分类含预算标准、管理费提取比例（到账时自动算管理费）、中检/结项日期范围限制。
- 中检/结项双模式：限定日期范围（系统自动发预警）或随时提交。
- 申报计划：科研处建计划（时间窗/分类/是否评审/指南附件）→ 启动 → 人员在窗内申报 → 到期自动停止。
- 形式审查辅助：查看申报人「主持+参与」全部项目。
- 在线评审：申报批次转评审 → 评审计划 → 专家指派（专家库/分组）→ 发送通知 → 进度监控。
- 合作单位校验：合作单位合同金额之和 = 外拨金额（南林版强校验）。

## D. 成果域补充需求
- 期刊源库 + 刊物级别：级别关联多个期刊源，按年度管理；录论文时按发表时间匹配期刊源自动带出级别。
- 网推论文/专利认领：推送 → 导入/忽略 → 与库内重复/相似去重提示。
- 转载情况登记：论文名/类型/时间/备注。
- 作者三类型：本校老师（系统带出）/本校学生/外校人员（手填）。
- 成果修改权限：仅第一作者/通讯作者且状态可改。

## E. 知识产权域补充需求
- 专利全生命周期：预申请 → 申请 → 公开 → 授权 → 年费 → 转让。
- 年费预警：授权后提醒第一发明人缴费；滞纳金专利另发预警。
- 代理公司协作：选代理 → 推送 → 代理接收/维护 → 发明人可见；代理公司库管理。
- 知产运营（南林）：转让/运营/赋权登记 → 审核 → 公示 15 天 → 签订合同。

## F. 通用底座需求
- Excel 导入导出底座：模板下载 → 上传导入 → 导入日志（模块/数量/人/时间，支持撤销）；选择性导出（选字段+排序+预览）。
- 通知/待办：任务中心（待办理/办理中/已完结）+ 今日待办 + 站内消息双向收发 + 业务咨询。
- 打印能力：入账通知单/中检通知书/用章审批单/报销单（前端打印视图即可）。
- PDF 任务书/申报书导入解析（LLM：信息一次录入多次带出）。
- 执行/提醒类：智能提醒（进度/超期/风险/自定义）。

## G. 明确不纳入本轮（记录留档）
- 低代码表单/流程设计器、可视化表单设计、跨系统集成（OA/财务/钉钉/企微）、移动端门户、个人学术主页定制、医学伦理审查流程、文档共享、学术交流（会议/讲座/派遣/接受）、教研教改/研究生管理、教育部统计报表。
- 理由：与当前 16 模块契约体系距离远、工程量大、非用户核心诉求（经费闭环+功能完备化）。

## H. 需求 → 本轮 Phase 映射
| 需求组 | Phase |
|---|---|
| A 两级审核+批量审核 | P6 |
| B 经费补充（外拨/结转/科目/三维进度/预警配置） | P4（科目+外拨+结转）、P8（三维进度+预警配置） |
| B 批量导入/认领审核强化 | P4 |
| C 中检/结项日期范围预警 | P7 |
| C 申报计划+形式审查 | P9 |
| D 期刊源库+网推认领+转载 | P5 |
| E 专利年费预警+生命周期 | P5（预警）、P9（运营留档不做） |
| F 导入导出底座 | P4 |
| F 任务中心+站内消息 | P6（通知中心扩展） |
| F PDF 解析（LLM） | P7 |
| F 执行进度三维监控 | P8 |
