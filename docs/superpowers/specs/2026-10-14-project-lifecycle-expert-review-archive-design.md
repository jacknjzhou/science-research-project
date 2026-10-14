# 设计规格 · 项目全过程(E) + 科研成果(R) 真实化 + 专家评审(N) + 科研档案(O) 端到端实现

- 日期：2026-10-14
- 分支：develop（不自动推，遵循既有约定：合并/PR/推送须主人确认）
- 作者：QoderWork（头脑风暴产出，待主人评审）
- 关联计划：实现计划由 `superpowers-writing-plans` 基于本规格生成；本轮经主人拍板为**单一全覆盖计划**（内部按依赖分相）

---

## 0. 背景与动机

`docs/` 下 11 张竞品（Colloa 科研管理系统）参考截图，逐项对照本仓库后，识别出两类差距：

- **已契约化但未落地**：E 项目过程、R 科研成果等 10 个模块已有 `design/*.openapi.yaml` + `*.ddl.sql`，但后端仅 P/U/V/M 四个域有真实 Go 垂直切片，其余走 `oapi.Passthrough` 生成假数据。截图主打的「项目全过程管理」「经费自动化」「成果全生命周期」其实**契约已覆盖**，缺的是真实 handler/store/前端接通。
- **设计里根本没有**：专家库与随机/组合抽取评审、独立科研档案（跨域聚合 + 四性检测 + 借阅检索）、以及对象存储（`sys_print_template.file_url` 注释「对象存储」但后端无实际文件服务）。

上一轮（V 学术活动 + M 绩效评价）已验证「端到端真实现」垂直切片模式（契约 → DDL → sqlc → Go handler+store → Casbin+ABAC → 前端接通 → 测试）。本轮把该模式推广到四个域，并首次引入对象存储基础设施。

### 0.1 本轮锁定决策（主人逐项确认）

1. **范围**：四个域全做——E 项目过程（真实化）、R 科研成果（真实化）、N 专家评审/专家库（新建）、O 独立科研档案（新建）。**不做**：可视化表单设计器、图形化 BPM 流程引擎、移动端、SSO/多系统集成、低代码平台（顺延后续计划）。
2. **层次**：端到端真实现（真实 Go handler/store + 前端真实 API 接通 + 关 mock 后打真后端），保留 mock curated override 便于无后端演示。
3. **专家评审深度**：做到「回写 E/R 业务对象」——评审事件挂到现有业务对象（中检评审→`E_MID_CHECK`、结题评审→`E_FINAL_ACCEPT`、成果评价→`R_OUTPUT`），通过/不通过回写被评审对象 status。因回写需 E/R 真实，故本轮**连 E/R 一起建真实切片**（主人确认）。
4. **科研档案深度**：清单 + 上传（对象存储 MinIO）+ 归档流程（提交→四性检测→入库）+ 全文检索/借阅。
5. **计划组织**：单一全覆盖实现计划（主人确认），内部按依赖分相（E→R→N→O），执行按计划顺序推进。

### 0.2 现状事实（供实现参照）

- 后端真实垂直切片仅 `modules/p`、`modules/sysadmin`、`modules/activity`(V)、`modules/performance`(M)；其余 10 域 `oapi.Passthrough`。
- 全部业务表已由 `design/*.ddl.sql` 经 `backend-go/migrations/gen.go` 汇总进 `000001_init.up.sql` 建出——**含 E_*、R_* 全部表**，故 E/R 真实化是「给已存在的表建 handler/store」，非建表。
- 关键既有结构（本轮须复用/对接，勿另起炉灶）：
  - `E_MID_CHECK.expert_ids JSONB`（评审专家 user_id 数组，R-EXPERT，在线打分）、`conclusion`（CONTINUE/CORRECT/TERMINATE）、`status`（PLANNED/IN_REVIEW/SCORED/CONCLUDED/CORRECTING）。
  - `E_FINAL_ACCEPT.status`（APPLIED/TECH_REVIEW/FIN_REVIEW/APPROVED/REJECTED/NEED_SUPPLEMENT，技术+财务双轨并行）。
  - `E_PROJECT_DOC`、`E_ARCHIVE_CHECKLIST`（status TEMPLATE/IN_PROGRESS/PASSED/BLOCKED）——项目过程内档案，与本轮「跨域独立档案」边界见 §6.0。
  - `R_OUTPUT.status`（AUTO_FETCHED/PENDING_CLAIM/CLAIMED/ASSIGNED_TO_PROJECT/…）、`claim_status`（UNCLAIMED/PENDING/CLAIMED/REJECTED/NOT_MINE/DOUBTFUL）、`authors JSONB`。
  - 角色枚举含 `R-EXPERT`（`00-common.sql` 角色表），专家天然对应此角色。
