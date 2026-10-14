# 设计规格 · 学术活动管理(V) + 科研绩效评价(M) 端到端实现

- 日期：2026-10-14
- 分支：develop（不自动推，遵循既有约定）
- 作者：QoderWork（头脑风暴产出，待主人评审）
- 关联计划：实现计划将由 `superpowers-writing-plans` 基于本规格生成

---

## 0. 背景与动机

`docs/` 下新增 11 张竞品（Colloa 科研管理系统）参考截图。将其能力全景与本仓库（契约驱动、M0 地基阶段）逐项对照后，识别出「设计里根本没有」的能力缺口：移动端、可视化表单设计器、图形化流程/BPM 引擎、SSO 集成中心、学术活动管理、科研绩效评价、甘特图进度、PDF 智能解析、多类型 E2E、独立科研档案。

本轮经主人拍板，锁定旗舰范围：**补齐两个当前完全缺失的业务域——学术活动管理（新模块 V）与科研绩效评价（新模块 M）**，且做到**端到端真实现**（复刻 P/U 已验证的垂直切片模式：契约 → DDL → sqlc → Go handler+store → Casbin+ABAC → 前端接通 → 测试）。

### 0.1 本轮四条锁定决策

1. **范围**：仅 V（学术活动）+ M（绩效评价）两个新业务域；**不做**通用工作流引擎（M3）、可视化表单设计器（M2）、移动端（M1）、SSO（M4）——这些顺延后续计划。
2. **层次**：端到端真实现（真实 Go handler/store + 前端真实 API 接通），不是仅契约/mock。
3. **绩效取数**：`calculate` 端点**读真实已建表**（R_OUTPUT / F_INCOME / E_PROJECT / T_DEAL）聚合，按方案因子计分；无数据时靠种子演示。
4. **前端**：新页面写真实 `api` 调用（关 mock 后打真后端），同时保留 mock curated override 便于无后端演示——与 P/U 完全一致。

### 0.2 现状事实（供实现参照）

- 后端仅 `modules/p`（申报，3 动作）与 `modules/sysadmin`（用户权限，完整）有真实实现；其余 10 域走 `oapi.Passthrough` 假数据。
- 全部业务表已由 `design/*.ddl.sql` 经 `migrations/gen.go` 汇总进 `000001_init.up.sql` 建出（含 R/F/E/T 等），故绩效跨模块取数**读的是真实存在的表**。
- 迁移生成器按文件名排序、`00-common.sql` 置顶自动纳入所有 `*.ddl.sql`；新增 `13-*.ddl.sql`、`14-*.ddl.sql` 天然衔接。
- sqlc 采用「每模块一个独立引擎块」模式（裁剪 schema + 专属 queries 目录 + 专属 package），P 块 package=`store`、U 块 package=`sysstore`。多块并发生成在 Windows 需 `GOMAXPROCS=1` 规避 wazero OOM。
- 前端 `client.ts` 真实 fetch + `auth.ts` 提供 token/roles/caps；`main.ts` 按 `VITE_USE_MOCK` 条件动态 import mock；路由 `meta.roles` + `beforeEach` 守卫；`v-perm` 指令做按钮级门控。

---

## 1. 模块编号与命名

| 编号 | 名称 | 字母 | 前缀（编号中心） | 表前缀 | sqlc package | store 目录 |
|---|---|---|---|---|---|---|
| 13 | 学术活动管理 | V | `ACT`（活动） | `v_` | `vstore` | `internal/modules/activity/store` |
| 14 | 科研绩效评价 | M | `PERF`（绩效记录）、`PAY`（发放） | `m_` | `mstore` | `internal/modules/performance/store` |

