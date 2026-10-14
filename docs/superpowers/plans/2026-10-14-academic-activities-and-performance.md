# 学术活动管理(V) + 科研绩效评价(M) 端到端实现计划

**目标：** 新增两个当前完全缺失的业务域——模块 13 学术活动管理（字母 V）、模块 14 科研绩效评价（字母 M）——按 P/U 已验证的垂直切片做到端到端真实现：契约 → DDL → 迁移 → sqlc → Go handler+store → Casbin+ABAC → 前端真实接通 + mock override → 测试。

**架构：** 契约驱动单真源。`design/13-*.openapi.yaml`/`design/14-*.openapi.yaml` 与 `design/13-*.ddl.sql`/`design/14-*.ddl.sql` 为源；契约逐字节 `cp` 到 `frontend/src/api/schema/`；DDL 经 `migrations/gen.go` 自动汇入 `000001_init.up.sql`。后端每个新模块一个 sqlc 引擎块（独立裁剪 schema + queries 目录 + package + out），handler 强制以 `auth.DomainFrom(c)` 的数据域作 ABAC 首参，状态机用硬编码端点校验（非通用引擎）。`router.Build` 在 `d.Pool != nil` 时真实 `Register`，覆盖 passthrough。

**技术栈：** Go 1.23 + Gin v1.10 + pgx/v5 + sqlc v1.27（`GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1`）+ Casbin v2（keyMatch2）；PostgreSQL 15；Vue 3.4 + TS 5.3 + Vite 4.5（`VITE_USE_MOCK` 构建期内联）。

**规格真源：** `docs/superpowers/specs/2026-10-14-academic-activities-and-performance-design.md`（commit fef9d85）。本计划逐条落地其 §1–§9。

**环境铁律（每个任务都遵守）：**
- git 分支 = `develop`；**每改一个文件即单独 `git add <文件>`**，不用 `git add -A`/`.`；**完成本计划不自动 push**，收尾询问主人。
- 本机 git-bash：给子进程传环境变量用 `VAR=x cmd` 前缀语法，不用 `set`。
- 本机无 Docker/真库：连库集成用例以 `ARK_TEST_DATABASE_URL` 门控，无则 `t.Skip`。
- 禁 `go mod tidy`（会强拉需 go1.25 的依赖）；新增依赖须定向 `go get`（本计划不引入新依赖，全部复用现有 go.mod）。
- 契约 yaml 改完必须 `cp` 同步到 `frontend/src/api/schema/` 同名文件，两套逐字节一致。
- Glob 工具在 `D:\SynologyDrive\...` 路径可能返回空，列文件用 Bash `ls`/`find`。

---

## 文件结构映射（先锁定分解，再拆任务）

