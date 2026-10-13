# 科研管理系统 · 详细设计与接口契约

**版本**：v1.0 · **日期**：2026-10-13
**上游文档**：`../PRODUCT_PLAN.md`（产品规划 v1.1）、`../TECH_ARCHITECTURE.md`（架构与技术方案 v1.0）、`../PRD/README.md`（PRD 通用规约 v1.1）及 01–11 模块 PRD
**读者对象**：后端开发、前端开发、测试、DBA、AI 工程师

> 本目录把 M1 核心模块的 PRD 落地为可实现的**详细设计 + 数据库 DDL + OpenAPI 接口契约**。术语、命名、状态、编号一律以 `../PRD/README.md` 为准，本文只引用与实现，不重复定义。

---

## 一、交付物与目录结构

每个核心模块交付三件套：

```
design/
  README.md                    ← 本文件：全局约定 + 共享实体登记表 + 产物索引
  00-common.sql                ← 横切平台表（字典/制度包/编号中心/组织/法人/用户/打印模板/审计）
  <模块>-<代号>.detail.md       ← 详细设计（字段字典/服务分层/业务规则/事件契约/校验）
  <模块>-<代号>.ddl.sql         ← 该模块建表 DDL（PostgreSQL 15 方言，含信创达梦差异注记）
  <模块>-<代号>.openapi.yaml    ← 该模块对外 REST 契约（OpenAPI 3.0.3，可导入 Swagger/Postman）
```

M1 核心模块范围：01 申报(P) · 02 过程(E) · 03 经费(F) · 04 成果(R) · 07 人员(S) · 09 采购与合同(G) · 10 资产与耗材(A)。05/06/08/11 的 P0 骨架并入 M1，但详细设计延后到 M2，本批次不交付。

---

## 二、数据库落地约定（对齐 PRD 2.2 / 2.6 / 2.7 / 2.8 / 2.11 / 2.12 / 2.13）

### 2.1 通用字段（所有业务表默认含，DDL 中不再逐表注释）

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` | 主键 |
| `code` | `VARCHAR(64) UNIQUE` | 业务编号（人可读，取自统一编号中心） |
| `tenant_id` | `BIGINT NOT NULL` | 多租户隔离键（总院法人边界） |
| `status` | `VARCHAR(32) NOT NULL` | 状态，取值为大写蛇形 token（见 §四） |
| `deleted` | `SMALLINT NOT NULL DEFAULT 0` | 逻辑删除（0 正常 / 1 删除） |
| `creator_id` | `BIGINT NOT NULL` | 创建人 user_id |
| `modifier_id` | `BIGINT` | 最后修改人 |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | 创建时间 |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | 更新时间 |
| `remark` | `TEXT` | 备注 |

**v1.1 治理三字段**（G/A/X 及涉及成本归属的 F 表额外携带）：`legal_entity_id BIGINT NOT NULL`（法人细分，PRD 2.12）、`security_level VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'`（`PUBLIC/INTERNAL/SECRET/TOP_SECRET`，PRD 2.13）、`policy_pack_id BIGINT`（命中制度包快照，PRD 2.10，用于复算）。

> **软删 + 唯一**：`code` 在含逻辑删除场景下用**部分唯一索引** `WHERE deleted = 0` 实现，避免删除后编号复用冲突。

### 2.2 标量约定

- 金额一律 `NUMERIC(18,2)`（单位元，PostgreSQL `DECIMAL` 同义）；比例/置信度用 `NUMERIC(6,4)`。
- 时间一律 `TIMESTAMPTZ`（时区基准 Asia/Shanghai，落库存 UTC）；纯日期用 `DATE`。
- 半结构化（作者列表、评分明细、分录、JSON 表单）用 `JSONB`，高频查询字段另建表达式索引或提升为生成列。
- 枚举优先用 `VARCHAR + CHECK (IN (...))` 而非数据库原生 ENUM，便于信创达梦迁移与灰度扩值；字典可配项一律走 `sys_dict`，禁止硬编码（PRD 2.8）。

### 2.3 命名规约

- **表名**：`{模块前缀}_{业务名}`，前缀取 `P_/E_/F_/R_/T_/C_/S_/D_/G_/A_/X_`，模块前缀体系唯一。
- **单号前缀**（`code` 值里的前缀）：以 `../PRD/README.md` 2.11 注册表为唯一来源（PRJ/BUD/EXP/DISB/REQ/ORD/SUP/SOSC/CON/OSC/AST/DSP/…）。**表名前缀与单号前缀分属两套体系，互不混用。**
- **外键列**：`{被引表去前缀语义}_id`；跨模块引用只存对方主键 `id`（`BIGINT`），不建跨模块物理外键（微服务库隔离），一致性走事件（见 `../TECH_ARCHITECTURE.md` §八）。同模块内允许物理外键。
- **索引**：查询主路径 `(tenant_id, legal_entity_id, status)` 组合索引 + `code` 唯一 + `project_id`/`*_user_id` 常用过滤列单独索引。