- 新前缀须在 `00-common.sql` 末尾的 `seq_prefix_registry` INSERT 追加登记：`('ACT','学术活动','V','v1.0',TRUE)`、`('PERF','绩效记录','M','v1.0',TRUE)`、`('PAY','绩效发放','M','v1.0',TRUE)`。
- 契约文件：`design/13-学术活动管理-V.openapi.yaml`、`design/14-科研绩效评价-M.openapi.yaml`；DDL：`design/13-学术活动管理-V.ddl.sql`、`design/14-科研绩效评价-M.ddl.sql`；detail：同名 `.detail.md`。
- 契约副本须逐字节 `cp` 到 `frontend/src/api/schema/`（mock 读前端副本）。

---

## 2. 通用约定（两模块共用，严格对齐 design/README.md §2 与 00-common/01-P 既有风格）

- 每张业务表内联通用列：`id BIGINT GENERATED ALWAYS AS IDENTITY PK`、`code VARCHAR(64)`、`tenant_id BIGINT NOT NULL`、`status VARCHAR(32) NOT NULL`（CHECK 枚举）、`deleted SMALLINT NOT NULL DEFAULT 0`、`creator_id BIGINT NOT NULL`、`modifier_id BIGINT`、`created_at/updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`remark TEXT`。
- 枚举一律 `VARCHAR + CHECK(IN)`；金额 `NUMERIC(18,2)`；时间 `TIMESTAMPTZ`；半结构化 `JSONB`；字典可配项走 `sys_dict`（如活动类型/级别/因子码），禁止业务代码硬编码。
- 跨模块只存对方主键 id 作**逻辑外键**，不建物理外键（如 project_id→E_PROJECT、staff_user_id→sys_user、factor 取数→R/F/T）。同模块内可建物理外键。
- 唯一索引用部分索引 `WHERE deleted = 0`；常用查询建 `(tenant_id, status)`、外键列索引。
- 涉密列：V 活动带 `security_level`（默认 INTERNAL），走 X 模块治理读取过滤；M 绩效记录属个人敏感，读取按 staff_user_id ABAC 限本人 + 管理角色。
- 响应统一 `ApiResponse{code,message,data,traceId,timestamp}`（code=0 成功）；分页 `PageResult{list,total,page,size}`（page 1-based，size 默认 20 上限 200）；写方法支持 `Idempotency-Key`；认证 Bearer JWT。
- 命名 case：沿用 P/U 的 snake_case 对齐 DDL（V/M 新模块统一 snake_case）。

---

## 3. 模块 V · 学术活动管理

### 3.1 数据表

**v_activity**（活动主表）
- 通用列 + `security_level VARCHAR(16) DEFAULT 'INTERNAL'`
- 业务列：`activity_type VARCHAR(32)` CHECK(CONFERENCE/LECTURE/SEMINAR/TRAINING/OTHER)、`level VARCHAR(16)` CHECK(INTERNATIONAL/NATIONAL/PROVINCIAL/CAMPUS)、`host_mode VARCHAR(16)` CHECK(HOST/ATTEND/SPONSOR)、`title VARCHAR(256) NOT NULL`、`theme VARCHAR(256)`、`start_at TIMESTAMPTZ`、`end_at TIMESTAMPTZ`、`venue VARCHAR(256)`、`online_url VARCHAR(512)`、`host_unit VARCHAR(128)`、`organizer_dept_id BIGINT`（逻辑→sys_org）、`invited_experts JSONB DEFAULT '[]'`、`est_attendees INT`、`project_id BIGINT`（逻辑→E_PROJECT）、`budget_subject_code VARCHAR(64)`（逻辑→F 科目/sys_dict）、`budget_amount NUMERIC(18,2)`、`agenda JSONB DEFAULT '[]'`（多场次 [{title,speaker,startAt,endAt,venue}]）、`attachment_ids JSONB DEFAULT '[]'`、`minutes_rich TEXT`（纪要，归档时填）、`sign_in_count INT`（实到人数）、`hold_at/hold_proof_ids JSONB`（举办凭证）、`submit_at/approve_at/archive_at/cancel_at TIMESTAMPTZ`、`cancel_reason VARCHAR(512)`。
- 唯一：`uk_v_activity_code (tenant_id, code) WHERE deleted=0`；索引：type/level/status/时间区间/organizer_dept/project。

**v_activity_participant**（参与人）
- `id`、`activity_id BIGINT NOT NULL REFERENCES v_activity(id)`、`user_id BIGINT`（逻辑→sys_user，可空=外部专家）、`guest_name VARCHAR(64)`（外部人员快照）、`role VARCHAR(16)` CHECK(SPEAKER/CHAIR/MEMBER/ATTENDEE)、`report_title VARCHAR(256)`、`tenant_id`、`created_at`。
- 唯一：`uk_v_participant (activity_id, user_id, role) WHERE user_id IS NOT NULL`。

**v_activity_review**（多级审核留痕）
- `id`、`activity_id REFERENCES v_activity(id)`、`review_level SMALLINT`（1=部门 2=院所/主管）、`reviewer_id BIGINT`（逻辑→sys_user）、`action VARCHAR(16)` CHECK(APPROVE/REJECT/RETURN)、`opinion VARCHAR(512)`、`acted_at TIMESTAMPTZ DEFAULT now()`、`tenant_id`。
- 索引：`(activity_id, review_level)`。

### 3.2 状态机（硬编码，端点驱动，非通用引擎）

```
DRAFT ──submit──▶ SUBMITTED ──approve(L1)──▶ DEPT_REVIEW ──approve(L2)──▶ APPROVED
  ▲                    │ REJECT/RETURN ───────────────────────────────▶ RETURNED ──(edit)──▶ DRAFT
  └──────(edit/RETURN)─┘