**新建 — V 域（学术活动，包 `activity`，store package `vstore`）：**
- 创建 `design/13-学术活动管理-V.openapi.yaml` — 契约真源（tag: activity；13 endpoints）
- 创建 `design/13-学术活动管理-V.ddl.sql` — 3 表 DDL（`v_activity` / `v_activity_participant` / `v_activity_review`）
- 创建 `design/13-学术活动管理-V.detail.md` — 字段/状态机/权限细则（文档，非编译物）
- 创建 `frontend/src/api/schema/13-学术活动管理-V.openapi.yaml` — 契约逐字节副本
- 创建 `backend-go/db/schema/v_schema.sql` — sqlc 裁剪 schema（仅 v_* + 被读 sys_org 无；V 仅操作自有 3 表）
- 创建 `backend-go/db/query_v/v_activity.sql` / `v_activity_participant.sql` / `v_activity_review.sql` — sqlc 查询
- 生成 `backend-go/internal/modules/activity/store/*` — sqlc 产物（db.go/models.go/*.sql.go）
- 创建 `backend-go/internal/modules/activity/{handler,routes,mapper}.go`
- 创建 `backend-go/internal/modules/activity/{contract_test,handler_test}.go`
- 创建 `backend-go/testdata/seed_v.sql`
- 创建 `frontend/src/views/ActivityView.vue`
- 创建 `frontend/src/api/mock/overrides/activity.ts`

**新建 — M 域（绩效评价，包 `performance`，store package `mstore`）：**
- 创建 `design/14-科研绩效评价-M.openapi.yaml` / `.ddl.sql`（5 表：`m_scheme`/`m_scheme_factor`/`m_record`/`m_record_item`/`m_payout`）/ `.detail.md`
- 创建 `frontend/src/api/schema/14-科研绩效评价-M.openapi.yaml`
- 创建 `backend-go/db/schema/m_schema.sql`（m_* + 被读只读表 `r_output`/`f_income`/`e_project`/`t_deal` 的取数所需列裁剪）
- 创建 `backend-go/db/query_m/m_scheme.sql` / `m_scheme_factor.sql` / `m_record.sql` / `m_record_item.sql` / `m_payout.sql` / `metrics.sql`（跨表聚合，SELECT 只读 R/F/E/T）
- 生成 `backend-go/internal/modules/performance/store/*`
- 创建 `backend-go/internal/modules/performance/{handler,records,routes,mapper,calculate}.go`
- 创建 `backend-go/internal/modules/performance/{contract_test,handler_test,calculate_test}.go`
- 创建 `backend-go/testdata/seed_m.sql`
- 创建 `frontend/src/views/PerformanceView.vue` + `frontend/src/api/mock/overrides/performance.ts`

**修改（横切）：**
- `design/00-common.sql` — `seq_prefix_registry` INSERT 追加 `ACT`/`PERF`/`PAY`
- `backend-go/migrations/000001_init.{up,down}.sql` — 由 `go generate ./migrations/...` 重生成
- `backend-go/migrations/gen_test.go` — 增断言：`v_activity`/`m_scheme` 建表存在 + 前缀登记
- `backend-go/sqlc.yaml` — 追加 V、M 两个 engine 块
- `backend-go/Makefile` — `drift` 目标纳入两个新 store 目录
- `backend-go/internal/router.go` — `if d.Pool != nil` 内 `activity.Register(...)`、`performance.Register(...)`
- `backend-go/internal/platform/auth/policy.csv` — V/M 两组规则
- `backend-go/internal/platform/auth/policy_test.go` / `caps_test.go` — 鉴权矩阵 + caps 派生用例
- `frontend/src/api/schema/index.ts` — `MODULE_CODES` 加 `'13':'V'`、`'14':'M'`
- `frontend/src/router/index.ts` — `/activity`、`/performance` 路由
- `frontend/src/App.vue` — 侧栏分组新增两项

**责任边界：** store 目录只由 sqlc 生成（勿手改）；`handler.go` 只做 HTTP+状态机校验+数据域注入，取数/落库全走 store；`mapper.go` 只做 store 行 → 契约 snake_case map；`calculate.go` 只做因子聚合与计分纯逻辑（可脱离 gin 单测）。

---

## 阶段一 · 模块 V（学术活动管理）

约定：V 全部路径前缀 `/activities`（相对受保护分组 `/api/v1`，即整路径 `/api/v1/activities...`）。活动状态机 token：`DRAFT/SUBMITTED/DEPT_REVIEW/APPROVED/HELD/ARCHIVED/REJECTED/RETURNED/CANCELLED`。

### 任务 V-1：V 契约 openapi

**文件：**
- 创建：`design/13-学术活动管理-V.openapi.yaml`

- [ ] **步骤 1：写契约文件**（components 段与 12-U 契约同构，直接内联，勿 $ref 跨文件——契约各自独立被 `oapi.LoadDir` 解析）

```yaml
openapi: 3.0.3
info:
  title: 科研管理系统 · 13 学术活动管理 API（模块 V）
  version: "1.0.0"
  description: >-
    学术活动申报-审批-举办-归档全生命周期 REST 契约。统一响应 ApiResponse{code,message,data,traceId,timestamp}；
    分页 PageResult{list,total,page,size}；认证 Bearer JWT；写方法支持 Idempotency-Key。
    实体字段名与 DDL 列名一致（snake_case）。授权 Casbin（RBAC）+ 数据域 ABAC（tenant_id/security_level）。
servers:
  - url: https://{host}/api/v1
    variables:
      host: { default: api.institute.example.com }
tags:
  - { name: activity, description: 学术活动（会议/讲座/研讨/培训）申报审批与归档 }
security:
  - bearerAuth: []
paths:
  /activities:
    get:
      tags: [activity]
      summary: 活动列表（租户隔离 + 多条件筛选 + 分页）
      operationId: listActivities
      parameters:
        - { name: activity_type, in: query, schema: { type: string, enum: [CONFERENCE, LECTURE, SEMINAR, TRAINING, OTHER] } }
        - { name: level, in: query, schema: { type: string, enum: [INTERNATIONAL, NATIONAL, PROVINCIAL, CAMPUS] } }
        - { name: host_mode, in: query, schema: { type: string, enum: [HOST, ATTEND, SPONSOR] } }
        - { name: status, in: query, schema: { type: string, enum: [DRAFT, SUBMITTED, DEPT_REVIEW, APPROVED, HELD, ARCHIVED, REJECTED, RETURNED, CANCELLED] } }
        - { name: organizer_dept_id, in: query, schema: { type: integer, format: int64 } }
        - { name: from, in: query, description: 起始日期 YYYY-MM-DD, schema: { type: string } }
        - { name: to, in: query, description: 截止日期 YYYY-MM-DD, schema: { type: string } }
        - { name: keyword, in: query, description: 匹配 title/theme, schema: { type: string } }
        - $ref: '#/components/parameters/Page'
        - $ref: '#/components/parameters/Size'
      responses:
        '200':
          description: 分页活动列表
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        allOf:
                          - $ref: '#/components/schemas/PageResult'
                          - type: object
                            properties:
                              list: { type: array, items: { $ref: '#/components/schemas/Activity' } }
        '401': { $ref: '#/components/responses/Unauthorized' }
    post:
      tags: [activity]
      summary: 新建活动（DRAFT，分配 code=ACT-年-序）
      operationId: createActivity
      parameters: [ { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/ActivityRequest' }
      responses:
        '200':
          description: 创建后的活动
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Activity' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '401': { $ref: '#/components/responses/Unauthorized' }
        '403': { $ref: '#/components/responses/Forbidden' }
  /activities/{id}:
    get:
      tags: [activity]
      summary: 活动详情（含 participants + reviews）
      operationId: getActivity
      parameters: [ { $ref: '#/components/parameters/PathId' } ]
      responses:
        '200':
          description: 活动详情
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/ActivityDetail' }
        '404': { $ref: '#/components/responses/NotFound' }
    put:
      tags: [activity]
      summary: 编辑活动（仅 DRAFT/RETURNED 可编辑）
      operationId: updateActivity
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/ActivityRequest' }
      responses:
        '200':
          description: 更新后的活动
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Activity' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
    delete:
      tags: [activity]
      summary: 软删活动（deleted=1）
      operationId: deleteActivity
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 操作结果
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { id: { type: integer, format: int64 }, deleted: { type: boolean } } }
        '404': { $ref: '#/components/responses/NotFound' }
  /activities/{id}/submit:
    post:
      tags: [activity]
      summary: 提交审批（DRAFT/RETURNED → SUBMITTED）
      operationId: submitActivity
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 提交后的活动
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Activity' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /activities/{id}/approve:
    post:
      tags: [activity]
      summary: 审批（review_level 1=部门 2=院所/主管；action APPROVE/REJECT/RETURN）
      operationId: approveActivity
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [action]
              properties:
                review_level: { type: integer, enum: [1, 2] }
                action: { type: string, enum: [APPROVE, REJECT, RETURN] }
                opinion: { type: string, nullable: true }
      responses:
        '200':
          description: 审批后的活动
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Activity' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /activities/{id}/hold:
    post:
      tags: [activity]
      summary: 标记已举办（APPROVED → HELD，body 实到人数/凭证）
      operationId: holdActivity
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                sign_in_count: { type: integer }
                hold_proof_ids: { type: array, items: { type: string } }
      responses:
        '200':
          description: 更新后的活动
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Activity' }
        '409': { $ref: '#/components/responses/Conflict' }
  /activities/{id}/archive:
    post:
      tags: [activity]
      summary: 归档（HELD → ARCHIVED，body 纪要）
      operationId: archiveActivity
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                minutes_rich: { type: string }
      responses:
        '200':
          description: 更新后的活动
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Activity' }
        '409': { $ref: '#/components/responses/Conflict' }
  /activities/{id}/cancel:
    post:
      tags: [activity]
      summary: 取消（非终态 → CANCELLED，body reason）
      operationId: cancelActivity
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        content:
          application/json:
            schema: { type: object, properties: { cancel_reason: { type: string } } }
      responses:
        '200':
          description: 更新后的活动
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Activity' }
        '409': { $ref: '#/components/responses/Conflict' }
  /activities/calendar:
    get:
      tags: [activity]
      summary: 按月日历视图
      operationId: activityCalendar
      parameters:
        - { name: month, in: query, required: true, description: YYYY-MM, schema: { type: string } }
      responses:
        '200':
          description: 该月活动（按 start_at 落布）
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        type: object
                        properties:
                          month: { type: string }
                          list: { type: array, items: { $ref: '#/components/schemas/Activity' } }
  /activities/stats:
    get:
      tags: [activity]
      summary: 按维度聚合计数
      operationId: activityStats
      parameters:
        - { name: group_by, in: query, schema: { type: string, enum: [activity_type, level, organizer_dept_id, month] } }
      responses:
        '200':
          description: 聚合桶
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        type: object
                        properties:
                          buckets: { type: array, items: { type: object, properties: { key: { type: string }, count: { type: integer } } } }
  /activities/{id}/participants:
    get:
      tags: [activity]
      summary: 参与人列表
      operationId: listParticipants
      parameters: [ { $ref: '#/components/parameters/PathId' } ]
      responses:
        '200':
          description: 参与人数组
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        type: object
                        properties:
                          list: { type: array, items: { $ref: '#/components/schemas/Participant' } }
    post:
      tags: [activity]
      summary: 新增参与人
      operationId: addParticipant
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/ParticipantRequest' }
      responses:
        '200':
          description: 新增后的参与人
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Participant' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '409': { $ref: '#/components/responses/Conflict' }
  /activities/{id}/participants/{pid}:
    delete:
      tags: [activity]
      summary: 移除参与人
      operationId: removeParticipant
      parameters:
        - { name: id, in: path, required: true, schema: { type: integer, format: int64 } }
        - { name: pid, in: path, required: true, schema: { type: integer, format: int64 } }
        - { $ref: '#/components/parameters/IdempotencyKey' }
      responses:
        '200':
          description: 操作结果
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { id: { type: integer, format: int64 }, deleted: { type: boolean } } }
        '404': { $ref: '#/components/responses/NotFound' }
components:
  securitySchemes:
    bearerAuth: { type: http, scheme: bearer, bearerFormat: JWT }
  parameters:
    IdempotencyKey: { name: Idempotency-Key, in: header, required: false, schema: { type: string } }
    Page: { name: page, in: query, required: false, schema: { type: integer, minimum: 1, default: 1 } }
    Size: { name: size, in: query, required: false, schema: { type: integer, minimum: 1, maximum: 200, default: 20 } }
    PathId: { name: id, in: path, required: true, schema: { type: integer, format: int64 } }
  responses:
    BadRequest: { description: 参数校验失败（40001）, content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } } }
    Unauthorized: { description: 未认证（40101）, content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } } }
    Forbidden: { description: 越权（40301）, content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } } }
    NotFound: { description: 不存在（40401）, content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } } }
    Conflict: { description: 状态机非法迁移/冲突（40901）, content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } } }
  schemas:
    ApiResponse:
      type: object
      required: [code, message, traceId, timestamp]
      properties:
        code: { type: integer }
        message: { type: string }
        data: { nullable: true }
        traceId: { type: string }
        timestamp: { type: integer, format: int64 }
    PageResult:
      type: object
      properties:
        list: { type: array, items: { type: object } }
        total: { type: integer, format: int64 }
        page: { type: integer }
        size: { type: integer }
    Activity:
      type: object
      properties:
        id: { type: integer, format: int64 }
        code: { type: string, nullable: true }
        tenant_id: { type: integer, format: int64 }
        status: { type: string, enum: [DRAFT, SUBMITTED, DEPT_REVIEW, APPROVED, HELD, ARCHIVED, REJECTED, RETURNED, CANCELLED] }
        security_level: { type: string, enum: [PUBLIC, INTERNAL, SECRET, TOP_SECRET] }
        activity_type: { type: string, enum: [CONFERENCE, LECTURE, SEMINAR, TRAINING, OTHER] }
        level: { type: string, enum: [INTERNATIONAL, NATIONAL, PROVINCIAL, CAMPUS] }
        host_mode: { type: string, enum: [HOST, ATTEND, SPONSOR] }
        title: { type: string }
        theme: { type: string, nullable: true }
        start_at: { type: string, format: date-time, nullable: true }
        end_at: { type: string, format: date-time, nullable: true }
        venue: { type: string, nullable: true }
        online_url: { type: string, nullable: true }
        host_unit: { type: string, nullable: true }
        organizer_dept_id: { type: integer, format: int64, nullable: true }
        invited_experts: { type: array, items: { type: object } }
        est_attendees: { type: integer, nullable: true }
        project_id: { type: integer, format: int64, nullable: true }
        budget_subject_code: { type: string, nullable: true }
        budget_amount: { type: string, nullable: true, description: NUMERIC(18,2) 以字符串承载 }
        agenda: { type: array, items: { type: object } }
        attachment_ids: { type: array, items: { type: string } }
        minutes_rich: { type: string, nullable: true }
        sign_in_count: { type: integer, nullable: true }
        hold_proof_ids: { type: array, items: { type: string } }
        submit_at: { type: string, format: date-time, nullable: true }
        approve_at: { type: string, format: date-time, nullable: true }
        archive_at: { type: string, format: date-time, nullable: true }
        cancel_at: { type: string, format: date-time, nullable: true }
        cancel_reason: { type: string, nullable: true }
        creator_id: { type: integer, format: int64 }
        created_at: { type: string, format: date-time }
        updated_at: { type: string, format: date-time }
        remark: { type: string, nullable: true }
    ActivityDetail:
      allOf:
        - $ref: '#/components/schemas/Activity'
        - type: object
          properties:
            participants: { type: array, items: { $ref: '#/components/schemas/Participant' } }
            reviews: { type: array, items: { $ref: '#/components/schemas/Review' } }
    ActivityRequest:
      type: object
      required: [title, activity_type]
      properties:
        activity_type: { type: string, enum: [CONFERENCE, LECTURE, SEMINAR, TRAINING, OTHER] }
        level: { type: string, enum: [INTERNATIONAL, NATIONAL, PROVINCIAL, CAMPUS] }
        host_mode: { type: string, enum: [HOST, ATTEND, SPONSOR] }
        title: { type: string }
        theme: { type: string, nullable: true }
        start_at: { type: string, format: date-time, nullable: true }
        end_at: { type: string, format: date-time, nullable: true }
        venue: { type: string, nullable: true }
        online_url: { type: string, nullable: true }
        host_unit: { type: string, nullable: true }
        organizer_dept_id: { type: integer, format: int64, nullable: true }
        invited_experts: { type: array, items: { type: object }, nullable: true }
        est_attendees: { type: integer, nullable: true }
        project_id: { type: integer, format: int64, nullable: true }
        budget_subject_code: { type: string, nullable: true }
        budget_amount: { type: string, nullable: true }
        agenda: { type: array, items: { type: object }, nullable: true }
        attachment_ids: { type: array, items: { type: string }, nullable: true }
        security_level: { type: string, enum: [PUBLIC, INTERNAL, SECRET, TOP_SECRET], nullable: true }
        remark: { type: string, nullable: true }
    Participant:
      type: object
      properties:
        id: { type: integer, format: int64 }
        activity_id: { type: integer, format: int64 }
        user_id: { type: integer, format: int64, nullable: true }
        guest_name: { type: string, nullable: true }
        role: { type: string, enum: [SPEAKER, CHAIR, MEMBER, ATTENDEE] }
        report_title: { type: string, nullable: true }
    ParticipantRequest:
      type: object
      required: [role]
      properties:
        user_id: { type: integer, format: int64, nullable: true }
        guest_name: { type: string, nullable: true }
        role: { type: string, enum: [SPEAKER, CHAIR, MEMBER, ATTENDEE] }
        report_title: { type: string, nullable: true }
    Review:
      type: object
      properties:
        id: { type: integer, format: int64 }
        activity_id: { type: integer, format: int64 }
        review_level: { type: integer }
        reviewer_id: { type: integer, format: int64 }
        action: { type: string, enum: [APPROVE, REJECT, RETURN] }
        opinion: { type: string, nullable: true }
        acted_at: { type: string, format: date-time }
```

- [ ] **步骤 2：逐字节同步到前端**

运行：`cp "design/13-学术活动管理-V.openapi.yaml" "frontend/src/api/schema/13-学术活动管理-V.openapi.yaml"`（在项目根）
验证：`diff -q design/13-学术活动管理-V.openapi.yaml frontend/src/api/schema/13-学术活动管理-V.openapi.yaml` → 无输出。

- [ ] **步骤 3：Commit**

```bash
git add "design/13-学术活动管理-V.openapi.yaml"
git add "frontend/src/api/schema/13-学术活动管理-V.openapi.yaml"
git commit -m "feat(V): 新增学术活动管理契约 13 并同步前端 schema 副本"
```

### 任务 V-2：V DDL（3 张业务表）

**文件：**
- 创建：`design/13-学术活动管理-V.ddl.sql`
- 创建：`design/13-学术活动管理-V.detail.md`

- [ ] **步骤 1：写 DDL**（通用列内联；跨模块仅存 `*_id` 逻辑外键，不建物理 FK；同模块 participant/review→v_activity 建物理 FK；唯一索引带 `WHERE deleted=0`）

```sql
-- =============================================================================
-- 13-学术活动管理-V.ddl.sql · 模块 V（学术活动）建表脚本
-- 版本 v1.0 · 2026-10-14
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4）
-- 约定：金额 NUMERIC(18,2)；时间 TIMESTAMPTZ；枚举 VARCHAR+CHECK；字典走 sys_dict；
--       跨模块只存 *_id 逻辑外键（organizer_dept→sys_org、project→E_PROJECT、budget_subject→F），
--       同模块内 participant/review 对 v_activity 建物理外键。
-- 编号：v_activity.code 前缀 ACT（svc-numbering 分配，见 00-common seq_prefix_registry）。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- V_ACTIVITY · 活动主表（申报→审批→举办→归档；状态机见 detail.md）
--   DRAFT→SUBMITTED→DEPT_REVIEW→APPROVED→HELD→ARCHIVED；分支 REJECTED/RETURNED/CANCELLED
-- -----------------------------------------------------------------------------
CREATE TABLE v_activity (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','SUBMITTED','DEPT_REVIEW','APPROVED','HELD',
                                       'ARCHIVED','REJECTED','RETURNED','CANCELLED')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  -- 业务列 ─────────────────────────────────────────────
  activity_type      VARCHAR(32) NOT NULL
                     CHECK (activity_type IN ('CONFERENCE','LECTURE','SEMINAR','TRAINING','OTHER')),
  level              VARCHAR(16)
                     CHECK (level IN ('INTERNATIONAL','NATIONAL','PROVINCIAL','CAMPUS')),
  host_mode          VARCHAR(16)
                     CHECK (host_mode IN ('HOST','ATTEND','SPONSOR')),
  title              VARCHAR(256) NOT NULL,
  theme              VARCHAR(256),
  start_at           TIMESTAMPTZ,
  end_at             TIMESTAMPTZ,
  venue              VARCHAR(256),
  online_url         VARCHAR(512),
  host_unit          VARCHAR(128),
  organizer_dept_id  BIGINT,                        -- 逻辑外键 → sys_org(id)
  invited_experts    JSONB        NOT NULL DEFAULT '[]'::jsonb, -- [{name,org,title}]
  est_attendees      INT,
  project_id         BIGINT,                        -- 逻辑外键 → e_project(id)
  budget_subject_code VARCHAR(64),                  -- 逻辑引用 F 科目 / sys_dict
  budget_amount      NUMERIC(18,2),                 -- 登记用，不联动 F 冻结（YAGNI §7）
  agenda             JSONB        NOT NULL DEFAULT '[]'::jsonb, -- [{title,speaker,startAt,endAt,venue}]
  attachment_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb,
  minutes_rich       TEXT,                          -- 纪要（归档时填）
  sign_in_count      INT,                           -- 实到人数
  hold_proof_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 举办凭证对象 id
  submit_at          TIMESTAMPTZ,
  approve_at         TIMESTAMPTZ,
  archive_at         TIMESTAMPTZ,
  cancel_at          TIMESTAMPTZ,
  cancel_reason      VARCHAR(512)
);
CREATE UNIQUE INDEX uk_v_activity_code     ON v_activity(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_v_activity_tenant_st      ON v_activity(tenant_id, status);
CREATE INDEX idx_v_activity_type           ON v_activity(tenant_id, activity_type);
CREATE INDEX idx_v_activity_level          ON v_activity(tenant_id, level);
CREATE INDEX idx_v_activity_dept           ON v_activity(organizer_dept_id);
CREATE INDEX idx_v_activity_project        ON v_activity(project_id);
CREATE INDEX idx_v_activity_start          ON v_activity(start_at);

COMMENT ON TABLE  v_activity IS '学术活动主表：会议/讲座/研讨/培训申报审批举办归档（模块 V）';
COMMENT ON COLUMN v_activity.status             IS '状态机 token：DRAFT/SUBMITTED/DEPT_REVIEW/APPROVED/HELD/ARCHIVED/REJECTED/RETURNED/CANCELLED';
COMMENT ON COLUMN v_activity.security_level     IS '密级；读取按网络域/密级过滤（复用 X 治理谓词），默认 INTERNAL';
COMMENT ON COLUMN v_activity.organizer_dept_id  IS '主办部门，逻辑外键 → sys_org(id)，不建物理 FK';
COMMENT ON COLUMN v_activity.project_id         IS '关联项目，逻辑外键 → e_project(id)';
COMMENT ON COLUMN v_activity.budget_amount      IS '活动预算（登记），NUMERIC(18,2)，不联动经费冻结';


-- -----------------------------------------------------------------------------
-- V_ACTIVITY_PARTICIPANT · 参与人（内部 user 或外部 guest）
-- -----------------------------------------------------------------------------
CREATE TABLE v_activity_participant (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  activity_id   BIGINT NOT NULL REFERENCES v_activity(id),
  user_id       BIGINT,                            -- 逻辑外键 → sys_user(id)；空=外部专家
  guest_name    VARCHAR(64),                       -- 外部人员姓名快照
  role          VARCHAR(16) NOT NULL
                CHECK (role IN ('SPEAKER','CHAIR','MEMBER','ATTENDEE')),
  report_title  VARCHAR(256),
  tenant_id     BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_v_participant_user ON v_activity_participant(activity_id, user_id, role) WHERE user_id IS NOT NULL;
CREATE INDEX idx_v_participant_activity   ON v_activity_participant(activity_id);

COMMENT ON TABLE v_activity_participant IS '活动参与人：内部 user_id 或外部 guest_name，含角色与报告题目';


-- -----------------------------------------------------------------------------
-- V_ACTIVITY_REVIEW · 多级审核留痕（1=部门 2=院所/主管）
-- -----------------------------------------------------------------------------
CREATE TABLE v_activity_review (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  activity_id  BIGINT NOT NULL REFERENCES v_activity(id),
  review_level SMALLINT NOT NULL,
  reviewer_id  BIGINT NOT NULL,                    -- 逻辑外键 → sys_user(id)
  action       VARCHAR(16) NOT NULL
               CHECK (action IN ('APPROVE','REJECT','RETURN')),
  opinion      VARCHAR(512),
  acted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  tenant_id    BIGINT NOT NULL
);
CREATE INDEX idx_v_review_activity ON v_activity_review(activity_id, review_level);

COMMENT ON TABLE v_activity_review IS '活动审核留痕：每级审批动作/意见/时间，可追溯';
```

- [ ] **步骤 2：写 detail.md**（文档：状态机图、端点→迁移映射、权限矩阵、字段口径；对齐 §3）。内容以规格 §3 为基展开三节：3.1 数据字典、3.2 状态机（把 §3.2 ASCII 图誊入并补“非法迁移→40901”“RETURN→RETURNED 可编辑重提”“归档须 HELD 且 minutes 非空”），3.3 权限矩阵表。无编译物，写完即通过。

- [ ] **步骤 3：Commit**

```bash
git add "design/13-学术活动管理-V.ddl.sql"
git add "design/13-学术活动管理-V.detail.md"
git commit -m "feat(V): 新增学术活动 DDL（v_activity/participant/review）与设计细则"
```

---

### 任务 V-3：编号前缀登记 ACT

**文件：**
- 修改：`design/00-common.sql`（末尾 `INSERT INTO seq_prefix_registry` 块，当前 16 行以 `('EXF',...)` 收尾，行号≈308-324）

- [ ] **步骤 1：追加 ACT/PERF/PAY 三行**（V 与 M 前缀一次登记到位，避免后续再改同文件；PERF/PAY 在阶段二用到）

把结尾 `  ('EXF','涉密外传/输出审计','X','v1.1',TRUE);` 改为（去分号、续行、末行加分号）：

```sql
  ('EXF','涉密外传/输出审计','X','v1.1',TRUE),
  ('ACT','学术活动','V','v1.0',TRUE),
  ('PERF','绩效记录','M','v1.0',TRUE),
  ('PAY','绩效发放','M','v1.0',TRUE);
```

- [ ] **步骤 2：Commit**

```bash
git add "design/00-common.sql"
git commit -m "chore(common): 登记编号前缀 ACT/PERF/PAY"
```

---

### 任务 V-4：重生成迁移 + 断言

**文件：**
- 生成：`backend-go/migrations/000001_init.up.sql`、`000001_init.down.sql`
- 修改：`backend-go/migrations/gen_test.go`

- [ ] **步骤 1：重跑生成器**

运行（在 `backend-go/`）：`go generate ./migrations/...`
预期：`000001_init.up.sql` 体积增大，含 `-- ===== 13-学术活动管理-V.ddl.sql =====` 段与 `CREATE TABLE v_activity`。

- [ ] **步骤 2：写失败断言**（先加断言跑，确认生成物满足——非先失败，因生成物已含；此步是回归钉）

在 `gen_test.go` 的 `TestGenerateFromDesign` 的 `want` 切片追加 `"CREATE TABLE v_activity"`，并新增一个独立用例：

```go
// TestGenerateUp_HasVActivity 守卫 V 模块建表进入迁移；一旦 design/13 被漏排/改名，compose 后无表可写。
func TestGenerateUp_HasVActivity(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"CREATE TABLE v_activity", "CREATE TABLE v_activity_participant", "CREATE TABLE v_activity_review"} {
		if !strings.Contains(strings.ToLower(up), strings.ToLower(want)) {
			t.Fatalf("迁移缺少 V 模块对象: %s", want)
		}
	}
	if !strings.Contains(up, "'ACT'") {
		t.Fatal("seq_prefix_registry 未登记 ACT 前缀")
	}
}
```

- [ ] **步骤 3：运行迁移测试**

运行：`go test ./migrations/... -run 'TestGenerate' -v`
预期：PASS（含新用例）。若 `TestGenerateUp_UniqueIndexNames`/`UniqueRelationNames` 失败，说明 V 索引/表名与既有模块撞名——按守卫提示加 `v_` 前缀（本 DDL 已带 `v_` 前缀，正常不撞）。

- [ ] **步骤 4：Commit**

```bash
git add backend-go/migrations/000001_init.up.sql
git add backend-go/migrations/000001_init.down.sql
git add backend-go/migrations/gen_test.go
git commit -m "chore(V): 重生成迁移纳入 v_activity 三表并加断言"
```

---

### 任务 V-5：sqlc V 引擎块 + 裁剪 schema

**文件：**
- 创建：`backend-go/db/schema/v_schema.sql`
- 修改：`backend-go/sqlc.yaml`（`sql:` 列表末尾追加第三个 engine 块）

- [ ] **步骤 1：写裁剪 schema**（V 仓储只操作自有 3 表，语句原样摘自 `000001_init.up.sql`；不含被读表）

把 `design/13-学术活动管理-V.ddl.sql` 里三条 `CREATE TABLE v_activity/v_activity_participant/v_activity_review` 语句原样拷入 `v_schema.sql`（去掉 `COMMENT ON` 与索引，sqlc 只需表结构）。文件头加注释：

```sql
-- 裁剪 schema：仅 V 仓储所需的 3 张自有表；语句原样摘自 000001_init.up.sql。
-- 原因：sqlc v1.27 wazero 解析器无法吃 ~394KB 全量迁移。V 不跨读他模块表，故无额外只读表。
```

- [ ] **步骤 2：在 `sqlc.yaml` 末尾追加 V 块**（`version: "2"` 的 `sql:` 数组已有 P、U 两块，这是第三块）

```yaml
  - engine: "postgresql"
    # 第三生成块：V 仓储（学术活动）。独立 schema/queries/out；package=vstore。
    schema: "db/schema/v_schema.sql"
    queries: "db/query_v"
    gen:
      go:
        package: "vstore"
        out: "internal/modules/activity/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          v_activity: Activity
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          # created_at/updated_at → time.Time；可空时间列 → *time.Time；NUMERIC budget_amount 保 string
          - column: "v_activity.created_at"
            go_type: "time.Time"
          - column: "v_activity.updated_at"
            go_type: "time.Time"
          - column: "v_activity.start_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "v_activity.end_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "v_activity.submit_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "v_activity.approve_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "v_activity.archive_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "v_activity.cancel_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "v_activity.budget_amount"
            go_type: "string"
          - column: "v_activity_participant.created_at"
            go_type: "time.Time"
          - column: "v_activity_review.acted_at"
            go_type: "time.Time"
```

> `budget_amount` 用 `string`：与 P 的 `total_budget` 同策略（在查询里 `::text`）。`v_activity_review.acted_at` 有默认值但被显式写，也钉 `time.Time`。

- [ ] **步骤 3：Commit（配置先落，查询在 V-6）**

```bash
git add backend-go/db/schema/v_schema.sql
git add backend-go/sqlc.yaml
git commit -m "chore(V): 配置 sqlc V 引擎块与裁剪 schema"
```

---

### 任务 V-6：V 的 sqlc 查询文件

**文件：**
- 创建：`backend-go/db/query_v/v_activity.sql`
- 创建：`backend-go/db/query_v/v_activity_participant.sql`
- 创建：`backend-go/db/query_v/v_activity_review.sql`

- [ ] **步骤 1：写 `v_activity.sql`**（list 多条件软删过滤 + 分页；read 租户隔离；create 返回全列；update 编辑；transition 仅改 status 与对应时间戳；stats 按维度分组）

```sql
-- name: ListActivities :many
SELECT id, code, tenant_id, status, security_level, activity_type, level, host_mode,
       title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
       invited_experts, est_attendees, project_id, budget_subject_code,
       budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
       sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
       cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted
FROM v_activity
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::text   IS NULL OR status = $2::text)
  AND ($3::text   IS NULL OR activity_type = $3::text)
  AND ($4::text   IS NULL OR level = $4::text)
  AND ($5::text   IS NULL OR host_mode = $5::text)
  AND ($6::bigint IS NULL OR organizer_dept_id = $6::bigint)
  AND ($7::timestamptz IS NULL OR start_at >= $7::timestamptz)
  AND ($8::timestamptz IS NULL OR start_at <= $8::timestamptz)
  AND ($9::text   IS NULL OR title ILIKE $9::text OR theme ILIKE $9::text)
ORDER BY id DESC
LIMIT $11 OFFSET $10;

-- name: CountActivities :one
SELECT count(*)::int AS n
FROM v_activity
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::text   IS NULL OR status = $2::text)
  AND ($3::text   IS NULL OR activity_type = $3::text)
  AND ($4::text   IS NULL OR level = $4::text)
  AND ($5::text   IS NULL OR host_mode = $5::text)
  AND ($6::bigint IS NULL OR organizer_dept_id = $6::bigint)
  AND ($7::timestamptz IS NULL OR start_at >= $7::timestamptz)
  AND ($8::timestamptz IS NULL OR start_at <= $8::timestamptz)
  AND ($9::text   IS NULL OR title ILIKE $9::text OR theme ILIKE $9::text);

-- name: GetActivity :one
SELECT id, code, tenant_id, status, security_level, activity_type, level, host_mode,
       title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
       invited_experts, est_attendees, project_id, budget_subject_code,
       budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
       sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
       cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted
FROM v_activity
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: CreateActivity :one
INSERT INTO v_activity (
  tenant_id, status, security_level, creator_id, code, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code, budget_amount,
  agenda, attachment_ids, remark
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
  COALESCE($17::jsonb, '[]'::jsonb), $18, $19, $20, $21::numeric,
  COALESCE($22::jsonb, '[]'::jsonb), COALESCE($23::jsonb, '[]'::jsonb), $24
)
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: UpdateActivity :one
UPDATE v_activity SET
  activity_type = $4, level = $5, host_mode = $6, title = $7, theme = $8,
  start_at = $9, end_at = $10, venue = $11, online_url = $12, host_unit = $13,
  organizer_dept_id = $14, invited_experts = COALESCE($15::jsonb, '[]'::jsonb),
  est_attendees = $16, project_id = $17, budget_subject_code = $18,
  budget_amount = $19::numeric, agenda = COALESCE($20::jsonb, '[]'::jsonb),
  attachment_ids = COALESCE($21::jsonb, '[]'::jsonb), security_level = $22, remark = $23,
  modifier_id = $24, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status IN ('DRAFT','RETURNED')
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: TransitionStatus :one
-- 通用状态迁移：由 handler 校验 from→to 合法后调用；set 对应时间戳列（按 to 选）用 CASE 落。
UPDATE v_activity SET
  status = $4,
  submit_at  = CASE WHEN $4 = 'SUBMITTED'  THEN now() ELSE submit_at  END,
  approve_at = CASE WHEN $4 IN ('APPROVED') THEN now() ELSE approve_at END,
  archive_at = CASE WHEN $4 = 'ARCHIVED'   THEN now() ELSE archive_at END,
  cancel_at  = CASE WHEN $4 = 'CANCELLED'  THEN now() ELSE cancel_at  END,
  modifier_id = $5,
  updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = $3
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkHold :one
UPDATE v_activity SET
  status = 'HELD', sign_in_count = $4,
  hold_proof_ids = COALESCE($5::jsonb, hold_proof_ids),
  approve_at = CASE WHEN approve_at IS NULL THEN now() ELSE approve_at END,
  modifier_id = $6, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'APPROVED'
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkArchive :one
UPDATE v_activity SET
  status = 'ARCHIVED', minutes_rich = $4, archive_at = now(), modifier_id = $5, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'HELD'
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkCancel :one
UPDATE v_activity SET
  status = 'CANCELLED', cancel_at = now(), cancel_reason = $4, modifier_id = $5, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
  AND status NOT IN ('ARCHIVED','CANCELLED')
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: SoftDeleteActivity :execrows
UPDATE v_activity SET deleted = 1, status = 'CANCELLED', updated_at = now(), modifier_id = $3
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: ListCalendar :many
SELECT id, code, tenant_id, status, security_level, activity_type, level, host_mode,
       title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
       invited_experts, est_attendees, project_id, budget_subject_code,
       budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
       sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
       cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted
FROM v_activity
WHERE deleted = 0 AND tenant_id = $1
  AND start_at >= $2 AND start_at < $3
ORDER BY start_at;

-- name: StatsByType :many
SELECT activity_type AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1
GROUP BY activity_type ORDER BY count DESC;

-- name: StatsByLevel :many
SELECT level AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1 AND level IS NOT NULL
GROUP BY level ORDER BY count DESC;

-- name: StatsByDept :many
SELECT organizer_dept_id::text AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1 AND organizer_dept_id IS NOT NULL
GROUP BY organizer_dept_id ORDER BY count DESC;

-- name: StatsByMonth :many
SELECT to_char(date_trunc('month', start_at), 'YYYY-MM') AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1 AND start_at IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

> `TransitionStatus` 参数序：`$1 id, $2 tenant_id, $3 from_status, $4 to_status, $5 modifier_id`——handler 校验合法迁移后传入；`RETURNING` 让所有 update/transition 直接回全行，免二次查。sqlc 会把重复 SELECT 列列表推断为同一 row 模型 `Activity`（因 `rename v_activity: Activity`）。

- [ ] **步骤 2：写 `v_activity_participant.sql`**

```sql
-- name: ListParticipants :many
SELECT id, activity_id, user_id, guest_name, role, report_title, tenant_id, created_at
FROM v_activity_participant
WHERE activity_id = $1 AND tenant_id = $2
ORDER BY id;

-- name: AddParticipant :one
INSERT INTO v_activity_participant (activity_id, user_id, guest_name, role, report_title, tenant_id)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, activity_id, user_id, guest_name, role, report_title, tenant_id, created_at;

-- name: DeleteParticipant :execrows
DELETE FROM v_activity_participant
WHERE id = $1 AND activity_id = $2 AND tenant_id = $3;
```

- [ ] **步骤 3：写 `v_activity_review.sql`**

```sql
-- name: ListReviews :many
SELECT id, activity_id, review_level, reviewer_id, action, opinion, acted_at, tenant_id
FROM v_activity_review
WHERE activity_id = $1 AND tenant_id = $2
ORDER BY review_level, acted_at;

-- name: InsertReview :one
INSERT INTO v_activity_review (activity_id, review_level, reviewer_id, action, opinion, tenant_id)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, activity_id, review_level, reviewer_id, action, opinion, acted_at, tenant_id;
```

- [ ] **步骤 4：Commit**

```bash
git add backend-go/db/query_v/v_activity.sql
git add backend-go/db/query_v/v_activity_participant.sql
git add backend-go/db/query_v/v_activity_review.sql
git commit -m "feat(V): 新增学术活动 sqlc 查询（list/read/create/update/transition/calendar/stats/participant/review）"
```

### 任务 V-7：生成 V 的 DAL（sqlc）

**文件：**
- 生成：`backend-go/internal/modules/activity/store/{db.go,models.go,v_activity.sql.go,v_activity_participant.sql.go,v_activity_review.sql.go}`

- [ ] **步骤 1：串行生成（Windows 避 wazero OOM）**

运行（在 `backend-go/`）：`GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate`
预期：生成 `internal/modules/activity/store/` 下 5 个文件；无 `panic: out of bounds memory access`。若报某 query 列不匹配，按 sqlc 报错行回改 `db/query_v/*.sql` 的列清单与 DDL 对齐后重跑。

- [ ] **步骤 2：编译校验**

运行：`go build ./internal/modules/activity/store/`
预期：成功。打开 `models.go` 确认 `Activity` 结构体含 `BudgetAmount string`、`CreatedAt time.Time`、`StartAt *time.Time`（override 生效）；`VActivityParticipant`、`VActivityReview` 两模型存在。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/activity/store/
git commit -m "feat(V): sqlc 生成 vstore 数据访问层"
```

---

### 任务 V-8：store 形状钉测（无 DB 编译守卫）

**文件：**
- 创建：`backend-go/internal/modules/activity/store/compile_test.go`

- [ ] **步骤 1：写测试**（仿 sysadmin/store/compile_test.go，仅断言生成类型与查询方法签名存在，编译即通过，钉住列名/类型漂移）

```go
package vstore

import (
	"context"
	"testing"
	"time"
)

// TestStoreShapes 钉住 sqlc 生成物的关键字段类型，防止列/类型漂移破坏 handler 映射。
func TestStoreShapes(t *testing.T) {
	var a Activity
	a.CreatedAt = time.Time{}     // override: time.Time
	a.StartAt = nil               // nullable → *time.Time
	a.BudgetAmount = "1000.00"    // NUMERIC ::text → string
	a.Status = "DRAFT"
	var p VActivityParticipant
	p.GuestName = nil             // nullable → *string
	var r VActivityReview
	r.ActedAt = time.Time{}
	// 方法存在性（不调用，仅取函数值）
	_ = (&Queries{}).ListActivities
	_ = (&Queries{}).CountActivities
	_ = (&Queries{}).CreateActivity
	_ = (&Queries{}).TransitionStatus
	_ = func(q *Queries) { _ = q.SoftDeleteActivity(context.Background(), SoftDeleteActivityParams{}) }
	_ = a; _ = p; _ = r
}
```

> 若某生成类型/参数结构名与上述不符（如 `SoftDeleteActivityParams` 实际叫别的），以生成物为准改测试——它是钉，不是猜。`Activity` 各可空列若生成为 `*string`/`pgtype.*` 而非指针，回到 V-5 的 overrides 补列级 override 后重生成。

- [ ] **步骤 2：运行**

运行：`go test ./internal/modules/activity/store/ -run TestStoreShapes -v`
预期：PASS（编译过即胜）。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/activity/store/compile_test.go
git commit -m "test(V): 钉住 vstore 生成类型形状"
```

---

### 任务 V-9：V mapper（store 行 → 契约 snake_case）

**文件：**
- 创建：`backend-go/internal/modules/activity/mapper.go`

- [ ] **步骤 1：写映射**（JSONB 列解回数组/对象；指针列 nil-safe；时间 RFC3339Nano；形状严格对齐 `design/13` 的 Activity/Participant/Review）

```go
package activity

import (
	"encoding/json"
	"time"

	vstore "github.com/eplugger/ark/internal/modules/activity/store"
)

// jsonToAny 把 []byte(JSONB) 解成 any；空/坏回落 []any{}（契约要求数组字段恒为数组）。
func jsonToAny(b []byte, fallback any) any {
	if len(b) == 0 {
		return fallback
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return fallback
	}
	return v
}

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

// ToAPIActivity 映射 v_activity 行为契约 Activity（snake_case）。
func ToAPIActivity(r vstore.Activity) map[string]any {
	out := map[string]any{
		"id":                r.ID,
		"tenant_id":         r.TenantID,
		"status":            r.Status,
		"security_level":    r.SecurityLevel,
		"activity_type":     r.ActivityType,
		"title":             r.Title,
		"invited_experts":   jsonToAny(r.InvitedExperts, []any{}),
		"agenda":            jsonToAny(r.Agenda, []any{}),
		"attachment_ids":    jsonToAny(r.AttachmentIds, []any{}),
		"hold_proof_ids":    jsonToAny(r.HoldProofIds, []any{}),
		"budget_amount":     r.BudgetAmount, // 已是 string（::text）；无值时为 ""→契约允许 null，下面兜
		"creator_id":        r.CreatorID,
		"deleted":           r.Deleted,
		"created_at":        fmtTime(r.CreatedAt),
		"updated_at":        fmtTime(r.UpdatedAt),
	}
	if r.BudgetAmount == "" {
		out["budget_amount"] = nil
	}
	putStr := func(k string, v *string) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putStr("code", r.Code)
	putStr("level", r.Level)
	putStr("host_mode", r.HostMode)
	putStr("theme", r.Theme)
	putStr("venue", r.Venue)
	putStr("online_url", r.OnlineURL)
	putStr("host_unit", r.HostUnit)
	putStr("budget_subject_code", r.BudgetSubjectCode)
	putStr("minutes_rich", r.MinutesRich)
	putStr("cancel_reason", r.CancelReason)
	putStr("remark", r.Remark)
	// 可空整型
	putInt := func(k string, v *int64) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putInt("organizer_dept_id", r.OrganizerDeptID)
	putInt("project_id", r.ProjectID)
	putSmallInt := func(k string, v *int32) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putSmallInt("est_attendees", r.EstAttendees)
	putSmallInt("sign_in_count", r.SignInCount)
	putStr("modifier_id_str", nilPtrStr()) // 占位防误；modifier_id 单独处理
	delete(out, "modifier_id_str")
	if r.ModifierID != nil {
		out["modifier_id"] = *r.ModifierID
	} else {
		out["modifier_id"] = nil
	}
	out["start_at"] = fmtTimePtr(r.StartAt)
	out["end_at"] = fmtTimePtr(r.EndAt)
	out["submit_at"] = fmtTimePtr(r.SubmitAt)
	out["approve_at"] = fmtTimePtr(r.ApproveAt)
	out["archive_at"] = fmtTimePtr(r.ArchiveAt)
	out["cancel_at"] = fmtTimePtr(r.CancelAt)
	return out
}

// nilPtrStr 返回 (*string)(nil)——仅为上面 putStr 复用签名的辅助；实际未使用。
func nilPtrStr() *string { return nil }

func ToAPIParticipant(r vstore.VActivityParticipant) map[string]any {
	return map[string]any{
		"id":           r.ID,
		"activity_id":  r.ActivityID,
		"user_id":      r.UserID,
		"guest_name":   r.GuestName,
		"role":         r.Role,
		"report_title": r.ReportTitle,
	}
}

func ToAPIReview(r vstore.VActivityReview) map[string]any {
	return map[string]any{
		"id":           r.ID,
		"activity_id":  r.ActivityID,
		"review_level": r.ReviewLevel,
		"reviewer_id":  r.ReviewerID,
		"action":       r.Action,
		"opinion":      r.Opinion,
		"acted_at":     fmtTime(r.ActedAt),
	}
}
```

> 说明：`putSmallInt`/`putInt` 依 sqlc 实际生成的可空整型指针类型（`*int64`/`*int32`）；若生成为 `pgtype.Int8`/`Int4`，改用 `.Int64/Int32` + `.Valid`。**以 V-7 生成的 `models.go` 为准调整这两处 helper**（列类型由 override/NULL 决定）。上面 `modifier_id_str` 两段是刻意留下的“勿照抄”示例——正式实现删除它们，仅保留紧随其后的 `if r.ModifierID != nil` 分支。

- [ ] **步骤 2：编译**

运行：`go build ./internal/modules/activity/`
预期：成功（handler/routes 未写，仅 mapper 包编译——若因未用 `nilPtrStr` 报错，删除那段占位代码后重编）。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/activity/mapper.go
git commit -m "feat(V): 新增 v_activity/participant/review → 契约映射"
```

---

### 任务 V-10：V handler（增删改查 + 状态机 + 日历/统计/参与人）

**文件：**
- 创建：`backend-go/internal/modules/activity/handler.go`

- [ ] **步骤 1：写 handler 骨架 + CRUD**（`DomainFrom(c)` 取数据域；编号 code 分配用 M0 简化：`ACT-<年>-<id补零>`，与 P 一致——P 用 DB 默认 NULL code 亦可，本实现创建后回写；为免引入编号中心依赖，沿用“创建后按主键回写 code”的 M0 演示策略，见 §6 注）

```go
package activity

import (
	"encoding/json"
	"fmt"
	"strconv"
	"time"

	vstore "github.com/eplugger/ark/internal/modules/activity/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct{ q *vstore.Queries }

func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: vstore.New(pool)} }

func pageArgs(c *gin.Context) (page, size, limit, offset int32) {
	p, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	s, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if p < 1 {
		p = 1
	}
	if s < 1 {
		s = 20
	}
	if s > 200 {
		s = 200
	}
	return int32(p), int32(s), int32(s), int32((p - 1) * s)
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

func optInt64(c *gin.Context, k string) *int64 {
	if v := c.Query(k); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return &n
		}
	}
	return nil
}

// bindActivity 解析 ActivityRequest（create/update 共用）。
type activityBody struct {
	ActivityType      string          `json:"activity_type" binding:"required"`
	Title             string          `json:"title" binding:"required"`
	Level             *string         `json:"level"`
	HostMode          *string         `json:"host_mode"`
	Theme             *string         `json:"theme"`
	StartAt           *string         `json:"start_at"`
	EndAt             *string         `json:"end_at"`
	Venue             *string         `json:"venue"`
	OnlineURL         *string         `json:"online_url"`
	HostUnit          *string         `json:"host_unit"`
	OrganizerDeptID   *int64          `json:"organizer_dept_id"`
	InvitedExperts    json.RawMessage `json:"invited_experts"`
	EstAttendees      *int32          `json:"est_attendees"`
	ProjectID         *int64          `json:"project_id"`
	BudgetSubjectCode *string         `json:"budget_subject_code"`
	BudgetAmount      *string         `json:"budget_amount"`
	Agenda            json.RawMessage `json:"agenda"`
	AttachmentIDs     json.RawMessage `json:"attachment_ids"`
	SecurityLevel     *string         `json:"security_level"`
	Remark            *string         `json:"remark"`
}

func parseTS(s *string) *time.Time {
	if s == nil || *s == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, *s)
	if err != nil {
		return nil
	}
	return &t
}

func jsonOrEmpty(b json.RawMessage) []byte {
	if len(b) == 0 {
		return []byte("[]")
	}
	return b
}

func numeric(s *string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != nil && *s != "" {
		_ = n.Scan(*s)
	}
	return n
}

func (h *Handler) ListActivities(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	var from, to *time.Time
	if f := optQuery(c, "from"); f != nil {
		if t, err := time.Parse("2006-01-02", *f); err == nil {
			from = &t
		}
	}
	if t := optQuery(c, "to"); t != nil {
		if tt, err := time.Parse("2006-01-02", *t); err == nil {
			to = &tt
		}
	}
	var kw *string
	if v := optQuery(c, "keyword"); v != nil {
		w := "%" + *v + "%"
		kw = &w
	}
	rows, err := h.q.ListActivities(c, vstore.ListActivitiesParams{
		TenantID: d.TenantID, Status: optQuery(c, "status"), ActivityType: optQuery(c, "activity_type"),
		Level: optQuery(c, "level"), HostMode: optQuery(c, "host_mode"), OrganizerDeptID: optInt64(c, "organizer_dept_id"),
		From: from, To: to, Keyword: kw, Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountActivities(c, vstore.CountActivitiesParams{
		TenantID: d.TenantID, Status: optQuery(c, "status"), ActivityType: optQuery(c, "activity_type"),
		Level: optQuery(c, "level"), HostMode: optQuery(c, "host_mode"), OrganizerDeptID: optInt64(c, "organizer_dept_id"),
		From: from, To: to, Keyword: kw,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIActivity(vstore.Activity(r)))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

func (h *Handler) GetActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	parts, _ := h.q.ListParticipants(c, vstore.ListParticipantsParams{ActivityID: id, TenantID: d.TenantID})
	revs, _ := h.q.ListReviews(c, vstore.ListReviewsParams{ActivityID: id, TenantID: d.TenantID})
	plist := make([]map[string]any, 0, len(parts))
	for _, p := range parts {
		plist = append(plist, ToAPIParticipant(p))
	}
	rlis := make([]map[string]any, 0, len(revs))
	for _, rv := range revs {
		rlis = append(rlis, ToAPIReview(rv))
	}
	out := ToAPIActivity(vstore.Activity(r))
	out["participants"] = plist
	out["reviews"] = rlis
	httpx.WriteOK(c, out)
}

func (h *Handler) CreateActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	var body activityBody
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	sl := "INTERNAL"
	if body.SecurityLevel != nil && *body.SecurityLevel != "" {
		sl = *body.SecurityLevel
	}
	r, err := h.q.CreateActivity(c, vstore.CreateActivityParams{
		TenantID: d.TenantID, Status: "DRAFT", SecurityLevel: sl, CreatorID: d.UserID,
		Code: nil, ActivityType: body.ActivityType, Level: body.Level, HostMode: body.HostMode,
		Title: body.Title, Theme: body.Theme, StartAt: parseTS(body.StartAt), EndAt: parseTS(body.EndAt),
		Venue: body.Venue, OnlineUrl: body.OnlineURL, HostUnit: body.HostUnit, OrganizerDeptId: body.OrganizerDeptID,
		InvitedExperts: jsonOrEmpty(body.InvitedExperts), EstAttendees: body.EstAttendees, ProjectId: body.ProjectID,
		BudgetSubjectCode: body.BudgetSubjectCode, BudgetAmount: numeric(body.BudgetAmount),
		Agenda: jsonOrEmpty(body.Agenda), AttachmentIds: jsonOrEmpty(body.AttachmentIDs), Remark: body.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	// M0 code 分配：ACT-<年>-<id 6 位补零>，回写（不引编号中心，见 §6 注）
	code := fmt.Sprintf("ACT-%d-%06d", time.Now().Year(), r.ID)
	_ = code // 见步骤 2：若已加 AssignCode 查询则回写；否则 ToAPI 里 code=null 由 passthrough 演示
	httpx.WriteOK(c, ToAPIActivity(vstore.Activity(r)))
}

func (h *Handler) UpdateActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body activityBody
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	sl := "INTERNAL"
	if body.SecurityLevel != nil && *body.SecurityLevel != "" {
		sl = *body.SecurityLevel
	}
	r, err := h.q.UpdateActivity(c, vstore.UpdateActivityParams{
		ID: id, TenantID: d.TenantID, ActivityType: body.ActivityType, Level: body.Level,
		HostMode: body.HostMode, Title: body.Title, Theme: body.Theme, StartAt: parseTS(body.StartAt),
		EndAt: parseTS(body.EndAt), Venue: body.Venue, OnlineUrl: body.OnlineURL, HostUnit: body.HostUnit,
		OrganizerDeptId: body.OrganizerDeptID, InvitedExperts: jsonOrEmpty(body.InvitedExperts),
		EstAttendees: body.EstAttendees, ProjectId: body.ProjectID, BudgetSubjectCode: body.BudgetSubjectCode,
		BudgetAmount: numeric(body.BudgetAmount), Agenda: jsonOrEmpty(body.Agenda),
		AttachmentIds: jsonOrEmpty(body.AttachmentIDs), SecurityLevel: sl, Remark: body.Remark, ModifierID: d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "活动不存在或状态不可编辑（仅 DRAFT/RETURNED）")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(vstore.Activity(r)))
}

func (h *Handler) DeleteActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	n, err := h.q.SoftDeleteActivity(c, vstore.SoftDeleteActivityParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}
```

> `AssignCode` 若需要真实回写 code，追加一条 `-- name: AssignCode :exec UPDATE v_activity SET code=$3 WHERE id=$1 AND tenant_id=$2` 到 `v_activity.sql` 后重生成并在 Create 末尾 `_ = h.q.AssignCode(...)`。M0 演示不强制，故默认留空 code。

- [ ] **步骤 2：写状态机与其余端点（追加到同文件）**

```go
// 合法迁移表（硬编码状态机，端点驱动）。键 = from，值 = 允许 to 集合。
var allowedTransitions = map[string]map[string]bool{
	"DRAFT":       {"SUBMITTED": true, "CANCELLED": true},
	"RETURNED":    {"SUBMITTED": true, "CANCELLED": true},
	"SUBMITTED":   {"DEPT_REVIEW": true, "APPROVED": true, "REJECTED": true, "RETURNED": true, "CANCELLED": true},
	"DEPT_REVIEW": {"APPROVED": true, "REJECTED": true, "RETURNED": true, "CANCELLED": true},
	"APPROVED":    {"HELD": true, "CANCELLED": true},
	"HELD":        {"ARCHIVED": true},
}

// 单级审批：APPROVE→APPROVED 或进入下一级；REJECT→REJECTED；RETURN→RETURNED。
func nextOnApprove(from string, level int16, action string) (to string, ok bool) {
	switch action {
	case "REJECT":
		if from == "SUBMITTED" || from == "DEPT_REVIEW" {
			return "REJECTED", true
		}
	case "RETURN":
		if from == "SUBMITTED" || from == "DEPT_REVIEW" {
			return "RETURNED", true
		}
	case "APPROVE":
		if from == "SUBMITTED" {
			if level <= 1 {
				return "DEPT_REVIEW", true // 部门一级通过后进入院所级
			}
			return "APPROVED", true
		}
		if from == "DEPT_REVIEW" {
			return "APPROVED", true
		}
	}
	return "", false
}

func (h *Handler) SubmitActivity(c *gin.Context) { h.transition(c, "SUBMITTED") }

func (h *Handler) transition(c *gin.Context, to string) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	cur, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	if !allowedTransitions[cur.Status][to] {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移："+cur.Status+"→"+to)
		return
	}
	r, err := h.q.TransitionStatus(c, vstore.TransitionStatusParams{
		ID: id, TenantID: d.TenantID, FromStatus: cur.Status, ToStatus: to, ModifierID: d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "状态迁移失败")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(vstore.Activity(r)))
}

func (h *Handler) ApproveActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		ReviewLevel *int16  `json:"review_level"`
		Action      string  `json:"action" binding:"required"`
		Opinion     *string `json:"opinion"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	level := int16(1)
	if body.ReviewLevel != nil {
		level = *body.ReviewLevel
	}
	cur, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	to, ok := nextOnApprove(cur.Status, level, body.Action)
	if !ok {
		httpx.WriteErr(c, 409, 40901, "非法审批：当前态 "+cur.Status+" 不支持该动作/层级")
		return
	}
	// 写留痕
	_, _ = h.q.InsertReview(c, vstore.InsertReviewParams{
		ActivityId: id, ReviewLevel: level, ReviewerId: d.UserID, Action: body.Action, Opinion: body.Opinion, TenantID: d.TenantID,
	})
	r, err := h.q.TransitionStatus(c, vstore.TransitionStatusParams{
		ID: id, TenantID: d.TenantID, FromStatus: cur.Status, ToStatus: to, ModifierID: d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "状态迁移失败")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(vstore.Activity(r)))
}

func (h *Handler) HoldActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		SignInCount  *int32   `json:"sign_in_count"`
		HoldProofIDs []string `json:"hold_proof_ids"`
	}
	_ = c.ShouldBindJSON(&body)
	var proofs []byte
	if len(body.HoldProofIDs) > 0 {
		proofs, _ = json.Marshal(body.HoldProofIDs)
	}
	r, err := h.q.MarkHold(c, vstore.MarkHoldParams{
		ID: id, TenantID: d.TenantID, SignInCount: body.SignInCount, HoldProofIds: proofs, ModifierID: d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "仅 APPROVED 可标记举办")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(vstore.Activity(r)))
}

func (h *Handler) ArchiveActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		MinutesRich *string `json:"minutes_rich"`
	}
	_ = c.ShouldBindJSON(&body)
	if body.MinutesRich == nil || *body.MinutesRich == "" {
		httpx.WriteErr(c, 400, 40002, "归档需填纪要")
		return
	}
	r, err := h.q.MarkArchive(c, vstore.MarkArchiveParams{
		ID: id, TenantID: d.TenantID, MinutesRich: body.MinutesRich, ModifierID: d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "仅 HELD 可归档")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(vstore.Activity(r)))
}

func (h *Handler) CancelActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		CancelReason *string `json:"cancel_reason"`
	}
	_ = c.ShouldBindJSON(&body)
	r, err := h.q.MarkCancel(c, vstore.MarkCancelParams{
		ID: id, TenantID: d.TenantID, CancelReason: body.CancelReason, ModifierID: d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "终态不可取消")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(vstore.Activity(r)))
}

func (h *Handler) ActivityCalendar(c *gin.Context) {
	d := auth.DomainFrom(c)
	month := c.DefaultQuery("month", time.Now().Format("2006-01"))
	start, err := time.Parse("2006-01", month)
	if err != nil {
		httpx.WriteErr(c, 400, 40003, "month 需 YYYY-MM")
		return
	}
	end := start.AddDate(0, 1, 0)
	rows, _ := h.q.ListCalendar(c, vstore.ListCalendarParams{TenantID: d.TenantID, StartAt: start, EndAt: end})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIActivity(vstore.Activity(r)))
	}
	httpx.WriteOK(c, gin.H{"month": month, "list": list})
}

func (h *Handler) ActivityStats(c *gin.Context) {
	d := auth.DomainFrom(c)
	groupBy := c.DefaultQuery("group_by", "activity_type")
	type bucket struct {
		Key   string `json:"key"`
		Count int32  `json:"count"`
	}
	var raw []struct {
		Key   string `json:"key"`
		Count int32  `json:"count"`
	}
	var err error
	switch groupBy {
	case "level":
		raw, err = statsTo(h.q.StatsByLevel(c, d.TenantID))
	case "organizer_dept_id":
		raw, err = statsTo(h.q.StatsByDept(c, d.TenantID))
	case "month":
		raw, err = statsTo(h.q.StatsByMonth(c, d.TenantID))
	default:
		raw, err = statsTo(h.q.StatsByType(c, d.TenantID))
	}
	if err != nil {
		httpx.WriteErr(c, 500, 50004, "统计失败")
		return
	}
	buckets := make([]bucket, 0, len(raw))
	for _, r := range raw {
		buckets = append(buckets, bucket{Key: r.Key, Count: r.Count})
	}
	httpx.WriteOK(c, gin.H{"buckets": buckets})
}

// statsTo 归一各 StatsBy* 生成行（均为 {Key string, Count int32}）到统一切片。
// 各方法返回各自 Row 类型，用泛型收敛。
func statsTo[T any](rows []T, err error) ([]struct {
	Key   string `json:"key"`
	Count int32  `json:"count"`
}, error) {
	if err != nil {
		return nil, err
	}
	// 反射代价高且脆；改为逐类型 switch 在调用点处理更稳。此处保留占位说明，
	// 实际实现见步骤 3 的具体化版本。
	out := make([]struct {
		Key   string `json:"key"`
		Count int32  `json:"count"`
	}, 0, len(rows))
	return out, nil
}

func (h *Handler) ListParticipants(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, _ := h.q.ListParticipants(c, vstore.ListParticipantsParams{ActivityID: id, TenantID: d.TenantID})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIParticipant(r))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

func (h *Handler) AddParticipant(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		UserID      *int64  `json:"user_id"`
		GuestName   *string `json:"guest_name"`
		Role        string  `json:"role" binding:"required"`
		ReportTitle *string `json:"report_title"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if body.UserID == nil && (body.GuestName == nil || *body.GuestName == "") {
		httpx.WriteErr(c, 400, 40004, "user_id 与 guest_name 至少给一个")
		return
	}
	// 归属校验：活动须存在且属本租户
	if _, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	r, err := h.q.AddParticipant(c, vstore.AddParticipantParams{
		ActivityID: id, UserID: body.UserID, GuestName: body.GuestName, Role: body.Role, ReportTitle: body.ReportTitle, TenantID: d.TenantID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "参与人重复或写入冲突")
		return
	}
	httpx.WriteOK(c, ToAPIParticipant(r))
}

func (h *Handler) RemoveParticipant(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	pid, _ := strconv.ParseInt(c.Param("pid"), 10, 64)
	n, err := h.q.DeleteParticipant(c, vstore.DeleteParticipantParams{ID: pid, ActivityID: id, TenantID: d.TenantID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "参与人不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": pid, "deleted": true})
}
```

- [ ] **步骤 3：具体化 stats（删除 `statsTo` 泛型占位）**

把 `ActivityStats` 里的 `raw, err = statsTo(...)` 各分支改为直接对每种生成 Row 构造 `buckets`。示例（其余三个分支同构，仅方法名与字段来源不同）：

```go
	switch groupBy {
	case "level":
		rows, err := h.q.StatsByLevel(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, 500, 50004, "统计失败")
			return
		}
		for _, r := range rows {
			buckets = append(buckets, bucket{Key: r.Key, Count: r.Count})
		}
	// organizer_dept_id → h.q.StatsByDept；month → h.q.StatsByMonth；default → h.q.StatsByType（同体）
	default:
		rows, err := h.q.StatsByType(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, 500, 50004, "统计失败")
			return
		}
		for _, r := range rows {
			buckets = append(buckets, bucket{Key: r.Key, Count: r.Count})
		}
	}
	httpx.WriteOK(c, gin.H{"buckets": buckets})
```

> 删除步骤 2 中 `statsTo` 泛型函数与其占位注释。四个 `StatsBy*` 生成行的 `Key` 均为 `string`（列已 `::text` 或 `to_char`），`Count` 为 `int32`（`count(*)::int`）。`StatsByDept` 的 `key` 来自 `organizer_dept_id::text`，`StatsByMonth` 来自 `to_char(...)`——均文本，类型一致。

- [ ] **步骤 4：编译**

运行：`go build ./internal/modules/activity/`
预期：成功。若参数结构名/字段名与生成物不符（sqlc 命名规则），以 `store/*.sql.go` 的 `XxxParams` 为准修正调用点——这是唯一的“对表”动作，其余逻辑不变。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/modules/activity/handler.go
git commit -m "feat(V): 学术活动 handler（CRUD+状态机+日历/统计/参与人）"
```

---

### 任务 V-11：V routes

**文件：**
- 创建：`backend-go/internal/modules/activity/routes.go`

- [ ] **步骤 1：写注册**（gin v1.10 的 `gin.IRoutes` 无 `Group()`，直接相对路径注册；参数名统一 `:id`、`:pid`）

```go
package activity

import "github.com/gin-gonic/gin"

// Register 把 V 竖切挂到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 静态段 calendar/stats 先于 /:id 注册无冲突（gin 路由树区分静态与参数段，且方法一致）。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/activities", h.ListActivities)
	r.POST("/activities", h.CreateActivity)
	r.GET("/activities/calendar", h.ActivityCalendar)
	r.GET("/activities/stats", h.ActivityStats)
	r.GET("/activities/:id", h.GetActivity)
	r.PUT("/activities/:id", h.UpdateActivity)
	r.DELETE("/activities/:id", h.DeleteActivity)
	r.POST("/activities/:id/submit", h.SubmitActivity)
	r.POST("/activities/:id/approve", h.ApproveActivity)
	r.POST("/activities/:id/hold", h.HoldActivity)
	r.POST("/activities/:id/archive", h.ArchiveActivity)
	r.POST("/activities/:id/cancel", h.CancelActivity)
	r.GET("/activities/:id/participants", h.ListParticipants)
	r.POST("/activities/:id/participants", h.AddParticipant)
	r.DELETE("/activities/:id/participants/:pid", h.RemoveParticipant)
}
```

> `POST /activities/:id/submit` 等 POST 静态子路径与 `DELETE /activities/:id/participants/:pid` 共存不冲突（gin httprouter 对同层“静态段 vs 参数段”允许，因 `participants`、`submit` 等是不同字面量段）。若 gin 启动 panic 报 wildcard 冲突，把 `:pid` 改到不同父路径下——本路由树结构经 P/U 同类模式验证可行。

- [ ] **步骤 2：Commit**

```bash
git add backend-go/internal/modules/activity/routes.go
git commit -m "feat(V): 学术活动路由注册（15 条，覆盖契约 13 端点）"
```

---

### 任务 V-12：router 装配 V

**文件：**
- 修改：`backend-go/internal/router.go:8-18`（import 块）、`:51-54`（`if d.Pool != nil` 块）

- [ ] **步骤 1：加 import**

在 import 块内加：`"github.com/eplugger/ark/internal/modules/activity"`（与既有 `p`、`sysadmin` 并列）。

- [ ] **步骤 2：注册**

把 `if d.Pool != nil { ... }` 内改为：

```go
	if d.Pool != nil {
		p.Register(api, p.NewHandler(d.Pool))
		sysadmin.Register(api, sysadmin.NewHandler(d.Pool, d.Enforcer))
		activity.Register(api, activity.NewHandler(d.Pool))
	}
```

- [ ] **步骤 3：编译 + 现有路由测试回归**

运行：`go build ./... && go test ./internal/ -run TestBuild -v`
预期：`TestBuild_*` 全 PASS（未加 M 前，`/perf` 仍走 passthrough，不受影响）。

- [ ] **步骤 4：Commit**

```bash
git add backend-go/internal/router.go
git commit -m "feat(V): router 在 Pool!=nil 时注册学术活动竖切"
```

### 任务 V-13：Casbin 学术活动域策略 + 鉴权矩阵 + 能力覆盖

**文件：**
- 修改：`backend-go/internal/platform/auth/policy.csv`（末尾追加 V 段）
- 修改：`backend-go/internal/platform/auth/policy_test.go:52-63`（cases 表内追加 V 断言行）
- 测试：`backend-go/internal/platform/auth/caps_v_test.go`（新建，能力覆盖断言）

> 设计要点：state-transition 动作（submit/approve/hold/archive/cancel）在 V-11 均注册为 **POST**。若给 R-STAFF 放行宽泛的 `POST /api/v1/activities/*`，研究员就能越权调用 `approve`。故对研究员按**子路径显式列举**（`/activities/*/submit`、`/activities/*/participants`、`/activities/*/participants/*`），只给 submit，不给 approve/hold/archive/cancel；主管给全量 POST/PUT/DELETE；领导只给 approve/hold 审批动作；审计员只读。keyMatch2 中 `*` → `.*`，`/api/v1/activities/*` 能匹配 `/activities/calendar`、`/activities/stats`、`/activities/1`、`/activities/1/submit`，但**匹配不到裸** `/activities`（无尾斜杠），因此 list/create 需各补一条精确 `/api/v1/activities`。

- [ ] **步骤 1：追加 V 段到 `policy.csv`**

在 `policy.csv` 现有内容末尾（`# ---- 每个已认证角色都能读自身身份/能力 ----` 段之前）插入：

```csv
# ---- 学术活动域（V）：研究员建/编/提交、主管全权、领导审批、审计只读 ----
# 研究员：读列表/详情、创建、编辑、参与人维护、提交（submit）；不得 approve/hold/archive/cancel/delete
p, R-STAFF,   /api/v1/activities,                    GET
p, R-STAFF,   /api/v1/activities,                    POST
p, R-STAFF,   /api/v1/activities/*,                  GET
p, R-STAFF,   /api/v1/activities/*,                  PUT
p, R-STAFF,   /api/v1/activities/*/submit,           POST
p, R-STAFF,   /api/v1/activities/*/participants,     POST
p, R-STAFF,   /api/v1/activities/*/participants/*,   DELETE
# 主管：本域全量读写（含 approve/hold/archive/cancel、删除）
p, R-MANAGER, /api/v1/activities,                    GET
p, R-MANAGER, /api/v1/activities,                    POST
p, R-MANAGER, /api/v1/activities/*,                  GET
p, R-MANAGER, /api/v1/activities/*,                  POST
p, R-MANAGER, /api/v1/activities/*,                  PUT
p, R-MANAGER, /api/v1/activities/*,                  DELETE
# 领导：读 + 审批类动作（approve / hold）
p, R-LEADER,  /api/v1/activities,                    GET
p, R-LEADER,  /api/v1/activities/*,                  GET
p, R-LEADER,  /api/v1/activities/*/approve,          POST
p, R-LEADER,  /api/v1/activities/*/hold,             POST
# 审计员：本域只读
p, R-AUDITOR, /api/v1/activities,                    GET
p, R-AUDITOR, /api/v1/activities/*,                  GET
```

- [ ] **步骤 2：扩鉴权矩阵用例**

在 `policy_test.go` 的 `cases := []c{ ... }` 切片内，`// —— 未知角色：一律拒 ——` 之前追加：

```go
		// —— 学术活动域 V：按角色收敛 ——
		{"R-STAFF",   "/api/v1/activities",                "POST", true},   // 建活动
		{"R-STAFF",   "/api/v1/activities/1/submit",        "POST", true},   // 提交
		{"R-STAFF",   "/api/v1/activities/1/participants",  "POST", true},   // 加参与人
		{"R-STAFF",   "/api/v1/activities/1/approve",       "POST", false},  // 越权审批→拒
		{"R-STAFF",   "/api/v1/activities/1/hold",          "POST", false},  // 越权挂起→拒
		{"R-STAFF",   "/api/v1/activities/1",               "DELETE", false},// 越权删除→拒
		{"R-MANAGER", "/api/v1/activities/1/approve",       "POST", true},   // 主管审批
		{"R-MANAGER", "/api/v1/activities/1",               "DELETE", true}, // 主管删除
		{"R-LEADER",  "/api/v1/activities/1/approve",       "POST", true},   // 领导审批
		{"R-LEADER",  "/api/v1/activities/1",               "DELETE", false},// 领导不可删
		{"R-LEADER",  "/api/v1/activities/1/cancel",        "POST", false},  // 领导无 cancel
		{"R-AUDITOR", "/api/v1/activities",                 "GET", true},    // 审计只读（列表）
		{"R-AUDITOR", "/api/v1/activities/1",               "POST", false},  // 审计无写
		{"R-FINANCE", "/api/v1/activities",                 "GET", false},   // 财务未获 V 域授权
```

- [ ] **步骤 3：运行矩阵测试**

运行：`go test ./internal/platform/auth/ -run TestAuthMatrix_TransportLayer -v`
预期：PASS（含新增 14 条 V 断言）。若某条 false 不符，回到步骤 1 校正子路径（尤其 `*` 与裸路径）。

- [ ] **步骤 4：写能力覆盖测试 `caps_v_test.go`**

```go
package auth

import (
	"os"
	"strings"
	"testing"
)

// R-STAFF 的 BuildCaps 应包含 submit 动作的能力模板，但不包含 approve/hold 审批动作。
// 与鉴权矩阵同源：前端 auth.can 据此门控按钮可见性。
func TestBuildCaps_ActivityStaffCaps(t *testing.T) {
	model := os.Getenv("ARK_AUTH_MODEL_PATH")
	if model == "" {
		model = "./model.conf"
	}
	pol := os.Getenv("ARK_AUTH_POLICY_PATH")
	if pol == "" {
		pol = "./policy.csv"
	}
	enf, err := NewEnforcer(model, pol)
	if err != nil {
		t.Fatal(err)
	}
	caps := BuildCaps(enf, []string{"R-STAFF"})
	var hasSubmit, hasApprove, hasHold bool
	for _, c := range caps {
		switch {
		case strings.HasSuffix(c, "/api/v1/activities/*/submit POST"):
			hasSubmit = true
		case strings.HasSuffix(c, "/api/v1/activities/*/approve POST"):
			hasApprove = true
		case strings.HasSuffix(c, "/api/v1/activities/*/hold POST"):
			hasHold = true
		}
	}
	if !hasSubmit {
		t.Errorf("R-STAFF 应有 submit 能力: %v", caps)
	}
	if hasApprove || hasHold {
		t.Errorf("R-STAFF 不应有审批(approve/hold)能力: approve=%v hold=%v", hasApprove, hasHold)
	}
}
```

- [ ] **步骤 5：运行能力测试**

运行：`go test ./internal/platform/auth/ -run TestBuildCaps -v`
预期：`TestBuildCaps_ActivityStaffCaps`、`TestBuildCaps_NoWritesForAuditor`、`TestBuildCaps_FromPolicy` 全 PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/platform/auth/policy.csv backend-go/internal/platform/auth/policy_test.go backend-go/internal/platform/auth/caps_v_test.go
git commit -m "feat(V): Casbin 学术活动域策略（按动作收敛）+ 鉴权矩阵/能力覆盖测试"
```

### 任务 V-14：学术活动契约校验 + handler 测试（DB 门控）

**文件：**
- 测试：`backend-go/internal/modules/activity/contract_test.go`（新建）
- 测试：`backend-go/internal/modules/activity/handler_test.go`（新建）

> 与 `p` 包同构：纯契约形状测试无 DB 常跑；endpoint/transition 测试无 `ARK_TEST_DATABASE_URL` 时 `t.Skip`。`newTestEngine` 用 `Register(api, NewHandler(pool))` 挂到 `/api/v1` 分组。V handler 读 `d.UserID` 作 creator/modifier，故 `injectDomain` 须同时塞 `CtxTenantID` 与 `CtxUserID`（P 只塞了租户）。

- [ ] **步骤 1：写 `contract_test.go`**