- E 契约端点（15）：`GET /project/mine`、`GET /project/{id}`、`GET /project/{id}/tasks`、`PUT /project/{id}/tasks/{taskId}`、`POST /project/{id}/progress-report`、`POST /project/{id}/mid-check`、`POST /project/{id}/change-request`、`POST /project/{id}/change-request/{changeId}/approve`、`POST /project/{id}/final-accept`、`GET /project/{id}/health-score`、`GET /project/{id}/risk-warnings`、`POST /project/{id}/risk-warnings/{warningId}/ack`、`GET /project/{id}/archive-checklist`、`POST /project/{id}/archive-checklist/validate`、`GET /project/{id}/trace`。
- R 契约端点（15，operationId）：`listOutputs GET /output`、`createOutput POST /output`、`listMyOutputs GET /output/mine`、`listPendingClaim GET /output/pending-claim`、`claimOutputs POST /output/claim`、`rejectOutputs POST /output/reject`、`markNotMine POST /output/mark-not-mine`、`aiFill POST /output/ai-fill`、`aiDedup POST /output/ai-dedup`、`linkProjects POST /output/{id}/projects`、`listPatents GET /output/patents`、`listMetricSnapshots GET /output/{id}/metrics`、`refreshCited POST /output/{id}/metrics/refresh`、`exportOutputs GET /output/export`、`getOutput GET /output/{id}`。
- sqlc 每模块一个独立引擎块（现 4 块：p/sysadmin/activity/performance），Windows 生成须 `GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1`；禁 `go mod tidy`。
- 可选过滤须用 `sqlc.narg('name')::type IS NULL OR col = sqlc.narg('name')::type`（否则非空 ColumnN 参数使空过滤条件返回 0 行）。
- 前端真实 fetch `client.ts` + `auth.ts`；`main.ts` 按 `VITE_USE_MOCK` 条件动态 import mock；命名三向 1:1（`section id="v-<name>"` ↔ 路由 `name` ↔ App.vue 侧栏 `v`）。

---

## 1. 模块编号与命名

| 序 | 名称 | 字母 | 契约文件 | 表前缀 | sqlc package | store 目录 | 状态 |
|---|---|---|---|---|---|---|---|
| 02 | 项目过程管理 | E | 已存在 | `E_` | `estore` | `internal/modules/project/store` | 真实化 |
| 04 | 科研成果管理 | R | 已存在 | `R_` | `rstore` | `internal/modules/output/store` | 真实化 |
| 15 | 专家与评审管理 | N | **新建** | `n_` | `nstore` | `internal/modules/expertreview/store` | 新建 |
| 16 | 科研档案管理 | O | **新建** | `o_` | `ostore` | `internal/modules/archive/store` | 新建 |

- 新建契约三件套：`design/15-专家与评审管理-N.{detail.md,ddl.sql,openapi.yaml}`、`design/16-科研档案管理-O.{detail.md,ddl.sql,openapi.yaml}`；契约 yaml 逐字节 `cp` 到 `frontend/src/api/schema/`。
- 新前缀登记进 `00-common.sql` 末尾 `seq_prefix_registry` INSERT：
  - `('EXR','专家','N','v1.0',TRUE)`、`('RVW','评审任务','N','v1.0',TRUE)`
  - `('ARC','科研档案','O','v1.0',TRUE)`、`('BORROW','借阅申请','O','v1.0',TRUE)`
- 前端 `frontend/src/api/schema/index.ts` 的 `MODULE_CODES` 追加 `'15':'N','16':'O'`。
- E/R 无新前缀（沿用 `PRJ` 等既有；E 子单据 code 走通用 code 或既有登记）。

> 命名一致性铁律：侧栏 `data-v` ↔ `section id="v-<name>"` ↔ `app.js`/路由 names 键三者数量与命名 1:1。

---

## 2. 通用约定（对齐 design/README.md §2 与 00-common/01-P 既有风格）