APPROVED ──hold──▶ HELD ──archive──▶ ARCHIVED
任意非终态 ──cancel──▶ CANCELLED
```
- 合法迁移由 handler 校验当前 status，非法迁移返回 40901 类业务码。
- REJECT→终态 REJECTED；RETURN→RETURNED（可编辑重提）。
- 归档要求已 HELD 且 minutes/凭证齐备。

### 3.3 端点（tag: activity）

- `GET  /activities` 列表：筛选 activity_type/level/host_mode/status/时间区间/organizer_dept/关键词(ILIKE title,theme)；分页；ABAC tenant_id + security_level。
- `POST /activities` 新建（DRAFT），分配 code（ACT-年-序）。
- `GET  /activities/{id}` 详情（含 participants + reviews）。
- `PUT  /activities/{id}` 编辑（仅 DRAFT/RETURNED）。
- `DELETE /activities/{id}` 软删（deleted=1）。
- `POST /activities/{id}/submit` DRAFT/RETURNED→SUBMITTED。
- `POST /activities/{id}/approve` body{review_level, action(APPROVE/REJECT/RETURN), opinion}；按 review_level 推进 SUBMITTED→DEPT_REVIEW→APPROVED 或转 REJECTED/RETURNED。
- `POST /activities/{id}/hold` APPROVED→HELD（body 实到人数/凭证）。
- `POST /activities/{id}/archive` HELD→ARCHIVED（body 纪要）。
- `POST /activities/{id}/cancel` →CANCELLED（body reason）。
- `GET  /activities/calendar?month=YYYY-MM` 返回该月活动（日历视图）。
- `GET  /activities/stats` 按 type/level/dept/month 聚合计数。
- 参与人：`GET/POST /activities/{id}/participants`、`DELETE /activities/{id}/participants/{pid}`。

### 3.4 权限（Casbin + ABAC）

- 建/提交/编辑本人发起活动：R-STAFF、R-MANAGER、R-LEADER。
- 审批（approve）：R-MANAGER、R-LEADER（对应 review_level）；R-ADMIN 兜底。
- 查看：登录可见列表，详情按 tenant + security_level 过滤（涉密活动仅对应网络域/密级可见，复用 X 读取谓词 hook）。
- policy.csv 追加（示例）：
  - R-STAFF：`/api/v1/activities POST`、`/api/v1/activities/* GET`、`/api/v1/activities/* PUT`（编辑限本人由 handler ABAC 再收）、`/api/v1/activities/*/submit POST`、`/api/v1/activities/*/participants* ...`
  - R-MANAGER/R-LEADER：上述 + `/api/v1/activities/*/approve POST`、`/hold`、`/archive`、`/cancel`
  - R-AUDITOR：`/api/v1/activities* GET`（只读）
  - R-ADMIN：随 `/api/v1/*` 通配已覆盖
- BuildCaps 自动把这些 p 规则派生成前端 caps；`/auth/me` 回显。

### 3.5 前端

- `views/ActivityView.vue`：列表（表格 + 类型/级别/状态筛选 + 关键词）+ 日历切换（按月）+ 统计条 + 新建/编辑抽屉 + 审批抽屉（通过/退回/驳回 + 意见）+ 参与人子表 + 归档上传。写按钮用 `v-perm="'/activities POST'"`、审批按钮 `v-perm="'/activities/{id}/approve POST'"`（容错前缀匹配）。
- 路由：`{ path:'/activity', name:'activity', meta:{zh:'学术活动',en:'ACADEMIC ACTIVITIES', roles:[R-STAFF,R-MANAGER,R-LEADER,R-AUDITOR,R-ADMIN]}, component: ActivityView }`。
- App.vue 侧栏新增「学术活动」项（归入合适分组），roles 与路由一致。
- mock curated override `overrides/activity.ts`（列表/日历/统计/详情演示数据）。

---

## 4. 模块 M · 科研绩效评价

### 4.1 数据表

**m_scheme**（绩效方案/考核规则）
- 通用列 + `name VARCHAR(128) NOT NULL`、`period_type VARCHAR(16)` CHECK(YEAR/QUARTER/MONTH)、`scope_dept_id BIGINT`（逻辑→sys_org，可空=全院）、`scope_staff_type VARCHAR(32)`（逻辑→sys_dict staff_type，可空=全部）、`effective_period VARCHAR(32)`（如 2026 / 2026Q1）、`version INT DEFAULT 1`、`active BOOLEAN DEFAULT FALSE`。
- 唯一：同 tenant+period_type+effective_period+scope 仅一个 active。

**m_scheme_factor**（考核因子）
- `id`、`scheme_id REFERENCES m_scheme(id)`、`factor_code VARCHAR(64) NOT NULL`（PAPER/PATENT/PROJECT/INCOME/AWARD/TRANSFER/BOOK/SOFTWARE/…，走 sys_dict）、`factor_name VARCHAR(128)`、`weight NUMERIC(6,2) NOT NULL DEFAULT 0`（占比）、`scoring_rule JSONB NOT NULL`（{method:COUNT|BY_LEVEL|BY_AMOUNT|LADDER, unit, ladder:[{min,max,score}], levelMap:{...}}）、`max_score NUMERIC(10,2)`、`data_source VARCHAR(32)` CHECK(R_OUTPUT/F_INCOME/E_PROJECT/T_DEAL/MANUAL)、`clause_ref VARCHAR(256)`（制度出处，可解释）、`sort_no INT`。
- 唯一：`uk_m_factor (scheme_id, factor_code)`。

**m_record**（绩效记录：某人×某方案×某周期）
- 通用列 + `scheme_id REFERENCES m_scheme(id)`、`staff_user_id BIGINT NOT NULL`（逻辑→sys_user）、`period VARCHAR(32) NOT NULL`、`dept_id BIGINT`、`total_score NUMERIC(10,2)`、`rank INT`、`calc_detail JSONB DEFAULT '{}'`、`calc_at TIMESTAMPTZ`、`calc_batch VARCHAR(64)`（批次号，幂等重算）、`confirmed_by/confirmed_at`、`approve_by/approve_at`。
- status CHECK：CALCULATED→CONFIRMED→APPROVED→PAID，分支 APPEAL（申诉）、VOID（作废）。
- 唯一：`uk_m_record (scheme_id, staff_user_id, period) WHERE deleted=0`（重算幂等 upsert）。

**m_record_item**（因子明细得分）
- `id`、`record_id REFERENCES m_record(id)`、`factor_code`、`metric_value NUMERIC(18,4)`（原始度量：篇数/金额/项数）、`raw_score NUMERIC(10,2)`、`weighted_score NUMERIC(10,2)`、`evidence JSONB DEFAULT '[]'`（命中单据 [{objectType,objectId,code,value}]）、`tenant_id`。
- 唯一：`uk_m_item (record_id, factor_code)`。

**m_payout**（绩效发放在线审批）
- 通用列 + `record_id REFERENCES m_record(id)`、`payee_user_id BIGINT NOT NULL`、`amount NUMERIC(18,2) NOT NULL`、`period VARCHAR(32)`、`pay_channel VARCHAR(32)`（工资/专项，走 sys_dict）、`approver_ids JSONB DEFAULT '[]'`（审批链快照）、`approved_at/paid_at`、`voucher_code VARCHAR(64)`（联动 F 凭证，逻辑外键）。
- status CHECK：DRAFT→APPROVING→APPROVED→PAID，分支 REJECTED。
- 唯一：`uk_m_payout (record_id) WHERE deleted=0 AND status<>'REJECTED'`（一条记录一笔有效发放）。

### 4.2 状态机

- 记录：`CALCULATED →(本人/管理员确认) CONFIRMED →(审批) APPROVED →(发放完成) PAID`；`CALCULATED/CONFIRMED →(申诉) APPEAL →(重算) CALCULATED`；`VOID` 作废。
- 发放：`DRAFT → APPROVING → APPROVED → PAID`；`REJECTED` 回退。

### 4.3 端点（tag: performance）

方案/因子：
- `GET/POST /perf/schemes`、`GET/PUT/DELETE /perf/schemes/{id}`、`POST /perf/schemes/{id}/activate`。
- `GET/POST /perf/schemes/{id}/factors`、`PUT/DELETE /perf/schemes/{id}/factors/{factorId}`。

计算与记录：
- `POST /perf/schemes/{id}/calculate` body{period, deptIds?/staffIds?}：**核心**——按方案因子从 R_OUTPUT/F_INCOME/E_PROJECT/T_DEAL 真表聚合 metric_value，套用 scoring_rule 计算 raw/weighted/total，upsert m_record + 覆盖 m_record_item（calc_batch 幂等）。
- `GET /perf/records`（筛选 scheme/period/dept/status/关键词，分页，ABAC）。
- `GET /perf/records/{id}`、`GET /perf/records/{id}/detail`（含 items + evidence）。
- `POST /perf/records/{id}/confirm`、`/appeal`（body reason）、`/approve`、`/void`。

发放：
- `POST /perf/payouts`（从 APPROVED 记录发起，body amount/channel）、`GET /perf/payouts`、`POST /perf/payouts/{id}/approve`、`/pay`、`/reject`。

个人与统计：
- `GET /perf/me?period=`（我的绩效，ABAC 强制 staff_user_id=当前用户）。
- `GET /perf/ranking?schemeId=&period=&top=`（排行/分布，管理角色可见）。

### 4.4 权限（Casbin + ABAC）

- 方案/因子配置、触发 calculate、approve、payout：R-ADMIN、R-LEADER、R-MANAGER。
- confirm/appeal 本人记录：R-STAFF（ABAC 限 staff_user_id=本人）。
- 查看：R-STAFF 仅 `/perf/me`；管理/审计角色可 `/perf/records`、`/perf/ranking`。R-AUDITOR 只读全量。
- policy.csv 追加：`/api/v1/perf/* GET`（各角色，me 除外由 ABAC）、`/api/v1/perf/schemes* POST/PUT/DELETE`（管理）、`/api/v1/perf/*/calculate POST`、`/api/v1/perf/records/*/confirm|appeal POST`（本人/管理）、`/api/v1/perf/records/*/approve POST`、`/api/v1/perf/payouts* ...`（管理）。
- ABAC 铁律：`/perf/me`、`/perf/records/{id}` 读取时，非管理角色强制 `staff_user_id == auth.DomainFrom(c).UserID`。现有 `auth.Claims`/`Domain` 已含 `UserID`（`jwt.go` Claims.UserID、`domain.go` Domain.UserID 由 CtxUserID 填充），**无需增补**，直接使用即可。

### 4.5 前端

- `views/PerformanceView.vue`（Tab 式）：① 方案与因子配置（表格 + 因子编辑：权重/计分方式/取数来源/制度出处）；② 绩效记录（列表 + 「触发计算」+ 明细抽屉展示 items/evidence + 确认/申诉）；③ 发放审批（payout 列表 + 审批/付款）；④ 我的绩效（当前用户记录 + 排行）。
- 路由：`{ path:'/performance', name:'performance', meta:{zh:'科研绩效评价',en:'PERFORMANCE', roles:[R-STAFF,R-MANAGER,R-LEADER,R-AUDITOR,R-ADMIN]} }`。
- App.vue 侧栏新增「绩效评价」项。
- mock override `overrides/performance.ts`。

---

## 5. 跨模块数据流（绩效自动计算取数）

`calculate` 读真表现有列聚合（不新增对被读模块的写）：
- 论文/专利/著作/获奖数：`R_OUTPUT`（按 author/owner user + 周期 + output_type 计数或按级别加权）。
- 到账经费：`F_INCOME`（按 project→PI 或 staff 关联，周期内金额求和）。
- 立项项目数/级别：`E_PROJECT`（按 PI、周期、类型）。
- 转化金额：`T_DEAL`/`T_INCOME`（按成果完成人）。
- 关联口径：以 `staff_user_id` 为轴，经各表逻辑外键（PI/author/owner）归集；具体谓词在 handler 的 sqlc 查询里实现，`evidence` 回填命中单据 id 以便复核（可解释、可反查，对齐竞品「减少人为干扰」）。
- 若被读表无数据（dev 未灌），calculate 返回 metric_value=0 的记录（不报错），演示依赖 §6.4 种子。

---

## 6. 落地机制（实现层，供写计划展开）

### 6.1 契约与 schema 同步
- 新建 `design/13-*.openapi.yaml`、`design/14-*.openapi.yaml`（含 components、状态机 enum、错误码）；`cp` 到 `frontend/src/api/schema/`，逐字节一致（漂移校验）。

### 6.2 DDL 与迁移
- 新建 `design/13-*.ddl.sql`、`design/14-*.ddl.sql`；`00-common.sql` 追加 ACT/PERF/PAY 前缀登记。
- `go generate ./migrations/...` 重生成 `000001_init.{up,down}.sql`；`gen_test.go` 增补断言（含 v_activity/m_scheme 建表存在）。

### 6.3 sqlc 引擎块
- `sqlc.yaml` 追加两个 engine 块：V（schema=`db/schema/v_schema.sql` 裁剪 v_* + 被读 R/F/E/T 只读表、queries=`db/query_v`、package=`vstore`、out=`internal/modules/activity/store`）；M（`m_schema.sql`/`query_m`/`mstore`/`internal/modules/performance/store`）。
- 裁剪 schema 语句原样摘自迁移；`GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1` 生成；`Makefile` drift 目标纳入两个新 store 目录。
- calculate 的跨表聚合查询写在 `db/query_m/*.sql`（SELECT 只读 R/F/E/T），生成到 mstore。

### 6.4 后端 handler
- `internal/modules/activity/{handler,routes,mapper}.go`、`internal/modules/performance/{handler,routes,mapper,mapper 计算引擎}`；handler 强制 `auth.DomainFrom(c).TenantID` 作首参（ABAC），状态机校验、编号分配、软删、审核留痕。
- `router.go`：`if d.Pool != nil { activity.Register(...); performance.Register(...) }`；`cmd/server/main.go` 无需改（reader 已接）。

### 6.5 Casbin
- `policy.csv` 追加 V/M 两组规则（见 §3.4/§4.4）；`policy_test.go` 鉴权矩阵补用例；`caps_test`/`BuildCaps` 覆盖新 obj。

### 6.6 前端
- 两个 view + 路由 + App.vue 侧栏项 + mock override；`auth.can`/`v-perm` 门控写操作；关 mock 联调清单。

### 6.7 测试与验证
- 后端：契约静态测试（形状合规）、handler 单测（gin 测试上下文 + 状态机/ABAC 分支）、DB 门控集成测试（`ARK_TEST_DATABASE_URL` 无则 SKIP）、`TestBuild_*FallsBackToPassthrough` 共存测试。
- 本机可跑：`go build/vet/test ./...`、`npm run typecheck && npm run build`、契约漂移、migrations/sqlc 漂移。
- BLOCKED（本机无 Docker/真库，留 CI）：连库集成用例实跑、compose 端到端冒烟。

---

## 7. YAGNI 边界（明确不做，登记后续）

- 通用可配置工作流引擎 / 图形化流程设计器（V/M 用硬编码状态机端点，未来 M3 再抽引擎）。
- 可视化表单设计器（M2）。
- 移动端 App / 响应式（M1）、SSO 与第三方集成中心（M4）。
- 绩效因子的 AI 建议计分（本轮纯确定性规则，AI 仅概率建议的铁律下不接入）。
- 学术活动的经费自动占用/冻结（budget_amount 仅登记，不联动 F 冻结；留后续）。
- 跨法人绩效并表口径细分（沿用 tenant 级，legal_entity 维度留 P-U2-org）。

---

## 8. 验收标准（Definition of Done）

1. 两模块契约 + DDL + 迁移重生成零漂移；前端 schema 副本逐字节同步。
2. `go build/vet/test ./...` 全绿；auth/sysadmin/activity/performance 包测试 PASS，DB 门控用例无库时 SKIP。
3. sqlc 两个新引擎块生成成功，store 编译测试钉住形状。
4. Casbin 鉴权矩阵覆盖 V/M 关键路径（含 R-STAFF 越权 approve 被拒、R-AUDITOR 只读、/perf/me ABAC 限本人）。
5. 前端 `typecheck`+`build` 通过；两新页在 mock 下有演示数据、关 mock 后可打真后端（联调清单交付）。
6. 绩效 `calculate` 能从 R/F/E/T 真表按因子计分产出 record+item+evidence，幂等重算。
7. 学术活动状态机全链路（建→提→审→办→归）可用，退回/驳回分支正确。

---

## 9. 风险与缓解

- **体量**：两域端到端 ≈ 30+ 任务，比用户管理（20）更重。缓解：写计划时按「V 域先行、M 域次之」分组，每组内契约→库→码→测→前端顺序，可分阶段交付。
- **绩效取数口径**：跨模块关联字段（谁是成果完成人/项目 PI）若既有表数据稀疏，calculate 结果偏空。缓解：种子灌演示关联数据；evidence 可反查便于核对。
- **ABAC UserID**：`/perf/me` 限本人依赖 `Domain.UserID`——已确认现 `auth.Claims`/`Domain` 含 UserID 且登录签发写入，无需增补；实现时仅需在 handler 正确取用并配越权单测。
- **多引擎块 OOM**：sqlc 4 块并发生成 Windows 易 OOM。缓解：`GOMAXPROCS=1` 串行（已验证）。
- **passthrough 绕过鉴权**：未注册路由走 NoRoute 不经中间件。缓解：V/M 全部端点在 `Pool!=nil` 时真实 Register 覆盖，联调清单显式核对 Authorization 附带。