```go
package activity

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// mustSpec 从仓库根 design/ 载入契约。测试工作目录 = backend-go/internal/modules/activity，
// 上溯 4 级至仓库根，故 ../../../../design。可用 DESIGN_DIR 覆盖。
func mustSpec(t *testing.T) *oapi.Spec {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../../../design"
	}
	s, err := oapi.LoadDir(d)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// 纯形状校验：GET /activities 的 data 应为 PageResult；total 由 integer 漂成 string 必须被拒。
func TestValidate_ActivityContractShape(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/activities")
	if op == nil {
		t.Fatal("未找到 GET /activities")
	}
	dataSchema := oapi.ResolveDataSchema(op)

	good := map[string]any{
		"list":  []any{},
		"total": 5,
		"page":  1,
		"size":  20,
	}
	if errs := oapi.Validate(good, dataSchema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}

	bad := map[string]any{"list": []any{}, "total": "五", "page": 1, "size": 20}
	if errs := oapi.Validate(bad, dataSchema); len(errs) == 0 {
		t.Fatal("类型漂移(total: string)未被校验器捕获")
	}
}

// DB 门控：真实 handler 的响应 data 须对契约合规。
func TestListActivities_ConformsToContract(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	e := newTestEngine(t)
	spec := mustSpec(t)
	op := spec.Find("GET", "/activities")
	dataSchema := oapi.ResolveDataSchema(op)

	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/activities", nil))
	var env map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &env)

	if errs := oapi.Validate(env["data"], dataSchema); len(errs) > 0 {
		t.Fatalf("响应 data 不合契约: %v", errs)
	}
}
```

- [ ] **步骤 2：写 `handler_test.go`**

```go
package activity

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// M0 无鉴权中间件，手工塞数据域（V handler 需 tenant_id + user_id）。
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxUserID, int64(1001))
	c.Next()
}

func newTestEngine(t *testing.T) *gin.Engine {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomain)
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool))
	return e
}

// 依赖 testdata/seed_v.sql：tenant=1 未删 2 行，A 为 DRAFT 可流转。
func TestListActivities_Endpoint(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/activities?page=1&size=20", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int `json:"code"`
		Data struct {
			List  []map[string]any `json:"list"`
			Total int              `json:"total"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Code != 0 || env.Data.Total != 2 || len(env.Data.List) != 2 {
		t.Fatalf("列表结果不符（期望 tenant=1 未删 2 行）: %+v", env)
	}
	row := env.Data.List[0]
	if _, ok := row["budget_amount"].(string); !ok {
		t.Fatalf("budget_amount 应为字符串: %#v", row["budget_amount"])
	}
}

func TestGetActivity_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/activities/999999", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("期望 404，实得 %d", w.Code)
	}
}