- 每张业务表内联通用列：`id BIGINT GENERATED ALWAYS AS IDENTITY PK`、`code VARCHAR(64)`、`tenant_id BIGINT NOT NULL`、`status VARCHAR(32) NOT NULL`（CHECK 枚举）、`deleted SMALLINT NOT NULL DEFAULT 0`、`creator_id BIGINT NOT NULL`、`modifier_id BIGINT`、`created_at/updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`remark TEXT`。
- 枚举一律 `VARCHAR + CHECK(IN)`；金额 `NUMERIC(18,2)`；时间 `TIMESTAMPTZ`；半结构化 `JSONB`；可配项走 `sys_dict`（专家领域标签、档案门类、借阅类型等），禁止业务代码硬编码。
- 跨模块只存对方主键 id 作**逻辑外键**，不建物理外键（E_* 同模块内可建物理外键，R_* 同）。N/O 引用 E/R/P 均为逻辑外键。
- 唯一索引用部分索引 `WHERE deleted = 0`；常用查询建 `(tenant_id, status)`、外键列索引。
- 涉密列：E/R 已有 `security_level`；N 专家/评审、O 档案均带 `security_level`（默认 INTERNAL），走 X 读取过滤 hook。
- 响应统一 `ApiResponse{code,message,data,traceId,timestamp}`（code=0 成功）；分页 `PageResult{list,total,page,size}`（page 1-based，size 默认 20 上限 200）；写方法支持 `Idempotency-Key`；认证 Bearer JWT。
- 契约金额/NUMERIC 字段前端统一走 `@/utils/money` 的 `toNum/toWan` 解析（契约里是 string）。
- 命名 case：E/R 既有 DDL 表名/列名沿用其现状（DDL 未加引号→PG 折叠小写）；N/O 新模块列名 snake_case。

---

## 3. 域 E · 项目过程管理（真实化）

### 3.1 范围

给已存在的 `E_PROJECT / E_TASK / E_MILESTONE / E_PROGRESS_REPORT / E_MID_CHECK / E_CHANGE_REQUEST / E_FINAL_ACCEPT / E_PROJECT_DOC / E_HEALTH_HISTORY / E_ARCHIVE_CHECKLIST` 建真实 sqlc store + Go handler + 路由 + Casbin/ABAC，并把前端 `ProjectsView.vue`/`ProjectView.vue` 从 mock 切到真实 API（保留 curated override）。

### 3.2 端点实现分类（对齐契约 15 端点）

- **list/read（真查库）**：`GET /project/mine`（ABAC pi_user_id=当前用户，分页）、`GET /project/{id}`（详情 + tasks/milestones 概要）、`GET /project/{id}/tasks`。
- **action（状态机 + 回写）**：`PUT /project/{id}/tasks/{taskId}`（任务派工/状态）、`POST /project/{id}/progress-report`（DRAFT→SUBMITTED）、`POST /project/{id}/mid-check`（建中检，PLANNED→IN_REVIEW；`expert_ids` 由 N 域抽取回填，见 §5.5）、`POST /project/{id}/change-request` + `.../approve`（变更 DRAFT→…→EFFECTIVE，回写 E_PROJECT 对应字段）、`POST /project/{id}/final-accept`（APPLIED→TECH_REVIEW/FIN_REVIEW→APPROVED/REJECTED，技术+财务双轨）。
- **computed（保留 passthrough 或轻实现）**：`GET /project/{id}/health-score`、`GET /project/{id}/risk-warnings` + `ack`、`GET /project/{id}/trace`、`GET /project/{id}/archive-checklist` + `validate`。
  - 决策：`health-score` 基于 `E_HEALTH_HISTORY`/`E_MILESTONE.weight` 真算（M 已示范跨表聚合，成本低）；`risk-warnings`/`trace`/`archive-checklist.validate` 视工作量——`trace` 复用 00-common 追溯节点表读；`archive-checklist.validate` 真查清单完成度。若某计算端点本轮不实现，明确保留 `oapi.Passthrough` 并在计划里登记，勿静默半实现。

### 3.3 甘特图进度（截图「自动化任务推进 + 甘特图跟踪进度」）

数据源即 `E_MILESTONE`（due_date/actual_date/status/weight）+ `E_TASK`。后端只需真实返回里程碑/任务列表；前端 `ProjectView.vue` 增加甘特视图（纯前端渲染，按 due/actual 画条 + 完成百分比重算健康度）。不引入第三方甘特库，用 CSS/内联 SVG 绘制，保持自包含。

### 3.4 权限

- 项目负责人（R-STAFF 且 pi_user_id=本人）：查看/编辑本人项目、派工、填报进度、发起变更/中检/结题。
- R-MANAGER/R-LEADER：全量查看、审批变更、中检结论、结题审批。
- R-FINANCE：结题财务轨（FIN_REVIEW）。
- R-AUDITOR：只读。
- policy.csv 追加 `/api/v1/project*` 相应 p 规则；BuildCaps 派生前端 caps。

---

## 4. 域 R · 科研成果管理（真实化）

### 4.1 范围

给已存在的 `R_OUTPUT` + 六张扩展表（`R_PAPER_EXT/R_PATENT_EXT/R_SOFTWARE_EXT/R_STANDARD_EXT/R_AWARD_EXT/R_BOOK_EXT`）+ `R_CLAIM_RECORD / R_METRIC_SNAPSHOT / R_DATASET / R_OUTPUT_PROJECT` 建真实 store + handler + 路由 + 权限，前端成果屏（现有 `ClaimView.vue` 认领 + 新增/接通成果列表屏）切真实 API。

### 4.2 端点实现分类（对齐契约 15 端点）

- **list/read**：`listOutputs`、`getOutput`（含对应扩展表 join）、`listMyOutputs`（ABAC author/owner=本人）、`listPendingClaim`（claim_status=PENDING/UNCLAIMED 且命中本人署名）、`listPatents`（output_type=PATENT 的生命周期视图）、`listMetricSnapshots`。
- **action**：`createOutput`（分配 code、写扩展表、算 title_hash 去重键）、`claimOutputs`/`rejectOutputs`/`markNotMine`（改 claim_status + 写 R_CLAIM_RECORD）、`linkProjects`（写 R_OUTPUT_PROJECT）。
- **AI（保留 passthrough）**：`aiFill`、`aiDedup` 属 AI hint，本轮**不实现真实算法**，保留 `oapi.Passthrough`，计划中登记为后续。
- **集成（保留 passthrough）**：`refreshCited`（全球引文库外部集成）、`exportOutputs`（导出，若无导出基础设施则保留 passthrough 或最小 CSV 实现——计划中定夺）。

### 4.3 成果全生命周期（截图「论文/专利/著作/获奖/标准/软件」）

`R_OUTPUT.output_type` + 对应 `R_*_EXT` 扩展表已建模，真实化即：create 时按 output_type 落扩展表、read 时 join 扩展表回填。专利预申请→申请→公开→授权→年费→转让 的生命周期用 `R_PATENT_EXT` 状态列承载（沿用契约既有定义，不新增）。

### 4.4 权限

- R-STAFF：查看/新建本人成果、认领/否认 pending-claim（ABAC 限命中本人）。
- R-MANAGER/R-LEADER：审核成果、关联项目。
- R-AUDITOR：只读。
- policy.csv 追加 `/api/v1/output*`；`ai-fill`/`ai-dedup`/`refresh-cited` 由 passthrough 兜底，权限规则一并登记避免前端 caps 缺失。

---

## 5. 域 N · 专家与评审管理（新建）

### 5.1 数据表（DDL：`design/15-专家与评审管理-N.ddl.sql`，表前缀 `n_`）

**n_expert**（专家库主表）
- 通用列 + `security_level`。
- 业务列：`name VARCHAR(64) NOT NULL`、`gender VARCHAR(8)`、`title VARCHAR(64)`（职称，sys_dict）、`education VARCHAR(32)`、`org_name VARCHAR(128)`（所在单位）、`dept VARCHAR(128)`、`phone VARCHAR(32)`、`email VARCHAR(128)`、`user_id BIGINT`（逻辑→sys_user，本院专家可空=纯外部）、`source VARCHAR(16)` CHECK(INTERNAL/EXTERNAL)、`field_tags JSONB DEFAULT '[]'`（研究领域标签数组，sys_dict）、`expertise_level VARCHAR(16)` CHECK(JUNIOR/SENIOR/EXPERT)、`avoid_orgs JSONB DEFAULT '[]'`（回避单位名列表）、`avoid_person_ids JSONB DEFAULT '[]'`（回避人员 user_id）、`bank_account JSONB`（评审费收款信息，加密列走 X 治理）、`cv_doc_ids JSONB DEFAULT '[]'`（O 域 document id）、`last_review_at TIMESTAMPTZ`、`review_count INT DEFAULT 0`。
- 状态：`status CHECK(CANDIDATE/ACTIVE/SUSPENDED/BLACKLIST)`。
- 唯一：`uk_n_expert_code (tenant_id, code) WHERE deleted=0`；索引：`(tenant_id,status)`、`field_tags GIN`、`user_id`。

**n_expert_group**（专家分组/遴选池，轻量）
- `id`、`name VARCHAR(128)`、`tenant_id`、`criteria JSONB`（筛选条件快照）、`expert_ids JSONB DEFAULT '[]'`、通用列。唯一 `uk_n_group_name(tenant_id,name) WHERE deleted=0`。

**n_review_task**（评审任务/事件）
- 通用列 + `code`（RVW-年-序）、`security_level`。
- 业务列：`biz_type VARCHAR(24)` CHECK(MID_CHECK/FINAL_ACCEPT/OUTPUT_EVAL/PROJECT_APPLY/OTHER)、`target_type VARCHAR(32)`（被评审对象类型 token）、`target_id BIGINT`（逻辑外键→E_MID_CHECK/E_FINAL_ACCEPT/R_OUTPUT/E_PROJECT id）、`project_id BIGINT`（逻辑→E_PROJECT，用于回避判定）、`title VARCHAR(256)`、`review_method VARCHAR(16)` CHECK(RANDOM/COMBINATION/MANUAL)、`plan_count INT NOT NULL`（拟抽专家数）、`draw_rule JSONB`（{field_tags:[], min_title, org_diversity, exclude_user_ids[], exclude_orgs[]}）、`status`、`conclusion VARCHAR(16)` CHECK(PASS/Fail/CORRECT/…按 biz_type 语义)、`score_summary JSONB`、`drawn_at/started_at/concluded_at TIMESTAMPTZ`。
- 状态机：`DRAFT → DRAWN → INVITING → QUORUM → IN_REVIEW → COLLECTING → CONCLUDED`；分支 `CANCELLED`。
- 唯一 `uk_n_task_code`；索引 `(project_id,biz_type)`、`(target_type,target_id)`、`(tenant_id,status)`。

**n_review_invitation**（抽取/邀请名单）
- `id`、`task_id REFERENCES n_review_task`、`expert_id REFERENCES n_expert`、`seat_no INT`、`avoid_hit BOOLEAN DEFAULT FALSE`（回避命中审计）、`response VARCHAR(16)` CHECK(PENDING/ACCEPT/DECLINE/EXPIRED)、`invited_at/responded_at TIMESTAMPTZ`、`tenant_id`、`created_at`。
- 唯一 `uk_n_invite (task_id, expert_id)`。

**n_review_score**（在线打分）
- `id`、`task_id REFERENCES n_review_task`、`expert_id REFERENCES n_expert`、`target_type/target_id`、`dimension_scores JSONB`（[{dim,score,max}]）、`total_score NUMERIC(10,2)`、`comment TEXT`、`status` CHECK(SUBMITTED/ABSTAIN)、`submitted_at`、`tenant_id`。
- 唯一 `uk_n_score (task_id, expert_id)`。

**n_review_fee**（评审费，联动 F）
- 通用列 + `task_id REFERENCES n_review_task`、`expert_id REFERENCES n_expert`、`amount NUMERIC(18,2) NOT NULL`、`pay_channel VARCHAR(32)`（sys_dict）、`pay_status` CHECK(UNPAID/PAID)、`paid_at`、`voucher_code VARCHAR(64)`（逻辑→F 凭证）。
- 唯一 `uk_n_fee (task_id, expert_id)`。

### 5.2 端点（tag: expertreview）

专家库：
- `GET/POST /experts`、`GET/PUT/DELETE /experts/{id}`、`POST /experts/{id}/status`（启用/暂停/黑名单）。
- `GET /experts/groups`、`POST /experts/groups`（可选，若本轮从简则登记后续）。

评审任务与抽取：
- `GET/POST /reviews`、`GET /reviews/{id}`、`DELETE /reviews/{id}`。
- `POST /reviews/{id}/draw` body{method?,plan_count?}：**核心抽取引擎**——按 `draw_rule` 从 `n_expert(status=ACTIVE)` 过滤（领域/职称匹配）→ 剔除回避（`avoid_orgs ∩ 项目承担单位`、`avoid_person_ids ∩ 项目成员/PI`、专家本人 `user_id ∩ 项目成员`）→ RANDOM（洗牌取 N，可传 seed 复现）或 COMBINATION（按单位/职称分层配额取 N）→ 生成 `n_review_invitation`（seat_no 排序，avoid_hit 记录被剔除者供审计）→ task DRAFT→DRAWN。
- `POST /reviews/{id}/invite`（DRAWN→INVITING，回填 `E_MID_CHECK.expert_ids`=已接受专家 user_id，见 §5.5）。
- `POST /reviews/{id}/accept`/`decline`（专家本人或代录，更新 invitation.response；达法定人数→QUORUM）。
- `POST /reviews/{id}/start`（QUORUM→IN_REVIEW）。
- `POST /reviews/{id}/scores`（专家提交打分，写 n_review_score；全员完成→COLLECTING）。
- `POST /reviews/{id}/conclude` body{conclusion}：汇总 score_summary→CONCLUDED，并**回写 E/R 业务对象**（§5.5）。
- `POST /reviews/{id}/cancel`、`POST /reviews/{id}/fees`（生成评审费，联动 F）。
- `GET /reviews/{id}/statistics`（分布/命中，可保留 passthrough 若从简）。

### 5.3 权限

- 专家库增删改、抽取、邀请、结论、评审费：R-MANAGER/R-LEADER/R-ADMIN。
- 打分/接受/拒绝：R-EXPERT（ABAC 限 invitation.expert_id 关联到当前 user 或代录授权）。
- 查看：R-AUDITOR 只读全量；R-MANAGER 全量；专家仅见自身邀请/打分。
- policy.csv 追加 `/api/v1/experts*`、`/api/v1/reviews*`；BuildCaps 派生。

### 5.4 前端

- `views/ExpertReviewView.vue`（Tab）：① 专家库（列表 + 领域/职称/状态筛选 + 新建/编辑抽屉 + 回避关系维护 + 启停）；② 评审任务（列表 + 新建 + **抽取面板**：选方法/拟抽数/规则→预览命中名单→确认→邀请）；③ 打分与结论（任务详情 + 专家打分进度 + 汇总 + 结论回写按钮）；④ 评审费（列表 + 生成/发放）。
- 路由 `{ path:'/expert-review', name:'expert-review', meta:{zh:'专家与评审', roles:[R-EXPERT,R-MANAGER,R-LEADER,R-AUDITOR,R-ADMIN]} }`；侧栏新增「专家与评审」项（`v:'expert-review'`）。
- mock override `overrides/expertreview.ts`。

### 5.5 回写 E/R（跨模块写，经 E/R 真实 service 单一写者）

- 抽取邀请接受后：`E_MID_CHECK.expert_ids` ← 已接受专家 `user_id` 数组（经 E 域导出的 store 方法 `SetMidCheckExperts(ctx, midCheckID, userIds)`，N 不直接 UPDATE E 表，保持 E 为单一写者）。
- 结论回写：`conclude` 时按 `biz_type` 调 E/R 导出方法：
  - MID_CHECK → `E.ConcludeMidCheck(id, conclusion, scoreSummary)`：置 `E_MID_CHECK.status=CONCLUDED`、`conclusion`，并按结论驱动 `E_PROJECT.status`（CONTINUE→EXECUTING / CORRECT→CORRECTING / TERMINATE→TERMINATED）。
  - FINAL_ACCEPT → `E.ConcludeFinalAccept(id, pass)`：TECH_REVIEW 轨结论回写 `E_FINAL_ACCEPT.status`（APPROVED/REJECTED/NEED_SUPPLEMENT）。
  - OUTPUT_EVAL → `R.ConcludeOutputEval(outputId, pass)`：回写 `R_OUTPUT.status`/认定标记。
- 依赖：N 在 E/R 之后实现（计划顺序保证）；E/R store 须导出上述方法（在 E/R 任务里一并落地并在计划中交叉引用）。

---

## 6. 域 O · 科研档案管理（新建）

### 6.0 与 E 内既有档案的边界

`E_PROJECT_DOC`（项目过程文档）、`E_ARCHIVE_CHECKLIST`（项目归档清单）是**项目过程内**的档案，保留在 E 域。本轮 O 是**跨域独立档案库**：以「案卷」为单位，`source_module + source_id` 指回任意来源对象（E 项目 / R 成果 / F 经费单据 / P 申报 / G 合同 / V 活动…），统一门类清单 + 四性检测 + 入库 + 借阅 + 全文检索。二者不重叠：E 管过程内文档，O 管归档卷宗（可摄取 E 文档作为来源之一）。

### 6.1 数据表（DDL：`design/16-科研档案管理-O.ddl.sql`，表前缀 `o_`）

**o_document**（电子件元数据，对象存储）
- 通用列 + `security_level`。
- 业务列：`name VARCHAR(256) NOT NULL`、`doc_type VARCHAR(64)`（mime/扩展名）、`size_bytes BIGINT`、`bucket VARCHAR(64)`、`object_key VARCHAR(512)`（MinIO key）、`checksum_sha256 VARCHAR(64)`、`uploader_id BIGINT`、`uploaded_at TIMESTAMPTZ`、`source_module VARCHAR(8)`、`source_id BIGINT`（逻辑外键，可空）、`text_content TEXT`（抽取正文，供全文检索）、`status` CHECK(UPLOADING/STORED/MISSING)。
- 唯一 `uk_o_doc_key(tenant_id, bucket, object_key) WHERE deleted=0`；索引 `text_content` 走 `GIN(to_tsvector('simple', text_content))` + `pg_trgm`（`00-common.sql` §0 已前置 `CREATE EXTENSION pg_trgm`）。

**o_archive**（案卷）
- 通用列 + `code`（ARC-年-序）、`security_level`。
- 业务列：`title VARCHAR(256) NOT NULL`、`archive_type VARCHAR(24)` CHECK(PROJECT/OUTPUT/EXPENSE/CONTRACT/ACTIVITY/OTHER)、`source_module VARCHAR(8)`、`source_id BIGINT`（逻辑→来源对象）、`source_code VARCHAR(64)`、`owner_dept_id BIGINT`（逻辑→sys_org）、`retention_years INT`（保管期限）、`submitter_id/submit_at`、`archivist_id/filed_at`、`status`。
- 状态机：`PENDING_SUBMIT → SUBMITTED → CHECKING → PASSED → ARCHIVED`；`CHECKING → REJECTED →(补正) SUBMITTED`；`ARCHIVED → DESTROYED`（到期销毁，走审批）。
- 唯一 `uk_o_arc_code`；索引 `(source_module,source_id)`、`(tenant_id,status)`。

**o_archive_item**（归档门类清单条目）
- `id`、`archive_id REFERENCES o_archive`、`category_code VARCHAR(64)`（门类，sys_dict）、`category_name VARCHAR(128)`、`required BOOLEAN DEFAULT TRUE`、`doc_id REFERENCES o_document`（可空=缺）、`status` CHECK(MISSING/FILLED/CHECKED)、`sort_no INT`、`tenant_id`。
- 唯一 `uk_o_item (archive_id, category_code)`。

**o_archive_check**（四性检测报告）
- `id`、`archive_id REFERENCES o_archive`、`check_type VARCHAR(16)` CHECK(AUTHENTICITY/INTEGRITY/USABILITY/SECURITY)、`result` CHECK(PASS/FAIL/WARN)、`detail JSONB`、`checked_at`、`checker_id`、`tenant_id`。
- 唯一 `uk_o_check (archive_id, check_type)`。

**o_borrow**（借阅申请）
- 通用列 + `code`（BORROW-年-序）、`archive_id REFERENCES o_archive`、`borrower_user_id BIGINT`、`purpose VARCHAR(512)`、`borrow_type` CHECK(READ/COPY)、`approved_by/approved_at`、`due_at/returned_at`、`status` CHECK(SUBMITTED/APPROVED/REJECTED/RETURNED/EXPIRED)。
- 索引 `(archive_id,status)`、`(borrower_user_id)`。

### 6.2 端点（tag: archive）

文件与文档：
- `POST /documents`（multipart 上传→MinIO→写 o_document，返回 id/object_key；供 N/E/O 复用）、`GET /documents/{id}`、`GET /documents/{id}/download`（presigned URL 或流）、`DELETE /documents/{id}`（软删 + 可选对象删除）。

案卷与归档流程：
- `GET/POST /archives`、`GET/PUT/DELETE /archives/{id}`、`GET /archives/{id}/items`、`POST /archives/{id}/items`（挂门类条目/文档）、`DELETE /archives/{id}/items/{itemId}`。
- `POST /archives/{id}/ingest` body{source_module,source_id}：从来源对象拉取文档生成清单条目（如从 E 项目摄取 E_PROJECT_DOC）。
- `POST /archives/{id}/submit`（PENDING_SUBMIT→SUBMITTED）。
- `POST /archives/{id}/check`：**四性检测**（真实性=checksum 校验、完整性=required 门类齐备、可用性=格式/可读、安全性=密级/权限），写 o_archive_check，全 PASS→CHECKING→PASSED，否则→REJECTED/保持 CHECKING。
- `POST /archives/{id}/file`（PASSED→ARCHIVED，档案员确认入库）。
- `POST /archives/{id}/destroy` body{reason}（ARCHIVED→DESTROYED，审批 + 留痕）。

检索与借阅：
- `GET /archives/search?keyword=&type=&dept=&from=&to=`（全文 + 元数据过滤，ABAC 密级）。
- `POST /archives/{id}/borrow`、`GET /borrows`、`POST /borrows/{id}/approve`/`reject`、`POST /borrows/{id}/return`。
- `GET /archives/stats`（归档完成度/门类分布，可保留 passthrough 若从简）。

### 6.3 权限

- 上传/建案卷/提交：R-STAFF（本人来源对象关联）。
- 四性检测/入库/销毁：R-ADMIN（档案员，或新增 `R-ARCHIVIST` 角色——若加须同步 00-common 角色枚举 + 前端 roles；本轮倾向复用 R-ADMIN/R-MANAGER，避免角色枚举漂移，计划中定夺）。
- 借阅审批：R-MANAGER/R-ADMIN。借阅人：登录用户（ABAC 密级 + 案卷可见性）。
- 检索：ABAC tenant + security_level（涉密案卷仅对应密级可见，复用 X hook）。
- policy.csv 追加 `/api/v1/documents*`、`/api/v1/archives*`、`/api/v1/borrows*`。

### 6.4 前端

- `views/ArchiveView.vue`（Tab）：① 案卷台账（列表 + 状态/门类筛选 + 新建 + 摄取来源 + 提交/检测/入库/销毁动作，按角色门控）；② 四性检测（报告展示）；③ 全文检索（关键词高亮）；④ 借阅（我的借阅 + 审批）。
- 路由 `{ path:'/archive', name:'archive', meta:{zh:'科研档案', roles:[R-STAFF,R-MANAGER,R-LEADER,R-AUDITOR,R-ADMIN]} }`；侧栏「科研档案」项（`v:'archive'`）。
- mock override `overrides/archive.ts`。

---

## 7. 对象存储基础设施（MinIO）

- `docker-compose.yml` 新增 `minio` 服务（`minio/minio`，`server /data --console-address ":9001"`，卷 `minio-data`，端口 9000/9001，env `MINIO_ROOT_USER/PASSWORD`，healthcheck）；backend 服务加 env `ARK_S3_ENDPOINT=http://minio:9000`、`ARK_S3_ACCESS_KEY`、`ARK_S3_SECRET_KEY`、`ARK_S3_BUCKET=ark-docs`、`depends_on minio: service_healthy`。
- Go 新增 `internal/platform/storage`：封装 minio-go/v7（或 aws-sdk-go-v2 S3），提供 `Put/Get/PresignURL/Remove`；`cmd/server` 初始化注入 `Deps.Storage`。
- 上传端点归属 O 域 `/documents`（multipart→Put→写 o_document）；E/N 引用返回的 document id/object_key。
- 无 MinIO 的宿主（本地无 docker）：storage 客户端初始化失败时，O 上传端点返回明确 503 业务码，单测用假 storage 接口（`storage.Bucket` 接口 + fake）覆盖，DB/MinIO 门控集成测试 `ARK_S3_ENDPOINT` 缺省则 SKIP（与既有 DB-gated 测试同策略）。
- 依赖新增：`github.com/minio/minio-go/v7`（定向 `go get`，禁 `go mod tidy`）。