### 2.4 信创达梦差异注记（DDL 顶部统一声明，达梦部署时按此替换）

| 项 | PostgreSQL 15（默认） | 达梦 / 信创替代 |
|----|----------------------|-----------------|
| 自增主键 | `GENERATED ALWAYS AS IDENTITY` | `IDENTITY(1,1)` |
| 时间戳 | `TIMESTAMPTZ` | `TIMESTAMP WITH TIME ZONE` |
| 布尔 | `BOOLEAN` | `SMALLINT`（0/1） |
| JSON | `JSONB` | `CLOB`/`VARCHAR` 存 JSON 文本 + 应用层解析 |
| 数组/`IN` CHECK | `CHECK(col IN(...))` | 同 |
| 全文检索 | `pg_trgm / tsvector` | 应用层 ES / 达梦全文索引 |
| 部分唯一索引 | `CREATE UNIQUE INDEX ... WHERE` | 用普通唯一索引 + `deleted` 复合键替代 |
| 向量 | `pgvector` | Milvus 独立服务 |

---

## 三、API 落地约定（对齐 PRD 2.5）

- 风格 RESTful：`/api/{version}/{module}/{resource}`，version=`v1`。
- 统一响应包裹：

```json
{ "code": 0, "message": "ok", "data": {}, "traceId": "...", "timestamp": 1700000000000 }
```

- 分页：请求 `page`(1-based)+`size`（默认 20，上限 200）；响应 `data = { list: [], total: 0, page, size }`。
- 认证：`Authorization: Bearer <JWT>`；刷新走 Refresh Token。
- 幂等：所有 `POST/PUT` 支持 `Idempotency-Key` 请求头（UUID，服务端缓存去重）。
- 限流：普通 100 req/min，AI 接口 20 req/min（`429` 返回）。
- 错误码：`code` 非 0 为业务错误，HTTP 状态表达传输层（2xx/4xx/5xx）；`06 异常处理` 分节列模块级错误码。
- OpenAPI 每个模块为**自包含 3.0.3 文档**（含自身 `info/servers/paths/components`），可单独导入 Swagger Editor / Postman。

### 3.1 事件契约（内部 Kafka）

命名 `domain.action`，value 为 JSON，必带 `{ eventId, eventType, occurredAt, tenantId, legalEntityId, traceId, payload }`。跨模块事件（到货转资产、外拨联动、成本分摊、项目立项）遵循 `../TECH_ARCHITECTURE.md` §八的 Saga 编排，落库记录 `policy_pack_id` 快照。

---

## 四、状态 token 登记表（PRD 2.6）

状态持久态为大写蛇形 token，中文仅 `TOKEN=中文` 映射。各模块状态机 token 汇总（DDL `CHECK` 与 OpenAPI `enum` 以此为准）：

| 模块 | 主体 | 状态 token 序列 |
|------|------|-----------------|
| P | 申报 | `DRAFT/SUBMITTED/FORMAL_CHECK/RECOMMENDED/UNDER_REVIEW/INTERVIEWING/DECIDED/PUBLISHED/SIGNED/EXECUTING/REJECTED/WITHDRAWN` |
| P | 决议 | `DRAFT/APPROVED/REJECTED/PENDING_INTERVIEW` |
| E | 项目 | `EXECUTING/MID_CHECK/DELAYED/COMPLETING/CLOSED/TERMINATED`（含整改 `CORRECTING`、变更 `CHANGING`） |
| E | 中检结论 | `CONTINUE/CORRECT/TERMINATE` |
| E | 结题结论 | `PASS/PASS_WITH_CONDITIONS/FAIL` |
| F | 预算 | `DRAFT/SUBMITTED/UNDER_REVIEW/APPROVED/EXECUTING/ADJUSTING/RE_APPROVED/CLOSED` |
| F | 报销 | `DRAFT/SUBMITTED/AI_REVIEW/HUMAN_REVIEW/APPROVED/REJECTED/RETURNED/PAID/VOUCHER_SYNCED` |
| F | 到账认领 | `UNCLAIMED=未认领/AUTO_MATCHED=自动匹配/CLAIMED=人工认领/DOUBTFUL=存疑` |
| F | 异常级别 | `HIGH/MED/LOW` |
| R | 成果 | `AUTO_FETCHED/PENDING_CLAIM/CLAIMED/ASSIGNED_TO_PROJECT/COUNTED_FOR_PERFORMANCE/MANUAL_DRAFT/PENDING_REVIEW/REJECTED` |
| S | 雇佣状态 | `ONBOARD=在职/RESIGNED=离职/RETIRED=退休/VISITING=访问/GUEST=客座/REHIRE=返聘` |
| G | 采购申请 | `DRAFT/SUBMITTED/WAY_DECIDED/BIDDING/ORDERED/CANCELLED` |
| G | 供应商 | `PENDING/IN_LIBRARY/REJECTED/EXPIRED` |
| G | 招标 | `PUBLICIZING/AWARDED/CHALLENGE` |
| G | 合同 | `DRAFT/REVIEW/TO_SIGN/ACTIVE/AMENDING/SETTLING/ARCHIVED/TERMINATED` |
| G | 订单 | `DRAFT/CONFIRMED/EXECUTING/COMPLETED/CANCELLED` |
| G | 到货 | `PENDING/SHIPPED/ARRIVED/ACCEPTED/REJECTED` |
| A | 资产 | `PENDING_RECEIPT/IN_USE/IDLE/UNDER_MAINT/TRANSFERRING/PENDING_DISPOSE/DISPOSED` |
| A | 耗材库存 | `IN_STOCK/LOW_STOCK/NEAR_EXPIRY/EXPIRED/STAGNANT` |
| A | 领用 | `REQUESTED/DOUBLE_CONFIRM/ISSUED`（+ `IN_STOCK` 退库回环） |
| A | 处置 | `APPLIED/APPRAISED/APPROVED/EXECUTING/BOOKED/ARCHIVED` |