// DRAFT → SUBMITTED 合法流转；重复 submit 应命中状态机拒绝（40901）。
func TestSubmitActivity_Transition(t *testing.T) {
	e := newTestEngine(t)
	// 先建一条 DRAFT
	body := bytes.NewBufferString(`{"title":"T1 学术报告","activity_type":"LECTURE"}`)
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/activities", body)
	req.Header.Set("Content-Type", "application/json")
	e.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("创建失败 HTTP %d body=%s", w.Code, w.Body.String())
	}
	var created struct {
		Data struct {
			ID     int64  `json:"id"`
			Status string `json:"status"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &created)
	if created.Data.Status != "DRAFT" {
		t.Fatalf("新建应为 DRAFT，实得 %q", created.Data.Status)
	}

	subURL := "/api/v1/activities/" + strconv.FormatInt(created.Data.ID, 10) + "/submit"
	w2 := httptest.NewRecorder()
	e.ServeHTTP(w2, httptest.NewRequest("POST", subURL, nil))
	if w2.Code != 200 {
		t.Fatalf("submit HTTP %d body=%s", w2.Code, w2.Body.String())
	}

	// 再次 submit：已 SUBMITTED，状态机应拒
	w3 := httptest.NewRecorder()
	e.ServeHTTP(w3, httptest.NewRequest("POST", subURL, nil))
	var denied map[string]any
	_ = json.Unmarshal(w3.Body.Bytes(), &denied)
	if denied["code"] == float64(0) {
		t.Fatalf("重复 submit 不应成功: %s", w3.Body.String())
	}
}
```

> 拼 `submit` URL 用标准库 `strconv.FormatInt(created.Data.ID, 10)`（与 M-15 测试同源）；测试文件 import 块须含 `"strconv"`。不引入自定义 `itoa`。

- [ ] **步骤 3：跑无 DB 的契约形状测试**

运行：`DESIGN_DIR=../../../../design go test ./internal/modules/activity/ -run TestValidate_ActivityContractShape -v`
预期：PASS。endpoint 测试本机无库会 `t.Skip`（正常）。

- [ ] **步骤 4：有库条件回归（可选，CI/本地有 Postgres 时）**

先灌种子（见 V-15），再：
运行：`ARK_TEST_DATABASE_URL=postgres://ark:ark@localhost:5432/ark go test ./internal/modules/activity/ -v`
预期：`TestListActivities_*`、`TestGetActivity_404WhenMissing`、`TestSubmitActivity_Transition` 全 PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/modules/activity/contract_test.go backend-go/internal/modules/activity/handler_test.go
git commit -m "test(V): 学术活动契约形状校验 + DB 门控 handler/状态机测试"
```

### 任务 V-15：学术活动演示种子

**文件：**
- 创建：`backend-go/testdata/seed_v.sql`

> 与 `seed_p.sql` 同规格：tenant=1 未删 2 行（供 `TestListActivities_Endpoint` 断言 total==2），1 行 tenant=2，1 行 tenant=1 且 `deleted=1`。列名对齐 V-2 DDL（`activity_type`/`level`/`host_mode`/`organizer_dept_id`/`venue`/`budget_amount` 等）；时间戳用相对 `now()`。

- [ ] **步骤 1：写 `seed_v.sql`**（列名/枚举严格对齐 V-2 DDL）

```sql
-- 2 行 tenant=1 正常（A 为 DRAFT 供状态机流转测试），1 行 tenant=2，1 行 tenant=1 且 deleted=1
INSERT INTO v_activity
  (tenant_id, status, creator_id, title, activity_type, level, host_mode,
   organizer_dept_id, start_at, end_at, venue, budget_amount)
VALUES
  (1,'DRAFT',    1001,'A 量子计算专题报告','LECTURE','NATIONAL',   'HOST',  5001, now()+interval '7 day', now()+interval '7 day' + interval '2 hour','主楼报告厅','5000.00'),
  (1,'SUBMITTED',1001,'B 交叉学科研讨会',  'SEMINAR','PROVINCIAL', 'HOST',  5001, now()+interval '14 day',now()+interval '14 day'+ interval '6 hour','国际会议中心','20000.00'),
  (2,'DRAFT',    1002,'C 院内学术讲座',    'LECTURE','CAMPUS',     'ATTEND',5002, now()+interval '3 day', now()+interval '3 day' + interval '1 hour','三楼会议室','0.00'),
  (1,'DRAFT',    1001,'D 已撤销活动',      'OTHER',  'CAMPUS',     'HOST',  5001, now()+interval '1 day', now()+interval '1 day',              '临时','0.00');
UPDATE v_activity SET deleted=1 WHERE title='D 已撤销活动';

-- 给 A 活动挂 2 名参与人（演示 participants 子资源；user_id 逻辑外键）
INSERT INTO v_activity_participant (tenant_id, activity_id, user_id, role)
SELECT 1, id, 2001, 'SPEAKER' FROM v_activity WHERE title='A 量子计算专题报告'
UNION ALL
SELECT 1, id, 2002, 'MEMBER'  FROM v_activity WHERE title='A 量子计算专题报告';
```

> 种子列与枚举严格取自 V-2 DDL 的 CHECK：`activity_type`∈{CONFERENCE,LECTURE,SEMINAR,TRAINING,OTHER}、`level`∈{INTERNATIONAL,NATIONAL,PROVINCIAL,CAMPUS}、`host_mode`∈{HOST,ATTEND,SPONSOR}、`role`∈{SPEAKER,CHAIR,MEMBER,ATTENDEE}。若 DDL 已改这些取值，以 DDL 为准更正种子（种子服从 schema，不改 schema）。v_activity_participant 无 creator_id 列，勿插。

- [ ] **步骤 2：语法自检（有库条件）**

运行（本地 PG）：`psql "$ARK_TEST_DATABASE_URL" -f backend-go/testdata/seed_v.sql && psql "$ARK_TEST_DATABASE_URL" -c "SELECT count(*) FROM v_activity WHERE tenant_id=1 AND deleted=0;"`
预期：`count = 2`。无库时跳过（文件仅入仓，CI 灌库后生效）。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/testdata/seed_v.sql
git commit -m "chore(V): 学术活动演示种子（2 可见/1 跨租户/1 软删 + 参与人）"
```

---

## 阶段二 · 模块 M（科研绩效评价）

> 约定：M 全部路径前缀 `/perf`（整路径 `/api/v1/perf...`）。绩效记录状态机 token：`CALCULATED/CONFIRMED/APPROVED/PAID/APPEAL/VOID`；发放单状态机：`DRAFT/APPROVING/APPROVED/PAID/REJECTED`。M 的 `calculate` 端点跨模块只读取数：`r_output`（成果数/级别）、`f_income`（到账经费）、`e_project`（在研项目数）、`t_deal`（转化）。取数 SQL 只碰这些表的**已存在列**，绝不改它们的 DDL。

### 任务 M-1：绩效评价契约（14-…-M.openapi.yaml）

**文件：**
- 创建：`design/14-科研绩效评价-M.openapi.yaml`
- 同步副本：`frontend/src/api/schema/14-科研绩效评价-M.openapi.yaml`（`cp` 逐字节一致）

> components 段与 12-U / 13-V 契约同构：统一 `ApiResponse{code,message,data,traceId,timestamp}` 包裹，列表用 `allOf:[ApiResponse,{data:{allOf:[PageResult,{list:{items:$ref}}]}}]`。金额/权重（NUMERIC）契约声明为 `type: string`（精度串），与前端 `utils/money.ts` 解析一致。全部路径前缀 `/perf`（相对分组）。

- [ ] **步骤 1：写契约文件**

```yaml
openapi: 3.0.3
info:
  title: 科研管理系统 · 14 科研绩效评价 API（模块 M）
  version: "1.0.0"
  description: >-
    绩效方案/因子配置、按方案从 R/F/E/T 真表聚合自动计分、记录确认-申诉-审批、在线发放审批、
    个人绩效与排行。统一响应 ApiResponse{code,message,data,traceId,timestamp}；分页 PageResult{list,total,page,size}；
    认证 Bearer JWT；写方法支持 Idempotency-Key。实体字段名与 DDL 列名一致（snake_case）。
    授权 Casbin（RBAC）+ 数据域 ABAC（tenant_id；/perf/me 与个人记录强制 staff_user_id=当前用户）。
servers:
  - url: https://{host}/api/v1
    variables:
      host: { default: api.institute.example.com }
tags:
  - { name: performance, description: 科研绩效评价（方案·计分·记录·发放） }
security:
  - bearerAuth: []
paths:
  /perf/schemes:
    get:
      tags: [performance]
      summary: 方案列表（租户隔离 + 筛选 + 分页）
      operationId: listSchemes
      parameters:
        - { name: period_type, in: query, schema: { type: string, enum: [YEAR, QUARTER, MONTH] } }
        - { name: effective_period, in: query, schema: { type: string } }
        - { name: scope_dept_id, in: query, schema: { type: integer, format: int64 } }
        - { name: active, in: query, schema: { type: boolean } }
        - { name: keyword, in: query, schema: { type: string } }
        - $ref: '#/components/parameters/Page'
        - $ref: '#/components/parameters/Size'
      responses:
        '200':
          description: 分页方案列表
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        allOf:
                          - $ref: '#/components/schemas/PageResult'
                          - type: object
                            properties:
                              list: { type: array, items: { $ref: '#/components/schemas/Scheme' } }
    post:
      tags: [performance]
      summary: 新建方案（DRAFT，含 code=PERF 前缀由编号中心分配）
      operationId: createScheme
      parameters: [ { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/SchemeRequest' }
      responses:
        '200':
          description: 创建后的方案
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Scheme' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
  /perf/schemes/{id}:
    get:
      tags: [performance]
      summary: 方案详情（含 factors）
      operationId: getScheme
      parameters: [ { $ref: '#/components/parameters/PathId' } ]
      responses:
        '200':
          description: 方案详情
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/SchemeDetail' }
        '404': { $ref: '#/components/responses/NotFound' }
    put:
      tags: [performance]
      summary: 编辑方案（仅未生效可改）
      operationId: updateScheme
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/SchemeRequest' }
      responses:
        '200':
          description: 更新后的方案
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Scheme' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
    delete:
      tags: [performance]
      summary: 软删方案（deleted=1）
      operationId: deleteScheme
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 操作结果
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { id: { type: integer, format: int64 }, deleted: { type: boolean } } }
        '404': { $ref: '#/components/responses/NotFound' }
  /perf/schemes/{id}/activate:
    post:
      tags: [performance]
      summary: 启用方案（同 tenant+period_type+effective_period+scope 置唯一 active，旧 active 转 SUPERSEDED）
      operationId: activateScheme
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 启用后的方案
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Scheme' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/schemes/{id}/factors:
    get:
      tags: [performance]
      summary: 方案因子列表
      operationId: listFactors
      parameters: [ { $ref: '#/components/parameters/PathId' } ]
      responses:
        '200':
          description: 因子数组
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { list: { type: array, items: { $ref: '#/components/schemas/Factor' } } } }
    post:
      tags: [performance]
      summary: 新增/覆盖方案因子（uk scheme_id+factor_code upsert）
      operationId: upsertFactor
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/FactorRequest' }
      responses:
        '200':
          description: 保存后的因子
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Factor' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '404': { $ref: '#/components/responses/NotFound' }
  /perf/schemes/{id}/factors/{factorId}:
    put:
      tags: [performance]
      summary: 编辑因子
      operationId: updateFactor
      parameters:
        - { $ref: '#/components/parameters/PathId' }
        - { name: factorId, in: path, required: true, schema: { type: integer, format: int64 } }
        - { $ref: '#/components/parameters/IdempotencyKey' }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/FactorRequest' }
      responses:
        '200':
          description: 更新后的因子
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Factor' }
        '404': { $ref: '#/components/responses/NotFound' }
    delete:
      tags: [performance]
      summary: 删除因子
      operationId: deleteFactor
      parameters:
        - { $ref: '#/components/parameters/PathId' }
        - { name: factorId, in: path, required: true, schema: { type: integer, format: int64 } }
        - { $ref: '#/components/parameters/IdempotencyKey' }
      responses:
        '200':
          description: 操作结果
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { factor_id: { type: integer, format: int64 }, deleted: { type: boolean } } }
        '404': { $ref: '#/components/responses/NotFound' }
  /perf/schemes/{id}/calculate:
    post:
      tags: [performance]
      summary: 触发计分（按方案因子从 R/F/E/T 真表聚合→算分→upsert 记录+明细，calc_batch 幂等）
      operationId: calculatePerformance
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/CalculateRequest' }
      responses:
        '200':
          description: 计算结果汇总
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/CalculateResult' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
  /perf/records:
    get:
      tags: [performance]
      summary: 绩效记录列表（筛选 scheme/period/dept/status/keyword，分页，ABAC）
      operationId: listRecords
      parameters:
        - { name: scheme_id, in: query, schema: { type: integer, format: int64 } }
        - { name: period, in: query, schema: { type: string } }
        - { name: dept_id, in: query, schema: { type: integer, format: int64 } }
        - { name: staff_user_id, in: query, schema: { type: integer, format: int64 } }
        - { name: status, in: query, schema: { type: string, enum: [CALCULATED, CONFIRMED, APPROVED, PAID, APPEAL, VOID] } }
        - { name: keyword, in: query, schema: { type: string } }
        - $ref: '#/components/parameters/Page'
        - $ref: '#/components/parameters/Size'
      responses:
        '200':
          description: 分页记录列表
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        allOf:
                          - $ref: '#/components/schemas/PageResult'
                          - type: object
                            properties:
                              list: { type: array, items: { $ref: '#/components/schemas/Record' } }
  /perf/records/{id}:
    get:
      tags: [performance]
      summary: 记录详情（非管理角色强制 staff_user_id=本人）
      operationId: getRecord
      parameters: [ { $ref: '#/components/parameters/PathId' } ]
      responses:
        '200':
          description: 绩效记录
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Record' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
  /perf/records/{id}/detail:
    get:
      tags: [performance]
      summary: 记录明细（含 items + evidence）
      operationId: getRecordDetail
      parameters: [ { $ref: '#/components/parameters/PathId' } ]
      responses:
        '200':
          description: 记录明细
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/RecordDetail' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
  /perf/records/{id}/confirm:
    post:
      tags: [performance]
      summary: 本人/管理确认（CALCULATED → CONFIRMED）
      operationId: confirmRecord
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 确认后的记录
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Record' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/records/{id}/appeal:
    post:
      tags: [performance]
      summary: 申诉（CALCULATED/CONFIRMED → APPEAL，body reason）
      operationId: appealRecord
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { type: object, required: [reason], properties: { reason: { type: string } } }
      responses:
        '200':
          description: 申诉后的记录
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Record' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/records/{id}/approve:
    post:
      tags: [performance]
      summary: 审批（CONFIRMED → APPROVED，管理角色）
      operationId: approveRecord
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 审批后的记录
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Record' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/records/{id}/void:
    post:
      tags: [performance]
      summary: 作废（任意未发放态 → VOID，body reason）
      operationId: voidRecord
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: false
        content:
          application/json:
            schema: { type: object, properties: { reason: { type: string } } }
      responses:
        '200':
          description: 作废后的记录
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Record' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/payouts:
    get:
      tags: [performance]
      summary: 发放单列表（筛选 scheme/period/status，分页）
      operationId: listPayouts
      parameters:
        - { name: period, in: query, schema: { type: string } }
        - { name: status, in: query, schema: { type: string, enum: [DRAFT, APPROVING, APPROVED, PAID, REJECTED] } }
        - { name: payee_user_id, in: query, schema: { type: integer, format: int64 } }
        - $ref: '#/components/parameters/Page'
        - $ref: '#/components/parameters/Size'
      responses:
        '200':
          description: 分页发放单
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        allOf:
                          - $ref: '#/components/schemas/PageResult'
                          - type: object
                            properties:
                              list: { type: array, items: { $ref: '#/components/schemas/Payout' } }
    post:
      tags: [performance]
      summary: 从 APPROVED 记录发起发放（DRAFT，body record_id/amount/channel）
      operationId: createPayout
      parameters: [ { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/PayoutRequest' }
      responses:
        '200':
          description: 创建后的发放单
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Payout' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/payouts/{id}/approve:
    post:
      tags: [performance]
      summary: 发放审批通过（DRAFT/APPROVING → APPROVED）
      operationId: approvePayout
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 审批后的发放单
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Payout' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/payouts/{id}/pay:
    post:
      tags: [performance]
      summary: 标记发放完成（APPROVED → PAID，回填 voucher_code，记录联动 PAID）
      operationId: payPayout
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: false
        content:
          application/json:
            schema: { type: object, properties: { voucher_code: { type: string } } }
      responses:
        '200':
          description: 完成后的发放单
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Payout' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/payouts/{id}/reject:
    post:
      tags: [performance]
      summary: 驳回发放（DRAFT/APPROVING → REJECTED，body reason）
      operationId: rejectPayout
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: false
        content:
          application/json:
            schema: { type: object, properties: { reason: { type: string } } }
      responses:
        '200':
          description: 驳回后的发放单
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/Payout' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
        '409': { $ref: '#/components/responses/Conflict' }
  /perf/me:
    get:
      tags: [performance]
      summary: 我的绩效（ABAC 强制 staff_user_id=当前用户）
      operationId: myPerformance
      parameters:
        - { name: period, in: query, schema: { type: string } }
      responses:
        '200':
          description: 当前用户记录明细数组
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { list: { type: array, items: { $ref: '#/components/schemas/RecordDetail' } } } }
        '401': { $ref: '#/components/responses/Unauthorized' }
  /perf/ranking:
    get:
      tags: [performance]
      summary: 排行/分布（管理角色可见）
      operationId: perfRanking
      parameters:
        - { name: scheme_id, in: query, required: true, schema: { type: integer, format: int64 } }
        - { name: period, in: query, required: true, schema: { type: string } }
        - { name: top, in: query, schema: { type: integer, default: 20 } }
      responses:
        '200':
          description: 排行
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { list: { type: array, items: { $ref: '#/components/schemas/RankItem' } } } }
        '403': { $ref: '#/components/responses/Forbidden' }
components:
  securitySchemes:
    bearerAuth: { type: http, scheme: bearer, bearerFormat: JWT }
  parameters:
    Page:  { name: page,  in: query, schema: { type: integer, default: 1, minimum: 1 } }
    Size:  { name: size,  in: query, schema: { type: integer, default: 20, minimum: 1, maximum: 200 } }
    PathId: { name: id, in: path, required: true, schema: { type: integer, format: int64 } }
    IdempotencyKey: { name: Idempotency-Key, in: header, required: false, schema: { type: string } }
  responses:
    BadRequest:
      description: 参数错误
      content:
        application/json:
          schema: { $ref: '#/components/schemas/ApiResponse' }
    Unauthorized:
      description: 未认证
      content:
        application/json:
          schema: { $ref: '#/components/schemas/ApiResponse' }
    Forbidden:
      description: 无权限/越权
      content:
        application/json:
          schema: { $ref: '#/components/schemas/ApiResponse' }
    NotFound:
      description: 资源不存在
      content:
        application/json:
          schema: { $ref: '#/components/schemas/ApiResponse' }
    Conflict:
      description: 状态冲突（非法流转/重复）
      content:
        application/json:
          schema: { $ref: '#/components/schemas/ApiResponse' }
  schemas:
    ApiResponse:
      type: object
      properties:
        code:      { type: integer }
        message:   { type: string }
        data:      { type: object }
        traceId:   { type: string, nullable: true }
        timestamp: { type: string, nullable: true }
    PageResult:
      type: object
      properties:
        total: { type: integer }
        page:  { type: integer }
        size:  { type: integer }
    Scheme:
      type: object
      properties:
        id:               { type: integer, format: int64 }
        code:             { type: string, nullable: true }
        name:             { type: string }
        period_type:      { type: string, enum: [YEAR, QUARTER, MONTH] }
        scope_dept_id:    { type: integer, format: int64, nullable: true }
        scope_staff_type: { type: string, nullable: true }
        effective_period: { type: string }
        version:          { type: integer }
        active:           { type: boolean }
        status:           { type: string, enum: [DRAFT, ACTIVE, SUPERSEDED] }
        created_at:       { type: string, format: date-time }
        updated_at:       { type: string, format: date-time }
    SchemeRequest:
      type: object
      required: [name, period_type, effective_period]
      properties:
        name:             { type: string }
        period_type:      { type: string, enum: [YEAR, QUARTER, MONTH] }
        scope_dept_id:    { type: integer, format: int64, nullable: true }
        scope_staff_type: { type: string, nullable: true }
        effective_period: { type: string }
        remark:           { type: string, nullable: true }
    Factor:
      type: object
      properties:
        id:           { type: integer, format: int64 }
        scheme_id:    { type: integer, format: int64 }
        factor_code:  { type: string }
        factor_name:  { type: string }
        weight:       { type: string }
        scoring_rule: { type: object }
        max_score:    { type: string, nullable: true }
        data_source:  { type: string, enum: [R_OUTPUT, F_INCOME, E_PROJECT, T_DEAL, MANUAL] }
        clause_ref:   { type: string, nullable: true }
        sort_no:      { type: integer }
    FactorRequest:
      type: object
      required: [factor_code, data_source, scoring_rule]
      properties:
        factor_code:  { type: string }
        factor_name:  { type: string }
        weight:       { type: string }
        scoring_rule: { type: object }
        max_score:    { type: string, nullable: true }
        data_source:  { type: string, enum: [R_OUTPUT, F_INCOME, E_PROJECT, T_DEAL, MANUAL] }
        clause_ref:   { type: string, nullable: true }
        sort_no:      { type: integer }
    SchemeDetail:
      allOf:
        - $ref: '#/components/schemas/Scheme'
        - type: object
          properties:
            factors: { type: array, items: { $ref: '#/components/schemas/Factor' } }
    Record:
      type: object
      properties:
        id:             { type: integer, format: int64 }
        scheme_id:      { type: integer, format: int64 }
        scheme_name:    { type: string, nullable: true }
        staff_user_id:  { type: integer, format: int64 }
        staff_name:     { type: string, nullable: true }
        period:         { type: string }
        dept_id:        { type: integer, format: int64, nullable: true }
        total_score:    { type: string }
        rank:           { type: integer, nullable: true }
        status:         { type: string, enum: [CALCULATED, CONFIRMED, APPROVED, PAID, APPEAL, VOID] }
        calc_batch:     { type: string, nullable: true }
        calc_at:        { type: string, format: date-time, nullable: true }
        confirmed_at:   { type: string, format: date-time, nullable: true }
        approve_at:     { type: string, format: date-time, nullable: true }
    RecordItem:
      type: object
      properties:
        id:             { type: integer, format: int64 }
        record_id:      { type: integer, format: int64 }
        factor_code:    { type: string }
        factor_name:    { type: string, nullable: true }
        metric_value:   { type: string }
        raw_score:      { type: string }
        weighted_score: { type: string }
        evidence:       { type: array, items: { type: object } }
    RecordDetail:
      allOf:
        - $ref: '#/components/schemas/Record'
        - type: object
          properties:
            items: { type: array, items: { $ref: '#/components/schemas/RecordItem' } }
    Payout:
      type: object
      properties:
        id:            { type: integer, format: int64 }
        code:          { type: string, nullable: true }
        record_id:     { type: integer, format: int64 }
        payee_user_id: { type: integer, format: int64 }
        payee_name:    { type: string, nullable: true }
        amount:        { type: string }
        period:        { type: string, nullable: true }
        pay_channel:   { type: string, nullable: true }
        status:        { type: string, enum: [DRAFT, APPROVING, APPROVED, PAID, REJECTED] }
        approved_at:   { type: string, format: date-time, nullable: true }
        paid_at:       { type: string, format: date-time, nullable: true }
        voucher_code:  { type: string, nullable: true }
    PayoutRequest:
      type: object
      required: [record_id, amount]
      properties:
        record_id:   { type: integer, format: int64 }
        amount:      { type: string }
        pay_channel: { type: string, nullable: true }
    CalculateRequest:
      type: object
      required: [period]
      properties:
        period:    { type: string, description: 计算周期，如 2026 / 2026Q1 / 2026-03 }
        dept_ids:  { type: array, items: { type: integer, format: int64 } }
        staff_ids: { type: array, items: { type: integer, format: int64 } }
    CalculateResult:
      type: object
      properties:
        calc_batch:  { type: string }
        period:      { type: string }
        computed:    { type: integer, description: 本次计算的人数 }
        inserted:    { type: integer }
        updated:     { type: integer }
    RankItem:
      type: object
      properties:
        rank:          { type: integer }
        staff_user_id: { type: integer, format: int64 }
        staff_name:    { type: string, nullable: true }
        dept_id:       { type: integer, format: int64, nullable: true }
        total_score:   { type: string }
```

> `CalculateResult` 缩进末行 `updated:` 后无 `description` 属正常（YAML 允许空值键）。执行者若 lint 报尾空行可删。

- [ ] **步骤 2：同步到前端 schema（逐字节）**

```bash
cp "design/14-科研绩效评价-M.openapi.yaml" "frontend/src/api/schema/14-科研绩效评价-M.openapi.yaml"
diff -q "design/14-科研绩效评价-M.openapi.yaml" "frontend/src/api/schema/14-科研绩效评价-M.openapi.yaml" && echo SYNC_OK
```
预期：打印 `SYNC_OK`（无差异）。

- [ ] **步骤 3：契约漂移自检**

运行（Go）：`go test ./internal/platform/oapi/ -run TestSpec -v`（若有 LoadDir 冒烟用例则应识别新文件）。
运行（前端 typecheck，若已加 '14':'M' 见前端任务；此处仅解析容错）：暂跳过，前端任务再验。

- [ ] **步骤 4：Commit**

```bash
git add "design/14-科研绩效评价-M.openapi.yaml" "frontend/src/api/schema/14-科研绩效评价-M.openapi.yaml"
git commit -m "feat(M): 绩效评价 OpenAPI 契约 + 前端 schema 同步副本"
```

### 任务 M-2：绩效评价 DDL（5 表）

**文件：**
- 创建：`design/14-科研绩效评价-M.ddl.sql`
- 创建：`design/14-科研绩效评价-M.detail.md`

> 通用列内联（对齐 00-common §2.1：id/code/tenant_id/status/deleted/creator_id/modifier_id/created_at/updated_at/remark；顶层实体表 m_scheme/m_record/m_payout 追加 `security_level`、`legal_entity_id`、`policy_pack_id` 治理三列）。跨模块仅存 `*_id` 逻辑外键（staff_user_id→sys_user、dept_id→sys_org、voucher_code→F），**不建物理 FK**；同模块内 m_scheme_factor→m_scheme、m_record→m_scheme、m_record_item→m_record、m_payout→m_record 建物理 FK。`uk_m_record` 与 `uk_m_payout` 用部分唯一索引实现幂等。被读表 r_output/f_income/e_project/t_deal 只被 SQL 引用，DDL 不动它们。

- [ ] **步骤 1：写 DDL**

```sql
-- =============================================================================
-- 14 科研绩效评价 · M（模块前缀 PERF/PAY）
-- 版本 v1.0 · 2026-10-14
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4）
-- 约定：金额/权重 NUMERIC；时间 TIMESTAMPTZ；枚举 VARCHAR+CHECK；字典走 sys_dict；
--       计分 metric_value NUMERIC(18,4)；score NUMERIC(10,2)；payout/amount NUMERIC(18,2)。
--       跨模块只存 *_id 逻辑外键；同模块内 factor→scheme、item→record、payout→record 建物理 FK。
-- 编号：m_scheme/m_record code 前缀 PERF、m_payout code 前缀 PAY（svc-numbering 分配，见 00-common seq_prefix_registry）。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- M_SCHEME · 绩效方案（考核规则容器；同 tenant+period_type+effective_period+scope 唯一 active）
-- -----------------------------------------------------------------------------
CREATE TABLE m_scheme (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  legal_entity_id    BIGINT,
  policy_pack_id     BIGINT,                          -- 逻辑外键 → sys_policy_pack(id)
  -- 业务列 ─────────────────────────────────────────────
  name               VARCHAR(128) NOT NULL,
  period_type        VARCHAR(16) NOT NULL
                     CHECK (period_type IN ('YEAR','QUARTER','MONTH')),
  scope_dept_id      BIGINT,                          -- 逻辑外键 → sys_org(id)；空=全院
  scope_staff_type   VARCHAR(32),                     -- 逻辑引用 sys_dict(staff_type)；空=全部
  effective_period   VARCHAR(32) NOT NULL,            -- 生效周期串，如 2026 / 2026Q1 / 2026-03
  version            INT NOT NULL DEFAULT 1,
  active             BOOLEAN NOT NULL DEFAULT FALSE   -- 同维度仅一个 true
);
CREATE UNIQUE INDEX uk_m_scheme_active
  ON m_scheme(tenant_id, period_type, effective_period, COALESCE(scope_dept_id,0), COALESCE(scope_staff_type,''))
  WHERE active = TRUE AND deleted = 0;                -- 部分唯一：同维度仅一个生效
CREATE UNIQUE INDEX uk_m_scheme_code ON m_scheme(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_m_scheme_tenant_st  ON m_scheme(tenant_id, status);

COMMENT ON TABLE  m_scheme IS '绩效方案：周期/范围/版本，因子集合的容器（模块 M）';
COMMENT ON COLUMN m_scheme.active          IS '当前生效标记；与 status=ACTIVE 同步维护';
COMMENT ON COLUMN m_scheme.effective_period IS '生效周期串，决定 calculate 的时间窗';


-- -----------------------------------------------------------------------------
-- M_SCHEME_FACTOR · 考核因子（计分规则；uk scheme_id+factor_code）
-- -----------------------------------------------------------------------------
CREATE TABLE m_scheme_factor (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scheme_id    BIGINT NOT NULL REFERENCES m_scheme(id),
  tenant_id    BIGINT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  creator_id   BIGINT NOT NULL,
  -- 业务列 ─────────────────────────────────────────────
  factor_code  VARCHAR(64) NOT NULL,                  -- PAPER/PATENT/PROJECT/INCOME/AWARD/TRANSFER/BOOK/SOFTWARE/…（sys_dict）
  factor_name  VARCHAR(128),
  weight       NUMERIC(6,2) NOT NULL DEFAULT 0,       -- 占比
  scoring_rule JSONB        NOT NULL DEFAULT '{}'::jsonb, -- {method:COUNT|BY_LEVEL|BY_AMOUNT|LADDER,unit,ladder:[{min,max,score}],levelMap:{...}}
  max_score    NUMERIC(10,2),
  data_source  VARCHAR(32) NOT NULL
               CHECK (data_source IN ('R_OUTPUT','F_INCOME','E_PROJECT','T_DEAL','MANUAL')),
  clause_ref   VARCHAR(256),                          -- 制度出处（可解释）
  sort_no      INT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uk_m_factor ON m_scheme_factor(scheme_id, factor_code);
CREATE INDEX idx_m_factor_scheme ON m_scheme_factor(scheme_id);

COMMENT ON TABLE m_scheme_factor IS '方案因子：权重/计分方式/取数来源/制度出处（模块 M）';
COMMENT ON COLUMN m_scheme_factor.scoring_rule IS '计分规则 JSON：method + 各方式参数';


-- -----------------------------------------------------------------------------
-- M_RECORD · 绩效记录（某人×某方案×某周期；uk scheme+staff+period WHERE deleted=0 幂等 upsert）
--   CALCULATED→CONFIRMED→APPROVED→PAID；分支 APPEAL、VOID
-- -----------------------------------------------------------------------------
CREATE TABLE m_record (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'CALCULATED'
                     CHECK (status IN ('CALCULATED','CONFIRMED','APPROVED','PAID','APPEAL','VOID')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  legal_entity_id    BIGINT,
  -- 业务列 ─────────────────────────────────────────────
  scheme_id          BIGINT NOT NULL REFERENCES m_scheme(id),
  staff_user_id      BIGINT NOT NULL,                 -- 逻辑外键 → sys_user(id)
  period             VARCHAR(32) NOT NULL,            -- 记录所属周期（继承方案 effective_period）
  dept_id            BIGINT,                          -- 逻辑外键 → sys_org(id)
  total_score        NUMERIC(10,2) NOT NULL DEFAULT 0,
  rank               INT,                             -- 名次（排行计算回填）
  calc_detail        JSONB NOT NULL DEFAULT '{}'::jsonb, -- 计分明细快照/算法参数留痕
  calc_batch         VARCHAR(64),                     -- 批次号（幂等重算）
  calc_at            TIMESTAMPTZ,
  confirmed_by       BIGINT,
  confirmed_at       TIMESTAMPTZ,
  approve_by         BIGINT,
  approve_at         TIMESTAMPTZ,
  appeal_reason      VARCHAR(512),                    -- 申诉理由（APPEAL 时填）
  void_reason        VARCHAR(512)                     -- 作废理由（VOID 时填）
);
CREATE UNIQUE INDEX uk_m_record ON m_record(scheme_id, staff_user_id, period) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_m_record_code ON m_record(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_m_record_scheme_period ON m_record(scheme_id, period);
CREATE INDEX idx_m_record_staff        ON m_record(staff_user_id, period);
CREATE INDEX idx_m_record_dept         ON m_record(dept_id);

COMMENT ON TABLE  m_record IS '绩效记录：自动计分产出的人员×方案×周期得分与状态（模块 M）';
COMMENT ON COLUMN m_record.status IS '状态机 token：CALCULATED/CONFIRMED/APPROVED/PAID/APPEAL/VOID';
COMMENT ON COLUMN m_record.calc_batch IS '计算批次号，同 batch 重算幂等（upsert 覆盖）';


-- -----------------------------------------------------------------------------
-- M_RECORD_ITEM · 因子明细得分（uk record_id+factor_code；evidence 命中单据可反查）
-- -----------------------------------------------------------------------------
CREATE TABLE m_record_item (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  record_id      BIGINT NOT NULL REFERENCES m_record(id),
  tenant_id      BIGINT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- 业务列 ─────────────────────────────────────────────
  factor_code    VARCHAR(64) NOT NULL,
  metric_value   NUMERIC(18,4) NOT NULL DEFAULT 0,    -- 原始度量：篇数/金额/项数
  raw_score      NUMERIC(10,2) NOT NULL DEFAULT 0,    -- 规则映射后未加权分
  weighted_score NUMERIC(10,2) NOT NULL DEFAULT 0,    -- raw×weight（或按权重占比）
  evidence       JSONB NOT NULL DEFAULT '[]'::jsonb   -- [{objectType,objectId,code,value}]
);
CREATE UNIQUE INDEX uk_m_item ON m_record_item(record_id, factor_code);
CREATE INDEX idx_m_item_record ON m_record_item(record_id);

COMMENT ON TABLE m_record_item IS '因子明细得分：每项 metric/raw/weighted + 证据单据（模块 M）';


-- -----------------------------------------------------------------------------
-- M_PAYOUT · 绩效发放在线审批（uk record_id WHERE deleted=0 AND status<>'REJECTED'）
--   DRAFT→APPROVING→APPROVED→PAID；分支 REJECTED
-- -----------------------------------------------------------------------------
CREATE TABLE m_payout (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','APPROVING','APPROVED','PAID','REJECTED')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  legal_entity_id    BIGINT,
  -- 业务列 ─────────────────────────────────────────────
  record_id          BIGINT NOT NULL REFERENCES m_record(id),
  payee_user_id      BIGINT NOT NULL,                 -- 逻辑外键 → sys_user(id)
  amount             NUMERIC(18,2) NOT NULL,          -- 发放金额（元）
  period             VARCHAR(32),
  pay_channel        VARCHAR(32),                     -- 工资/专项，逻辑引用 sys_dict
  approver_ids       JSONB NOT NULL DEFAULT '[]'::jsonb, -- 审批链快照 [{userId,at,action}]
  approved_at        TIMESTAMPTZ,
  paid_at            TIMESTAMPTZ,
  voucher_code       VARCHAR(64),                     -- 联动 F 凭证（逻辑外键）
  reject_reason      VARCHAR(512)
);
CREATE UNIQUE INDEX uk_m_payout_record ON m_payout(record_id) WHERE deleted = 0 AND status <> 'REJECTED';
CREATE UNIQUE INDEX uk_m_payout_code  ON m_payout(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_m_payout_tenant_st   ON m_payout(tenant_id, status);

COMMENT ON TABLE  m_payout IS '绩效发放单：从 APPROVED 记录发起的在线审批付款（模块 M）';
COMMENT ON COLUMN m_payout.status IS '状态机 token：DRAFT/APPROVING/APPROVED/PAID/REJECTED';
```

> 唯一索引表达式：`uk_m_scheme_active` 用了 `COALESCE(scope_dept_id,0)` / `COALESCE(scope_staff_type,'')`。PG 允许表达式唯一索引；若达梦方言不支持（信创），在 detail.md 记“生产达梦改应用层校验唯一”，本 PG 基线保留。gen_test 的 `TestGenerateUp_UniqueIndexNames` 守卫要求全库唯一索引名不冲突——`uk_m_*`/`idx_m_*` 前缀已隔离。

- [ ] **步骤 2：写 detail.md**

按规格 §4 展开三节：4.1 数据字典（5 表逐列口径，重点 `scoring_rule` JSON 四种 method 的语义：`COUNT`=按单据数×unit；`BY_LEVEL`=levelMap{output_type→分}；`BY_AMOUNT`=metric 即金额×unit；`LADDER`=ladder 区间→分值），4.2 两条状态机 ASCII 图 + “非法迁移→40901 / 越权→40301”，4.3 权限矩阵表（含 `/perf/me` ABAC 限本人）。写完即通过。

- [ ] **步骤 3：Commit**

```bash
git add "design/14-科研绩效评价-M.ddl.sql" "design/14-科研绩效评价-M.detail.md"
git commit -m "feat(M): 新增绩效评价 DDL（m_scheme/factor/record/item/payout 5 表）与设计细则"
```

### 任务 M-3：重生成迁移 + gen_test 断言 M 表

**文件：**
- 生成：`backend-go/migrations/000001_init.up.sql` / `.down.sql`（由 `migrations/gen.go` 自动纳入 `14-*.ddl.sql`）
- 修改：`backend-go/migrations/gen_test.go`（追加 `TestGenerateUp_HasMScheme`）

> `WriteFiles` 按文件名排序把 `design/*.ddl.sql` 拼进 `000001_init`（`00-common` 置顶）。新增 `14-*.ddl.sql` 自动进入迁移，无需手改拼接清单。

- [ ] **步骤 1：重生成**

运行：`cd backend-go && go generate ./migrations/...`
预期：`000001_init.up.sql` 出现 `CREATE TABLE m_scheme/m_scheme_factor/m_record/m_record_item/m_payout`；`.down.sql` 出现对应 `DROP TABLE`（逆序）。

- [ ] **步骤 2：加断言**

在 `gen_test.go` 追加（仿 `TestGenerateUp_HasVActivity`）：

```go
func TestGenerateUp_HasMScheme(t *testing.T) {
	up := readUpSQL(t) // 复用文件内既有读取 helper；若无则 os.ReadFile("./000001_init.up.sql")
	for _, tbl := range []string{"m_scheme", "m_scheme_factor", "m_record", "m_record_item", "m_payout"} {
		if !strings.Contains(up, "CREATE TABLE "+tbl) {
			t.Fatalf("迁移缺少建表：%s", tbl)
		}
	}
	for _, pref := range []string{"'PERF'", "'PAY'"} {
		if !strings.Contains(up, pref) {
			t.Fatalf("迁移缺少编号前缀登记：%s", pref)
		}
	}
}
```

> `readUpSQL`/`strings` 若 gen_test.go 尚未引入，补 `import "strings"` 与就地读取。既有 8 守卫（含 `TestGenerateUp_UniqueIndexNames`）须继续 PASS——新 `uk_m_*` 名字不得与既有库内其它唯一索引名重复。

- [ ] **步骤 3：跑迁移守卫全套**

运行：`cd backend-go && go test ./migrations/ -v`
预期：既有守卫 + `TestGenerateUp_HasVActivity` + `TestGenerateUp_HasMScheme` 全 PASS。若 `UniqueIndexNames` 报冲突，给重复索引改名（加 `m_` 前缀）。

- [ ] **步骤 4：Commit**

```bash
git add backend-go/migrations/000001_init.up.sql backend-go/migrations/000001_init.down.sql backend-go/migrations/gen_test.go
git commit -m "chore(M): 迁移重生成纳入 m_* 5 表 + gen_test 断言"
```

### 任务 M-4：sqlc M 引擎块 + 裁剪 schema（含只读跨表）

**文件：**
- 创建：`backend-go/db/schema/m_schema.sql`
- 修改：`backend-go/sqlc.yaml`（`sql:` 列表末尾追加第四个 engine 块）

> M 与 V 不同：calculate 需跨读 R/F/E/T，故裁剪 schema 除 5 张自有 `m_*` 表外，还要**内联被读表的最小列**（仅 metrics.sql 引用的列），让 sqlc 能静态解析跨表查询。**运行时**查询打的是真库（`000001_init` 全量表），裁剪文件只服务 sqlc 编译期类型解析——因此这里列定义只需保证「被 SELECT/WHERE 引用的列存在且类型对」，可省略无关列。

- [ ] **步骤 1：写 `m_schema.sql`**

```sql
-- 裁剪 schema：M 仓储所需 5 张自有表 + 被 calculate 跨读的 R/F/E/T 最小列（仅 sqlc 编译期解析用）。
-- 自有表语句原样摘自 000001_init.up.sql；跨表仅保留 metrics.sql 引用到的列，运行时打真库全量表。
-- 原因：sqlc v1.27 wazero 解析器无法吃 ~394KB 全量迁移。

-- ===== M 自有表（去 COMMENT/索引，保留列与类型）=====
CREATE TABLE m_scheme (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code VARCHAR(64), tenant_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT', deleted SMALLINT NOT NULL DEFAULT 0,
  creator_id BIGINT NOT NULL, modifier_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark TEXT, security_level VARCHAR(16) NOT NULL DEFAULT 'INTERNAL',
  legal_entity_id BIGINT, policy_pack_id BIGINT,
  name VARCHAR(128) NOT NULL, period_type VARCHAR(16) NOT NULL,
  scope_dept_id BIGINT, scope_staff_type VARCHAR(32), effective_period VARCHAR(32) NOT NULL,
  version INT NOT NULL DEFAULT 1, active BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE m_scheme_factor (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scheme_id BIGINT NOT NULL, tenant_id BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  creator_id BIGINT NOT NULL,
  factor_code VARCHAR(64) NOT NULL, factor_name VARCHAR(128), weight NUMERIC(6,2) NOT NULL DEFAULT 0,
  scoring_rule JSONB NOT NULL DEFAULT '{}'::jsonb, max_score NUMERIC(10,2),
  data_source VARCHAR(32) NOT NULL, clause_ref VARCHAR(256), sort_no INT NOT NULL DEFAULT 0
);
CREATE TABLE m_record (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code VARCHAR(64), tenant_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'CALCULATED', deleted SMALLINT NOT NULL DEFAULT 0,
  creator_id BIGINT NOT NULL, modifier_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark TEXT, security_level VARCHAR(16) NOT NULL DEFAULT 'INTERNAL', legal_entity_id BIGINT,
  scheme_id BIGINT NOT NULL, staff_user_id BIGINT NOT NULL, period VARCHAR(32) NOT NULL, dept_id BIGINT,
  total_score NUMERIC(10,2) NOT NULL DEFAULT 0, rank INT, calc_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  calc_batch VARCHAR(64), calc_at TIMESTAMPTZ,
  confirmed_by BIGINT, confirmed_at TIMESTAMPTZ, approve_by BIGINT, approve_at TIMESTAMPTZ,
  appeal_reason VARCHAR(512), void_reason VARCHAR(512)
);
CREATE TABLE m_record_item (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  record_id BIGINT NOT NULL, tenant_id BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  factor_code VARCHAR(64) NOT NULL, metric_value NUMERIC(18,4) NOT NULL DEFAULT 0,
  raw_score NUMERIC(10,2) NOT NULL DEFAULT 0, weighted_score NUMERIC(10,2) NOT NULL DEFAULT 0,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE m_payout (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code VARCHAR(64), tenant_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT', deleted SMALLINT NOT NULL DEFAULT 0,
  creator_id BIGINT NOT NULL, modifier_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark TEXT, security_level VARCHAR(16) NOT NULL DEFAULT 'INTERNAL', legal_entity_id BIGINT,
  record_id BIGINT NOT NULL, payee_user_id BIGINT NOT NULL, amount NUMERIC(18,2) NOT NULL,
  period VARCHAR(32), pay_channel VARCHAR(32), approver_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  approved_at TIMESTAMPTZ, paid_at TIMESTAMPTZ, voucher_code VARCHAR(64), reject_reason VARCHAR(512)
);

-- ===== 被读跨模块表：仅 metrics.sql 引用的列（运行时打真库全量表）=====
CREATE TABLE r_output (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, code VARCHAR(64), deleted SMALLINT NOT NULL DEFAULT 0,
  output_type VARCHAR(32) NOT NULL, publish_date DATE, authors JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE e_project (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, deleted SMALLINT NOT NULL DEFAULT 0,
  pi_user_id BIGINT NOT NULL, department_id BIGINT, project_type VARCHAR(64),
  start_date DATE, total_budget NUMERIC(18,2) NOT NULL DEFAULT 0
);
CREATE TABLE f_income (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, project_id BIGINT,
  status VARCHAR(32) NOT NULL, receipt_date DATE, amount NUMERIC(18,2) NOT NULL
);
CREATE TABLE t_deal (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, output_id BIGINT NOT NULL,
  contract_amount NUMERIC(18,2) NOT NULL DEFAULT 0, signed_at TIMESTAMPTZ
);
```

> 若 sqlc 解析仍报某跨表列不存在，说明运行时真库该列名不同——回到 `design/02/03/04/05` DDL 核对**真实列名**并同步裁剪文件与 metrics.sql（三者列名必须一致）。上表列名取自本计划 M-5 引用的集合，与 design DDL 已核对（`e_project.pi_user_id`/`department_id`、`f_income.receipt_date`/`amount`/`status`、`r_output.publish_date`/`authors`、`t_deal.contract_amount`/`signed_at`）。

- [ ] **步骤 2：在 `sqlc.yaml` 末尾追加第四块**

```yaml
  - engine: "postgresql"
    # 第四生成块：M 仓储（绩效评价）。独立 schema/queries/out；package=mstore。
    # 跨读 R/F/E/T 的最小列已并入 m_schema.sql（仅编译期解析用，运行时打真库）。
    schema: "db/schema/m_schema.sql"
    queries: "db/query_m"
    gen:
      go:
        package: "mstore"
        out: "internal/modules/performance/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          m_scheme: Scheme
          m_scheme_factor: SchemeFactor
          m_record: Record
          m_record_item: RecordItem
          m_payout: Payout
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          # 时间戳 → time.Time/*time.Time（供 mapper fmtTime/fmtTimePtr 直接吃）。
          # 关键：NUMERIC 列**不做** →string override——保持 sqlc/pgx 原生 pgtype.Numeric。
          # 原因见下注：entity 查询用 SELECT */RETURNING *（返回 model），若把 NUMERIC 钉成
          # string 会让 model 字段变 string，而 `SELECT *` 回传 numeric OID，pgx 向 string 扫描未经验证；
          # 保持 pgtype.Numeric（原生可空类型，扫描恒安全），金额→契约 string 在 mapper 用 numDec() 格式化。
          - column: "m_scheme.created_at"
            go_type: "time.Time"
          - column: "m_scheme.updated_at"
            go_type: "time.Time"
          - column: "m_scheme_factor.created_at"
            go_type: "time.Time"
          - column: "m_scheme_factor.updated_at"
            go_type: "time.Time"
          - column: "m_record.created_at"
            go_type: "time.Time"
          - column: "m_record.updated_at"
            go_type: "time.Time"
          - column: "m_record.calc_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "m_record.confirmed_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "m_record.approve_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "m_record_item.created_at"
            go_type: "time.Time"
          - column: "m_payout.created_at"
            go_type: "time.Time"
          - column: "m_payout.updated_at"
            go_type: "time.Time"
          - column: "m_payout.approved_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "m_payout.paid_at"
            go_type: { type: "time.Time", pointer: true }
```

> `emit_pointers_for_null_types: true` 让可空**基础类型**（rank INT→`*int32`、dept_id/scope_dept_id BIGINT→`*int64`、modifier_id/period/clause_ref 等→指针）自动成指针；NUMERIC 无论可空与否都是 `pgtype.Numeric`（本身可空，靠 `.Valid` 判空），不需 override。时间戳 override 把 `TIMESTAMPTZ` 从默认 `pgtype.Timestamptz` 钉成 `time.Time`/`*time.Time`（可空列配 pointer:true）以便 mapper 直接用。

- [ ] **步骤 3：Commit（配置先落，查询在 M-5）**

```bash
git add backend-go/db/schema/m_schema.sql
git add backend-go/sqlc.yaml
git commit -m "chore(M): 配置 sqlc M 引擎块与裁剪 schema（含只读跨表列）"
```

### 任务 M-5：M 的 sqlc 查询文件

**文件：**
- 创建：`backend-go/db/query_m/m_scheme.sql`
- 创建：`backend-go/db/query_m/m_scheme_factor.sql`
- 创建：`backend-go/db/query_m/metrics.sql`
- 创建：`backend-go/db/query_m/m_record.sql`（见本任务步骤 4）
- 创建：`backend-go/db/query_m/m_payout.sql`（见本任务步骤 5）

> 约定同 V：list 用软删+租户+多条件可空过滤+`LIMIT/OFFSET`；NUMERIC 一律 `::text AS <col>`（配合 mstore override string）；状态动作用 `WHERE status=$from` 守门（非法迁移自然 0 行→handler 转 40901）；metrics 查询只读、返回 metric + jsonb evidence。`ANY($x::bigint[])` 传 `[]int64`（nil→NULL 视为不过滤）。

- [ ] **步骤 1：写 `m_scheme.sql`**

```sql
-- name: ListSchemes :many
SELECT * FROM m_scheme
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::text   IS NULL OR period_type = $2::text)
  AND ($3::text   IS NULL OR effective_period = $3::text)
  AND ($4::bigint IS NULL OR scope_dept_id = $4::bigint)
  AND ($5::text   IS NULL OR status = $5::text)
  AND ($6::text   IS NULL OR name ILIKE $6::text)
ORDER BY id DESC
LIMIT $8 OFFSET $7;

-- name: CountSchemes :one
SELECT count(*)::int AS n
FROM m_scheme
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::text   IS NULL OR period_type = $2::text)
  AND ($3::text   IS NULL OR effective_period = $3::text)
  AND ($4::bigint IS NULL OR scope_dept_id = $4::bigint)
  AND ($5::text   IS NULL OR status = $5::text)
  AND ($6::text   IS NULL OR name ILIKE $6::text);

-- name: GetScheme :one
SELECT * FROM m_scheme
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: CreateScheme :one
INSERT INTO m_scheme (tenant_id, creator_id, status, security_level, legal_entity_id, policy_pack_id,
                      name, period_type, scope_dept_id, scope_staff_type, effective_period, version, active, remark)
VALUES ($1, $2, 'DRAFT', COALESCE($3::text,'INTERNAL'), $4, $5,
        $6, $7, $8, $9, $10, 1, FALSE, $11)
RETURNING *;

-- name: UpdateScheme :one
UPDATE m_scheme SET
  name = COALESCE($3::text, name),
  period_type = COALESCE($4::text, period_type),
  scope_dept_id = COALESCE($5::bigint, scope_dept_id),
  scope_staff_type = COALESCE($6::text, scope_staff_type),
  effective_period = COALESCE($7::text, effective_period),
  remark = COALESCE($8::text, remark),
  modifier_id = $9, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'DRAFT'
RETURNING *;

-- name: SoftDeleteScheme :execrows
UPDATE m_scheme SET deleted = 1, modifier_id = $3, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: SupersedeActiveInScope :exec
-- 启用前置：把同维度（tenant+period_type+effective_period+scope_dept+scope_staff_type）当前 active 的方案转 SUPERSEDED
UPDATE m_scheme SET active = FALSE, status = 'SUPERSEDED', updated_at = now()
WHERE deleted = 0 AND active = TRUE AND tenant_id = $1 AND period_type = $2 AND effective_period = $3
  AND COALESCE(scope_dept_id,0) = COALESCE($4::bigint,0)
  AND COALESCE(scope_staff_type,'') = COALESCE($5::text,'');

-- name: ActivateScheme :one
UPDATE m_scheme SET active = TRUE, status = 'ACTIVE', updated_at = now(), modifier_id = $3
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
RETURNING *;
```

- [ ] **步骤 2：写 `m_scheme_factor.sql`**

```sql
-- name: ListFactors :many
SELECT * FROM m_scheme_factor
WHERE scheme_id = $1
ORDER BY sort_no ASC, id ASC;

-- name: UpsertFactor :one
INSERT INTO m_scheme_factor (scheme_id, tenant_id, creator_id, factor_code, factor_name,
                             weight, scoring_rule, max_score, data_source, clause_ref, sort_no)
VALUES ($1, $2, $3, $4, $5, COALESCE($6::numeric,0), COALESCE($7::jsonb,'{}'::jsonb),
        $8, $9, $10, COALESCE($11::int,0))
ON CONFLICT (scheme_id, factor_code) DO UPDATE SET
  factor_name  = EXCLUDED.factor_name,
  weight       = EXCLUDED.weight,
  scoring_rule = EXCLUDED.scoring_rule,
  max_score    = EXCLUDED.max_score,
  data_source  = EXCLUDED.data_source,
  clause_ref   = EXCLUDED.clause_ref,
  sort_no      = EXCLUDED.sort_no,
  updated_at   = now()
RETURNING *;

-- name: UpdateFactor :one
UPDATE m_scheme_factor SET
  factor_name  = COALESCE($4::text, factor_name),
  weight       = COALESCE($5::numeric, weight),
  scoring_rule = COALESCE($6::jsonb, scoring_rule),
  max_score    = COALESCE($7::numeric, max_score),
  data_source  = COALESCE($8::text, data_source),
  clause_ref   = COALESCE($9::text, clause_ref),
  sort_no      = COALESCE($10::int, sort_no),
  updated_at   = now()
WHERE id = $1 AND scheme_id = $2 AND tenant_id = $3
RETURNING *;

-- name: DeleteFactor :execrows
DELETE FROM m_scheme_factor WHERE id = $1 AND scheme_id = $2 AND tenant_id = $3;

-- name: ListFactorsBySchemeForCalc :many
-- calculate 用：取某方案全部因子（含 scoring_rule）。SELECT * → []SchemeFactor（weight/max_score 为 pgtype.Numeric）。
SELECT * FROM m_scheme_factor
WHERE scheme_id = $1 AND tenant_id = $2
ORDER BY sort_no ASC, id ASC;
```

- [ ] **步骤 3：写 `metrics.sql`**（跨模块只读聚合；全部带 tenant 谓词，空数据返回 0/空数组不报错）

```sql
-- name: MetricsOutputsByStaff :many
-- R_OUTPUT：按完成人（authors 含该 user_id）在周期内、按 output_type 分组的成果数 + 证据。
-- BY_LEVEL 计分在 Go 端用 levelMap 乘各组 cnt；COUNT 法对全部 cnt 求和。
SELECT o.output_type,
       count(*)::int AS cnt,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','R_OUTPUT','objectId',o.id,'code',o.code,'value',1)),'[]'::jsonb) AS evidence
FROM r_output o
WHERE o.tenant_id = $1
  AND o.deleted = 0
  AND ($2::date IS NULL OR o.publish_date >= $2::date)
  AND ($3::date IS NULL OR o.publish_date <= $3::date)
  AND o.authors @> jsonb_build_array(jsonb_build_object('user_id', $4::bigint))
GROUP BY o.output_type;

-- name: MetricsIncomeByStaff :one
-- F_INCOME：该 staff 作为 PI 的项目（经 e_project 关联）在周期内的到账金额求和 + 证据。
SELECT COALESCE(sum(fi.amount),0)::numeric(18,4)::text AS metric,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','F_INCOME','objectId',fi.id,'value',fi.amount)),'[]'::jsonb) AS evidence
FROM f_income fi
JOIN e_project ep ON ep.id = fi.project_id
WHERE fi.tenant_id = $1
  AND ep.tenant_id = $1
  AND ep.pi_user_id = $2::bigint
  AND fi.status = 'ACTIVE'
  AND ($3::date IS NULL OR fi.receipt_date >= $3::date)
  AND ($4::date IS NULL OR fi.receipt_date <= $4::date);

-- name: MetricsProjectsByStaff :many
-- E_PROJECT：该 staff 作为 PI 在周期内立项的项目，按 project_type 分组计数 + 预算求和 + 证据。
SELECT ep.project_type,
       count(*)::int AS cnt,
       COALESCE(sum(ep.total_budget),0)::numeric(18,4)::text AS amount,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','E_PROJECT','objectId',ep.id,'value',ep.total_budget)),'[]'::jsonb) AS evidence
FROM e_project ep
WHERE ep.tenant_id = $1
  AND ep.deleted = 0
  AND ep.pi_user_id = $2::bigint
  AND ($3::date IS NULL OR ep.start_date >= $3::date)
  AND ($4::date IS NULL OR ep.start_date <= $4::date)
GROUP BY ep.project_type;

-- name: MetricsTransferByStaff :one
-- T_DEAL：该 staff 作为成果完成人的转化合同，在周期内签约金额求和 + 证据。
SELECT COALESCE(sum(td.contract_amount),0)::numeric(18,4)::text AS metric,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','T_DEAL','objectId',td.id,'value',td.contract_amount)),'[]'::jsonb) AS evidence
FROM t_deal td
JOIN r_output o ON o.id = td.output_id
WHERE td.tenant_id = $1
  AND o.deleted = 0
  AND o.authors @> jsonb_build_array(jsonb_build_object('user_id', $2::bigint))
  AND ($3::date IS NULL OR td.signed_at::date >= $3::date)
  AND ($4::date IS NULL OR td.signed_at::date <= $4::date);

-- name: ListCalcStaff :many
-- calculate 取数轴：确定要计算的人员集合。默认取在研项目 PI（distinct）；dept_ids 非空则限定部门范围。
-- staff_ids 由 handler 直接给定（不走此查询），二者互斥。
SELECT DISTINCT ep.pi_user_id AS staff_user_id, ep.department_id AS dept_id
FROM e_project ep
WHERE ep.tenant_id = $1
  AND ep.deleted = 0
  AND ($2::bigint[] IS NULL OR ep.department_id = ANY($2::bigint[]));
```

> 证据 `objectId` 用被读表 `id`（真实列，M-4 已核）。`value` 放该项贡献（成果=1、经费/转化=金额、项目=预算），供前端反查复核。若某跨表列名与真库不符，改 `metrics.sql` + `m_schema.sql` 内联定义两处一致，再重跑 sqlc（M-6）。

- [ ] **步骤 4：写 `m_record.sql`**

> 约定同 `m_scheme.sql`：实体查询一律 `SELECT *`/`RETURNING *` → sqlc 直接返回 `Record`/`RecordItem` model（不生成 per-query Row、无需 `Model(row)` 转换）。NUMERIC 列（`total_score`/`metric_value`/`raw_score`/`weighted_score`）保持 `pgtype.Numeric`，契约字符串格式化交给 M-8 mapper 的 `numDec`。可空基础类型靠 `emit_pointers_for_null_types` 自动成指针（`rank *int32`、`dept_id/confirmed_by/approve_by *int64`、`period/appeal_reason/void_reason *string` 等）。仅 `CountRecords`（聚合）、`RankedRecords`（window 加 `rn` 列）保留自定义投影。

```sql
-- name: ListRecords :many
SELECT * FROM m_record
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::bigint IS NULL OR scheme_id = $2::bigint)
  AND ($3::text   IS NULL OR period = $3::text)
  AND ($4::bigint IS NULL OR dept_id = $4::bigint)
  AND ($5::bigint IS NULL OR staff_user_id = $5::bigint)
  AND ($6::text   IS NULL OR status = $6::text)
  AND ($7::text   IS NULL OR code ILIKE $7::text)
ORDER BY total_score DESC NULLS LAST, id DESC
LIMIT $9 OFFSET $8;

-- name: CountRecords :one
SELECT count(*)::int AS n
FROM m_record
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::bigint IS NULL OR scheme_id = $2::bigint)
  AND ($3::text   IS NULL OR period = $3::text)
  AND ($4::bigint IS NULL OR dept_id = $4::bigint)
  AND ($5::bigint IS NULL OR staff_user_id = $5::bigint)
  AND ($6::text   IS NULL OR status = $6::text)
  AND ($7::text   IS NULL OR code ILIKE $7::text);

-- name: GetRecord :one
SELECT * FROM m_record
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: UpsertRecord :one
-- calculate 幂等：同 (scheme,staff,period WHERE deleted=0) 覆盖重算（M0 直接覆盖，含已确认态；生产可加 status 谓词）。
INSERT INTO m_record (tenant_id, creator_id, status, scheme_id, staff_user_id, period, dept_id,
                      total_score, calc_detail, calc_batch, calc_at, security_level)
VALUES ($1, $2, 'CALCULATED', $3, $4, $5, $6, $7::numeric, $8::jsonb, $9, now(), COALESCE($10::text,'INTERNAL'))
ON CONFLICT (scheme_id, staff_user_id, period) WHERE deleted = 0 DO UPDATE SET
  total_score = EXCLUDED.total_score,
  calc_detail = EXCLUDED.calc_detail,
  calc_batch  = EXCLUDED.calc_batch,
  calc_at     = now(),
  dept_id     = EXCLUDED.dept_id,
  status      = 'CALCULATED',
  modifier_id = EXCLUDED.creator_id,
  updated_at  = now()
RETURNING *;

-- name: DeleteItemsByRecord :exec
DELETE FROM m_record_item WHERE record_id = $1;

-- name: InsertItem :one
INSERT INTO m_record_item (record_id, tenant_id, factor_code, metric_value, raw_score, weighted_score, evidence)
VALUES ($1, $2, $3, $4::numeric, $5::numeric, $6::numeric, COALESCE($7::jsonb,'[]'::jsonb))
ON CONFLICT (record_id, factor_code) DO UPDATE SET
  metric_value = EXCLUDED.metric_value,
  raw_score    = EXCLUDED.raw_score,
  weighted_score = EXCLUDED.weighted_score,
  evidence     = EXCLUDED.evidence
RETURNING *;

-- name: ListItems :many
SELECT * FROM m_record_item
WHERE record_id = $1
ORDER BY id ASC;

-- name: ConfirmRecord :one
UPDATE m_record SET status='CONFIRMED', confirmed_by=$3, confirmed_at=now(), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='CALCULATED'
RETURNING *;

-- name: AppealRecord :one
UPDATE m_record SET status='APPEAL', appeal_reason=$4, modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status IN ('CALCULATED','CONFIRMED')
RETURNING *;

-- name: ApproveRecord :one
UPDATE m_record SET status='APPROVED', approve_by=$3, approve_at=now(), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='CONFIRMED'
RETURNING *;

-- name: VoidRecord :one
UPDATE m_record SET status='VOID', void_reason=COALESCE($4, void_reason), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status <> 'PAID'
RETURNING *;

-- name: MarkRecordPaid :one
UPDATE m_record SET status='PAID', updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='APPROVED'
RETURNING *;

-- name: ListMyRecords :many
-- /perf/me：ABAC 强制 staff_user_id=本人。返回记录，明细由 handler 逐个 ListItems 组装。
SELECT * FROM m_record
WHERE deleted = 0 AND tenant_id = $1 AND staff_user_id = $2
  AND ($3::text IS NULL OR period = $3::text)
ORDER BY period DESC, id DESC;

-- name: RankedRecords :many
-- /perf/ranking：某方案某周期按总分降序取名次（window row_number）。子查询 SELECT * 保 model 列 + 追加 rn。
SELECT * FROM (
  SELECT *, row_number() OVER (ORDER BY total_score DESC, id ASC) AS rn
  FROM m_record
  WHERE deleted = 0 AND tenant_id = $1 AND scheme_id = $2 AND period = $3
    AND status IN ('CALCULATED','CONFIRMED','APPROVED','PAID')
) r
ORDER BY rn ASC
LIMIT $4;
```

> `UpsertRecord` 的 `ON CONFLICT ... WHERE deleted = 0` 是**部分索引仲裁**必备谓词（对应 `uk_m_record`）。`RankedRecords` 因为加了 window 列 `rn`，sqlc 会生成 `RankedRecordsRow`（= model 全列 + `Rn int64`），是唯一需要单独 Row 结构的查询——M-8 `ToAPIRank` 接收 `RankedRecordsRow`。其余记录/明细查询都返回 model。`ListMyRecords`/`RankedRecords` 不 join sys_user/sys_org，故 `staff_name`/`scheme_name` 由 handler 侧留空（M0 留空，契约 nullable）。

- [ ] **步骤 5：写 `m_payout.sql`**

> 约定同 `m_record.sql`：实体查询 `SELECT *`/`RETURNING *` → 返回 `Payout` model（`amount` NUMERIC 保持 `pgtype.Numeric`，`approver_ids`/`reject_reason` 等按 nullable 出指针/[]byte）；仅 `CountPayouts` 聚合保留 `count(*)::int`。

```sql
-- name: ListPayouts :many
SELECT * FROM m_payout
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::text   IS NULL OR period = $2::text)
  AND ($3::text   IS NULL OR status = $3::text)
  AND ($4::bigint IS NULL OR payee_user_id = $4::bigint)
ORDER BY id DESC
LIMIT $6 OFFSET $5;

-- name: CountPayouts :one
SELECT count(*)::int AS n
FROM m_payout
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::text   IS NULL OR period = $2::text)
  AND ($3::text   IS NULL OR status = $3::text)
  AND ($4::bigint IS NULL OR payee_user_id = $4::bigint);

-- name: GetPayout :one
SELECT * FROM m_payout
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: CreatePayout :one
INSERT INTO m_payout (tenant_id, creator_id, status, record_id, payee_user_id, amount, period, pay_channel, security_level)
VALUES ($1, $2, 'DRAFT', $3, $4, $5::numeric, $6, $7, COALESCE($8::text,'INTERNAL'))
RETURNING *;

-- name: ApprovePayout :one
UPDATE m_payout
SET status='APPROVED', approved_at=now(), modifier_id=$3, updated_at=now(),
    approver_ids = approver_ids || jsonb_build_array(jsonb_build_object('userId',$3,'at',now(),'action','APPROVE'))
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status IN ('DRAFT','APPROVING')
RETURNING *;

-- name: PayPayout :one
UPDATE m_payout
SET status='PAID', paid_at=now(), voucher_code=COALESCE($4, voucher_code), modifier_id=$3, updated_at=now(),
    approver_ids = approver_ids || jsonb_build_array(jsonb_build_object('userId',$3,'at',now(),'action','PAY'))
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='APPROVED'
RETURNING *;

-- name: RejectPayout :one
UPDATE m_payout
SET status='REJECTED', reject_reason=COALESCE($4, reject_reason), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status IN ('DRAFT','APPROVING')
RETURNING *;
```

> `approver_ids || jsonb_build_array(...)` 用 jsonb 拼接追加审批留痕（`approver_ids` 默认 `'[]'`，非 NULL，拼接安全）。`SELECT *`/`RETURNING *` 后所有 payout 查询返回 `Payout` model，`amount` 为 `pgtype.Numeric`（M-11 建 payout 传 `numeric(strPtr(...))`，读经 M-8 `numDec` 格式化）。

- [ ] **步骤 6：Commit（五个查询文件齐）**

```bash
git add backend-go/db/query_m/m_scheme.sql backend-go/db/query_m/m_scheme_factor.sql backend-go/db/query_m/metrics.sql backend-go/db/query_m/m_record.sql backend-go/db/query_m/m_payout.sql
git commit -m "feat(M): 绩效 sqlc 查询（scheme/factor/record/payout + 跨表 metrics）"
```

### 任务 M-6：sqlc 生成 M 数据访问层

**文件：**
- 生成：`backend-go/internal/modules/performance/store/{db.go,models.go,m_scheme.sql.go,m_scheme_factor.sql.go,metrics.sql.go,m_record.sql.go,m_payout.sql.go}`

- [ ] **步骤 1：串行生成（Windows 避 wazero OOM）**

运行（在 `backend-go/`）：`GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate`
预期：生成 `internal/modules/performance/store/` 下文件；无 `panic: out of bounds memory access`。若报某跨表列不存在，按报错行改 `m_schema.sql` 内联读表列 + `metrics.sql` 引用保持一致后重跑。

- [ ] **步骤 2：编译校验**

运行：`go build ./internal/modules/performance/store/`
预期：成功。打开 `models.go` 确认 `Scheme`（含 `CreatedAt time.Time`）、`SchemeFactor`（`Weight pgtype.Numeric`、`MaxScore pgtype.Numeric`——SELECT * 返回 model，NUMERIC 不 override 恒为 `pgtype.Numeric`）、`Record`（`TotalScore pgtype.Numeric`、`Rank *int32`、`CalcAt *time.Time`）、`RecordItem`（`MetricValue/RawScore/WeightedScore pgtype.Numeric`、`Evidence []byte`）、`Payout`（`Amount pgtype.Numeric`、`ApproverIDs []byte`）形状符合预期。另确认非实体查询生成 Row：`RankedRecordsRow`（model 全列 + `Rn int64`）、metrics 各查询 Row（`::text` 投影出 `string`/`[]byte`）。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/performance/store/
git commit -m "feat(M): sqlc 生成 mstore 数据访问层"
```

### 任务 M-7：mstore 形状钉测（无 DB 编译守卫）

**文件：**
- 创建：`backend-go/internal/modules/performance/store/compile_test.go`

- [ ] **步骤 1：写测试**（仿 V-8；仅断言生成类型与方法签名，编译即通过）

```go
package mstore

import (
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

func TestStoreShapes(t *testing.T) {
	var s Scheme
	s.CreatedAt = time.Time{}          // override: time.Time
	s.Active = true
	var f SchemeFactor
	f.Weight = pgtype.Numeric{}        // SELECT * → NUMERIC 不 override，恒 pgtype.Numeric
	f.MaxScore = pgtype.Numeric{}      // NUMERIC 可空也是 pgtype.Numeric（靠 .Valid 判空）
	var r Record
	r.TotalScore = pgtype.Numeric{}    // pgtype.Numeric
	r.Rank = nil                       // INT nullable → *int32
	r.CalcAt = nil                     // *time.Time
	var it RecordItem
	it.MetricValue = pgtype.Numeric{} // pgtype.Numeric
	it.Evidence = []byte("[]")        // JSONB → []byte
	var p Payout
	p.Amount = pgtype.Numeric{}        // pgtype.Numeric
	p.ApproverIDs = []byte("[]")
	// 非实体查询的 Row 结构存在性
	var rr RankedRecordsRow
	rr.Rn = 1                          // window row_number → int64（列名 rn）
	_ = rr
	// 方法存在性（取函数值，不调用）
	_ = (&Queries{}).ListSchemes
	_ = (&Queries{}).UpsertRecord
	_ = (&Queries{}).MetricsOutputsByStaff
	_ = (&Queries{}).MetricsIncomeByStaff
	_ = (&Queries{}).ListCalcStaff
	_ = (&Queries{}).RankedRecords
	_ = (&Queries{}).PayPayout
	_ = s; _ = f; _ = r; _ = it; _ = p
}
```

> 若某生成类型/参数名与此不符，以生成物为准改测试。关键：实体查询用 `SELECT *`/`RETURNING *`，NUMERIC 列一律是 `pgtype.Numeric`（不是 `string`，也无需列级 override）；只有 `metrics.sql`（`::text` 投影）与聚合/Row 查询出 `string`。`RankedRecords` 因带 window 列 `rn` 生成 `RankedRecordsRow`（model 全列 + `Rn int64`）。

- [ ] **步骤 2：运行**

运行：`go test ./internal/modules/performance/store/ -run TestStoreShapes -v`
预期：PASS。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/performance/store/compile_test.go
git commit -m "test(M): 钉住 mstore 生成类型形状"
```

### 任务 M-8：M mapper（store 行 → 契约 snake_case）

**文件：**
- 创建：`backend-go/internal/modules/performance/mapper.go`

> `performance` 是独立包，自带 `jsonToAny/fmtTime/fmtTimePtr/optStr/optInt64Ptr/numDec/numStrOrNil`（不与 `activity` 共享）。所有 ToAPI* 返回 `map[string]any`，键严格对齐 `design/14` 契约字段（snake_case）。`scheme_name`/`staff_name`/`payee_name` 无 join，留 `nil`（契约 nullable）。**数值格式化**：实体查询用 `SELECT *`，NUMERIC 列是 `pgtype.Numeric`；契约要 `string`，故本层用 `numDec`（落定标字符串，无效兜底 "0"，用于 NOT NULL 的读出字段：weight/total_score/metric_value/raw_score/weighted_score/amount）与 `numStrOrNil`（无效→`nil`，用于 nullable 的 `max_score`）。小数位对齐契约精度（weight/score/amount=2、metric_value=4）。

- [ ] **步骤 1：写映射**

```go
package performance

import (
	"encoding/json"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
)

func jsonToAny(b []byte, fallback any) any {
	if len(b) == 0 {
		return fallback
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return fallback
	}
	return v
}

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

func optStr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func optInt64Ptr(v *int64) any {
	if v == nil {
		return nil
	}
	return *v
}

// numDec：pgtype.Numeric → 定标字符串（d 位小数）。无效/!Valid 兜底 "0"（用于 NOT NULL 读出字段）。
func numDec(n pgtype.Numeric, d int) string {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return "0"
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

// numStrOrNil：pgtype.Numeric → 定标字符串；无效/!Valid → nil（用于契约 nullable 字段，如 max_score）。
func numStrOrNil(n pgtype.Numeric, d int) any {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return nil
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

func ToAPIScheme(r mstore.Scheme) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"name":             r.Name,
		"period_type":      r.PeriodType,
		"scope_dept_id":    optInt64Ptr(r.ScopeDeptID),
		"scope_staff_type": optStr(r.ScopeStaffType),
		"effective_period": r.EffectivePeriod,
		"version":          r.Version,
		"active":           r.Active,
		"status":           r.Status,
		"created_at":       fmtTime(r.CreatedAt),
		"updated_at":       fmtTime(r.UpdatedAt),
	}
}

func ToAPIFactor(r mstore.SchemeFactor) map[string]any {
	return map[string]any{
		"id":           r.ID,
		"scheme_id":    r.SchemeID,
		"factor_code":  r.FactorCode,
		"factor_name":  optStr(r.FactorName),
		"weight":       numDec(r.Weight, 2),        // pgtype.Numeric → "30.00"
		"scoring_rule": jsonToAny(r.ScoringRule, map[string]any{}),
		"max_score":    numStrOrNil(r.MaxScore, 2), // 可空
		"data_source":  r.DataSource,
		"clause_ref":   optStr(r.ClauseRef),
		"sort_no":      r.SortNo,
	}
}

// ToAPIRecord：list/get 通用形状（Record 契约字段）。items 不在此，detail 端点另拼。
func ToAPIRecord(r mstore.Record) map[string]any {
	return map[string]any{
		"id":            r.ID,
		"scheme_id":     r.SchemeID,
		"scheme_name":   nil,
		"staff_user_id": r.StaffUserID,
		"staff_name":    nil,
		"period":        r.Period,
		"dept_id":       optInt64Ptr(r.DeptID),
		"total_score":   numDec(r.TotalScore, 2), // "88.50"
		"rank":          r.Rank,                  // *int32 → JSON number/null
		"status":        r.Status,
		"calc_batch":    optStr(r.CalcBatch),
		"calc_at":       fmtTimePtr(r.CalcAt),
		"confirmed_at":  fmtTimePtr(r.ConfirmedAt),
		"approve_at":    fmtTimePtr(r.ApproveAt),
	}
}

func ToAPIRecordItem(r mstore.RecordItem) map[string]any {
	return map[string]any{
		"id":             r.ID,
		"record_id":      r.RecordID,
		"factor_code":    r.FactorCode,
		"factor_name":    nil,
		"metric_value":   numDec(r.MetricValue, 4),   // "3.0000"
		"raw_score":      numDec(r.RawScore, 2),
		"weighted_score": numDec(r.WeightedScore, 2),
		"evidence":       jsonToAny(r.Evidence, []any{}),
	}
}

// ToAPIRecordDetail：record + items 拼装（/perf/records/{id}/detail、/perf/me）。
func ToAPIRecordDetail(r mstore.Record, items []mstore.RecordItem) map[string]any {
	out := ToAPIRecord(r)
	list := make([]map[string]any, 0, len(items))
	for _, it := range items {
		list = append(list, ToAPIRecordItem(it))
	}
	out["items"] = list
	return out
}

func ToAPIPayout(r mstore.Payout) map[string]any {
	return map[string]any{
		"id":            r.ID,
		"code":          optStr(r.Code),
		"record_id":     r.RecordID,
		"payee_user_id": r.PayeeUserID,
		"payee_name":    nil,
		"amount":        numDec(r.Amount, 2), // "12000.00"
		"period":        optStr(r.Period),
		"pay_channel":   optStr(r.PayChannel),
		"status":        r.Status,
		"approved_at":   fmtTimePtr(r.ApprovedAt),
		"paid_at":       fmtTimePtr(r.PaidAt),
		"voucher_code":  optStr(r.VoucherCode),
	}
}

// ToAPIRank：RankedRecords 行 → RankItem（含生成列 rn 作 rank）。RankedRecordsRow = model 全列 + Rn int64。
func ToAPIRank(r mstore.RankedRecordsRow) map[string]any {
	return map[string]any{
		"rank":          r.Rn,
		"staff_user_id": r.StaffUserID,
		"staff_name":    nil,
		"dept_id":       optInt64Ptr(r.DeptID),
		"total_score":   numDec(r.TotalScore, 2),
	}
}
```

> 生成物列名/类型以 sqlc 实际输出为准：`RankedRecords` 的行结构体若叫 `RankedRecordsRow` 之外的名字、或 `r.Rn` 实为 `r.RowNumber`、或 `Record.Rank` 出成 `*int32` 之外的形态，回改此处。`numDec`/`numStrOrNil` 的字段归属须逐一对 `design/14` 契约 nullability：契约把某数值字段标为 `required`/非 null → 用 `numDec`（"0" 兜底），标为可空 → 用 `numStrOrNil`（→ null）。

- [ ] **步骤 2：编译**

运行：`go build ./internal/modules/performance/`
预期：成功（handler 未加时仅 mapper.go 也须单独编译通过；`json`/`time` 均被使用）。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/performance/mapper.go
git commit -m "feat(M): 绩效 store 行→契约 snake_case 映射"
```

### 任务 M-9：M handler 骨架 + 方案/因子 CRUD

**文件：**
- 创建：`backend-go/internal/modules/performance/handler.go`

> 定义 `Handler{q, pool}`（比 V 多存 `pool`，因 activate 需事务）与共享助手（与 V 同构但本包自带）。方案 create 后按主键回写 `code=PERF-<年>-<id>`（M0 简化，避免编号中心依赖，同 V-10 注）。activate 前 `SupersedeActiveInScope` 再 `ActivateScheme`，两步包一个事务：`h.pool.Begin(c)` → `qtx := h.q.WithTx(tx)`（sqlc 生成的 `WithTx(tx pgx.Tx) *Queries`，非回调式）→ `qtx.Supersede…(c,…) + qtx.Activate…(c,…)` → `tx.Commit(c)`，`defer tx.Rollback(c)` 兜底；无 DB 时不影响编译。

- [ ] **步骤 1：写 handler.go**

```go
package performance

import (
	"encoding/json"
	"strconv"
	"time"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Handler 同时持 pool：ActivateScheme 的两步（Supersede+Activate）须在一个事务内，
// sqlc 生成的是 `Queries.WithTx(tx pgx.Tx) *Queries`（不是回调式），需从 pool Begin 出 tx。
type Handler struct {
	q     *mstore.Queries
	pool  *pgxpool.Pool
}

func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: mstore.New(pool), pool: pool} }

// —— 共享助手 ——
func pageArgs(c *gin.Context) (page, size, limit, offset int32) {
	p, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	s, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if p < 1 {
		p = 1
	}
	if s < 1 {
		s = 20
	}
	if s > 200 {
		s = 200
	}
	return int32(p), int32(s), int32(s), int32((p - 1) * s)
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

func optInt64(c *gin.Context, k string) *int64 {
	if v := c.Query(k); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return &n
		}
	}
	return nil
}

func pathID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "非法 id")
		return 0, false
	}
	return id, true
}