---

## 8. 跨模块数据流总览

- **E→O**：`POST /archives/{id}/ingest` 从 E_PROJECT_DOC 摄取文档建清单条目。
- **R→O**：成果认定材料、专利证书等经 O 归档。
- **N→E**：抽取接受→`E.ConcludeMidCheck`/`SetMidCheckExperts` 回写中检专家与结论→驱动 `E_PROJECT.status`。
- **N→E(final)**：结题技术轨结论→`E.ConcludeFinalAccept`。
- **N→R**：成果评价结论→`R.ConcludeOutputEval`。
- **N→F**：评审费→F 凭证（逻辑外键 voucher_code，本轮仅登记关联，不强制建 F 真实切片）。
- **M→(E/R/T/F)**：M 已直读真表（上一轮完成），E/R 真实化后 M 取数从种子演示升级为真实业务数据（无代码改动，数据自然变实）。

---

## 9. 测试策略（复刻 V/M 模式）

- **sqlc 单测**：假 pool（`dbtest`）覆盖各 store CRUD/list 过滤（含 narg 空过滤回归）。
- **contract_test**：每域 handler 响应结构对齐契约 schema（复用 verify 思路）。
- **handler_test**：路由级——list/read/create/action happy path + 非法状态迁移 40901 + ABAC 越权 40301 + 不存在 40401。DB-gated（`ARK_TEST_DATABASE_URL`）真库跑；无库 SKIP。
- **policy/caps_test**：E/R/N/O 的 policy.csv 规则 → BuildCaps 派生 caps 断言（各角色可见端点集合）。
- **N 抽取引擎单测**：给定专家池 + 回避规则 + seed → 断言命中名单确定性、回避剔除正确、法定人数判定。
- **N→E/R 回写集成测**：DB-gated，抽取→邀请接受→conclude→断言 `E_MID_CHECK.expert_ids`/`status`/`E_PROJECT.status` 被正确回写。
- **O 四性检测单测**：缺 required 门类→INTEGRITY FAIL；checksum 不符→AUTHENTICITY FAIL；全通过→PASSED。上传测用 fake storage 接口。
- **前端**：`vue-tsc` typecheck + `VITE_USE_MOCK=true build` 双 exit 0；命名三向 1:1 grep 校验（新增 E/R 接通 + N/O 两屏）。
- **drift**：`make drift` 重跑 codegen 零 diff（sqlc 生成物 + oapi models + migrations）——须扩 drift 路径加 `internal/modules/{project,output,expertreview,archive}/store`。