---

## 五、共享实体登记表（跨模块引用契约）

以下为被多模块引用的"拥有方实体"，其余模块只存其 `id` 作逻辑外键，命名与主键以本表为准，确保跨模块一致：

| 实体（表） | 拥有模块 | 主键 | 业务编号 | 被引列名 |
|------------|----------|------|----------|----------|
| `sys_user` | common | `id` | — | `*_user_id` / `pi_user_id` |
| `sys_org` | common | `id` | — | `department_id` / `dept_id` |
| `sys_legal_entity` | common(X) | `id` | `LE-年-序` | `legal_entity_id` |
| `E_PROJECT` | 02 E | `id` | `PRJ-年-序` | `project_id` |
| `S_STAFF` | 07 S | `id` | — | `staff_id`（`user_id` 关联 sys_user） |
| `F_BUDGET` / `F_BUDGET_LINE` | 03 F | `id` | — | `budget_id` / `budget_line_id` |
| `F_SUBJECT` | 03 F | `id` | 科目编码 | `subject_id` / `budget_subject_code` |
| `F_EXPENSE` | 03 F | `id` | `EXP-年-序` | `expense_id` |
| `G_SUPPLIER` | 09 G | `id` | `SUP-`/`SOSC-` | `supplier_id` / `outsource_unit_id` |
| `G_CONTRACT` | 09 G | `id` | `CON-`/`OSC-` | `contract_id` |
| `A_ASSET` | 10 A | `id` | `AST-年-序` | `asset_id` |
| `A_CONSUMABLE` | 10 A | `id` | sku | `ref_sku` |
| `sys_policy_pack` | common | `id` | — | `policy_pack_id` |
| `E_ARCHIVE_CHECKLIST` | 02 E | `id` | — | `archive_checklist_id` |

引用规则遵循 PRD 2.15 单一事实来源：非拥有模块只读引用，不重复存储可派生字段。

---

## 六、模块产物索引

| 模块 | 代号 | 详细设计 | DDL | OpenAPI |
|------|------|----------|-----|---------|
| 01 项目申报与立项 | P | [detail](./01-项目申报与立项-P.detail.md) | [ddl](./01-项目申报与立项-P.ddl.sql) | [api](./01-项目申报与立项-P.openapi.yaml) |
| 02 项目过程管理 | E | [detail](./02-项目过程管理-E.detail.md) | [ddl](./02-项目过程管理-E.ddl.sql) | [api](./02-项目过程管理-E.openapi.yaml) |
| 03 科研经费管理 | F | [detail](./03-科研经费管理-F.detail.md) | [ddl](./03-科研经费管理-F.ddl.sql) | [api](./03-科研经费管理-F.openapi.yaml) |
| 04 科研成果管理 | R | [detail](./04-科研成果管理-R.detail.md) | [ddl](./04-科研成果管理-R.ddl.sql) | [api](./04-科研成果管理-R.openapi.yaml) |
| 07 人员与团队 | S | [detail](./07-人员与团队-S.detail.md) | [ddl](./07-人员与团队-S.ddl.sql) | [api](./07-人员与团队-S.openapi.yaml) |
| 09 采购与合同管理 | G | [detail](./09-采购与合同管理-G.detail.md) | [ddl](./09-采购与合同管理-G.ddl.sql) | [api](./09-采购与合同管理-G.openapi.yaml) |
| 10 资产与耗材管理 | A | [detail](./10-资产与耗材管理-A.detail.md) | [ddl](./10-资产与耗材管理-A.ddl.sql) | [api](./10-资产与耗材管理-A.openapi.yaml) |

横切平台表见 [00-common.sql](./00-common.sql)。

---

## 七、变更历史

| 版本 | 日期 | 作者 | 说明 |
|------|------|------|------|
| v1.0 | 2026-10-13 | 研发组 | 首批交付 M1 七核心模块详细设计 + DDL + OpenAPI |