func jsonOrEmpty(b json.RawMessage, def string) []byte {
	if len(b) == 0 {
		return []byte(def)
	}
	return b
}

func numeric(s *string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != nil && *s != "" {
		_ = n.Scan(*s)
	}
	return n
}

// —— 方案请求体 ——
type schemeBody struct {
	Name            string  `json:"name" binding:"required"`
	PeriodType      string  `json:"period_type" binding:"required"`
	EffectivePeriod string  `json:"effective_period" binding:"required"`
	ScopeDeptID     *int64  `json:"scope_dept_id"`
	ScopeStaffType  *string `json:"scope_staff_type"`
	SecurityLevel   *string `json:"security_level"`
	LegalEntityID   *int64  `json:"legal_entity_id"`
	PolicyPackID    *int64  `json:"policy_pack_id"`
	Remark          *string `json:"remark"`
}

// —— 因子请求体 ——
type factorBody struct {
	FactorCode  string          `json:"factor_code" binding:"required"`
	FactorName  *string         `json:"factor_name"`
	Weight      *string         `json:"weight"`
	ScoringRule json.RawMessage `json:"scoring_rule" binding:"required"`
	MaxScore    *string         `json:"max_score"`
	DataSource  string          `json:"data_source" binding:"required"`
	ClauseRef   *string         `json:"clause_ref"`
	SortNo      *int32          `json:"sort_no"`
}

// —— 方案 handler ——
func (h *Handler) ListSchemes(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListSchemes(c, mstore.ListSchemesParams{
		TenantID: d.TenantID, PeriodType: optQuery(c, "period_type"),
		EffectivePeriod: optQuery(c, "effective_period"), ScopeDeptID: optInt64(c, "scope_dept_id"),
		Status: optQuery(c, "status"), Keyword: optQuery(c, "keyword"),
		Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountSchemes(c, mstore.CountSchemesParams{
		TenantID: d.TenantID, PeriodType: optQuery(c, "period_type"),
		EffectivePeriod: optQuery(c, "effective_period"), ScopeDeptID: optInt64(c, "scope_dept_id"),
		Status: optQuery(c, "status"), Keyword: optQuery(c, "keyword"),
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIScheme(r)) // ListSchemes SELECT * → []mstore.Scheme，无需转换
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

func (h *Handler) GetScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	s, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	factors, _ := h.q.ListFactors(c, id)
	out := ToAPIScheme(s)
	fl := make([]map[string]any, 0, len(factors))
	for _, f := range factors {
		fl = append(fl, ToAPIFactor(f))
	}
	out["factors"] = fl
	httpx.WriteOK(c, out)
}

func (h *Handler) CreateScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b schemeBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	s, err := h.q.CreateScheme(c, mstore.CreateSchemeParams{
		TenantID: d.TenantID, CreatorID: d.UserID, SecurityLevel: deref(b.SecurityLevel),
		LegalEntityID: b.LegalEntityID, PolicyPackID: b.PolicyPackID,
		Name: b.Name, PeriodType: b.PeriodType, ScopeDeptID: b.ScopeDeptID,
		ScopeStaffType: b.ScopeStaffType, EffectivePeriod: b.EffectivePeriod, Remark: b.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	// M0 回写 code（PERF-年-id 补零）；生产替换为 svc-numbering 分配
	code := "PERF-" + strconv.Itoa(yearOf(s.CreatedAt)) + "-" + zeroPad(s.ID, 6)
	httpx.WriteOK(c, ToAPIScheme(withSchemeCode(s, code)))
}

func (h *Handler) UpdateScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	var b schemeBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	s, err := h.q.UpdateScheme(c, mstore.UpdateSchemeParams{
		ID: id, TenantID: d.TenantID, Name: strPtr(b.Name), PeriodType: strPtr(b.PeriodType),
		ScopeDeptID: b.ScopeDeptID, ScopeStaffType: b.ScopeStaffType,
		EffectivePeriod: strPtr(b.EffectivePeriod), Remark: b.Remark, ModifierID: d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "方案不存在或状态不可编辑（仅 DRAFT）")
		return
	}
	httpx.WriteOK(c, ToAPIScheme(s)) // UpdateScheme RETURNING * → mstore.Scheme
}

func (h *Handler) DeleteScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	n, err := h.q.SoftDeleteScheme(c, mstore.SoftDeleteSchemeParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}

// ActivateScheme：同维度旧 active → SUPERSEDED，本方案 → ACTIVE（一个事务内两步）。
func (h *Handler) ActivateScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	s, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	tx, err := h.pool.Begin(c) // gin.Context 满足 context.Context
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "启用失败：开启事务出错")
		return
	}
	defer func() { _ = tx.Rollback(c) }() // Commit 后 Rollback 返回 ErrTxClosed，忽略
	qtx := h.q.WithTx(tx)                // sqlc 生成：返回绑定该 tx 的新 Queries
	if err := qtx.SupersedeActiveInScope(c, mstore.SupersedeActiveInScopeParams{
		TenantID: d.TenantID, PeriodType: s.PeriodType, EffectivePeriod: s.EffectivePeriod,
		ScopeDeptID: s.ScopeDeptID, ScopeStaffType: s.ScopeStaffType,
	}); err != nil {
		httpx.WriteErr(c, 409, 40901, "启用失败："+err.Error())
		return
	}
	if _, err := qtx.ActivateScheme(c, mstore.ActivateSchemeParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID}); err != nil {
		httpx.WriteErr(c, 409, 40901, "启用失败："+err.Error())
		return
	}
	if err := tx.Commit(c); err != nil {
		httpx.WriteErr(c, 500, 50002, "启用失败：提交出错")
		return
	}
	out, _ := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	httpx.WriteOK(c, ToAPIScheme(out))
}

// —— 因子 handler ——
func (h *Handler) ListFactors(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	if _, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	rows, err := h.q.ListFactors(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, f := range rows {
		list = append(list, ToAPIFactor(f))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

func (h *Handler) UpsertFactor(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	if _, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	var b factorBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	f, err := h.q.UpsertFactor(c, mstore.UpsertFactorParams{
		SchemeID: id, TenantID: d.TenantID, CreatorID: d.UserID, FactorCode: b.FactorCode,
		FactorName: b.FactorName, Weight: numeric(b.Weight), ScoringRule: jsonOrEmpty(b.ScoringRule, "{}"),
		MaxScore: numeric(b.MaxScore), DataSource: b.DataSource, ClauseRef: b.ClauseRef, SortNo: derefI32(b.SortNo),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "保存因子失败")
		return
	}
	httpx.WriteOK(c, ToAPIFactor(f))
}

func (h *Handler) UpdateFactor(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	fid, ok2 := pathID2(c, "factorId")
	if !ok2 {
		return
	}
	var b factorBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	f, err := h.q.UpdateFactor(c, mstore.UpdateFactorParams{
		ID: fid, SchemeID: id, TenantID: d.TenantID, FactorName: b.FactorName,
		Weight: numeric(b.Weight), ScoringRule: jsonOrEmpty(b.ScoringRule, "{}"), MaxScore: numeric(b.MaxScore),
		DataSource: strPtr(b.DataSource), ClauseRef: b.ClauseRef, SortNo: derefI32(b.SortNo),
	})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "因子不存在")
		return
	}
	httpx.WriteOK(c, ToAPIFactor(f))
}

func (h *Handler) DeleteFactor(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	fid, ok2 := pathID2(c, "factorId")
	if !ok2 {
		return
	}
	n, err := h.q.DeleteFactor(c, mstore.DeleteFactorParams{ID: fid, SchemeID: id, TenantID: d.TenantID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "因子不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"factor_id": fid, "deleted": true})
}

// —— 小助手：解引用/构造 ——
func deref(s *string) *string         { return s }
func derefI32(v *int32) int32         { if v != nil { return *v }; return 0 }
func strPtr(s string) *string         { return &s }

func pathID2(c *gin.Context, name string) (int64, bool) {
	id, err := strconv.ParseInt(c.Param(name), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "非法 "+name)
		return 0, false
	}
	return id, true
}

func yearOf(t time.Time) int { return t.Year() }

func zeroPad(v int64, width int) string {
	s := strconv.FormatInt(v, 10)
	for len(s) < width {
		s = "0" + s
	}
	return s
}

// withSchemeCode：CreateScheme RETURNING 无 code（IDENTITY 先行、code 后写），
// M0 演示直接以 Go 侧回写值构造 map，省一次 UPDATE。若 mstore.Scheme 无 Code 字段可赋值处，
// 则 ToAPIScheme 用生成行 + 覆盖 code。见下 ToAPISchemeWithCode。
func withSchemeCode(s mstore.Scheme, code string) mstore.Scheme {
	s.Code = &code
	return s
}
```

> 关键校正点（执行时逐条核对 sqlc 生成物，不符即改）：① 生成 Params 字段名——`ListSchemesParams.Keyword`（`$6` 对应 name ILIKE）、`Offset/Limit int32`；若 sqlc 命名不同（如 `Search`）以生成物为准。② `CreateSchemeParams.SecurityLevel` 因列 NOT NULL DEFAULT，sqlc 生成类型为 `string` 而非 `*string`——则把 `SecurityLevel: deref(b.SecurityLevel)` 改为 `SecurityLevel: coalesceStr(b.SecurityLevel,"INTERNAL")` 并加该助手；`LegalEntityID/PolicyPackID` 可空→`*int64` 或 `pgtype.Int8`。③ `UpdateSchemeParams.Name/PeriodType/EffectivePeriod` 在查询里 `COALESCE($3::text,...)`，sqlc 视其为可空参数→`*string`，故 `strPtr(b.Name)` 正确。④ `TxQueries`/`WithTx` 需 `sqlc.yaml` 该块默认生成事务包装（v2 默认 `Queries`+`WithTx`）；若无则改用 `h.q.(*mstore.Queries)` 手动 `pool.Begin`。⑤ `mstore.Scheme.Code` 为 `*string`。

新增本地助手（若采用 ② 的 coalesce 变体）：

```go
func coalesceStr(s *string, def string) string {
	if s == nil || *s == "" {
		return def
	}
	return *s
}
```

- [ ] **步骤 2：编译**

运行：`go build ./internal/modules/performance/`
预期：成功（handler+mapper 一起编译；handler.go 用 `json`/`strconv`/`time`/`pgtype`/`pgxpool`/`gin`/`auth`/`httpx`/`mstore`——`context`、顶层 `pgx` 均未直接引用，故不 import；`tx pgx.Tx` 只出现在注释里）。

> 若 go vet 报某 import unused（如将来给 `sql.ErrNoRows`/`pgx.ErrNoRows` 加精确判需引入 `pgx`/`database/sql`），再按需补；当前通用 `err != nil` 处理不需要。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/performance/handler.go
git commit -m "feat(M): 绩效方案/因子 handler（CRUD+启用事务）+ 共享助手"
```

### 任务 M-10：calculate 取数引擎（跨模块只读聚合 → 计分 → upsert）

**文件：**
- 创建：`backend-go/internal/modules/performance/calculate.go`
- 测试：`backend-go/internal/modules/performance/calculate_test.go`

> **规格 §4/§5 核心交付物**：`POST /perf/schemes/{id}/calculate` 按方案因子从 `r_output`（成果数/级别）、`f_income`（到账经费）、`e_project`（在研项目数/预算）、`t_deal`（转化金额）真表**只读聚合**，逐因子按 `scoring_rule.method` 算分，累加 `total_score = Σ weighted_score`，幂等 upsert `m_record` + 重建 `m_record_item`（带证据）。**只碰这些表的已存在列，绝不改它们 DDL**（读它们靠 `metrics.sql`，运行期打真库全量表）。
>
> **分层**：`calculate.go` 含两类东西——① **纯函数**（`periodRange`、`scoreFactor`、`buildAgg` 的映射）不依赖 gin/DB，`calculate_test.go` 直接单测；② **方法** `(h *Handler).CalculatePerformance` + `computeStaff` 走 store（DB-gated，仅 handler_test 在有库时跑）。这样无 Docker 环境仍能对“计分逻辑”这一真正的业务大脑做 TDD。
>
> **四种计分法**（`scoring_rule` JSON）：
> - `COUNT`：`raw = Σ 单据数 × unit`（unit 缺省 1）。metric = 总单数。
> - `BY_LEVEL`：`raw = Σ_组 (cnt × levelMap[key])`，key = `output_type`/`project_type`；levelMap 缺该 key 记 0。metric = 总单数。
> - `BY_AMOUNT`：`raw = metric(金额) × unit`。金额来自 `F_INCOME`/`T_DEAL` 的 `amount`，或 `E_PROJECT` 的 `Σ 预算`。
> - `LADDER`：按 `metric`（金额优先，否则单数）落在 `ladder[{min,max,score}]` 首个区间取 `score`；无命中记 0。
> - `MANUAL` 数据源：不自动取数，`raw = 0`（M0 留人工/占位，注释说明）。
> 归一：`raw` 先按 `max_score`（若 >0）封顶，再 `weighted = raw × weight/100`；`total = Σ weighted`。

- [ ] **步骤 1：写 `calculate.go`**

```go
package performance

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
)

// scoringRule 是 m_scheme_factor.scoring_rule 的解析结构。
type scoringRule struct {
	Method   string              `json:"method"`   // COUNT | BY_LEVEL | BY_AMOUNT | LADDER
	Unit     *float64            `json:"unit"`     // 每单位分值（COUNT/BY_AMOUNT），缺省 1
	LevelMap map[string]float64  `json:"levelMap"` // BY_LEVEL：key(output_type/project_type)→分
	Ladder   []ladderTier        `json:"ladder"`   // LADDER：区间→分
}

type ladderTier struct {
	Min   float64 `json:"min"`
	Max   float64 `json:"max"` // 上界含（闭区间 [min,max]）；末档可用极大值
	Score float64 `json:"score"`
}

// aggResult 是某数据源对某 staff 聚合后的规范化信号。
type aggResult struct {
	byType   map[string]int32 // R_OUTPUT→output_type 计数；E_PROJECT→project_type 计数
	total    int32            // 单据总数（Σ byType 或单值型不适用则 0）
	amount   float64          // 金额（F_INCOME/T_DEAL 的 metric；E_PROJECT 的 Σ 预算）
	evidence []any            // 证据对象数组（直接落 m_record_item.evidence）
}

var reYear = regexp.MustCompile(`^(\d{4})$`)
var reQuarter = regexp.MustCompile(`^(\d{4})\s*[Qq]([1-4])$`)
var reMonth = regexp.MustCompile(`^(\d{4})-(\d{2})$`)

// periodRange：把 (periodType, period) 归一为 [from,to] 闭区间日期（pgtype.Date）。
// 支持 YEAR="2026" / QUARTER="2026Q3" / MONTH="2026-03"。无法解析→返回空(from/to Valid=false)，
// 由 metrics 的 `::date IS NULL` 分支兜底为“全时段”（M0 宽松，不报 400 之外错误）。
func periodRange(periodType, period string) (from, to pgtype.Date) {
	p := strings.TrimSpace(period)
	var start, next time.Time
	if m := reQuarter.FindStringSubmatch(p); m != nil {
		y, _ := strconv.Atoi(m[1])
		q, _ := strconv.Atoi(m[2])
		start = time.Date(y, time.Month((q-1)*3+1), 1, 0, 0, 0, 0, time.UTC)
		next = start.AddDate(0, 3, 0)
	} else if m := reMonth.FindStringSubmatch(p); m != nil {
		y, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		start = time.Date(y, time.Month(mo), 1, 0, 0, 0, 0, time.UTC)
		next = start.AddDate(0, 1, 0)
	} else if m := reYear.FindStringSubmatch(p); m != nil {
		y, _ := strconv.Atoi(m[1])
		start = time.Date(y, 1, 1, 0, 0, 0, 0, time.UTC)
		next = start.AddDate(1, 0, 0)
	} else {
		return pgtype.Date{Valid: false}, pgtype.Date{Valid: false}
	}
	_ = periodType // 冗余：以 period 串自证粒度；保留形参便于契约可读与将来校验
	toDay := next.AddDate(0, 0, -1)
	return pgtype.Date{Time: start, Valid: true}, pgtype.Date{Time: toDay, Valid: true}
}

// factorInput：scoreFactor 的窄入参，只取用得到的因子字段——把纯计分逻辑与 sqlc 生成物字段名解耦。
// Weight/MaxScore 直接接 mstore.SchemeFactor 的同名字段（SELECT * → pgtype.Numeric）。
type factorInput struct {
	FactorCode  string
	Weight      pgtype.Numeric
	MaxScore    pgtype.Numeric
	ScoringRule json.RawMessage
	DataSource  string
}

// scoreFactor：对一个因子 + 其数据源聚合结果，算出 (metric, raw, weighted, evidence)。纯函数。
func scoreFactor(f factorInput, agg aggResult) (metric, raw, weighted float64, evidence []any) {
	var rule scoringRule
	_ = json.Unmarshal(f.ScoringRule, &rule) // 解析失败→零值 rule，method=""→走 default 记 0
	weight := numN(f.Weight)
	maxScore := numN(f.MaxScore) // !Valid → 0（即不限顶）
	unit := 1.0
	if rule.Unit != nil && *rule.Unit != 0 {
		unit = *rule.Unit
	}
	evidence = agg.evidence
	if evidence == nil {
		evidence = []any{}
	}
	switch strings.ToUpper(strings.TrimSpace(rule.Method)) {
	case "COUNT":
		metric = float64(agg.total)
		raw = metric * unit
	case "BY_LEVEL":
		metric = float64(agg.total)
		for k, cnt := range agg.byType {
			raw += float64(cnt) * rule.LevelMap[k] // levelMap 无此 key → 0
		}
	case "BY_AMOUNT":
		metric = agg.amount
		raw = metric * unit
	case "LADDER":
		metric = agg.amount
		if metric == 0 {
			metric = float64(agg.total)
		}
		for _, t := range rule.Ladder {
			if metric >= t.Min && metric <= t.Max {
				raw = t.Score
				break
			}
		}
	default: // MANUAL / 未知 → 不自动计分
		metric = 0
		raw = 0
	}
	if maxScore > 0 && raw > maxScore {
		raw = maxScore
	}
	weighted = raw * weight / 100.0
	return metric, raw, weighted, evidence
}

// numOr：把 metrics.sql 里 NUMERIC::text 投影出的字符串转 float；失败或空返回 def（仅用于跨表聚合行）。
func numOr(s string, def float64) float64 {
	if s == "" {
		return def
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return def
	}
	return v
}

// numN：把 pgtype.Numeric（因子 Weight/MaxScore）转 float；!Valid 或出错返回 0。
func numN(n pgtype.Numeric) float64 {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return 0
	}
	return f.Float64
}

// ComputeResult：一次 calculate 的汇总（对齐契约 CalculateResult）。
type ComputeResult struct {
	CalcBatch string `json:"calc_batch"`
	Period    string `json:"period"`
	Computed  int    `json:"computed"`
	Inserted  int    `json:"inserted"`
	Updated   int    `json:"updated"`
}

type calculateBody struct {
	Period   string  `json:"period" binding:"required"`
	DeptIDs  []int64 `json:"dept_ids"`
	StaffIDs []int64 `json:"staff_ids"`
}

// CalculatePerformance：处理 POST /perf/schemes/{id}/calculate。
func (h *Handler) CalculatePerformance(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	scheme, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	var b calculateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	factors, err := h.q.ListFactorsBySchemeForCalc(c, mstore.ListFactorsBySchemeForCalcParams{SchemeID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "读取因子失败")
		return
	}
	if len(factors) == 0 {
		httpx.WriteErr(c, 400, 40001, "方案未配置因子，无法计算")
		return
	}
	from, to := periodRange(scheme.PeriodType, b.Period)

	// 解析待算人员集合：staff_ids 优先；否则按 dept_ids 取在研项目 PI（distinct）。
	staff := b.StaffIDs
	staffDept := map[int64]*int64{}
	if len(staff) == 0 {
		rows, err := h.q.ListCalcStaff(c, mstore.ListCalcStaffParams{TenantID: d.TenantID, DepartmentIds: b.DeptIDs})
		if err != nil {
			httpx.WriteErr(c, 500, 50002, "取计算人员失败")
			return
		}
		for _, r := range rows {
			staff = append(staff, r.StaffUserID)
			if r.DeptID != nil {
				staffDept[r.StaffUserID] = r.DeptID
			}
		}
	}

	batch := c.GetHeader("Idempotency-Key")
	if batch == "" {
		batch = fmt.Sprintf("BATCH-%s-%d", b.Period, time.Now().UTC().Unix())
	}

	res := ComputeResult{CalcBatch: batch, Period: b.Period}
	for _, sid := range staff {
		inserted, err := h.computeStaff(c, d, id, factors, sid, staffDept[sid], b.Period, from, to, batch)
		if err != nil {
			httpx.WriteErr(c, 500, 50002, "计算失败："+err.Error())
			return
		}
		res.Computed++
		if inserted {
			res.Inserted++
		} else {
			res.Updated++
		}
	}
	httpx.WriteOK(c, res)
}

// computeStaff：对单个 staff 聚合→算分→upsert record→重建 items。返回是否“新增”（false=覆盖）。
func (h *Handler) computeStaff(ctx context.Context, d auth.Domain, schemeID int64,
	factors []mstore.SchemeFactor, staffID int64, deptID *int64, period string,
	from, to pgtype.Date, batch string) (bool, error) {

	// 存在性预判（区分 inserted/updated）：同方案同周期该人是否已有记录。
	prescheme := schemeID
	cnt, err := h.q.CountRecords(ctx, mstore.CountRecordsParams{
		TenantID: d.TenantID, SchemeID: &prescheme, Period: &period,
		DeptID: nil, StaffUserID: &staffID, Status: nil, Keyword: nil,
	})
	if err != nil {
		return false, err
	}
	existed := cnt > 0

	// 只为“出现过的数据源”发查询，避免无谓扫描。
	need := map[string]bool{}
	for _, f := range factors {
		need[f.DataSource] = true
	}
	var (
		aggOut, aggProj aggResult
		aggInc, aggDeal aggResult
	)
	if need["R_OUTPUT"] {
		rows, err := h.q.MetricsOutputsByStaff(ctx, mstore.MetricsOutputsByStaffParams{
			TenantID: d.TenantID, PublishDate: from, PublishDate2: to, Authors: staffID,
		})
		if err != nil {
			return existed, err
		}
		aggOut = aggFromTypeRows(rows)
	}
	if need["E_PROJECT"] {
		rows, err := h.q.MetricsProjectsByStaff(ctx, mstore.MetricsProjectsByStaffParams{
			TenantID: d.TenantID, PiUserID: staffID, StartDate: from, StartDate2: to,
		})
		if err != nil {
			return existed, err
		}
		aggProj = aggFromProjRows(rows)
	}
	if need["F_INCOME"] {
		row, err := h.q.MetricsIncomeByStaff(ctx, mstore.MetricsIncomeByStaffParams{
			TenantID: d.TenantID, PiUserID: staffID, ReceiptDate: from, ReceiptDate2: to,
		})
		if err != nil {
			return existed, err
		}
		aggInc = aggFromAmountRow(row.Metric, row.Evidence)
	}
	if need["T_DEAL"] {
		row, err := h.q.MetricsTransferByStaff(ctx, mstore.MetricsTransferByStaffParams{
			TenantID: d.TenantID, Authors: staffID, SignedAt: from, SignedAt2: to,
		})
		if err != nil {
			return existed, err
		}
		aggDeal = aggFromAmountRow(row.Metric, row.Evidence)
	}

	// 逐因子算分，累加 total，收集明细。
	total := 0.0
	type itemRow struct {
		code             string
		metric, raw, wgt float64
		ev               []any
	}
	items := make([]itemRow, 0, len(factors))
	for _, f := range factors {
		var agg aggResult
		switch f.DataSource {
		case "R_OUTPUT":
			agg = aggOut
		case "E_PROJECT":
			agg = aggProj
		case "F_INCOME":
			agg = aggInc
		case "T_DEAL":
			agg = aggDeal
		default: // MANUAL
			agg = aggResult{}
		}
		fi := factorInput{
			FactorCode: f.FactorCode, Weight: f.Weight, MaxScore: f.MaxScore,
			ScoringRule: json.RawMessage(f.ScoringRule), DataSource: f.DataSource,
		}
		metric, raw, weighted, ev := scoreFactor(fi, agg)
		total += weighted
		items = append(items, itemRow{code: f.FactorCode, metric: metric, raw: raw, wgt: weighted, ev: ev})
	}

	// 组装 calc_detail（复核用的算分快照）。
	detail := map[string]any{
		"period": period, "calc_batch": batch, "scheme_id": schemeID,
		"total": round2(total),
		"factors": func() []map[string]any {
			out := make([]map[string]any, 0, len(items))
			for _, it := range items {
				out = append(out, map[string]any{
					"factor_code": it.code, "metric": it.metric,
					"raw_score": round2(it.raw), "weighted_score": round2(it.wgt),
				})
			}
			return out
		}(),
	}
	detailJSON, _ := json.Marshal(detail)

	rec, err := h.q.UpsertRecord(ctx, mstore.UpsertRecordParams{
		TenantID: d.TenantID, CreatorID: d.UserID, SchemeID: schemeID, StaffUserID: staffID,
		Period: period, DeptID: deptID, TotalScore: numericPtr(fmt.Sprintf("%.2f", round2(total))),
		CalcDetail: detailJSON, CalcBatch: batch, SecurityLevel: nil,
	})
	if err != nil {
		return existed, err
	}
	// 重建明细。
	if err := h.q.DeleteItemsByRecord(ctx, rec.ID); err != nil {
		return existed, err
	}
	for _, it := range items {
		evb, _ := json.Marshal(it.ev)
		if _, err := h.q.InsertItem(ctx, mstore.InsertItemParams{
			RecordID: rec.ID, TenantID: d.TenantID, FactorCode: it.code,
			MetricValue: numericPtr(fmt.Sprintf("%.4f", it.metric)),
			RawScore:    numericPtr(fmt.Sprintf("%.2f", round2(it.raw))),
			WeightedScore: numericPtr(fmt.Sprintf("%.2f", round2(it.wgt))),
			Evidence:    evb,
		}); err != nil {
			return existed, err
		}
	}
	return !existed, nil
}

// —— 把 sqlc 行规整为 aggResult ——

func aggFromTypeRows(rows []mstore.MetricsOutputsByStaffRow) aggResult {
	a := aggResult{byType: map[string]int32{}, evidence: []any{}}
	for _, r := range rows {
		a.byType[r.OutputType] = r.Cnt
		a.total += r.Cnt
		a.evidence = appendEvidence(a.evidence, r.Evidence)
	}
	return a
}

func aggFromProjRows(rows []mstore.MetricsProjectsByStaffRow) aggResult {
	a := aggResult{byType: map[string]int32{}, evidence: []any{}}
	for _, r := range rows {
		a.byType[r.ProjectType] = r.Cnt
		a.total += r.Cnt
		a.amount += numOr(r.Amount, 0)
		a.evidence = appendEvidence(a.evidence, r.Evidence)
	}
	return a
}

func aggFromAmountRow(metric string, ev []byte) aggResult {
	return aggResult{
		byType:   map[string]int32{},
		amount:   numOr(metric, 0),
		evidence: appendEvidence([]any{}, ev),
	}
}

// appendEvidence：把一行 JSONB 证据（形如 [{...},{...}]）解包追加到大数组；解析失败静默跳过。
func appendEvidence(dst []any, raw []byte) []any {
	if len(raw) == 0 {
		return dst
	}
	var part []any
	if err := json.Unmarshal(raw, &part); err != nil {
		return dst
	}
	return append(dst, part...)
}

// numericPtr：字符串→pgtype.Numeric（供 numeric 参数位；空/非法→无效）。
func numericPtr(s string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != "" {
		_ = n.Scan(s)
	}
	return n
}

func round2(f float64) float64 {
	return float64(int64(f*100+0.5)) / 100
}
```

> **执行时以 sqlc 生成物为准逐条核对（不符即改 calculate.go / M-5 查询，勿改真库 DDL）**：
> ① **参数结构体字段名**：`MetricsOutputsByStaffParams` 的日期入参，sqlc 依 `$2::date`/`$3::date` 生成的字段可能是 `PublishDate`/`PublishDate2`（同名列去重加后缀）或 `From_`/`To` 之类；`MetricsProjectsByStaffParams` 可能是 `{TenantID, PiUserID, StartDate, StartDate2}`；`MetricsIncomeByStaffParams` 的 staff 参数名可能叫 `PiUserID`（源自 `$2::bigint` 关联 ep.pi_user_id）。**打开生成文件按实际字段名回填**，语义：tenant、staff、from、to。`ListCalcStaffParams` 的数组入参可能叫 `DepartmentIds`/`DeptIds`。
> ② **行结构体**：`MetricsOutputsByStaffRow{OutputType string; Cnt int32; Evidence []byte}`、`MetricsProjectsByStaffRow{ProjectType string; Cnt int32; Amount string; Evidence []byte}`、`MetricsIncomeByStaffRow{Metric string; Evidence []byte}`、`MetricsTransferByStaffRow{Metric string; Evidence []byte}`、`ListCalcStaffRow{StaffUserID int64; DeptID *int64}`——列名以生成物为准。若 `Evidence` 生成为 `[]byte` 之外的类型（如 `json.RawMessage`），`appendEvidence` 形参相应调。
> ③ **日期参数类型**：`::date` → `pgtype.Date`；若 sqlc 生成的是 `*time.Time` 或 `pgtype.Timestamp`，把 `periodRange` 返回值与调用点统一改类型（语义不变）。
> ④ `UpsertRecordParams.TotalScore` 因 `$7::numeric` → `pgtype.Numeric`；`SecurityLevel` 因 `COALESCE($10::text,...)` → `*string`（传 nil 即取默认 INTERNAL）；`DeptID` 可空 → `*int64`。`InsertItemParams` 的三个分数位 `$4/$5/$6::numeric` → `pgtype.Numeric`（用 `numericPtr`）。若某位生成为 `string`，把 `numericPtr(...)` 换成裸字符串。
> ⑤ `CountRecordsParams.{SchemeID,Period,StaffUserID}` 须为指针（查询里 `IS NULL` 可选）——与 M-5 `CountRecords` 的 `($N ... IS NULL)` 一致；若 sqlc 判为非指针，改用只带 tenant+staff 的更宽谓词或补一条 `ExistsRecord` 查询。

- [ ] **步骤 2：写纯函数单测 `calculate_test.go`**（无 DB，真 TDD：先跑失败→再实现）

```go
package performance

import (
	"encoding/json"
	"testing"

	"github.com/jackc/pgx/v5/pgtype"
)

func pgnum(t *testing.T, s string) pgtype.Numeric {
	t.Helper()
	var n pgtype.Numeric
	if s != "" {
		if err := n.Scan(s); err != nil {
			t.Fatalf("pgnum scan %q: %v", s, err)
		}
	}
	return n
}

func mkFactor(t *testing.T, ds, weight, maxScore, rule string) factorInput {
	t.Helper()
	f := factorInput{DataSource: ds, Weight: pgnum(t, weight), FactorCode: "X"}
	if maxScore != "" {
		f.MaxScore = pgnum(t, maxScore)
	}
	if rule != "" {
		f.ScoringRule = json.RawMessage(rule)
	}
	return f
}

func TestPeriodRange_Year(t *testing.T) {
	from, to := periodRange("YEAR", "2026")
	if from.Time.Year() != 2026 || from.Time.Month() != 1 || from.Time.Day() != 1 {
		t.Fatalf("2026 起错: %v", from.Time)
	}
	if to.Time.Year() != 2026 || to.Time.Month() != 12 || to.Time.Day() != 31 {
		t.Fatalf("2026 止错: %v", to.Time)
	}
	if !from.Valid || !to.Valid {
		t.Fatal("年周期应有效")
	}
}

func TestPeriodRange_Quarter(t *testing.T) {
	from, to := periodRange("QUARTER", "2026Q3")
	if from.Time.Month() != 7 || from.Time.Day() != 1 {
		t.Fatalf("Q3 起错: %v", from.Time)
	}
	if to.Time.Month() != 9 || to.Time.Day() != 30 {
		t.Fatalf("Q3 止错(应 9/30): %v", to.Time)
	}
}

func TestPeriodRange_Month(t *testing.T) {
	from, to := periodRange("MONTH", "2026-02")
	if from.Time.Month() != 2 || from.Time.Day() != 1 {
		t.Fatalf("2 月起错: %v", from.Time)
	}
	if to.Time.Month() != 2 || to.Time.Day() != 28 {
		t.Fatalf("2026 非闰年 2 月止应为 28: %v", to.Time)
	}
}

func TestPeriodRange_Bad(t *testing.T) {
	from, _ := periodRange("YEAR", "not-a-date")
	if from.Valid {
		t.Fatal("非法周期串应返回 Valid=false")
	}
}

func TestScoreFactor_Count(t *testing.T) {
	f := mkFactor(t, "R_OUTPUT", "40.00", "", `{"method":"COUNT","unit":2}`)
	agg := aggResult{byType: map[string]int32{"PAPER": 3}, total: 3}
	metric, raw, weighted, _ := scoreFactor(f, agg)
	if metric != 3 || raw != 6 || weighted != 2.4 {
		t.Fatalf("COUNT: metric=%v raw=%v wgt=%v 期望 3/6/2.4", metric, raw, weighted)
	}
}

func TestScoreFactor_ByLevel(t *testing.T) {
	f := mkFactor(t, "R_OUTPUT", "50.00", "", `{"method":"BY_LEVEL","levelMap":{"PAPER":10,"PATENT":20}}`)
	agg := aggResult{byType: map[string]int32{"PAPER": 2, "PATENT": 1, "UNKNOWN": 5}, total: 8}
	_, raw, weighted, _ := scoreFactor(f, agg)
	// 2*10 + 1*20 + 5*0 = 40
	if raw != 40 || weighted != 20 {
		t.Fatalf("BY_LEVEL: raw=%v wgt=%v 期望 40/20", raw, weighted)
	}
}

func TestScoreFactor_ByAmount(t *testing.T) {
	f := mkFactor(t, "F_INCOME", "60.00", "30.00", `{"method":"BY_AMOUNT","unit":0.001}`)
	agg := aggResult{amount: 100000} // 100000*0.001=100，但 max_score=30 封顶
	_, raw, weighted, _ := scoreFactor(f, agg)
	if raw != 30 {
		t.Fatalf("BY_AMOUNT 应封顶 30，得 raw=%v", raw)
	}
	if weighted != 18 {
		t.Fatalf("30*60/100=18，得 wgt=%v", weighted)
	}
}

func TestScoreFactor_Ladder(t *testing.T) {
	f := mkFactor(t, "T_DEAL", "100.00", "", `{"method":"LADDER","ladder":[{"min":0,"max":100000,"score":10},{"min":100000,"max":1000000,"score":20}]}`)
	agg := aggResult{amount: 500000}
	_, raw, _, _ := scoreFactor(f, agg)
	if raw != 20 {
		t.Fatalf("LADDER 500000 应落第二档=20，得 %v", raw)
	}
}

func TestScoreFactor_Manual(t *testing.T) {
	f := mkFactor(t, "MANUAL", "10.00", "", `{}`)
	_, raw, _, _ := scoreFactor(f, aggResult{})
	if raw != 0 {
		t.Fatalf("MANUAL 应 0 分，得 %v", raw)
	}
}

func TestScoreFactor_BadRule(t *testing.T) {
	f := mkFactor(t, "R_OUTPUT", "10.00", "", `{ this is not json }`)
	_, raw, _, _ := scoreFactor(f, aggResult{total: 5})
	if raw != 0 {
		t.Fatalf("坏规则应记 0，得 %v", raw)
	}
}
```

> 上面所有测试都构造 `factorInput`（step 1 已定义），**不依赖** sqlc 生成物 `SchemeFactor` 的确切字段类型——纯计分逻辑被彻底解耦，无 DB 也能跑。`scoreFactor`/`periodRange`/`aggResult`/`factorInput` 均来自 `calculate.go`（同包，测试直接引用）。

- [ ] **步骤 3：运行单测（先失败后通过）**

- 先只写步骤 2 的测试、未写 `calculate.go` 时运行：`go test ./internal/modules/performance/ -run 'TestScoreFactor|TestPeriodRange' -v` → 预期编译失败（`scoreFactor`/`periodRange`/`factorInput`/`aggResult` undefined）。
- 补齐 `calculate.go`（步骤 1）后重跑：预期全部 `PASS`。

- [ ] **步骤 4：编译整包**

运行：`go build ./internal/modules/performance/`
预期：成功。（`regexp`/`strings`/`strconv`/`fmt`/`time`/`encoding/json`/`pgtype`/`context`/`mstore`/`auth`/`httpx`/`gin` 均被 `calculate.go` 使用。）

> 注意：`calculate.go` 与 `handler.go` 同包——`calculate.go` 用**新名字** `numericPtr`（区别于 handler 的 `numeric(*string) pgtype.Numeric`），**不要**重复定义 `numeric`、`pathID`、`pageArgs`、`optQuery`、`jsonOrEmpty`、`deref` 等（已在 handler.go）。本文件仅新增 `periodRange/scoreFactor/numOr/numN/round2/appendEvidence/aggFrom*/numericPtr/ComputeResult/calculateBody/scoringRule/ladderTier/aggResult/factorInput/reYear/reQuarter/reMonth`。若与别处重名冲突，改名或删冗余。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/modules/performance/calculate.go backend-go/internal/modules/performance/calculate_test.go
git commit -m "feat(M): calculate 取数引擎（跨 R/F/E/T 聚合+四计分法+幂等 upsert，纯函数单测）"
```

### 任务 M-11：绩效记录/发放/个人 handler（ABAC + 状态机）

**文件：**
- 创建：`backend-go/internal/modules/performance/records.go`

> 从 `handler.go` 拆出，聚焦 **记录（record）状态机 + 发放（payout）状态机 + 个人视图/排行**。同包，直接复用 handler.go 的 `Handler`/`NewHandler`/`pageArgs`/`optQuery`/`optInt64`/`pathID`/`jsonOrEmpty`/`numeric`/`deref`/`derefI32`/`strPtr` 等助手（**不重复定义**）。
>
> **ABAC 规则**（规格 §6/§7）：
> - 管理角色 `{R-ADMIN,R-MANAGER,R-LEADER}` 可跨人读写记录、审批/作废、查排行。
> - 非管理角色（含 R-STAFF/R-FINANCE/R-AUDITOR）只能看/操作**本人**记录：list/read 强制 `staff_user_id=本人`；confirm/appeal 允许本人；approve/void/ranking 需管理→否则 403。
> - 发放动作（create/approve/pay/reject）限 `{R-ADMIN,R-MANAGER,R-FINANCE,R-LEADER}`；非管理列发放时强制 `payee_user_id=本人`。
>
> **状态机前置**由 store 的 `WHERE status=...` 守卫保证：先 `GetRecord` 判存在(404)+ABAC(403)，再调迁移方法；迁移返回 `sql.ErrNoRows`（态不符）→ 409。

- [ ] **步骤 1：写 `records.go`**

```go
package performance

import (
	"strconv"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

var managerRoles = map[string]bool{"R-ADMIN": true, "R-MANAGER": true, "R-LEADER": true}
var payoutRoles = map[string]bool{"R-ADMIN": true, "R-MANAGER": true, "R-LEADER": true, "R-FINANCE": true}

func isManager(d auth.Domain) bool {
	for _, r := range d.Roles {
		if managerRoles[r] {
			return true
		}
	}
	return false
}

func canPayout(d auth.Domain) bool {
	for _, r := range d.Roles {
		if payoutRoles[r] {
			return true
		}
	}
	return false
}

// —— 记录列表 ——
func (h *Handler) ListRecords(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	var kw *string
	if v := optQuery(c, "keyword"); v != nil {
		w := "%" + *v + "%"
		kw = &w
	}
	// ABAC：非管理强制本人；管理可用查询里的 staff_user_id（可空=全部）。
	staff := optInt64(c, "staff_user_id")
	if !isManager(d) {
		uid := d.UserID
		staff = &uid
	}
	p := mstore.ListRecordsParams{
		TenantID: d.TenantID, SchemeID: optInt64(c, "scheme_id"), Period: optQuery(c, "period"),
		DeptID: optInt64(c, "dept_id"), StaffUserID: staff, Status: optQuery(c, "status"),
		Keyword: kw, Offset: offset, Limit: limit,
	}
	rows, err := h.q.ListRecords(c, p)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	cp := mstore.CountRecordsParams{
		TenantID: d.TenantID, SchemeID: optInt64(c, "scheme_id"), Period: optQuery(c, "period"),
		DeptID: optInt64(c, "dept_id"), StaffUserID: staff, Status: optQuery(c, "status"), Keyword: kw,
	}
	total, _ := h.q.CountRecords(c, cp)
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIRecord(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// readRecordForABAC：取记录 + 判存在 + 判越权。ok=false 时已写响应。
func (h *Handler) readRecordForABAC(c *gin.Context, id int64, mgrOnly bool) (mstore.Record, bool) {
	d := auth.DomainFrom(c)
	rec, err := h.q.GetRecord(c, mstore.GetRecordParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "记录不存在")
		return mstore.Record{}, false
	}
	if mgrOnly {
		if !isManager(d) {
			httpx.WriteErr(c, 403, 40301, "无权限：需管理角色")
			return mstore.Record{}, false
		}
		return rec, true
	}
	if !isManager(d) && rec.StaffUserID != d.UserID {
		httpx.WriteErr(c, 403, 40301, "越权：只能访问本人记录")
		return mstore.Record{}, false
	}
	return rec, true
}

func (h *Handler) GetRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	rec, ok := h.readRecordForABAC(c, id, false)
	if !ok {
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) GetRecordDetail(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	rec, ok := h.readRecordForABAC(c, id, false)
	if !ok {
		return
	}
	items, _ := h.q.ListItems(c, rec.ID)
	httpx.WriteOK(c, ToAPIRecordDetail(rec, items))
}

func (h *Handler) ConfirmRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if _, ok := h.readRecordForABAC(c, id, false); !ok {
		return
	}
	rec, err := h.q.ConfirmRecord(c, mstore.ConfirmRecordParams{ID: id, TenantID: d.TenantID, ConfirmedBy: d.UserID})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 CALCULATED 可确认）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) AppealRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	var body struct {
		Reason string `json:"reason" binding:"required"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if _, ok := h.readRecordForABAC(c, id, false); !ok {
		return
	}
	reason := body.Reason
	rec, err := h.q.AppealRecord(c, mstore.AppealRecordParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID, AppealReason: &reason})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 CALCULATED/CONFIRMED 可申诉）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) ApproveRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if _, ok := h.readRecordForABAC(c, id, true); !ok { // mgrOnly
		return
	}
	rec, err := h.q.ApproveRecord(c, mstore.ApproveRecordParams{ID: id, TenantID: d.TenantID, ApproveBy: d.UserID})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 CONFIRMED 可审批）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) VoidRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	var body struct {
		Reason *string `json:"reason"`
	}
	_ = c.ShouldBindJSON(&body) // void body 可选
	if _, ok := h.readRecordForABAC(c, id, true); !ok {
		return
	}
	rec, err := h.q.VoidRecord(c, mstore.VoidRecordParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID, VoidReason: body.Reason})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（已发放记录不可作废）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

// —— 发放单 ——
func (h *Handler) ListPayouts(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	payee := optInt64(c, "payee_user_id")
	if !canPayout(d) {
		uid := d.UserID
		payee = &uid
	}
	rows, err := h.q.ListPayouts(c, mstore.ListPayoutsParams{
		TenantID: d.TenantID, Period: optQuery(c, "period"), Status: optQuery(c, "status"),
		PayeeUserID: payee, Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountPayouts(c, mstore.CountPayoutsParams{
		TenantID: d.TenantID, Period: optQuery(c, "period"), Status: optQuery(c, "status"), PayeeUserID: payee,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIPayout(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetPayout：读单张发放单。非发放角色只能看本人（payee_user_id=本人）。
func (h *Handler) GetPayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	p, err := h.q.GetPayout(c, mstore.GetPayoutParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "发放单不存在")
		return
	}
	if !canPayout(d) && p.PayeeUserID != d.UserID {
		httpx.WriteErr(c, 403, 40301, "越权：只能访问本人发放单")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) CreatePayout(c *gin.Context) {
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限：需发放权限角色")
		return
	}
	var b struct {
		RecordID   int64  `json:"record_id" binding:"required"`
		Amount     string `json:"amount" binding:"required"`
		PayChannel *string `json:"pay_channel"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	rec, err := h.q.GetRecord(c, mstore.GetRecordParams{ID: b.RecordID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "记录不存在")
		return
	}
	if rec.Status != "APPROVED" {
		httpx.WriteErr(c, 409, 40901, "仅 APPROVED 记录可发起发放")
		return
	}
	p, err := h.q.CreatePayout(c, mstore.CreatePayoutParams{
		TenantID: d.TenantID, CreatorID: d.UserID, RecordID: rec.ID, PayeeUserID: rec.StaffUserID,
		Amount: numeric(strPtr(b.Amount)), Period: strPtr(rec.Period), PayChannel: b.PayChannel, SecurityLevel: nil,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建发放单失败")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) ApprovePayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限")
		return
	}
	p, err := h.q.ApprovePayout(c, mstore.ApprovePayoutParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 DRAFT/APPROVING 可审批）")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) PayPayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限")
		return
	}
	var body struct {
		VoucherCode *string `json:"voucher_code"`
	}
	_ = c.ShouldBindJSON(&body)
	p, err := h.q.PayPayout(c, mstore.PayPayoutParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID, VoucherCode: body.VoucherCode})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 APPROVED 可发放）")
		return
	}
	// 联动记录 → PAID（尽力而为，态不符忽略）。
	_, _ = h.q.MarkRecordPaid(c, mstore.MarkRecordPaidParams{ID: p.RecordID, TenantID: d.TenantID})
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) RejectPayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限")
		return
	}
	var body struct {
		Reason *string `json:"reason"`
	}
	_ = c.ShouldBindJSON(&body)
	p, err := h.q.RejectPayout(c, mstore.RejectPayoutParams{ID: id, TenantID: d.TenantID, ModifierID: d.UserID, RejectReason: body.Reason})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 DRAFT/APPROVING 可驳回）")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