---

## 10. 分相与任务分解地图（单一计划内部顺序）

> 主人选「单一全覆盖计划」。实现计划按下列依赖顺序展开为连续任务；每相内复刻 V/M 的任务粒度（契约→DDL→sqlc→store→mapper→handler→routes→policy→contract/handler test→前端接通→seed）。

- **Phase 0 基础设施**：MinIO compose 服务 + `internal/platform/storage` + fake 接口 + 依赖定向 go get。
- **Phase 1 域 E 真实化**：sqlc E 引擎块 + `db/query_e` + estore + mapper + handler（15 端点分类）+ routes + policy + tests + 前端 ProjectsView/ProjectView 接通 + 甘特视图 + seed_e.sql。**导出回写方法** `SetMidCheckExperts/ConcludeMidCheck/ConcludeFinalAccept`（供 N）。
- **Phase 2 域 R 真实化**：sqlc R 引擎块 + `db/query_r` + rstore + handler（list/read/action 真实，AI/export passthrough 保留）+ routes + policy + tests + 前端成果屏接通 + seed_r.sql。**导出** `ConcludeOutputEval`（供 N）。
- **Phase 3 域 N 新建**：`15-…-N.{detail.md,ddl.sql,openapi.yaml}` + cp 前端副本 + 前缀登记 + sqlc N 块 + nstore + 抽取引擎 + handler + routes + policy + tests（含回写集成，依赖 Phase1/2 方法）+ ExpertReviewView + override。
- **Phase 4 域 O 新建**：`16-…-O.{detail.md,ddl.sql,openapi.yaml}` + cp + 前缀登记 + sqlc O 块 + ostore + storage 接线 + 四性检测 + handler + routes + policy + tests + ArchiveView + override。
- **Phase 5 收口**：drift 路径扩展 + 全量 codegen + 全量 test + 前端 typecheck/build + 命名三向 grep + 契约字节同步 + 覆盖率报告。