// —— 个人视图 / 排行 ——
func (h *Handler) MyPerformance(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListMyRecords(c, mstore.ListMyRecordsParams{
		TenantID: d.TenantID, StaffUserID: d.UserID, Period: optQuery(c, "period"),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		items, _ := h.q.ListItems(c, r.ID)
		list = append(list, ToAPIRecordDetail(r, items))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

func (h *Handler) PerfRanking(c *gin.Context) {
	d := auth.DomainFrom(c)
	if !isManager(d) {
		httpx.WriteErr(c, 403, 40301, "无权限：排行仅管理角色可见")
		return
	}
	schemeID := optInt64(c, "scheme_id")
	period := optQuery(c, "period")
	if schemeID == nil || period == nil {
		httpx.WriteErr(c, 400, 40001, "缺少 scheme_id / period")
		return
	}
	top := int32(20)
	if v := c.Query("top"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			if n > 500 {
				n = 500
			}
			top = int32(n)
		}
	}
	rows, err := h.q.RankedRecords(c, mstore.RankedRecordsParams{
		TenantID: d.TenantID, SchemeID: *schemeID, Period: *period, Limit: top,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIRank(r))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}
```

> **执行时以 sqlc 生成物为准逐条核对（不符即改 records.go / M-5 查询）**：因 M-5 实体查询统一 `SELECT *`/`RETURNING *`，`ListRecords`/`GetRecord`/各记录迁移返回 `mstore.Record`、`ListItems` 返回 `[]mstore.RecordItem`、`ListPayouts`/`GetPayout`/payout 迁移返回 `mstore.Payout`——**无 per-query Row 结构、无 `.Model(row)` 转换**；仅 `RankedRecords` 出 `[]mstore.RankedRecordsRow`（含 `rn`）。逐项：
> ① 记录迁移 Params 字段名：`ConfirmRecordParams.ConfirmedBy`、`AppealRecordParams.{ModifierID,AppealReason}`、`ApproveRecordParams.ApproveBy`（$3 在 SQL 首现于 `approve_by`）、`VoidRecordParams.{ModifierID,VoidReason}` 均取自占位符首次出现列名——若 sqlc 用了别的（如统一 `ModifierID`），按生成物回填，语义=操作人/理由。
> ② `ListRecordsParams.Offset/Limit` 顺序/命名：查询 `LIMIT $9 OFFSET $8`，sqlc 一般生成 `Offset`(=$8) 在前、`Limit`(=$9) 在后，类型 `int32`（P 用 `@limit_/@offset_` rename；若本块未配 rename 且报 `Limit` 名不对，去 M-4 sqlc.yaml 该块补 `rename` 再重跑 sqlc）。
> ③ `CreatePayoutParams.Amount pgtype.Numeric`（`$5::numeric`）、`Period *string`、`PayChannel *string`、`SecurityLevel *string`——`numeric(strPtr(b.Amount))` 产 `pgtype.Numeric`。`ListPayoutsParams`/`CountPayoutsParams` 可空位为指针。
> ④ `RankedRecordsParams.Limit` 类型可能是 `int32`（`LIMIT $4`）；`RankedRecordsRow` 的 `rn` 生成列名可能是 `Rn`/`RowNumber`——已在 M-8 mapper 用 `r.Rn`，若不同回改 mapper。
> ⑤ `PayPayout`/`ApprovePayout`/`RejectPayout` `RETURNING *` → 返回 `mstore.Payout` model，`p.RecordID` 直接可用；`MarkRecordPaidParams.{ID,TenantID}`。
> ⑥ 越权/无权限用业务码 `40301`（对齐契约 Forbidden + httpx WriteErr(403,...)）；不存在 `40401`；态机不符 `40901`。

- [ ] **步骤 2：编译**

运行：`go build ./internal/modules/performance/`
预期：成功（`strconv`/`mstore`/`auth`/`httpx`/`gin` 均被使用；`managerRoles`/`payoutRoles`/`isManager`/`canPayout`/各 handler 方法齐）。

> 若 `ListItems` 返回切片名/元素类型与 `ToAPIRecordDetail(r []mstore.RecordItem)` 不符，按生成物调 mapper 或此处。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/performance/records.go
git commit -m "feat(M): 绩效记录/发放/个人视图 handler（ABAC+双状态机）"
```

### 任务 M-12：M routes

**文件：**
- 创建：`backend-go/internal/modules/performance/routes.go`

- [ ] **步骤 1：写注册**（gin v1.10 `gin.IRoutes` 无 `Group()`，相对路径注册；方案/记录/发放主键段统一 `:id`，因子段 `:factorId`。静态子段 `schemes/records/payouts/me/ranking` 与 `:id` 同层共存，方法一致即不冲突）

```go
package performance

import "github.com/gin-gonic/gin"

// Register 把 M 竖切挂到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 分层：/perf/schemes[/:id][/activate|/calculate|/factors[/:factorId]]
//
//	/perf/records[/:id][/detail|/confirm|/appeal|/approve|/void]
//	/perf/payouts[/:id][/approve|/pay|/reject]
//	/perf/me  /perf/ranking
func Register(r gin.IRoutes, h *Handler) {
	// 方案
	r.GET("/perf/schemes", h.ListSchemes)
	r.POST("/perf/schemes", h.CreateScheme)
	r.GET("/perf/schemes/:id", h.GetScheme)
	r.PUT("/perf/schemes/:id", h.UpdateScheme)
	r.DELETE("/perf/schemes/:id", h.DeleteScheme)
	r.POST("/perf/schemes/:id/activate", h.ActivateScheme)
	r.POST("/perf/schemes/:id/calculate", h.CalculatePerformance)
	// 因子（嵌在方案下）
	r.GET("/perf/schemes/:id/factors", h.ListFactors)
	r.POST("/perf/schemes/:id/factors", h.UpsertFactor)
	r.PUT("/perf/schemes/:id/factors/:factorId", h.UpdateFactor)
	r.DELETE("/perf/schemes/:id/factors/:factorId", h.DeleteFactor)
	// 记录
	r.GET("/perf/records", h.ListRecords)
	r.GET("/perf/records/:id", h.GetRecord)
	r.GET("/perf/records/:id/detail", h.GetRecordDetail)
	r.POST("/perf/records/:id/confirm", h.ConfirmRecord)
	r.POST("/perf/records/:id/appeal", h.AppealRecord)
	r.POST("/perf/records/:id/approve", h.ApproveRecord)
	r.POST("/perf/records/:id/void", h.VoidRecord)
	// 发放
	r.GET("/perf/payouts", h.ListPayouts)
	r.POST("/perf/payouts", h.CreatePayout)
	r.GET("/perf/payouts/:id", h.GetPayout)
	r.POST("/perf/payouts/:id/approve", h.ApprovePayout)
	r.POST("/perf/payouts/:id/pay", h.PayPayout)
	r.POST("/perf/payouts/:id/reject", h.RejectPayout)
	// 个人视图 / 排行
	r.GET("/perf/me", h.MyPerformance)
	r.GET("/perf/ranking", h.PerfRanking)
}
```

> `GetPayout` handler 已在 M-11 `records.go` 定义（非发放角色只看本人）。`/perf/me`、`/perf/ranking` 是单段静态，与 `/perf/schemes|records|payouts` 不冲突。所有 handler 名与 M-9/M-10/M-11 定义逐一对应：`ListSchemes/CreateScheme/GetScheme/UpdateScheme/DeleteScheme/ActivateScheme`、`ListFactors/UpsertFactor/UpdateFactor/DeleteFactor`、`CalculatePerformance`、`ListRecords/GetRecord/GetRecordDetail/ConfirmRecord/AppealRecord/ApproveRecord/VoidRecord`、`ListPayouts/GetPayout/CreatePayout/ApprovePayout/PayPayout/RejectPayout`、`MyPerformance/PerfRanking`。

- [ ] **步骤 2：编译**

运行：`go build ./internal/modules/performance/`
预期：成功（handler+records+calculate+mapper+routes 一起编译）。`routes.go` 里每个 `h.Xxx` 都能在 handler.go/records.go/calculate.go 找到对应方法；若报某方法 undefined，说明 M-9/M-10/M-11 漏写该 handler，按路由表补齐。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/performance/routes.go backend-go/internal/modules/performance/records.go
git commit -m "feat(M): 绩效评价路由注册（方案/因子/记录/发放/me/ranking）"
```

---

### 任务 M-13：router 装配 M

**文件：**
- 修改：`backend-go/internal/router.go`（import 块 + `if d.Pool != nil` 块）

- [ ] **步骤 1：加 import**

在 import 块内加：`"github.com/eplugger/ark/internal/modules/performance"`（与既有 `p`、`sysadmin`、`activity` 并列）。

- [ ] **步骤 2：注册**

把 `if d.Pool != nil { ... }` 内改为（在 V 之后追加 M 一行）：

```go
	if d.Pool != nil {
		p.Register(api, p.NewHandler(d.Pool))
		sysadmin.Register(api, sysadmin.NewHandler(d.Pool, d.Enforcer))
		activity.Register(api, activity.NewHandler(d.Pool))
		performance.Register(api, performance.NewHandler(d.Pool))
	}
```

- [ ] **步骤 3：编译 + 全量路由回归**

运行：`go build ./... && go test ./internal/ -run TestBuild -v`
预期：`TestBuild_*` 全 PASS。至此 `/perf/*` 走真实 handler（Pool 存在时）；无 Pool 的 dev/test 二进制仍由 `oapi.Passthrough` 的 `NoRoute` 兜底，不 404。

- [ ] **步骤 4：Commit**

```bash
git add backend-go/internal/router.go
git commit -m "feat(M): router 在 Pool!=nil 时注册绩效评价竖切"
```

### 任务 M-14：Casbin 绩效评价域策略 + 鉴权矩阵 + 能力覆盖

**文件：**
- 修改：`backend-go/internal/platform/auth/policy.csv`（在 V 段之后、`# ---- 每个已认证角色都能读自身身份/能力 ----` 段之前追加 M 段）
- 修改：`backend-go/internal/platform/auth/policy_test.go`（`cases` 表内追加 M 断言行）
- 测试：`backend-go/internal/platform/auth/caps_perf_test.go`（新建）

> keyMatch2 里 `*`→`.*`（跨段），故 `p, R-MANAGER, /api/v1/perf/*, GET` 一条即覆盖 `/perf/schemes`、`/perf/schemes/1/calculate`、`/perf/records/1/detail`、`/perf/me`、`/perf/ranking`、`/perf/payouts/1/pay`。`R-ADMIN` 由既有全局 `/api/v1/*` 四条覆盖、`R-AUDITOR` 只读由全局 `/api/v1/*, GET` 覆盖，均**不**在 M 段重复。传输层只做粗粒度 RBAC：谁能碰哪段子路径；跨人/跨租户的细粒度由 M-11 handler 的 ABAC（`isManager`/`canPayout`/`readRecordForABAC`/强制 `staff_user_id`·`payee_user_id`）兜底。故即便给 R-STAFF 放行 `GET /perf/*`，读他人记录/ranking 仍被 handler 挡为 40301。按动作收敛写权限：方案/因子增删改、activate、calculate 只给 R-MANAGER(+ADMIN)；record approve/void 给 R-MANAGER+R-LEADER；record confirm/appeal 给 R-STAFF（+MANAGER/ADMIN）；payout 建单与 approve/pay/reject 给 R-FINANCE(+MANAGER/ADMIN)。

- [ ] **步骤 1：追加 M 段到 `policy.csv`**

```csv
# ---- 科研绩效评价域（M）：主管全权、领导审批结果、研究员读写自身、财务发放 ----
# （R-ADMIN 全局读写、R-AUDITOR 全局只读已由上方通用规则覆盖，此处不重复）
# 主管：本域全量读写（方案/因子/calculate/activate/记录审批作废/发放/排行）
p, R-MANAGER, /api/v1/perf/*, GET
p, R-MANAGER, /api/v1/perf/*, POST
p, R-MANAGER, /api/v1/perf/*, PUT
p, R-MANAGER, /api/v1/perf/*, DELETE
# 领导：读 + 记录审批/作废（结果裁定，不建方案/不触发计算）
p, R-LEADER,  /api/v1/perf/*, GET
p, R-LEADER,  /api/v1/perf/records/*/approve, POST
p, R-LEADER,  /api/v1/perf/records/*/void,    POST
# 研究员：读本域（数据经 handler 收敛到本人/本租户）+ 确认/申诉本人记录
p, R-STAFF,   /api/v1/perf/*, GET
p, R-STAFF,   /api/v1/perf/records/*/confirm, POST
p, R-STAFF,   /api/v1/perf/records/*/appeal,   POST
# 财务：读记录/发放 + 建发放单 + approve/pay/reject
p, R-FINANCE, /api/v1/perf/*, GET
p, R-FINANCE, /api/v1/perf/payouts,           POST
p, R-FINANCE, /api/v1/perf/payouts/*/approve, POST
p, R-FINANCE, /api/v1/perf/payouts/*/pay,     POST
p, R-FINANCE, /api/v1/perf/payouts/*/reject,  POST
```

- [ ] **步骤 2：扩鉴权矩阵用例**

在 `policy_test.go` 的 `cases := []c{ ... }` 内，`// —— 未知角色：一律拒 ——` 之前追加：

```go
		// —— 绩效评价域 M：按动作收敛 ——
		{"R-MANAGER", "/api/v1/perf/schemes",              "POST", true},  // 建方案
		{"R-MANAGER", "/api/v1/perf/schemes/1/calculate",  "POST", true},  // 触发计算
		{"R-MANAGER", "/api/v1/perf/records/1/approve",    "POST", true},  // 审批记录
		{"R-STAFF",   "/api/v1/perf/me",                   "GET", true},   // 个人视图
		{"R-STAFF",   "/api/v1/perf/schemes",              "GET", true},   // 读方案
		{"R-STAFF",   "/api/v1/perf/schemes",              "POST", false}, // 越权建方案→拒
		{"R-STAFF",   "/api/v1/perf/schemes/1/calculate",  "POST", false}, // 越权计算→拒
		{"R-STAFF",   "/api/v1/perf/records/1/confirm",    "POST", true},  // 确认本人记录
		{"R-STAFF",   "/api/v1/perf/records/1/appeal",     "POST", true},  // 申诉
		{"R-STAFF",   "/api/v1/perf/records/1/approve",    "POST", false}, // 越权审批→拒
		{"R-LEADER",  "/api/v1/perf/records/1/approve",    "POST", true},  // 领导审批
		{"R-LEADER",  "/api/v1/perf/records/1/void",       "POST", true},  // 领导作废
		{"R-LEADER",  "/api/v1/perf/schemes/1/calculate",  "POST", false}, // 领导无 calculate
		{"R-FINANCE", "/api/v1/perf/payouts",              "POST", true},  // 建发放单
		{"R-FINANCE", "/api/v1/perf/payouts/1/pay",        "POST", true},  // 打款
		{"R-FINANCE", "/api/v1/perf/payouts/1/reject",     "POST", true},  // 驳回
		{"R-FINANCE", "/api/v1/perf/records/1/approve",    "POST", false}, // 财务无记录审批
		{"R-FINANCE", "/api/v1/perf/schemes/1",            "DELETE", false}, // 财务无方案删除
		{"R-AUDITOR", "/api/v1/perf/records",              "GET", true},   // 审计只读（全局 GET 覆盖）
		{"R-AUDITOR", "/api/v1/perf/payouts/1",            "POST", false}, // 审计无写
		{"R-ADMIN",   "/api/v1/perf/schemes",              "POST", true},  // 超管全局兜底
```

- [ ] **步骤 3：运行矩阵测试**

运行：`go test ./internal/platform/auth/ -run TestAuthMatrix_TransportLayer -v`
预期：PASS。若某 false/true 不符，回步骤 1 校正子路径（尤其 `*` 跨段与 `records/*/approve` vs `payouts` 裸路径）。

- [ ] **步骤 4：写能力覆盖测试 `caps_perf_test.go`**

```go
package auth

import (
	"os"
	"strings"
	"testing"

	"github.com/casbin/casbin/v2"
)

// perfEnf 载入 model+policy（与 caps_test.go 同源路径解析）。
func perfEnf(t *testing.T) *casbin.Enforcer {
	t.Helper()
	model := os.Getenv("ARK_AUTH_MODEL_PATH")
	if model == "" {
		model = "./model.conf"
	}
	pol := os.Getenv("ARK_AUTH_POLICY_PATH")
	if pol == "" {
		pol = "./policy.csv"
	}
	enf, err := NewEnforcer(model, pol)
	if err != nil {
		t.Fatal(err)
	}
	return enf
}

func hasCapSuffix(caps []string, suffix string) bool {
	for _, c := range caps {
		if strings.HasSuffix(c, suffix) {
			return true
		}
	}
	return false
}

// R-STAFF：有 confirm/appeal，无 calculate/approve/void/payout 写。
func TestBuildCaps_PerfStaffCaps(t *testing.T) {
	caps := BuildCaps(perfEnf(t), []string{"R-STAFF"})
	if !hasCapSuffix(caps, "/api/v1/perf/records/*/confirm POST") {
		t.Errorf("R-STAFF 应有 confirm 能力: %v", caps)
	}
	if !hasCapSuffix(caps, "/api/v1/perf/records/*/appeal POST") {
		t.Errorf("R-STAFF 应有 appeal 能力: %v", caps)
	}
	for _, bad := range []string{
		"/api/v1/perf/schemes/*/calculate POST",
		"/api/v1/perf/records/*/approve POST",
		"/api/v1/perf/payouts/*/pay POST",
	} {
		if hasCapSuffix(caps, bad) {
			t.Errorf("R-STAFF 不应有 %q 能力", bad)
		}
	}
}

// R-FINANCE：有 payouts 建单/pay/reject，无 records approve、无 schemes POST。
func TestBuildCaps_PerfFinanceCaps(t *testing.T) {
	caps := BuildCaps(perfEnf(t), []string{"R-FINANCE"})
	if !hasCapSuffix(caps, "/api/v1/perf/payouts/*/pay POST") {
		t.Errorf("R-FINANCE 应有 pay 能力: %v", caps)
	}
	if hasCapSuffix(caps, "/api/v1/perf/records/*/approve POST") {
		t.Errorf("R-FINANCE 不应有 record approve 能力")
	}
	if hasCapSuffix(caps, "/api/v1/perf/schemes POST") {
		t.Errorf("R-FINANCE 不应有建方案能力")
	}
}

// R-MANAGER：域内全量（POST/DELETE 通配即覆盖 calculate/approve/payouts pay 等）。
func TestBuildCaps_PerfManagerCaps(t *testing.T) {
	caps := BuildCaps(perfEnf(t), []string{"R-MANAGER"})
	for _, want := range []string{
		"/api/v1/perf/* POST",
		"/api/v1/perf/* DELETE",
	} {
		if !hasCapSuffix(caps, want) {
			t.Errorf("R-MANAGER 应有 %q 能力: %v", want, caps)
		}
	}
}
```

> `NewEnforcer` 返回 `*casbin.Enforcer`（`casbin "github.com/casbin/casbin/v2"`，已 import）。`BuildCaps` 每项 = `"<obj模板> <METHOD大写>"`（无角色前缀，见 `caps.go`），故 `hasCapSuffix` 用完整后缀串匹配；`R-MANAGER` 因 policy 用通配 `/api/v1/perf/*`，能力串即 `/api/v1/perf/* POST` 等，无需逐端点断言。若既有 `caps_v_test.go`（V-13）已定义同名 `hasCapSuffix` 助手，本文件复用之、勿重复声明（同包）。

- [ ] **步骤 5：运行能力测试**

运行：`go test ./internal/platform/auth/ -run TestBuildCaps -v`
预期：新增 3 个 Perf 测试 + V/U 既有测试全 PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/platform/auth/policy.csv backend-go/internal/platform/auth/policy_test.go backend-go/internal/platform/auth/caps_perf_test.go
git commit -m "feat(M): Casbin 绩效评价域策略（按动作收敛）+ 鉴权矩阵/能力覆盖测试"
```

### 任务 M-15：M 契约形状 + DB 门控集成测试 + seed

**文件：**
- 测试：`backend-go/internal/modules/performance/contract_test.go`（新建，无 DB 常跑）
- 测试：`backend-go/internal/modules/performance/handler_test.go`（新建，`ARK_TEST_DATABASE_URL` 门控）
- 数据：`backend-go/testdata/seed_m.sql`（新建，calculate 端到端可预期 total_score）

> 与 P/U/V 同构：`contract_test.go` 断言响应形状（字段齐、类型符）；`handler_test.go` 走完整 handler 链，`ARK_TEST_DATABASE_URL` 未设则 `t.Skip`。`injectDomain` 同 V：塞 `CtxTenantID`+`CtxUserID`+`CtxRoles`（记录/发放 handler 读 `d.UserID`、`d.Roles`）。

- [ ] **步骤 1：写 `contract_test.go`**

```go
package performance

import (
	"testing"
	"time"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/jackc/pgx/v5/pgtype"
)

func numLit(s string) pgtype.Numeric {
	var n pgtype.Numeric
	_ = n.Scan(s)
	return n
}

func TestToAPIFactorShape(t *testing.T) {
	f := mstore.SchemeFactor{
		ID: 1, SchemeID: 10, FactorCode: "PAPER_COUNT", FactorName: strPtr("论文数"),
		Weight: numLit("40.00"), MaxScore: numLit("100.00"), DataSource: "R_OUTPUT",
		ScoringRule: []byte(`{"method":"COUNT","unit":2}`), ClauseRef: nil, SortNo: 1,
	}
	out := ToAPIFactor(f)
	if out["weight"] != "40.00" {
		t.Fatalf("weight 应格式化 40.00，得 %v", out["weight"])
	}
	if out["max_score"] != "100.00" {
		t.Fatalf("max_score 应 100.00，得 %v", out["max_score"])
	}
	rule, ok := out["scoring_rule"].(map[string]any)
	if !ok || rule["method"] != "COUNT" {
		t.Fatalf("scoring_rule 应解为对象且 method=COUNT，得 %#v", out["scoring_rule"])
	}
	if out["factor_name"] != "论文数" {
		t.Fatalf("factor_name 应解引用，得 %v", out["factor_name"])
	}
}

func TestToAPIFactorMaxScoreNull(t *testing.T) {
	f := mstore.SchemeFactor{ID: 2, FactorCode: "X", Weight: numLit("10.00"), MaxScore: pgtype.Numeric{Valid: false}}
	out := ToAPIFactor(f)
	if v, ok := out["max_score"]; !ok || v != nil {
		t.Fatalf("无效 MaxScore → nil，得 %#v", out["max_score"])
	}
}

func TestToAPIRecordShape(t *testing.T) {
	rec := mstore.Record{
		ID: 5, SchemeID: 10, StaffUserID: 100, Period: "2026",
		TotalScore: numLit("88.50"), Status: "CALCULATED",
		CalcAt: &time.Time{}, Rank: nil,
	}
	out := ToAPIRecord(rec)
	if out["total_score"] != "88.50" {
		t.Fatalf("total_score 应 88.50，得 %v", out["total_score"])
	}
	if out["staff_name"] != nil || out["scheme_name"] != nil {
		t.Fatalf("无 join 字段应为 nil")
	}
	if out["status"] != "CALCULATED" {
		t.Fatalf("status 透传错，得 %v", out["status"])
	}
}

func TestToAPIPayoutShape(t *testing.T) {
	p := mstore.Payout{ID: 1, RecordID: 5, PayeeUserID: 100, Amount: numLit("12000.00"), Status: "DRAFT"}
	out := ToAPIPayout(p)
	if out["amount"] != "12000.00" {
		t.Fatalf("amount 应 12000.00，得 %v", out["amount"])
	}
}

func TestToAPIRankShape(t *testing.T) {
	r := mstore.RankedRecordsRow{ID: 5, StaffUserID: 100, TotalScore: numLit("90.00"), Rn: 1}
	out := ToAPIRank(r)
	if out["rank"] != int64(1) {
		t.Fatalf("rank=rn=1，得 %v", out["rank"])
	}
	if out["total_score"] != "90.00" {
		t.Fatalf("total_score 应 90.00，得 %v", out["total_score"])
	}
}
```

> `numLit("40.00")` 用 `pgtype.Numeric.Scan(string)` 造值（与 `numeric`/`pgnum` 同源）。字段名以 sqlc 生成物为准：`SchemeFactor.{ID,SchemeID,FactorCode,FactorName *string,Weight,MaxScore pgtype.Numeric,DataSource string,ScoringRule []byte,ClauseRef *string,SortNo int32}`、`Record.{ID,SchemeID,StaffUserID int64,Period string,TotalScore pgtype.Numeric,Rank *int32,Status string,CalcAt *time.Time}`、`Payout.{ID,RecordID,PayeeUserID int64,Amount pgtype.Numeric,Status string}`、`RankedRecordsRow{model 全列, Rn int64}`。若某字段名/类型不符（如 `Rank *int32` vs `Rank int32`），按生成物调整结构体字面量——本测只为钉契约字符串格式化，逻辑不符即改 mapper 而非真库。

- [ ] **步骤 2：Commit（契约测试）**

```bash
git add backend-go/internal/modules/performance/contract_test.go
git commit -m "test(M): mapper 数值/形状契约单测（SELECT *→pgtype.Numeric→string 格式化）"
```

- [ ] **步骤 3：写 `testdata/seed_m.sql`**

> 目标：一个已激活方案 + 覆盖 4 个数据源的因子 + 让某 staff 在 `2026Q3` 各表都有可预期数据，使 `calculate` 得出**手算可得**的 total_score。租户 `tenant_id=1`、creator/PI/作者 `staff=100`（与 handler_test 注入的 UserID 一致）。证据字段仅需 id，故各业务表只插 calculate 路径会读到的列（其余走 DEFAULT / NOT NULL 默认）。**先跑 `000001_init.up.sql` 建表再执行本 seed**。

```sql
-- 方案（YEAR 粒度便于跨表 publish_date/receipt_date 覆盖全年；此处用 2026Q3 计）
INSERT INTO m_scheme (id, code, tenant_id, creator_id, status, security_level,
                      name, period_type, effective_period, version, active)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'PERF-2026-000001', 1, 1, 'ACTIVE', 'INTERNAL',
   '2026 科研绩效方案', 'QUARTER', '2026Q3', 1, TRUE);

-- 因子（4 个数据源 + 4 计分法）
INSERT INTO m_scheme_factor (id, scheme_id, tenant_id, creator_id, factor_code, factor_name,
                             weight, scoring_rule, max_score, data_source, sort_no) OVERRIDING SYSTEM VALUE VALUES
  (1, 1, 1, 1, 'F_OUTPUT', '论文数×2',       40.00, '{"method":"COUNT","unit":2}',        100.00, 'R_OUTPUT',  1),
  (2, 1, 1, 1, 'F_LEVEL',  '项目分类型',      30.00, '{"method":"BY_LEVEL","levelMap":{"NATIONAL":60,"PROVINCIAL":30}}', 100.00, 'E_PROJECT', 2),
  (3, 1, 1, 1, 'F_INCOME', '到账经费',         20.00, '{"method":"BY_AMOUNT","unit":0.001}', 50.00,  'F_INCOME',  3),
  (4, 1, 1, 1, 'F_DEAL',   '转化分档',         10.00, '{"method":"LADDER","ladder":[{"min":0,"max":100000,"score":5},{"min":100000,"max":999999999,"score":10}]}', 10.00, 'T_DEAL', 4);

-- R_OUTPUT：1 篇（publish_date 落 2026Q3，作者含 user_id=100）
INSERT INTO r_output (id, code, tenant_id, creator_id, status, deleted, security_level,
                      output_type, publish_date, authors)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'OUT-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL', 'PAPER', DATE '2026-08-01',
   '[{"user_id":100,"role":"FIRST_AUTHOR"}]'::jsonb);

-- E_PROJECT：1 个省级项目（PI=100, start_date 落 2026Q3, 预算 500000）
INSERT INTO e_project (id, code, tenant_id, creator_id, status, deleted, security_level,
                       project_type, pi_user_id, department_id, start_date, total_budget)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'EPRJ-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL', 'PROVINCIAL', 100, 10,
   DATE '2026-07-15', 500000.00);

-- F_INCOME：到账 200000（挂上面项目，receipt_date 落 2026Q3）
INSERT INTO f_income (id, code, tenant_id, creator_id, status, deleted, security_level,
                      project_id, amount, receipt_date)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'INC-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL',
   1, 200000.00, DATE '2026-09-01');

-- T_DEAL：转化合同 150000（signed_at 落 2026Q3，output_id=1）
INSERT INTO t_deal (id, code, tenant_id, creator_id, status, deleted, security_level,
                    output_id, contract_amount, signed_at)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'DEAL-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL',
   1, 150000.00, TIMESTAMPTZ '2026-08-15T00:00:00Z');

-- 序列对齐（IDENTITY/BIGSERIAL 手工插 id 后须 setval，否则 handler 再插会撞主键）
SELECT setval(pg_get_serial_sequence('r_output','id'),  (SELECT COALESCE(MAX(id),1) FROM r_output));
SELECT setval(pg_get_serial_sequence('e_project','id'), (SELECT COALESCE(MAX(id),1) FROM e_project));
SELECT setval(pg_get_serial_sequence('f_income','id'),  (SELECT COALESCE(MAX(id),1) FROM f_income));
SELECT setval(pg_get_serial_sequence('t_deal','id'),    (SELECT COALESCE(MAX(id),1) FROM t_deal));
SELECT setval(pg_get_serial_sequence('m_scheme','id'),  (SELECT COALESCE(MAX(id),1) FROM m_scheme));
SELECT setval(pg_get_serial_sequence('m_scheme_factor','id'), (SELECT COALESCE(MAX(id),1) FROM m_scheme_factor));
```

> **手算预期 total_score（staff=100, scheme=1, period=2026Q3）**：
> - F_OUTPUT (COUNT unit=2)：1 篇 → raw=2, weighted=2*40/100=0.80
> - F_LEVEL (BY_LEVEL)：PROVINCIAL=1 → raw=1*30=30, weighted=30*30/100=9.00
> - F_INCOME (BY_AMOUNT unit=0.001)：200000*0.001=200，cap 50 → raw=50, weighted=50*20/100=10.00
> - F_DEAL (LADDER)：150000 落第二档 score=10，cap 10 → raw=10, weighted=10*10/100=1.00
> - **total = 0.80+9.00+10.00+1.00 = 20.80**
> 若真实表列名（`authors`/`pi_user_id`/`receipt_date`/`contract_amount`/`signed_at`）或 nullable 与本 seed 有出入（不同 R/F/E/T DDL 演进），按 `design/*.sql` 校正后再插——`calculate` 若返 0/空数组说明取数谓词与实际列名不符。

- [ ] **步骤 4：写 `handler_test.go`（DB 门控）**

```go
package performance

import (
	"bytes"
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func newPerfEngine(t *testing.T, pool *pgxpool.Pool) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	api := r.Group("/api/v1")
	Register(api, NewHandler(pool))
	return r
}

// 注入 domain（同 V 竖切约定：tenant + userID + roles）
func injectPerfDomain(roles []string, userID, tenantID int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Set(auth.CtxTenantID, tenantID)
		c.Set(auth.CtxUserID, userID)
		c.Set(auth.CtxRoles, roles)
		c.Next()
	}
}

// seed 前先清本域表（幂等，便于同库反复跑），再执行 seed_m.sql。
func runSeed(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	for _, trunc := range []string{
		`DELETE FROM m_record_item WHERE tenant_id=1`,
		`DELETE FROM m_payout WHERE tenant_id=1`,
		`DELETE FROM m_record WHERE tenant_id=1`,
		`DELETE FROM m_scheme_factor WHERE tenant_id=1`,
		`DELETE FROM m_scheme WHERE tenant_id=1`,
		`DELETE FROM t_deal WHERE tenant_id=1`,
		`DELETE FROM f_income WHERE tenant_id=1`,
		`DELETE FROM e_project WHERE tenant_id=1`,
		`DELETE FROM r_output WHERE tenant_id=1`,
	} {
		if _, err := pool.Exec(ctx, trunc); err != nil {
			t.Fatalf("清理失败 %q: %v", trunc, err)
		}
	}
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "testdata", "seed_m.sql"))
	if err != nil {
		t.Fatalf("seed 文件读取失败: %v", err)
	}
	if _, err := pool.Exec(ctx, string(b)); err != nil {
		t.Fatalf("seed 执行失败: %v", err)
	}
}

func poolForTest(t *testing.T) (context.Context, *pgxpool.Pool) {
	t.Helper()
	dsn := os.Getenv("ARK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("ARK_TEST_DATABASE_URL 未设置，跳过 DB 集成")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return ctx, pool
}

func TestCalculateEndToEnd(t *testing.T) {
	ctx, pool := poolForTest(t)
	runSeed(t, ctx, pool)

	r := newPerfEngine(t, pool)
	r.Use(injectPerfDomain([]string{"R-MANAGER"}, 1, 1)) // 主管触发

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/perf/schemes/1/calculate",
		bytes.NewBufferString(`{"period":"2026Q3","staff_ids":[100]}`))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("calculate 应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int `json:"code"`
		Data struct {
			Computed int `json:"computed"`
			Inserted int `json:"inserted"`
			Updated  int `json:"updated"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Data.Computed != 1 || env.Data.Inserted != 1 {
		t.Fatalf("应算 1 人/新 1 条，得 %+v", env.Data)
	}

	// 查记录验证 total_score≈20.80（seed 手算值）
	q := mstore.New(pool)
	uid := int64(100)
	lrows, err := q.ListRecords(ctx, mstore.ListRecordsParams{
		TenantID: 1, StaffUserID: &uid, Offset: 0, Limit: 10,
	})
	if err != nil || len(lrows) == 0 {
		t.Fatalf("记录未落库: err=%v rows=%d", err, len(lrows))
	}
	f, err := lrows[0].TotalScore.Float64Value()
	if err != nil || !f.Valid || math.Abs(f.Float64-20.80) > 1e-6 {
		t.Fatalf("total_score 期望 20.80，得 %v (err=%v)", f.Float64, err)
	}

	// 明细应有 4 个因子
	items, _ := q.ListItems(ctx, lrows[0].ID)
	if len(items) != 4 {
		t.Fatalf("应有 4 条因子明细，得 %d", len(items))
	}
}

// TestReadRecordForABAC_StaffCrossUser：R-STAFF(200) 读他人(100)记录应 403
func TestReadRecordForABAC_StaffCrossUser(t *testing.T) {
	ctx, pool := poolForTest(t)
	runSeed(t, ctx, pool)

	// 主管先 calculate 造一条 staff=100 的记录
	rc := newPerfEngine(t, pool)
	rc.Use(injectPerfDomain([]string{"R-MANAGER"}, 1, 1))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/perf/schemes/1/calculate",
		bytes.NewBufferString(`{"period":"2026Q3","staff_ids":[100]}`))
	req.Header.Set("Content-Type", "application/json")
	rc.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("前置 calculate 应 200，得 %d body=%s", w.Code, w.Body.String())
	}

	q := mstore.New(pool)
	uid := int64(100)
	lr, _ := q.ListRecords(ctx, mstore.ListRecordsParams{
		TenantID: 1, StaffUserID: &uid, Offset: 0, Limit: 1,
	})
	if len(lr) == 0 {
		t.Skip("calculate 未落记录")
	}
	recID := strconv.FormatInt(lr[0].ID, 10)

	// 另一 staff=200 的 R-STAFF 请求该记录 → handler ABAC 应 403
	r2 := newPerfEngine(t, pool)
	r2.Use(injectPerfDomain([]string{"R-STAFF"}, 200, 1))
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest("GET", "/api/v1/perf/records/"+recID, nil)
	r2.ServeHTTP(w2, req2)
	if w2.Code != http.StatusForbidden {
		t.Fatalf("跨人读应 403，得 %d body=%s", w2.Code, w2.Body.String())
	}
}
```

> 全用 `context.Background()`（模块 go 1.21.6，无 `t.Context()`）。`poolForTest` 统一取 DSN + skip + `t.Cleanup(pool.Close)`。`TotalScore` 断言用 `Float64Value()` + `math.Abs(...-20.80)<1e-6`（不依赖 `pgtype.Numeric` 内部 `Int`/`Exp` 表示）。`runSeed` 先按外键序删（item→payout→record→factor→scheme→业务表）再跑 seed_m.sql，保证可重复执行。若 `ListRecordsParams`/`GetRecordParams` 的可选字段名与生成物不符（如 `StaffUserID` 实际叫别的名），按 `m_record.sql.go` 回填。

- [ ] **步骤 5：运行**

无 DB：`go test ./internal/modules/performance/ -v` → 契约测试跑、DB 测试 skip。
有 DB（先手动跑 migrate + seed 或用 docker-compose 起 PG 后设 `ARK_TEST_DATABASE_URL`）：`ARK_TEST_DATABASE_URL=postgres://ark:ark@localhost:5432/ark?sslmode=disable go test ./internal/modules/performance/ -v` → 全 PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/modules/performance/handler_test.go backend-go/testdata/seed_m.sql
git commit -m "test(M): calculate 端到端 + ABAC 越权集成测（DB 门控，seed 手算 total=20.80）"
```

---

## 前端（FE）：契约驱动的 V/M 两屏

前端是**契约驱动 SPA**（Vite 4.5 + Vue 3.4 + TS 5.3）。数据流：视图 → `@/api/client`（拼 `/api/v1`）→ dev 下被 `@/api/mock` 拦截 fetch → `@/api/schema`（`?raw` 载入全部 yaml → `routeIndex` 键 `"METHOD /模板路径"` → `matchRoute` 命中）→ 优先取 curated override（`overrides/<view>.ts` 导出 `overrides` 映射，`overrides/index.ts` 用 `import.meta.glob` 自动合并）→ 未命中由 `generator.ts` 现场造数 → 统一 `ApiResponse` 包裹。切真后端只删 `main.ts` 的 `installMock()`。

**按钮门控口径**：`auth.can(want)` 的 `want` 形如 `"<路径> <METHOD>"`，其匹配器（`frontend/src/api/auth.ts` 的 `pathMatch`）只支持**全等**或 **grant 以 `/*`/`*` 结尾的前缀**，**不支持路径中段的 `*`**。故：域级读门控用 `auth.can('/activities GET')`（cap 模板 `/api/v1/activities GET` 能全等命中）；带 `:id`/动作的写门控（如 `submit`/`approve`）用 `auth.hasAnyRole([...])`（与路由 `meta.roles` 同源，稳健），与 `UsersView` 里 `auth.can('/admin/users POST')` 这类**静态路径**才用 can 的既有惯例一致。

---

### 任务 FE-1：契约注册表登记 V/M 模块码

**文件：**
- 修改：`frontend/src/api/schema/index.ts:23-26`（`MODULE_CODES`）

> 前置：任务 V-1、M-1 已把 `13-学术活动管理-V.openapi.yaml`、`14-科研绩效评价-M.openapi.yaml` **逐字节** `cp` 到 `frontend/src/api/schema/`。schema 目录用 `import.meta.glob('./*.yaml')` 自动载入全部 yaml；`moduleCodeFromFile` 用正则 `/(\d{2})-/` 从文件名取前两位作键，若 `MODULE_CODES` 无 `13`/`14`，这两屏所有 `op.module` 会落成 `'?'`（mock 造数与操作统计丢模块归属）。

- [ ] **步骤 1：补两个键**

把 `MODULE_CODES` 从：

```ts
const MODULE_CODES: Record<string, string> = {
  '01': 'P', '02': 'E', '03': 'F', '04': 'R', '05': 'T', '06': 'C',
  '07': 'S', '08': 'D', '09': 'G', '10': 'A', '11': 'X', '12': 'U',
}
```

改为（追加 `13`/`14`）：

```ts
const MODULE_CODES: Record<string, string> = {
  '01': 'P', '02': 'E', '03': 'F', '04': 'R', '05': 'T', '06': 'C',
  '07': 'S', '08': 'D', '09': 'G', '10': 'A', '11': 'X', '12': 'U',
  '13': 'V', '14': 'M',
}
```

- [ ] **步骤 2：确认两份 yaml 已就位**

运行（项目根）：`ls frontend/src/api/schema/13-*.yaml frontend/src/api/schema/14-*.yaml`
预期：两个文件都存在（V-1、M-1 的 `cp` 步骤产物）。若缺，回到 V-1 步骤 2 / M-1 步骤 2 补 `cp`。

- [ ] **步骤 3：类型检查**

运行：`cd frontend && npm run typecheck`
预期：无 TS 错误。（此步仅改常量对象，不引入新类型。）

- [ ] **步骤 4：Commit**

```bash
git add frontend/src/api/schema/index.ts
git commit -m "chore(fe): 契约注册表登记 13→V、14→M 模块码"
```

---

### 任务 FE-2：学术活动屏（V）

**文件：**
- 创建：`frontend/src/views/ActivityView.vue`
- 修改：`frontend/src/router/index.ts:29`（在 `portrait` 路由后、admin 段前插入 `/activity`）
- 修改：`frontend/src/App.vue:61-63`（人员组或新建活动组，加导航项 `v: 'activity'`）
- 创建：`frontend/src/api/mock/overrides/activity.ts`（curated V 数据 + 内存态迁移覆写）

> 契约真源：`design/13-学术活动管理-V.openapi.yaml`（tag `activity`）。视图只发 `/activities...` 相对路径（`client` 自动拼 `/api/v1`）。字段/枚举以契约 `Activity`/`ActivityDetail`/`Participant` 为准：`activity_type∈{CONFERENCE,LECTURE,SEMINAR,TRAINING,OTHER}`、`level∈{INTERNATIONAL,NATIONAL,PROVINCIAL,CAMPUS}`、`host_mode∈{HOST,ATTEND,SPONSOR}`、`status∈{DRAFT,SUBMITTED,DEPT_REVIEW,APPROVED,HELD,ARCHIVED,REJECTED,RETURNED,CANCELLED}`。`budget_amount` 是**字符串**（NUMERIC 承载），用 `@/utils/money` 的 `toWan`/`toNum` 解析。

- [ ] **步骤 1：创建 `ActivityView.vue`**

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toWan } from '@/utils/money'

type ActType = 'CONFERENCE' | 'LECTURE' | 'SEMINAR' | 'TRAINING' | 'OTHER'
type Level = 'INTERNATIONAL' | 'NATIONAL' | 'PROVINCIAL' | 'CAMPUS'
type HostMode = 'HOST' | 'ATTEND' | 'SPONSOR'
type Status =
  | 'DRAFT' | 'SUBMITTED' | 'DEPT_REVIEW' | 'APPROVED'
  | 'HELD' | 'ARCHIVED' | 'REJECTED' | 'RETURNED' | 'CANCELLED'

interface Activity {
  id: number
  code?: string | null
  status: Status
  activity_type: ActType
  level: Level
  host_mode: HostMode
  title: string
  theme?: string | null
  start_at?: string | null
  venue?: string | null
  host_unit?: string | null
  organizer_dept_id?: number | null
  est_attendees?: number | null
  budget_amount?: string | null
}
interface Participant { id: number; user_id?: number | null; guest_name?: string | null; role?: 'SPEAKER' | 'CHAIR' | 'MEMBER' | 'ATTENDEE' | null; report_title?: string | null }
interface Review { id: number; review_level?: number; reviewer_id?: number; action?: 'APPROVE' | 'REJECT' | 'RETURN'; opinion?: string | null; acted_at?: string }
interface ActivityDetail extends Activity { participants?: Participant[]; reviews?: Review[] }

const toast = (m: string) => (window as any).toast?.(m)

// —— 展示映射（中文标签 + 徽章色，色用设计系统既有 tag 变体）——
const TYPE_LABEL: Record<ActType, string> = { CONFERENCE: '学术会议', LECTURE: '讲座报告', SEMINAR: '研讨班', TRAINING: '培训', OTHER: '其他' }
const LEVEL_LABEL: Record<Level, string> = { INTERNATIONAL: '国际', NATIONAL: '国家', PROVINCIAL: '省级', CAMPUS: '校内' }
const MODE_LABEL: Record<HostMode, string> = { HOST: '主办', ATTEND: '参加', SPONSOR: '承办' }
const STATUS_LABEL: Record<Status, string> = { DRAFT: '草稿', SUBMITTED: '已提交', DEPT_REVIEW: '部门评审', APPROVED: '已批准', HELD: '已举办', ARCHIVED: '已归档', REJECTED: '已驳回', RETURNED: '已退回', CANCELLED: '已取消' }
function statusCls(s: Status): string {
  if (s === 'APPROVED' || s === 'ARCHIVED') return 'ok'
  if (s === 'REJECTED' || s === 'CANCELLED') return 'warn'
  if (s === 'SUBMITTED' || s === 'DEPT_REVIEW' || s === 'HELD') return 'info'
  return ''
}
const fmtDate = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—')

// —— 列表 + 筛选 ——
const items = ref<Activity[]>([])
const total = ref(0)
const loading = ref(true)
const busy = ref(false)
const fType = ref<'' | ActType>('')
const fLevel = ref<'' | Level>('')
const fStatus = ref<'' | Status>('')

async function load() {
  loading.value = true
  try {
    const { rows, total: t } = await list<Activity>('/activities', {
      activity_type: fType.value || undefined,
      level: fLevel.value || undefined,
      status: fStatus.value || undefined,
      size: 100,
    })
    items.value = rows ?? []
    total.value = t ?? items.value.length
  } catch (e: any) {
    toast('加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

// —— 统计条（按类型分组）——
const stats = ref<{ key: string; count: number }[]>([])
async function loadStats() {
  try {
    const d = await api.get<{ buckets?: { key: string; count: number }[] }>('/activities/stats', { group_by: 'activity_type' })
    stats.value = d?.buckets ?? []
  } catch { /* 统计失败不阻断主列表 */ }
}
onMounted(loadStats)

// —— 详情抽屉 ——
const detail = ref<ActivityDetail | null>(null)
const drawer = ref(false)
async function openDetail(a: Activity) {
  drawer.value = true
  detail.value = null
  try {
    detail.value = await api.get<ActivityDetail>(`/activities/${a.id}`)
  } catch (e: any) {
    toast('详情加载失败：' + (e?.message || e))
    drawer.value = false
  }
}
function closeDrawer() { drawer.value = false; detail.value = null }

// —— 动作（迁移）：按状态 + 角色显示按钮 ——
// 门控口径：域级读用 auth.can('/activities GET')；带 :id 的动作按角色（与路由 meta.roles 同源）。
const canManage = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER']))
const canStaffAct = computed(() => auth.hasAnyRole(['R-STAFF', 'R-MANAGER']))