> 交叉引用铁律（记忆教训）：新增任务后回改自审/文件结构映射/§中的任务号与包名；勿引用未创建文件。`store.E`/`store.R` 导出方法名在计划里须与 N 调用点逐字一致。

---

## 11. 规格自审（写后内联检查）

- **占位符**：无 TBD/TODO；「计划中定夺」项均为已给出默认决策 + 备选（角色 R-ARCHIVIST、export 实现、statistics passthrough），非悬空。
- **内部一致性**：端点分类与 §0.2 契约清单一致；回写方法名在 §3/§5/§10 三处一致（`SetMidCheckExperts/ConcludeMidCheck/ConcludeFinalAccept/ConcludeOutputEval`）；模块字母 N/O 未与既有 P/E/F/R/T/C/S/D/G/A/X/U/V/M 冲突；前缀 EXR/RVW/ARC/BORROW 未与既有登记冲突（EXP 已属 F 报销单，故专家用 EXR 避让）。
- **范围**：四域 + MinIO，体量大但依赖链清晰、单一计划内分相可控；已明确剔除表单设计器/BPM/移动端/SSO/低代码。
- **模糊**：档案员角色已给默认（复用 R-ADMIN/R-MANAGER）；AI/export 已明确保留 passthrough；O 摄取 E 文档的边界已界定。