async function transition(a: Activity, verb: 'submit' | 'approve' | 'hold' | 'archive' | 'cancel', body?: unknown) {
  if (busy.value) return
  busy.value = true
  try {
    await api.post(`/activities/${a.id}/${verb}`, body ?? {})
    toast(`${TYPE_LABEL[a.activity_type]}「${a.title}」已${VERB_CN[verb]} ✓`)
    await load()
    if (drawer.value && detail.value?.id === a.id) await openDetail(a)
  } catch (e: any) {
    toast('操作失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}
const VERB_CN: Record<string, string> = { submit: '提交', approve: '审批通过', hold: '标记举办', archive: '归档', cancel: '取消' }

async function doApprove(a: Activity, action: 'APPROVE' | 'REJECT' | 'RETURN') {
  await transition(a, 'approve', { review_level: 1, action, opinion: action === 'APPROVE' ? '同意' : '需补充材料' })
}

async function removeActivity(a: Activity) {
  if (busy.value) return
  busy.value = true
  try {
    await api.del(`/activities/${a.id}`)
    toast('已删除草稿')
    await load()
  } catch (e: any) {
    toast('删除失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

// —— 参与人维护（抽屉内）——
const npUserId = ref('')
const npRole = ref<'SPEAKER' | 'CHAIR' | 'MEMBER' | 'ATTENDEE'>('MEMBER')
async function addParticipant() {
  if (!detail.value || !npUserId.value) return toast('请填写参与人用户 ID')
  busy.value = true
  try {
    await api.post(`/activities/${detail.value.id}/participants`, { user_id: Number(npUserId.value), role: npRole.value })
    npUserId.value = ''
    await openDetail(detail.value)
    toast('已添加参与人 ✓')
  } catch (e: any) {
    toast('添加失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}
async function removeParticipant(pid: number) {
  if (!detail.value) return
  busy.value = true
  try {
    await api.del(`/activities/${detail.value.id}/participants/${pid}`)
    await openDetail(detail.value)
    toast('已移除参与人')
  } catch (e: any) {
    toast('移除失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

// 某条记录当前可执行的动作（状态机 × 角色）
function actionsFor(a: Activity): { key: string; label: string; cls: string; run: () => void; show: boolean }[] {
  const st = a.status
  return [
    { key: 'edit', label: '详情', cls: 'ghost', run: () => openDetail(a), show: true },
    { key: 'submit', label: '提交', cls: 'seal', run: () => transition(a, 'submit'), show: st === 'DRAFT' && canStaffAct.value },
    { key: 'approve', label: '批准', cls: 'seal', run: () => doApprove(a, 'APPROVE'), show: (st === 'SUBMITTED' || st === 'DEPT_REVIEW') && canManage.value },
    { key: 'return', label: '退回', cls: 'ghost', run: () => doApprove(a, 'RETURN'), show: (st === 'SUBMITTED' || st === 'DEPT_REVIEW') && canManage.value },
    { key: 'hold', label: '标记已举办', cls: 'ghost', run: () => transition(a, 'hold', { sign_in_count: a.est_attendees ?? 0 }), show: st === 'APPROVED' && canManage.value },
    { key: 'archive', label: '归档', cls: 'ghost', run: () => transition(a, 'archive', { minutes_rich: '（归档纪要）' }), show: st === 'HELD' && canManage.value },
    { key: 'cancel', label: '取消', cls: 'ghost', run: () => transition(a, 'cancel', { cancel_reason: '活动取消' }), show: st !== 'ARCHIVED' && st !== 'CANCELLED' && canManage.value },
    { key: 'del', label: '删除', cls: 'ghost', run: () => removeActivity(a), show: st === 'DRAFT' && canStaffAct.value },
  ].filter((x) => x.show)
}
</script>

<template>
  <section class="view on" id="v-activity">
    <div class="page-head">
      <div>
        <div class="page-title">学术<em>活动</em></div>
        <div class="page-sub">
          会议 / 讲座 / 研讨 / 培训全流程登记 → 审批 → 举办 → 归档 ·
          共 <b style="color:var(--seal)">{{ total }}</b> 条
          <span v-for="s in stats" :key="s.key" class="tag info" style="margin-left:8px">{{ TYPE_LABEL[s.key as ActType] || s.key }} {{ s.count }}</span>
        </div>
      </div>
    </div>

    <div class="filter-row">
      <select class="sel" v-model="fType" @change="load">
        <option value="">全部类型</option>
        <option value="CONFERENCE">学术会议</option><option value="LECTURE">讲座报告</option>
        <option value="SEMINAR">研讨班</option><option value="TRAINING">培训</option><option value="OTHER">其他</option>
      </select>
      <select class="sel" v-model="fLevel" @change="load">
        <option value="">全部级别</option>
        <option value="INTERNATIONAL">国际</option><option value="NATIONAL">国家</option>
        <option value="PROVINCIAL">省级</option><option value="CAMPUS">校内</option>
      </select>
      <select class="sel" v-model="fStatus" @change="load">
        <option value="">全部状态</option>
        <option v-for="(lbl, k) in STATUS_LABEL" :key="k" :value="k">{{ lbl }}</option>
      </select>
      <button class="btn sm ghost" @click="load">↻ 刷新</button>
    </div>

    <div class="grid" style="gap:12px">
      <div v-if="loading" class="card"><div class="card-b" style="padding:28px;text-align:center;color:var(--ink-mute)">正在加载学术活动…</div></div>
      <div v-else-if="!items.length" class="card"><div class="card-b" style="padding:28px;text-align:center;color:var(--ink-mute)">当前筛选下暂无活动。</div></div>

      <div class="act-card" v-for="a in items" :key="a.id">
        <div style="flex:1">
          <div style="font-family:var(--serif);font-weight:700;font-size:14px">{{ a.title }}</div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:5px">
            <span class="tag info">{{ TYPE_LABEL[a.activity_type] }}</span>
            <span class="tag">{{ LEVEL_LABEL[a.level] }}</span>
            <span class="tag">{{ MODE_LABEL[a.host_mode] }}</span>
            <span class="tag" :class="statusCls(a.status)">{{ STATUS_LABEL[a.status] }}</span>
          </div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:6px">
            📅 {{ fmtDate(a.start_at) }} · 📍 {{ a.venue || '—' }} · 👥 {{ a.est_attendees ?? '—' }} 人
            <template v-if="a.budget_amount"> · 预算 {{ toWan(a.budget_amount) }} 万</template>
          </div>
        </div>
        <div class="claim-actions">
          <button v-for="act in actionsFor(a)" :key="act.key" class="btn sm" :class="act.cls" :disabled="busy" @click="act.run">{{ act.label }}</button>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <div class="drawer-mask" v-if="drawer" @click="closeDrawer"></div>
    <aside class="drawer" v-if="drawer">
      <div class="drawer-head">
        <b>{{ detail?.title || '加载中…' }}</b>
        <button class="btn sm ghost" @click="closeDrawer">✕</button>
      </div>
      <div class="drawer-b" v-if="detail">
        <div class="kv"><span>编号</span><b>{{ detail.code || detail.id }}</b></div>
        <div class="kv"><span>类型/级别</span><b>{{ TYPE_LABEL[detail.activity_type] }} · {{ LEVEL_LABEL[detail.level] }}</b></div>
        <div class="kv"><span>起止</span><b>{{ fmtDate(detail.start_at) }} ~ {{ fmtDate(detail.end_at) }}</b></div>
        <div class="kv"><span>场地</span><b>{{ detail.venue || '—' }}</b></div>
        <div class="kv"><span>主办方</span><b>{{ detail.host_unit || '—' }}</b></div>
        <div class="kv"><span>状态</span><b><span class="tag" :class="statusCls(detail.status)">{{ STATUS_LABEL[detail.status] }}</span></b></div>

        <div class="sec-title">参与人（{{ detail.participants?.length ?? 0 }}）</div>
        <div class="plist">
          <div class="pitem" v-for="p in detail.participants" :key="p.id">
            <span>{{ p.guest_name || ('用户#' + p.user_id) }}<em v-if="p.role"> · {{ p.role }}</em></span>
            <button class="btn xs ghost" :disabled="busy" @click="removeParticipant(p.id)">移除</button>
          </div>
        </div>
        <div class="padd">
          <input class="sel" style="flex:1" v-model="npUserId" placeholder="参与人用户 ID" />
          <select class="sel" style="width:110px" v-model="npRole"><option value="SPEAKER">主讲</option><option value="CHAIR">主持</option><option value="MEMBER">成员</option><option value="ATTENDEE">参加</option></select>
          <button class="btn sm seal" :disabled="busy" @click="addParticipant">＋添加</button>
        </div>

        <div class="sec-title">审批轨迹（{{ detail.reviews?.length ?? 0 }}）</div>
        <div class="rlist">
          <div class="ritem" v-for="r in detail.reviews" :key="r.id">
            <b>L{{ r.review_level ?? 1 }} {{ r.action }}</b>
            <span>{{ r.reviewer_id ? '审查人#' + r.reviewer_id : '—' }}{{ r.opinion ? '：' + r.opinion : '' }}</span>
          </div>
          <div v-if="!detail.reviews?.length" style="color:var(--ink-mute);font-size:12px">暂无审批记录</div>
        </div>
      </div>
    </aside>
  </section>
</template>

<style scoped>
.act-card { display:flex; gap:12px; align-items:flex-start; background:var(--card,#fff); border:1px solid var(--line,#e5e0d5); border-radius:10px; padding:14px 16px; }
.claim-actions { display:flex; flex-wrap:wrap; gap:6px; justify-content:flex-end; max-width:280px; }
.btn.xs { font-size:11px; padding:2px 8px; }
.sel { font-size:12px; padding:5px 8px; border:1px solid var(--line,#d8d2c4); border-radius:6px; background:#fff; }
.filter-row { display:flex; gap:10px; align-items:center; margin:8px 0 14px; flex-wrap:wrap; }
.drawer-mask { position:fixed; inset:0; background:rgba(0,0,0,.32); z-index:40; }
.drawer { position:fixed; top:0; right:0; bottom:0; width:420px; max-width:92vw; background:#fff; z-index:41; box-shadow:-8px 0 28px rgba(0,0,0,.16); display:flex; flex-direction:column; }
.drawer-head { display:flex; justify-content:space-between; align-items:center; padding:14px 16px; border-bottom:1px solid var(--line,#eee); }
.drawer-b { padding:14px 16px; overflow:auto; }
.kv { display:flex; justify-content:space-between; font-size:12.5px; padding:5px 0; border-bottom:1px dashed var(--line,#f0ece0); }
.kv span { color:var(--ink-mute); }
.sec-title { font-family:var(--serif); font-weight:700; margin:14px 0 6px; font-size:13px; }
.pitem,.ritem { display:flex; justify-content:space-between; align-items:center; font-size:12px; padding:4px 0; }
.pitem em { color:var(--ink-mute); font-style:normal; }
.padd { display:flex; gap:6px; margin-top:8px; }
.ritem { flex-direction:column; align-items:flex-start; }
.ritem b { color:var(--seal,#b5462f); }
.ritem span { color:var(--ink-mute); }
</style>
```

> 关键约束：`id="v-activity"` 与 router `name: 'activity'`、App.vue 导航 `v: 'activity'` 三者命名 1:1（项目约定：视图 section id 用 `v-<name>` 连字符，导航 `v` 与路由 `name` 用同串）。`toWan` 来自既有 `@/utils/money`，接收字符串金额、返回“万”单位数值（`budget_amount` 是字符串承载的 NUMERIC，勿直接当数字运算）。

- [ ] **步骤 2：注册路由**

在 `frontend/src/router/index.ts` 的 `portrait` 路由（第 29 行）之后、`// —— 模块 U 管理页（新）——` 注释之前，插入一行：

```ts
  { path: '/activity', name: 'activity', meta: { zh: '学术活动', en: 'ACADEMIC ACTIVITIES', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }, component: () => import('@/views/ActivityView.vue') },
```

> `roles` 与后端 V 域鉴权矩阵一致：研究员/主管/领导可操作，审计只读；财务/专家不可达（守卫跳 `/forbidden`）。

- [ ] **步骤 3：侧栏导航**

在 `frontend/src/App.vue` 的 `groups` 数组里，`资 产 · 采 购` 组之后、`人 员` 组之前插入一组（或并入“项目管理”组，按 UI 口味择一，推荐独立组）：

```ts
  { t: '学 术 活 动', items: [
    { v: 'activity', ic: '✪', label: '学术活动管理', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] },
  ]},
```

> `v: 'activity'` 必须与路由 `name` 完全一致（`go(v)` 用 `router.push({ name: v })`，`route.name === item.v` 高亮当前项）。`roles` 与路由 `meta.roles` 同步，保证“菜单可见 = 路由可达”。

- [ ] **步骤 4：curated mock 数据**

创建 `frontend/src/api/mock/overrides/activity.ts`：

```ts
/**
 * Curated overrides —— 学术活动屏（module V）
 * 契约：13-学术活动管理-V.openapi.yaml（tag activity）
 * 键 = `METHOD /模板路径`（mock 用 matchRoute 命中的模板路径查表；带 {id} 的键用函数按 url 解析）。
 * 迁移类（submit/approve/hold/archive/cancel/delete）改写内存 store，使 reload 后状态可见；
 * 注意：override 函数只能拿到 url、拿不到请求体，故 approve 覆写统一置 APPROVED（真后端才区分 action）。
 */

type Status =
  | 'DRAFT' | 'SUBMITTED' | 'DEPT_REVIEW' | 'APPROVED'
  | 'HELD' | 'ARCHIVED' | 'REJECTED' | 'RETURNED' | 'CANCELLED'

interface ActRec {
  id: number; code: string; tenant_id: number; status: Status; security_level: string
  activity_type: string; level: string; host_mode: string; title: string; theme?: string
  start_at?: string; end_at?: string; venue?: string; host_unit?: string
  organizer_dept_id?: number; est_attendees?: number; budget_amount?: string
  creator_id: number; created_at: string; updated_at: string
}

const now = '2026-09-01T08:00:00Z'
const store: ActRec[] = [
  { id: 9001, code: 'ACT-2026-9001', tenant_id: 1, status: 'DRAFT', security_level: 'INTERNAL', activity_type: 'LECTURE', level: 'INTERNATIONAL', host_mode: 'HOST', title: '生成式模型在精密磨抛中的前沿进展', theme: '邀请 IEEE Fellow 做主题报告', start_at: '2026-10-15T01:30:00Z', venue: '行政楼报告厅', host_unit: '启元研究院', organizer_dept_id: 10, est_attendees: 180, budget_amount: '42000.00', creator_id: 100, created_at: now, updated_at: now },
  { id: 9002, code: 'ACT-2026-9002', tenant_id: 1, status: 'SUBMITTED', security_level: 'PUBLIC', activity_type: 'CONFERENCE', level: 'NATIONAL', host_mode: 'ATTEND', title: '中国机械工程学会年会（参会）', start_at: '2026-11-03T00:00:00Z', venue: '合肥', host_unit: '中国机械工程学会', organizer_dept_id: 10, est_attendees: 20, budget_amount: '96000.00', creator_id: 101, created_at: now, updated_at: now },
  { id: 9003, code: 'ACT-2026-9003', tenant_id: 1, status: 'DEPT_REVIEW', security_level: 'INTERNAL', activity_type: 'SEMINAR', level: 'CAMPUS', host_mode: 'HOST', title: '周五学术研讨：力位混合控制专题', start_at: '2026-09-26T07:00:00Z', venue: 'A3-205', host_unit: '智能制造研究室', organizer_dept_id: 11, est_attendees: 35, creator_id: 100, created_at: now, updated_at: now },
  { id: 9004, code: 'ACT-2026-9004', tenant_id: 1, status: 'APPROVED', security_level: 'INTERNAL', activity_type: 'TRAINING', level: 'PROVINCIAL', host_mode: 'SPONSOR', title: '省级科研仪器共享平台使用培训', start_at: '2026-10-08T00:30:00Z', venue: '测试中心', host_unit: '省科技厅', organizer_dept_id: 12, est_attendees: 60, budget_amount: '15000.00', creator_id: 102, created_at: now, updated_at: now },
  { id: 9005, code: 'ACT-2026-9005', tenant_id: 1, status: 'HELD', security_level: 'PUBLIC', activity_type: 'LECTURE', level: 'NATIONAL', host_mode: 'HOST', title: '院士讲坛：高端制造的中国路径', start_at: '2026-08-20T01:00:00Z', venue: '大礼堂', host_unit: '启元研究院', organizer_dept_id: 10, est_attendees: 500, creator_id: 103, created_at: now, updated_at: now },
  { id: 9006, code: 'ACT-2026-9006', tenant_id: 1, status: 'ARCHIVED', security_level: 'PUBLIC', activity_type: 'CONFERENCE', level: 'INTERNATIONAL', host_mode: 'ATTEND', title: 'ICRA 国际机器人大会（已归档）', start_at: '2026-06-01T00:00:00Z', venue: '维也纳', host_unit: 'IEEE RAS', organizer_dept_id: 10, est_attendees: 8, creator_id: 100, created_at: now, updated_at: now },
]

const participants: Record<number, { id: number; user_id?: number; guest_name?: string; role: string; report_title?: string }[]> = {
  9001: [
    { id: 7001, guest_name: 'Prof. Alan Reeves', role: 'SPEAKER', report_title: 'Diffusion priors for surface finishing' },
    { id: 7002, user_id: 100, role: 'CHAIR' },
  ],
  9005: [{ id: 7101, guest_name: '李院士', role: 'SPEAKER', report_title: '高端制造的中国路径' }],
}
let pidSeq = 7900

const reviews: Record<number, { id: number; review_level: number; reviewer_id: number; action: string; opinion?: string; acted_at: string }[]> = {
  9002: [{ id: 8001, review_level: 1, reviewer_id: 200, action: 'APPROVE', opinion: '同意，纳入年度计划', acted_at: now }],
  9003: [{ id: 8002, review_level: 1, reviewer_id: 201, action: 'RETURN', opinion: '请补充预算明细', acted_at: now }],
}
let ridSeq = 8900

function idFrom(url: string): number {
  const m = url.match(/\/activities\/(\d+)/)
  return m ? Number(m[1]) : 0
}
function find(id: number): ActRec | undefined {
  return store.find((a) => a.id === id)
}

export const overrides: Record<string, unknown> = {
  'GET /activities': { list: store, total: store.length, page: 1, size: 100 },

  'GET /activities/{id}': (url: string) => {
    const a = find(idFrom(url))
    const id = idFrom(url)
    return a ? { ...a, participants: participants[id] ?? [], reviews: reviews[id] ?? [] } : null
  },

  'GET /activities/{id}/participants': (url: string) => ({ list: participants[idFrom(url)] ?? [] }),

  'GET /activities/calendar': (url: string) => {
    const month = new URL(url, 'http://x.local').searchParams.get('month') || '2026-10'
    return { month, list: store.filter((a) => (a.start_at || '').startsWith(month)) }
  },

  'GET /activities/stats': (url: string) => {
    const gb = new URL(url, 'http://x.local').searchParams.get('group_by') || 'activity_type'
    const map: Record<string, number> = {}
    for (const a of store) {
      const key = String((a as any)[gb] ?? '未知')
      map[key] = (map[key] || 0) + 1
    }
    return { buckets: Object.entries(map).map(([key, count]) => ({ key, count })) }
  },

  // —— 迁移（改写内存 store；override 拿不到请求体，approve 统一 APPROVE）——
  'POST /activities': (url: string) => {
    const nid = Math.max(...store.map((a) => a.id)) + 1
    const rec: ActRec = { id: nid, code: `ACT-2026-${nid}`, tenant_id: 1, status: 'DRAFT', security_level: 'INTERNAL', activity_type: 'LECTURE', level: 'CAMPUS', host_mode: 'HOST', title: '新建活动（mock）', creator_id: 100, created_at: now, updated_at: now }
    store.push(rec)
    return rec
  },
  'POST /activities/{id}/submit': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'SUBMITTED'; a.updated_at = now } return a ?? null },
  'POST /activities/{id}/approve': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'APPROVED'; (reviews[a.id] ||= []).push({ id: ++ridSeq, review_level: 1, reviewer_id: 200, action: 'APPROVE', opinion: 'mock 通过', acted_at: now }); a.updated_at = now } return a ?? null },
  'POST /activities/{id}/hold': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'HELD'; a.updated_at = now } return a ?? null },
  'POST /activities/{id}/archive': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'ARCHIVED'; a.updated_at = now } return a ?? null },
  'POST /activities/{id}/cancel': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'CANCELLED'; a.updated_at = now } return a ?? null },
  'DELETE /activities/{id}': (url: string) => { const id = idFrom(url); const i = store.findIndex((a) => a.id === id); if (i >= 0) store.splice(i, 1); return { id, deleted: i >= 0 } },

  'POST /activities/{id}/participants': (url: string) => { const id = idFrom(url); const p = { id: ++pidSeq, user_id: 100, role: 'MEMBER' }; (participants[id] ||= []).push(p); return p },
  'DELETE /activities/{id}/participants/{pid}': (url: string) => {
    const id = idFrom(url)
    const pm = url.match(/\/participants\/(\d+)/)
    const pid = pm ? Number(pm[1]) : 0
    const arr = participants[id] || []
    const i = arr.findIndex((p) => p.id === pid)
    if (i >= 0) arr.splice(i, 1)
    return { id: pid, deleted: i >= 0 }
  },
}
```

> 覆写键全部是**模板路径**（`GET /activities/{id}`、`POST /activities/{id}/approve` 等），与 `routeIndex` 键 `${method} ${op.path}` 一致。函数签名 `(url) => data` 被 `resolveOverride` 识别；返回的裸对象会被 `envelope()` 包成 `ApiResponse`。store 是模块级可变数组，reload 视图后状态迁移可见。切真后端（删 `installMock()`）后本文件不参与线上路径。

- [ ] **步骤 5：类型检查 + 构建**

运行：`cd frontend && npm run typecheck && npm run build`
预期：typecheck 无 TS 报错；build 成功产出 `dist/`。若 `toWan`/`money` 路径解析报错，确认 `@/utils/money` 存在（既有 `ClaimView` 同款别名）。

- [ ] **步骤 6：Commit**

```bash
git add frontend/src/views/ActivityView.vue frontend/src/router/index.ts frontend/src/App.vue frontend/src/api/mock/overrides/activity.ts
git commit -m "feat(V): 学术活动前端屏（列表/筛选/状态机动作/参与人抽屉）+ mock curated 数据"
```

---

### 任务 FE-3：绩效评价屏（M）

**文件：**
- 创建：`frontend/src/views/PerformanceView.vue`
- 修改：`frontend/src/router/index.ts:30`（`activity` 路由后插入 `/performance`）
- 修改：`frontend/src/App.vue`（`学 术 活 动` 组内或新组，加导航项 `v: 'performance'`）
- 创建：`frontend/src/api/mock/overrides/performance.ts`

> 契约真源：`design/14-科研绩效评价-M.openapi.yaml`（tag `performance`）。五标签页对应五组端点：
> 方案 `GET/POST /perf/schemes`、`GET/PUT/DELETE /perf/schemes/{id}`、`POST /perf/schemes/{id}/activate`、`GET/POST /perf/schemes/{id}/factors`、`PUT/DELETE /perf/schemes/{id}/factors/{factorId}`、`POST /perf/schemes/{id}/calculate`；
> 记录 `GET /perf/records`、`GET /perf/records/{id}`、`GET /perf/records/{id}/detail`、`POST /perf/records/{id}/confirm|appeal|approve|void`；
> 发放 `GET /perf/payouts`、`POST /perf/payouts`、`GET /perf/payouts/{id}`、`POST /perf/payouts/{id}/approve|pay|reject`；
> 我的 `GET /perf/me`；排行 `GET /perf/ranking?scheme_id&period&top`。
> 枚举：`Scheme.status∈{DRAFT,ACTIVE,SUPERSEDED}`、`period_type∈{YEAR,QUARTER,MONTH}`；`Factor.data_source∈{R_OUTPUT,F_INCOME,E_PROJECT,T_DEAL,MANUAL}`；`Record.status∈{CALCULATED,CONFIRMED,APPROVED,PAID,APPEAL,VOID}`；`Payout.status∈{DRAFT,APPROVING,APPROVED,PAID,REJECTED}`。`weight`/`max_score`/`total_score`/`amount`/`metric_value`/`raw_score`/`weighted_score` 全部是**字符串**（NUMERIC 承载），展示走 `@/utils/money`。

- [ ] **步骤 1：创建 `PerformanceView.vue`**

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

type SchemeStatus = 'DRAFT' | 'ACTIVE' | 'SUPERSEDED'
type RecordStatus = 'CALCULATED' | 'CONFIRMED' | 'APPROVED' | 'PAID' | 'APPEAL' | 'VOID'
type PayoutStatus = 'DRAFT' | 'APPROVING' | 'APPROVED' | 'PAID' | 'REJECTED'
type DataSource = 'R_OUTPUT' | 'F_INCOME' | 'E_PROJECT' | 'T_DEAL' | 'MANUAL'

interface Scheme { id: number; code?: string | null; name: string; period_type: string; effective_period: string; version: number; active: boolean; status: SchemeStatus; scope_dept_id?: number | null; scope_staff_type?: string | null }
interface Factor { id: number; scheme_id: number; factor_code: string; factor_name?: string | null; weight: string; max_score?: string | null; data_source: DataSource; scoring_rule?: unknown; sort_no?: number }
interface SchemeDetail extends Scheme { factors?: Factor[] }
interface RecordItem { id: number; record_id: number; factor_code: string; factor_name?: string | null; metric_value: string; raw_score: string; weighted_score: string; evidence?: unknown[] }
interface PerfRecord { id: number; scheme_id: number; scheme_name?: string | null; staff_user_id: number; staff_name?: string | null; period: string; total_score: string; rank?: number | null; status: RecordStatus }
interface RecordDetail extends PerfRecord { items?: RecordItem[] }
interface Payout { id: number; code?: string | null; record_id: number; payee_user_id: number; payee_name?: string | null; amount: string; period?: string | null; status: PayoutStatus; voucher_code?: string | null }
interface RankItem { rank: number; staff_user_id: number; staff_name?: string | null; total_score: string }

const toast = (m: string) => (window as any).toast?.(m)

const canManage = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER']))
const canApprove = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER']))
const canFinance = computed(() => auth.hasAnyRole(['R-FINANCE', 'R-MANAGER']))
const canStaffAct = computed(() => auth.hasAnyRole(['R-STAFF', 'R-MANAGER']))

const REC_CN: Record<RecordStatus, string> = { CALCULATED: '已计算', CONFIRMED: '已确认', APPROVED: '已批准', PAID: '已发放', APPEAL: '申诉中', VOID: '已作废' }
const PAY_CN: Record<PayoutStatus, string> = { DRAFT: '草稿', APPROVING: '审批中', APPROVED: '已批准', PAID: '已发放', REJECTED: '已驳回' }
const SCHEME_CN: Record<SchemeStatus, string> = { DRAFT: '草稿', ACTIVE: '启用中', SUPERSEDED: '已停用' }
const DS_CN: Record<DataSource, string> = { R_OUTPUT: '成果', F_INCOME: '到账经费', E_PROJECT: '在研项目', T_DEAL: '转化合同', MANUAL: '手工' }
function recCls(s: RecordStatus) { return s === 'APPROVED' || s === 'PAID' ? 'ok' : s === 'VOID' ? 'warn' : s === 'APPEAL' ? 'info' : '' }

const tabs = ['scheme', 'record', 'payout', 'me', 'ranking'] as const
type Tab = typeof tabs[number]
const TAB_CN: Record<Tab, string> = { scheme: '考核方案', record: '考核记录', payout: '绩效发放', me: '我的绩效', ranking: '排行榜' }
const tab = ref<Tab>('scheme')
const busy = ref(false)

// —— 方案 tab ——
const schemes = ref<Scheme[]>([])
const curScheme = ref<SchemeDetail | null>(null)
async function loadSchemes() {
  const { rows } = await list<Scheme>('/perf/schemes', { size: 100 })
  schemes.value = rows ?? []
}
async function selectScheme(id: number) {
  curScheme.value = await api.get<SchemeDetail>(`/perf/schemes/${id}`)
}
async function activate(s: Scheme) {
  busy.value = true
  try { await api.post(`/perf/schemes/${s.id}/activate`); toast('方案已启用 ✓'); await loadSchemes(); if (curScheme.value?.id === s.id) await selectScheme(s.id) }
  catch (e: any) { toast('启用失败：' + (e?.message || e)) } finally { busy.value = false }
}
// 触发计算
const calcPeriod = ref('2026Q3')
async function runCalculate(s: Scheme) {
  busy.value = true
  try {
    const r = await api.post<{ computed?: number; inserted?: number }>(`/perf/schemes/${s.id}/calculate`, { period: calcPeriod.value })
    toast(`计算完成：${r?.computed ?? 0} 人 / 落库 ${r?.inserted ?? 0} 条`)
    await loadRecords()
  } catch (e: any) { toast('计算失败：' + (e?.message || e)) } finally { busy.value = false }
}

// —— 记录 tab ——
const records = ref<PerfRecord[]>([])
const curRecord = ref<RecordDetail | null>(null)
async function loadRecords() {
  const { rows } = await list<PerfRecord>('/perf/records', { size: 100 })
  records.value = rows ?? []
}
async function openRecord(id: number) { curRecord.value = await api.get<RecordDetail>(`/perf/records/${id}/detail`) }
async function recAction(rec: PerfRecord, verb: 'confirm' | 'appeal' | 'approve' | 'void', body?: unknown) {
  busy.value = true
  try { await api.post(`/perf/records/${rec.id}/${verb}`, body ?? {}); toast('操作成功 ✓'); await loadRecords(); if (curRecord.value?.id === rec.id) await openRecord(rec.id) }
  catch (e: any) { toast('失败：' + (e?.message || e)) } finally { busy.value = false }
}

// —— 发放 tab ——
const payouts = ref<Payout[]>([])
async function loadPayouts() { const { rows } = await list<Payout>('/perf/payouts', { size: 100 }); payouts.value = rows ?? [] }
async function createPayout(rec: PerfRecord) {
  busy.value = true
  try { await api.post('/perf/payouts', { record_id: rec.id, amount: rec.total_score }); toast('已生成发放单 ✓'); await loadPayouts() }
  catch (e: any) { toast('生成失败：' + (e?.message || e)) } finally { busy.value = false }
}
async function payoutAction(p: Payout, verb: 'approve' | 'pay' | 'reject') {
  busy.value = true
  try { await api.post(`/perf/payouts/${p.id}/${verb}`, {}); toast('发放单已' + verb + ' ✓'); await loadPayouts() }
  catch (e: any) { toast('失败：' + (e?.message || e)) } finally { busy.value = false }
}

// —— 我的绩效 tab ——
const mine = ref<RecordDetail[]>([])
async function loadMine() {
  const d = await api.get<{ list?: RecordDetail[] }>('/perf/me')
  mine.value = d?.list ?? []
}

// —— 排行 tab ——
const rankSchemeId = ref<number | ''>('')
const rankPeriod = ref('2026Q3')
const ranking = ref<RankItem[]>([])
async function loadRanking() {
  if (!rankSchemeId.value) return toast('请先选择方案')
  const d = await api.get<{ list?: RankItem[] }>('/perf/ranking', { scheme_id: rankSchemeId.value, period: rankPeriod.value, top: 20 })
  ranking.value = d?.list ?? []
}

function switchTab(t: Tab) {
  tab.value = t
  const boot: Partial<Record<Tab, () => Promise<void>>> = { scheme: loadSchemes, record: loadRecords, payout: loadPayouts, me: loadMine, ranking: () => Promise.resolve() }
  boot[t]?.().catch((e) => toast('加载失败：' + (e?.message || e)))
}
onMounted(() => { loadSchemes().catch(() => {}); loadRecords().catch(() => {}); rankSchemeId.value && loadRanking().catch(() => {}) })
</script>

<template>
  <section class="view on" id="v-performance">
    <div class="page-head">
      <div>
        <div class="page-title">科研<em>绩效评价</em></div>
        <div class="page-sub">方案 → 计算 → 确认/审批 → 发放 · 指标数据源直连 R/F/E/T 实绩</div>
      </div>
    </div>

    <div class="tabs">
      <span v-for="t in tabs" :key="t" class="tab" :class="{ on: tab === t }" @click="switchTab(t)">{{ TAB_CN[t] }}</span>
    </div>

    <!-- 方案 -->
    <div v-if="tab === 'scheme'" class="panel">
      <div class="card"><div class="card-b">
        <div v-if="!schemes.length" style="color:var(--ink-mute)">暂无方案。</div>
        <div class="row" v-for="s in schemes" :key="s.id" @click="selectScheme(s.id)">
          <div style="flex:1">
            <b>{{ s.name }}</b> <span class="tag" :class="s.status === 'ACTIVE' ? 'ok' : s.status === 'DRAFT' ? '' : 'warn'">{{ SCHEME_CN[s.status] }}</span>
            <div style="font-size:12px;color:var(--ink-mute)">{{ s.code || ('#' + s.id) }} · {{ s.period_type }} · 周期 {{ s.effective_period }} · v{{ s.version }}</div>
          </div>
          <div class="rowact">
            <input class="sel sm" v-model="calcPeriod" style="width:96px" @click.stop />
            <button v-if="s.status !== 'ACTIVE'" class="btn sm ghost" :disabled="busy" @click.stop="activate(s)">启用</button>
            <button class="btn sm seal" :disabled="busy || !canManage" @click.stop="runCalculate(s)">计算</button>
          </div>
        </div>
      </div></div>

      <div class="card" v-if="curScheme"><div class="card-b">
        <div class="sec-title">「{{ curScheme.name }}」指标（{{ curScheme.factors?.length ?? 0 }}）</div>
        <table class="tbl">
          <thead><tr><th>编码</th><th>名称</th><th>数据源</th><th>权重</th><th>上限</th></tr></thead>
          <tbody>
            <tr v-for="f in curScheme.factors" :key="f.id">
              <td>{{ f.factor_code }}</td><td>{{ f.factor_name || '—' }}</td>
              <td><span class="tag info">{{ DS_CN[f.data_source] }}</span></td>
              <td>{{ toNum(f.weight) }}</td><td>{{ f.max_score ? toNum(f.max_score) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div></div>
    </div>

    <!-- 记录 -->
    <div v-if="tab === 'record'" class="panel">
      <div class="card"><div class="card-b">
        <div v-if="!records.length" style="color:var(--ink-mute)">暂无记录（先在“方案”页触发计算）。</div>
        <table class="tbl" v-else>
          <thead><tr><th>人员</th><th>周期</th><th>方案</th><th>总分</th><th>排名</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="r in records" :key="r.id">
              <td>{{ r.staff_name || ('用户#' + r.staff_user_id) }}</td>
              <td>{{ r.period }}</td><td>{{ r.scheme_name || '#' + r.scheme_id }}</td>
              <td><b style="color:var(--seal)">{{ toNum(r.total_score).toFixed(2) }}</b></td>
              <td>{{ r.rank ?? '—' }}</td>
              <td><span class="tag" :class="recCls(r.status)">{{ REC_CN[r.status] }}</span></td>
              <td class="rowact">
                <button class="btn xs ghost" @click="openRecord(r.id)">明细</button>
                <button v-if="r.status === 'CALCULATED' && canStaffAct" class="btn xs seal" :disabled="busy" @click="recAction(r, 'confirm')">确认</button>
                <button v-if="r.status === 'CALCULATED' && canStaffAct" class="btn xs ghost" :disabled="busy" @click="recAction(r, 'appeal', { reason: '对指标口径有异议' })">申诉</button>
                <button v-if="(r.status === 'CONFIRMED' || r.status === 'APPEAL') && canApprove" class="btn xs seal" :disabled="busy" @click="recAction(r, 'approve')">审批</button>
                <button v-if="r.status === 'APPROVED' && canFinance" class="btn xs seal" :disabled="busy" @click="createPayout(r)">发放</button>
                <button v-if="r.status !== 'VOID' && canManage" class="btn xs ghost" :disabled="busy" @click="recAction(r, 'void', { reason: '数据修正' })">作废</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div></div>

      <div class="card" v-if="curRecord"><div class="card-b">
        <div class="sec-title">记录 #{{ curRecord.id }} 得分明细</div>
        <table class="tbl">
          <thead><tr><th>指标</th><th>测度值</th><th>原始分</th><th>加权分</th></tr></thead>
          <tbody>
            <tr v-for="it in curRecord.items" :key="it.id">
              <td>{{ it.factor_name || it.factor_code }}</td>
              <td>{{ toNum(it.metric_value) }}</td><td>{{ toNum(it.raw_score).toFixed(2) }}</td>
              <td><b>{{ toNum(it.weighted_score).toFixed(2) }}</b></td>
            </tr>
            <tr v-if="!curRecord.items?.length"><td colspan="4" style="color:var(--ink-mute)">无明细</td></tr>
          </tbody>
        </table>
        <button class="btn sm ghost" style="margin-top:8px" @click="curRecord = null">收起</button>
      </div></div>
    </div>

    <!-- 发放 -->
    <div v-if="tab === 'payout'" class="panel">
      <div class="card"><div class="card-b">
        <div v-if="!payouts.length" style="color:var(--ink-mute)">暂无发放单。</div>
        <table class="tbl" v-else>
          <thead><tr><th>单号</th><th>收款人</th><th>金额</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="p in payouts" :key="p.id">
              <td>{{ p.code || '#' + p.id }}</td>
              <td>{{ p.payee_name || ('用户#' + p.payee_user_id) }}</td>
              <td><b>¥ {{ toNum(p.amount).toFixed(2) }}</b></td>
              <td><span class="tag" :class="p.status === 'PAID' ? 'ok' : p.status === 'REJECTED' ? 'warn' : 'info'">{{ PAY_CN[p.status] }}</span></td>
              <td class="rowact">
                <button v-if="p.status === 'DRAFT' && canFinance" class="btn xs seal" :disabled="busy" @click="payoutAction(p, 'approve')">审批</button>
                <button v-if="p.status === 'APPROVED' && canFinance" class="btn xs seal" :disabled="busy" @click="payoutAction(p, 'pay')">付款</button>
                <button v-if="(p.status === 'DRAFT' || p.status === 'APPROVING') && canFinance" class="btn xs ghost" :disabled="busy" @click="payoutAction(p, 'reject')">驳回</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div></div>
    </div>

    <!-- 我的 -->
    <div v-if="tab === 'me'" class="panel">
      <div class="card" v-for="m in mine" :key="m.id"><div class="card-b">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>{{ m.period }} · 总分 <span style="color:var(--seal);font-size:18px">{{ toNum(m.total_score).toFixed(2) }}</span></b>
          <span class="tag" :class="recCls(m.status)">{{ REC_CN[m.status] }}</span>
        </div>
        <table class="tbl" style="margin-top:8px">
          <thead><tr><th>指标</th><th>加权分</th></tr></thead>
          <tbody><tr v-for="it in m.items" :key="it.id"><td>{{ it.factor_name || it.factor_code }}</td><td>{{ toNum(it.weighted_score).toFixed(2) }}</td></tr></tbody>
        </table>
      </div></div>
      <div v-if="!mine.length" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute);padding:24px">暂无属于你的绩效记录。</div></div>
    </div>

    <!-- 排行 -->
    <div v-if="tab === 'ranking'" class="panel">
      <div class="filter-row">
        <select class="sel" v-model="rankSchemeId">
          <option :value="''">选择方案…</option>
          <option v-for="s in schemes" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <input class="sel" v-model="rankPeriod" style="width:110px" />
        <button class="btn sm seal" :disabled="busy" @click="loadRanking">查询</button>
      </div>
      <div class="card"><div class="card-b">
        <table class="tbl">
          <thead><tr><th>名次</th><th>人员</th><th>总分</th></tr></thead>
          <tbody>
            <tr v-for="rk in ranking" :key="rk.rank">
              <td><b :style="rk.rank <= 3 ? 'color:var(--gold)' : undefined">{{ rk.rank }}</b></td>
              <td>{{ rk.staff_name || ('用户#' + rk.staff_user_id) }}</td>
              <td>{{ toNum(rk.total_score).toFixed(2) }}</td>
            </tr>
            <tr v-if="!ranking.length"><td colspan="3" style="color:var(--ink-mute)">选择方案后点“查询”</td></tr>
          </tbody>
        </table>
      </div></div>
    </div>
  </section>
</template>

<style scoped>
.tabs { display:flex; gap:6px; margin:6px 0 14px; flex-wrap:wrap; }
.tab { padding:6px 14px; border:1px solid var(--line,#d8d2c4); border-radius:20px; font-size:13px; cursor:pointer; background:#fff; }
.tab.on { background:var(--seal,#b5462f); color:#fff; border-color:var(--seal,#b5462f); }
.panel { display:flex; flex-direction:column; gap:12px; }
.row { display:flex; justify-content:space-between; align-items:center; padding:10px 6px; border-bottom:1px dashed var(--line,#eee); cursor:pointer; }
.row:hover { background:var(--hover,#fbf8f0); }
.rowact { display:flex; gap:6px; align-items:center; }
.btn.xs { font-size:11px; padding:2px 8px; }
.tbl { width:100%; border-collapse:collapse; font-size:12.5px; }
.tbl th { text-align:left; color:var(--ink-mute); font-weight:600; padding:6px; border-bottom:1px solid var(--line,#e5e0d5); }
.tbl td { padding:6px; border-bottom:1px solid var(--line,#f2eee4); }
.sel { font-size:12px; padding:5px 8px; border:1px solid var(--line,#d8d2c4); border-radius:6px; background:#fff; }
.sel.sm { padding:3px 6px; }
.sec-title { font-family:var(--serif); font-weight:700; margin-bottom:8px; font-size:13px; }
.filter-row { display:flex; gap:10px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
</style>
```

> 命名 1:1：`id="v-performance"` ↔ 路由 `name: 'performance'` ↔ 侧栏 `v: 'performance'`。金额/分数是字符串，统一 `toNum` 解析（`toNum('0')`=0，兜底不产 NaN）。`approve/void/payout` 等动作按角色门控，与后端 M 域鉴权矩阵一致；前端只是隐藏按钮，真权限仍由后端 Casbin + ABAC 兜底。

- [ ] **步骤 2：注册路由**

在 `frontend/src/router/index.ts` 的 `activity` 路由（步骤 FE-2 刚插入的那行）之后插入：

```ts
  { path: '/performance', name: 'performance', meta: { zh: '科研绩效评价', en: 'PERFORMANCE', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE', 'R-AUDITOR'] }, component: () => import('@/views/PerformanceView.vue') },
```

> 与后端 M 域鉴权矩阵对齐：研究员/主管/领导/财务可达（各自按钮由页内角色门控收敛），审计只读可达；专家/伦理不可达。

- [ ] **步骤 3：侧栏导航**

在 `frontend/src/App.vue` 的 `学 术 活 动` 组（FE-2 步骤 3 插入）里追加一项，或新建 `绩 效` 组。推荐并入同组，保持“新增域 = 新增一组两项”：

```ts
    { v: 'performance', ic: '★', label: '科研绩效评价', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE', 'R-AUDITOR'] },
```

> `v: 'performance'` = 路由 `name` = 视图 `section id` 去 `v-` 前缀，三者一致。

- [ ] **步骤 4：curated mock 数据**

创建 `frontend/src/api/mock/overrides/performance.ts`：

```ts
/**
 * Curated overrides —— 绩效评价屏（module M）
 * 契约：14-科研绩效评价-M.openapi.yaml（tag performance）
 * 分数/金额是字符串（NUMERIC 承载）。calculate/迁移类改写内存 store，使前端 reload 后可见状态流转。
 * 注意：override 函数只拿 url、拿不到请求体，calculate 覆写按固定样例补记录；真后端才按周期/范围实算 R/F/E/T。
 */

interface SchemeRec { id: number; code: string; name: string; period_type: string; effective_period: string; version: number; active: boolean; status: string; scope_dept_id?: number; scope_staff_type?: string }
interface FactorRec { id: number; scheme_id: number; factor_code: string; factor_name: string; weight: string; max_score?: string; data_source: string; sort_no: number }
interface ItemRec { id: number; record_id: number; factor_code: string; factor_name: string; metric_value: string; raw_score: string; weighted_score: string }
interface RecRec { id: number; scheme_id: number; scheme_name: string; staff_user_id: number; staff_name: string; period: string; dept_id?: number; total_score: string; rank?: number; status: string }
interface PayRec { id: number; code: string; record_id: number; payee_user_id: number; payee_name: string; amount: string; period: string; status: string; voucher_code?: string }

const schemes: SchemeRec[] = [
  { id: 1, code: 'PERF-2026-Q3', name: '2026 三季度科研绩效方案', period_type: 'QUARTER', effective_period: '2026Q3', version: 1, active: true, status: 'ACTIVE', scope_dept_id: 10 },
  { id: 2, code: 'PERF-2026-Y', name: '2026 年度综合绩效方案（草拟）', period_type: 'YEAR', effective_period: '2026', version: 1, active: false, status: 'DRAFT' },
]
const factors: FactorRec[] = [
  { id: 11, scheme_id: 1, factor_code: 'R_OUTPUT', factor_name: '论文/专利产出', weight: '40', max_score: '40', data_source: 'R_OUTPUT', sort_no: 1 },
  { id: 12, scheme_id: 1, factor_code: 'E_PROJECT', factor_name: '在研项目', weight: '20', max_score: '20', data_source: 'E_PROJECT', sort_no: 2 },
  { id: 13, scheme_id: 1, factor_code: 'F_INCOME', factor_name: '到账经费', weight: '30', max_score: '30', data_source: 'F_INCOME', sort_no: 3 },
  { id: 14, scheme_id: 1, factor_code: 'T_DEAL', factor_name: '转化合同额', weight: '10', max_score: '10', data_source: 'T_DEAL', sort_no: 4 },
]

let recSeq = 1200
const records: RecRec[] = [
  { id: 1001, scheme_id: 1, scheme_name: '2026 三季度科研绩效方案', staff_user_id: 100, staff_name: '周明远', period: '2026Q3', dept_id: 10, total_score: '20.80', rank: 1, status: 'CALCULATED' },
  { id: 1002, scheme_id: 1, scheme_name: '2026 三季度科研绩效方案', staff_user_id: 101, staff_name: '李工', period: '2026Q3', dept_id: 10, total_score: '17.50', rank: 2, status: 'CONFIRMED' },
  { id: 1003, scheme_id: 1, scheme_name: '2026 三季度科研绩效方案', staff_user_id: 102, staff_name: '王研究员', period: '2026Q3', dept_id: 11, total_score: '12.30', rank: 3, status: 'APPROVED' },
]
const itemsByRecord: Record<number, ItemRec[]> = {
  1001: [
    { id: 1, record_id: 1001, factor_code: 'R_OUTPUT', factor_name: '论文/专利产出', metric_value: '6', raw_score: '40', weighted_score: '16.00' },
    { id: 2, record_id: 1001, factor_code: 'E_PROJECT', factor_name: '在研项目', metric_value: '500000', raw_score: '20', weighted_score: '4.00' },
    { id: 3, record_id: 1001, factor_code: 'F_INCOME', factor_name: '到账经费', metric_value: '200000', raw_score: '30', weighted_score: '0.00' },
    { id: 4, record_id: 1001, factor_code: 'T_DEAL', factor_name: '转化合同额', metric_value: '150000', raw_score: '8', weighted_score: '0.80' },
  ],
}
const payouts: PayRec[] = [
  { id: 5001, code: 'PAY-2026-5001', record_id: 1003, payee_user_id: 102, payee_name: '王研究员', amount: '12300.00', period: '2026Q3', status: 'DRAFT' },
]
let paySeq = 5900

function seg(url: string, re: RegExp): number { const m = url.match(re); return m ? Number(m[1]) : 0 }
function withFactors(s: SchemeRec) { return { ...s, factors: factors.filter((f) => f.scheme_id === s.id) } }

export const overrides: Record<string, unknown> = {
  'GET /perf/schemes': { list: schemes, total: schemes.length, page: 1, size: 100 },
  'GET /perf/schemes/{id}': (url: string) => { const s = schemes.find((x) => x.id === seg(url, /\/schemes\/(\d+)/)); return s ? withFactors(s) : null },
  'POST /perf/schemes/{id}/activate': (url: string) => {
    const s = schemes.find((x) => x.id === seg(url, /\/schemes\/(\d+)/))
    if (s) { schemes.forEach((o) => { if (o.period_type === s.period_type && o.status === 'ACTIVE') { o.status = 'SUPERSEDED'; o.active = false } }); s.status = 'ACTIVE'; s.active = true }
    return s ? withFactors(s) : null
  },

  'POST /perf/schemes/{id}/calculate': (url: string) => {
    const id = seg(url, /\/schemes\/(\d+)/)
    const s = schemes.find((x) => x.id === id)
    // 固定补一条新记录演示（真后端按周期/范围实算 R/F/E/T）
    if (s) records.unshift({ id: ++recSeq, scheme_id: s.id, scheme_name: s.name, staff_user_id: 103, staff_name: '赵研究员', period: '2026Q3', dept_id: s.scope_dept_id ?? 10, total_score: '9.60', status: 'CALCULATED' })
    return { calc_batch: `BATCH-${id}-${Date.now()}`, period: '2026Q3', computed: 1, inserted: 1, updated: 0 }
  },

  'GET /perf/records': { list: records, total: records.length, page: 1, size: 100 },
  'GET /perf/records/{id}': (url: string) => records.find((r) => r.id === seg(url, /\/records\/(\d+)/)) ?? null,
  'GET /perf/records/{id}/detail': (url: string) => {
    const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/))
    return r ? { ...r, items: itemsByRecord[r.id] ?? [] } : null
  },
  'POST /perf/records/{id}/confirm': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'CONFIRMED'; return r ?? null },
  'POST /perf/records/{id}/appeal': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'APPEAL'; return r ?? null },
  'POST /perf/records/{id}/approve': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'APPROVED'; return r ?? null },
  'POST /perf/records/{id}/void': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'VOID'; return r ?? null },

  'GET /perf/me': (url: string) => ({ list: records.filter((r) => r.staff_user_id === 100).map((r) => ({ ...r, items: itemsByRecord[r.id] ?? [] })) }),

  'GET /perf/payouts': { list: payouts, total: payouts.length, page: 1, size: 100 },
  'POST /perf/payouts': () => { const p: PayRec = { id: ++paySeq, code: `PAY-2026-${paySeq}`, record_id: 1003, payee_user_id: 102, payee_name: '王研究员', amount: '12300.00', period: '2026Q3', status: 'DRAFT' }; payouts.unshift(p); return p },
  'POST /perf/payouts/{id}/approve': (url: string) => { const p = payouts.find((x) => x.id === seg(url, /\/payouts\/(\d+)/)); if (p) p.status = 'APPROVED'; return p ?? null },
  'POST /perf/payouts/{id}/pay': (url: string) => { const p = payouts.find((x) => x.id === seg(url, /\/payouts\/(\d+)/)); if (p) { p.status = 'PAID'; p.voucher_code = `VC-${p.id}` } return p ?? null },
  'POST /perf/payouts/{id}/reject': (url: string) => { const p = payouts.find((x) => x.id === seg(url, /\/payouts\/(\d+)/)); if (p) p.status = 'REJECTED'; return p ?? null },

  'GET /perf/ranking': (url: string) => {
    const u = new URL(url, 'http://x.local')
    const sid = Number(u.searchParams.get('scheme_id') || 1)
    const list = records.filter((r) => r.scheme_id === sid && r.status !== 'VOID')
      .sort((a, b) => Number(b.total_score) - Number(a.total_score))
      .slice(0, 20)
      .map((r, i) => ({ rank: i + 1, staff_user_id: r.staff_user_id, staff_name: r.staff_name, dept_id: r.dept_id, total_score: r.total_score }))
    return { list }
  },
}
```

> 覆写键全部是**模板路径**（与 `routeIndex` 键 `${method} ${op.path}` 一致）；`{id}`/`{factorId}`/`{pid}` 段用 `seg(url, /正则/)` 解析具体 ID。store 为模块级可变数组，reload 后状态流转可见。`PayRec.voucher_code` 已声明为可选，故 `pay` 覆写里的赋值合法。

- [ ] **步骤 5：类型检查 + 构建**

运行：`cd frontend && npm run typecheck && npm run build`
预期：均无错。`ActivityView`/`PerformanceView` 均随路由懒加载并入包（vite 自动 code-split）。若报 `@/utils/money` 找不到 `toWan`/`toNum`，确认 `frontend/src/utils/money.ts` 导出这两个（既有）。

- [ ] **步骤 6：Commit**

```bash
git add frontend/src/views/PerformanceView.vue frontend/src/router/index.ts frontend/src/App.vue frontend/src/api/mock/overrides/performance.ts
git commit -m "feat(M): 绩效评价前端屏（方案/记录/发放/我的/排行 五标签）+ mock curated 数据"
```

---

## 联调与交付（VER）

### 任务 VER：端到端验证 + 漂移守卫

**文件：**
- 修改：`backend-go/Makefile:61-64`（`drift` 目标纳入两个新 store 目录）
- 验证：全仓 build/test/typecheck + 契约/迁移漂移（无新增文件）

> 此任务是**收尾闸口**：前面每个 V/M/FE 任务各自 commit 后，这里跑一次“全绿 + 零漂移”总检，并把 spec §8 的 7 条验收逐条对账。任何一步红，回到对应任务修复后重跑，不新增功能。

- [ ] **步骤 1：`drift` 目标纳入新 store**

把 `backend-go/Makefile` 的 `drift` 目标（当前 `git diff --exit-code --` 只列 `internal/modules/p/store internal/modules/sysadmin/store api/gen migrations/...`）改为追加两个新 store 目录：

```make
drift: codegen ## 漂移守卫：重跑生成后若与已提交产物不一致则失败
	@$(GO) build ./... # 确保生成物可编译
	git diff --exit-code -- internal/modules/p/store internal/modules/sysadmin/store internal/modules/activity/store internal/modules/performance/store api/gen migrations/000001_init.up.sql migrations/000001_init.down.sql \
	  || (echo "codegen 产物与源不一致：请 make codegen 后提交"; exit 1)
```

> **缩进必须是 TAB**（Makefile 硬要求，非空格）。仅新增 `internal/modules/activity/store internal/modules/performance/store` 两处路径，其余原样保留。

- [ ] **步骤 2：后端全量重生成 + 编译 + 静态检查 + 单测**

运行（`backend-go/`）：

```bash
make codegen            # gen-sqlc（GOTOOLCHAIN=go1.23.4）+ gen-oapi + gen-migrations
go build ./...
go vet ./...
go test ./...           # 无 ARK_TEST_DATABASE_URL 时 DB 门控用例自动 SKIP
```
预期：`make codegen` 无 `panic: out of bounds memory access`；build/vet 无错；`go test ./...` 全 PASS（`activity`、`performance`、`auth`、`sysadmin`、`oapi`、`migrations` 包测试绿，DB 用例 SKIP）。

- [ ] **步骤 3：漂移守卫（应零差异）**

运行：`make drift`
预期：`git diff --exit-code` 通过（无输出、退出 0）。若失败，说明某任务改了 `design/*.{ddl.sql,openapi.yaml}`/`db/query_*`/`db/schema/*` 却未把重生成产物一并 commit——回该任务补 `git add` 相应生成目录后重跑。

- [ ] **步骤 4：契约逐字节同步校验（design ↔ frontend）**

运行（仓库根）：

```bash
diff -q "design/13-学术活动管理-V.openapi.yaml" "frontend/src/api/schema/13-学术活动管理-V.openapi.yaml" && \
diff -q "design/14-科研绩效评价-M.openapi.yaml" "frontend/src/api/schema/14-科研绩效评价-M.openapi.yaml" && \
echo SYNC_OK
```
预期：打印 `SYNC_OK`（两份均逐字节一致）。任一不一致 → 重新 `cp` 并按对应任务补 commit。

- [ ] **步骤 5：前端类型检查 + 构建**

运行（`frontend/`）：

```bash
npm run typecheck
VITE_USE_MOCK=true npm run build   # mock 演示构建
```
预期：typecheck 无 TS 错；build 成功产出 `dist/`。`ActivityView`/`PerformanceView` 作为懒加载 chunk 出现。

- [ ] **步骤 6：（可选，有 PG 时）集成测试 + 手算校验**

起库并跑门控用例（`backend-go/`）：

```bash
docker compose up -d postgres      # 或本地 PG；空库先跑 migrate（000001_init 含 v_*/m_* 建表）
export ARK_TEST_DATABASE_URL="postgres://ark:ark@localhost:5432/ark?sslmode=disable"
go test ./internal/modules/activity/ ./internal/modules/performance/ -v
```
预期：`TestCalculateEndToEnd` PASS（seed 手算 `total_score≈20.80`、`items=4`）、`TestReadRecordForABAC_StaffCrossUser` PASS（R-STAFF 越权读他人记录 403）。若失败多为 sqlc 参数名与手测不符，按生成的 `*.sql.go` Params 回填。

- [ ] **步骤 7：mock ↔ 真后端切换自检**

前端切真后端 = 删 `main.ts` 的 `installMock()`；后端 `DB_MODE=pg`（或默认参考实现）两态皆可跑。本步仅**文档级确认**联调清单，不改码：在 PR 描述里列出（a）关 mock 的构建命令 `VITE_USE_MOCK=false npm run build`、（b）后端指向真库的 env、（c）`/api/v1/activities*`、`/api/v1/perf/*` 共 42 条端点已由 Go 竖切注册、未实现者由 `oapi.Passthrough` 兜底。

- [ ] **步骤 8：Commit（Makefile + 任何收尾产物）**

```bash
git add backend-go/Makefile
git commit -m "chore(ci): drift 守卫纳入 activity/performance 两个新 store 目录"
```

---

## 规格 §8 验收对账（Definition of Done）

| # | 验收标准 | 覆盖任务 |
|---|----------|----------|
| 1 | 契约+DDL+迁移重生成零漂移；前端 schema 副本逐字节同步 | V-1/V-2、M-1/M-2（源），V-4/M-3（重生成+断言），VER 步骤 3–4 |
| 2 | `go build/vet/test ./...` 全绿；四包测试 PASS，DB 门控无库 SKIP | VER 步骤 2 |
| 3 | sqlc 两新引擎块生成成功，store 编译测试钉住形状 | V-5..V-8（activity store）、M-4..M-7（performance store） |
| 4 | Casbin 鉴权矩阵覆盖 V/M 关键路径（R-STAFF 越权 approve 被拒、R-AUDITOR 只读、`/perf/me` ABAC 限本人） | V-13、M-14；ABAC 越权集成测 M-15 |
| 5 | 前端 `typecheck`+`build` 通过；两新页 mock 有演示数据、关 mock 可打真后端 | FE-2/FE-3 + VER 步骤 5、7 |
| 6 | `calculate` 从 R/F/E/T 真表按因子计分产出 record+item+evidence、幂等重算 | M-10（calculate/metrics）、M-5（upsert 幂等）、VER 步骤 6 手算 20.80 |
| 7 | 学术活动状态机全链路（建→提→审→办→归）可用，退回/驳回分支正确 | V-10（handler 状态机）、V-14（端点测）、FE-2（动作按钮） |

> 全部 7 条均有对应任务与测试；无悬空验收项。

---

## 自审（写计划完成后）

**规格覆盖**：spec §3（V：3 表/13 端点/状态机）、§4（M：5 表/27 端点/五标签前端/跨模块 calculate）、§8 DoD 七条 → 均有任务落地（见上表）。V 域 15 任务 + M 域 15 任务 + FE 3 任务 + VER 1 任务。

**占位符扫描**：已消除 “TBD/稍后实现/二选一/执行者回填” 类表述——`voucher_code` 直接补进接口、`createPayout` 已接线到记录页按钮、Participant/Review 字段对齐契约（`guest_name`/`reviewer_id`/role 枚举 `SPEAKER,CHAIR,MEMBER,ATTENDEE`）、sqlc 实体查询一律 `SELECT *`/`RETURNING *` 返回 model、`ActivateScheme` 用真实 `pool.Begin → WithTx(tx pgx.Tx) → Commit`。仍存在的**受控回填点**是刻意的（契约字段名/Params 名须以 sqlc 实际生成物为准）：凡标注“按 `*.sql.go` 回填”处，均为生成后字段名核对，非功能缺失。

**类型一致性**：跨任务核对——store 包名 `vstore`（activity）/`mstore`（performance）与 handler import 别名一致；`Handler{q,pool}`+`NewHandler(pool)` 在 V/M 同构；mapper `numDec/numStrOrNil/numN` 与契约字符串字段、`pgtype.Numeric` 对齐；前端 `Activity/ActivityDetail/Participant/Review`、`Scheme/Factor/PerfRecord/RecordDetail/Payout/RankItem` 字段名与各自契约 schema 一致；命名 1:1：`id="v-activity"`↔`name:'activity'`↔侧栏 `v:'activity'`，`id="v-performance"`↔`name:'performance'`↔`v:'performance'`。

---

## 执行移交

计划已保存至 `docs/superpowers/plans/2026-10-14-academic-activities-and-performance.md`。两种执行方式：

1. **子 Agent 驱动（推荐）** — 每个任务派新的 subagent 实现、任务间两阶段审查，契合“契约→库→码→测→前端”的长链，隔离上下文、失败可单任务重试。
2. **顺序执行** — 本会话按批次推进，每批次后跑校验；适合想全程旁观每一步。

无论哪种：按 **V 域（V-1→V-15）先行 → M 域（M-1→M-15）→ FE（FE-1→FE-3）→ VER** 顺序；每任务末步 commit；**全程走 `develop` 分支、不自动推 `master`**，合并/PR 留待确认。选择哪种？