---

## 12. 完成定义（DoD）

1. E/R/N/O 四域契约端点中「真实化」类全部由真实 Go handler+store 提供（AI/export/computed 明确保留 passthrough 并登记）。
2. `make drift` 零 diff；`design/*.openapi.yaml` 与 `frontend/src/api/schema/` 字节同步。
3. 后端全量 `go test`（无库 SKIP）0 FAIL；DB-gated 集成测在备库环境全绿；N 回写、O 四性检测、抽取确定性单测通过。
4. 前端 `vue-tsc` + `VITE_USE_MOCK=true build` 双 exit 0；E/R 接通 + N/O 两新屏；命名三向 1:1 grep 通过。
5. MinIO 经 compose 起服务，`/documents` 上传→下载→presign 端到端可用（备 docker 环境）。
6. seq_prefix_registry 登记 EXR/RVW/ARC/BORROW；MODULE_CODES 加 15/16。
7. 提交到 develop（每相/每交付一 commit），**不推送**，推送/PR/合并须主人确认。

---

## 13. 执行移交

规格经主人批准后，调用 `superpowers-writing-plans` 基于本规格生成**单一全覆盖实现计划**（bite-sized TDD 任务，按 §10 分相顺序）。计划的终态是产出可执行任务清单；实现阶段用子 Agent 逐任务/逐相驱动，每交付一 commit，不自动推送。
