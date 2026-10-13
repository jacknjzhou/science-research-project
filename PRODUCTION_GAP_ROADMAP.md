# 科研管理系统 · 生产化差距与路线图（Go + Gin 方案）

> 版本：v1.0　编制日期：2026-10-13
> 适用范围：科研院所 / 研究机构赛道（对齐 `PRODUCT_PLAN.md` 定位）
> 关键决策：后端生产实现由 `TECH_ARCHITECTURE.md` 原推荐的 **Java 17 + Spring Cloud Alibaba** 调整为 **Go + Gin**；本文据 Go 栈重排技术选型、差距、里程碑与人力，并保留原文的 OLTP/OLAP 双引擎、信创、等保、涉密多法人等约束。
> 文档关系：`PRODUCT_PLAN.md`（做什么）→ `TECH_ARCHITECTURE.md`（架构愿景，含原 Java 方案，本文替换其后端语言选型）→ `PRD/`、`design/`（契约与数据模型，唯一真源）→ 本文（差多少、怎么补、按什么顺序）。

---

## 0. 现状基线（诚实快照）

当前仓库处于**契约驱动参考原型（M0 前半程）**，不是可上线系统。已具备与尚缺的对照如下：

已具备（高价值资产，Go 方案继续复用）：

- 契约即真源：`design/` 下 11 个模块的 OpenAPI（249 操作）+ DDL（133 张表，PG15 顶部带达梦差异注记）+ 横切底座 `00-common.sql` + 共享实体登记表。
- 参考后端：Node16 + Fastify 单通配分发器，`matchRoute` 解析回契约、按 200 schema 生成响应；`DB_MODE=pg` 生成式适配接通 Postgres（连不上自动回落，零回归），`npm run coverage` 离线审计绑定 122/249。
- 契约驱动前端：Vite+Vue3+TS，13 屏，数据流可一键切真实后端（删 `installMock()`）。
- 交付物：PRD 全模块（统一 12 节模板）、PRODUCT_PLAN 五层架构、TECH_ARCHITECTURE 组件图、DEPLOY。

尚缺（本文明细展开）：

- **无任何鉴权/权限**（grep 无 jwt/oauth/authoriz）。
- **无 CI/CD**（无 `.github/workflows`），测试仅契约校验 `verify` 与假 pool `dbtest`。
- 中间件未接：compose 仅 backend+frontend+postgres，无 Redis/Kafka/MinIO/ClickHouse。
- pg 适配是通用 CRUD，非领域逻辑；无事务/幂等外置/编号/预算控制/迁移工具/种子数据。
- AI 与大数据两条主线、外部集成（财务/OA/统一身份/文献专利）、信创适配、可观测、高可用——均未启动。

一句话定位：**骨架与规约验证已跑通，生产化 = 按 Go 目标形态重建后端服务层 + 补齐全部横切能力**。

---

## 1. 目标架构（Go + Gin）

### 1.1 形态原则

- **模块化单体优先，微服务按需**：Go+Gin 天然适合先做“结构清晰的模块化单体”（单 codebase、按域分包、独立可测），避免过早微服务带来的运维与分布式事务负担；当某域（如 AI、数据分析、涉密）需要独立伸缩或独立合规部署时，再沿域边界拆出服务。文档里的 `svc-*` 理解为“可拆分的域服务”，Gin 为其统一 HTTP 接入层。
- **契约驱动的 Go 化**：延续“契约即真源”，用 `oapi-codegen` 从 `design/*.openapi.yaml` 生成 Gin 路由注册、请求/响应 DTO 与 `validator` 标签，把现有 OpenAPI 资产直接变成 Go 代码骨架与运行时校验，避免契约与实现漂移。
- **静态编译、信创友好**：Go 编译为单静态二进制、交叉编译 `linux/arm64`，天然适配鲲鹏 CPU / 麒麟 OS，无需 JVM，内存与冷启动更省。

### 1.2 分层

```
外部：CAS/OAuth2 · 财务(用友/金蝶) · OA(泛微/致远) · 文献/专利 API · LLM(本地/云)
                    │
接入： APISIX / Traefik 网关（TLS、限流、路由、鉴权前置）
                    │
服务： Gin API 层(oapi-codegen 生成) → 领域服务层 → 适配层(仓储/RPC/消息/对象存储)
        │            │             │
      鉴权:JWT+Casbin 事务/幂等/编号  可观测:OTel+Prometheus+zap
                    │
数据： OLTP(PostgreSQL/达梦 · sqlc/GORM · pgx) ──CDC──> OLAP(ClickHouse)
      Redis(缓存/会话/分布式幂等/限流) · Kafka(事件/削峰) · MinIO(附件/扫描件) · pgvector/Milvus(向量)
平台： 配置/注册 etcd/Consul+Viper · 任务 asynq+cron · CI/CD · K8s · 信创底座
```

### 1.3 Java → Go 选型对照（核心）

| 能力 | 原 Java/Spring 方案 | Go+Gin 替代方案 | 备注 |
|---|---|---|---|
| Web 框架 | Spring MVC / WebFlux | **Gin** | 轻量高性能 HTTP 框架 |
| 微服务全家桶 | Spring Cloud Alibaba | 组合式：Gin + gRPC + 中立网关(APISIX/Traefik) + etcd/Consul | Go 无“全家桶”，按需组装；或评估 go-zero |
| 服务网关 | Spring Cloud Gateway | **APISIX**（或 Traefik）；内部可选 Go 网关服务 | 语言中立、可插拔鉴权/限流插件 |
| 注册与配置 | Nacos | **etcd / Consul** + **Viper**（如需 Nacos 有 Go SDK） | Viper 管本地/远程配置热加载 |
| 服务间调用 | OpenFeign / Dubbo | **gRPC（grpc-go）** 为主，跨语言/外部用 HTTP(resty) | proto 即接口契约 |
| 限流熔断降级 | Sentinel | **sony/gobreaker** + `golang.org/x/time/rate` + 网关层限流 | 熔断+令牌桶 |
| ORM/数据访问 | MyBatis / JPA | **sqlc**（类型安全、从 SQL 生成，首选）或 **GORM**；驱动 **pgx** | sqlc 契合“契约/DDL 真源”理念 |
| 分布式事务 | Seata | 优先**本地事务 + Outbox/Saga**；确需再上 **DTM** | 单体阶段尽量规避分布式事务 |
| 安全认证 | Spring Security | **golang-jwt/jwt** + **Casbin**（RBAC/ABAC） | 细粒度策略用 Casbin |
| 参数校验 | Bean Validation | **go-playground/validator** + oapi-codegen 生成校验 | 与契约联动 |
| 定时/异步任务 | XxlJob | **asynq**（Redis 任务队列）+ **robfig/cron** | 抓取/导入/报表 |
| 消息 | RocketMQ / Spring Cloud Bus | **Kafka（IBM/sarama 或 segmentio/kafka-go）** | 事件总线/削峰 |
| 缓存 | Redisson | **go-redis** | 主从+哨兵 |
| 可观测 | Micrometer + Sleuth | **OpenTelemetry-Go** + **Prometheus client（gin 中间件）** + **zap** 结构化日志 | traceId 贯穿 |
| 国密 | 厂商 SDK | **tjfoc/gmsm**（SM2/3/4） | 信创/涉密合规 |
| OLTP | 达梦/PG | 同（达梦经 `database/sql` 驱动 / ODBC；PG 走 pgx） | 保留双兼容 |
| OLAP | ClickHouse | 同 + Go 侧 **clickhouse-go** | CDC 由 Debezium/自建 |
| 对象存储 | MinIO | 同 + **minio-go** SDK | 附件/扫描件 |
| 向量检索 | — | **pgvector** 或 **Milvus** | 支撑 RAG |
| 契约→代码 | 手写 Controller | **oapi-codegen**（OpenAPI→Gin handler/DTO） | 最大化复用 design/ |

### 1.4 不变的部分（沿用既有约束）

数据库约定（snake_case、`deleted` 软删、`tenant_id`/`legal_entity_id`/`security_level`/`policy_pack_id`、TIMESTAMPTZ、JSONB、NUMERIC(18,2) 对外为 string、`id BIGINT GENERATED ALWAYS AS IDENTITY`）、跨模块只存逻辑外键不建物理 FK、G/A/成本表带法人+密级+制度包——这些由 DDL 固化，与语言无关，Go 层原样实现。OLTP/OLAP 双引擎、LLM 本地默认+云端可选、涉密子系统独立部署、等保三级、信创适配优先级（麒麟→达梦/人大金仓→东方通→鲲鹏）均保持不变。

---

## 2. 生产化差距总览（按维度）

里程碑列取值：M0 奠基 / M1 核心业务 / M2 涉密与集成 / M3 数据平台与信创。严重度：🔴阻断上线、🟠核心质量、🟡增强。

| # | 维度 | 当前状态 | 生产目标（Go 栈） | 主要缺口 | 严重度 | 里程碑 |
|---|---|---|---|---|---|---|
| 1 | 后端形态 | Node 契约参考原型（非上线件） | Go+Gin 模块化单体，按域可拆服务；oapi-codegen 由契约生成 | 用 Go 重写服务层，接管 249 路由 | 🔴 | M0–M1 |
| 2 | 身份认证 | 无 | 校园 CAS/OAuth2 单点 + 本地账号回退；JWT 签发/校验中间件 | 登录流、令牌、会话、刷新、吊销 | 🔴 | M0 |
| 3 | 授权与数据权限 | 无 | Casbin RBAC（角色）+ ABAC/数据域（法人/院所/项目三级可见）+ 字段脱敏 | 策略模型、数据域注入、脱敏、越权拦截 | 🔴 | M0–M1 |
| 4 | 审计与合规留痕 | 响应含 traceId 字段但无落库 | 全量操作审计表、敏感数据访问审计、不可篡改留痕 | 审计写入、查询、保留策略、等保映射 | 🔴 | M1 |
| 5 | 领域业务逻辑 | pg 通用 CRUD + 玩具状态机 | 真实流程与规则（申报→评审→立项→经费→成果→转化） | 域服务、校验规则、跨表事务、副作用 | 🔴 | M1–M2 |
| 6 | 事务与一致性 | 无事务边界 | 请求内本地事务、Outbox 事件、必要时 Saga/DTM | 事务封装、幂等消费、补偿 | 🔴 | M1 |
| 7 | 幂等 | 进程内 Map（多副本失效） | Redis 请求指纹幂等 + `Idempotency-Key` | 外置幂等、TTL、并发去重 | 🟠 | M0–M1 |
| 8 | 单号/序列 | 参考后端 seq 生成 | DB 序列表 + 乐观锁 + 前缀注册表（`seq_prefix_registry`） | 并发安全取号、按 2.11 登记前缀 | 🟠 | M1 |
| 9 | 数据访问层 | 生成式 SQL（参考） | sqlc/GORM + pgx/达梦驱动；仓储接口隔离 | 领域仓储实现、软删/租户强制谓词 | 🔴 | M1 |
| 10 | 数据库迁移 | initdb 一次性建空库 | 版本化迁移（golang-migrate）+ 可回滚 | 迁移流水线、灰度 DDL 变更 | 🟠 | M0–M1 |
| 11 | 种子/参考数据 | 空库 | 字典(`sys_dict`)、制度包(`policy_pack`)、角色/权限基线 | 初始化数据、环境差异化 | 🟠 | M1 |
| 12 | 缓存 | 无 | go-redis 缓存热点（字典/组织/权限/大屏结果） | 缓存层、失效策略、击穿防护 | 🟡 | M1 |
| 13 | 消息/事件 | 无 | Kafka：领域事件、状态流转、削峰、CDC 触发 | 生产者/消费者、死信、顺序 | 🟠 | M1–M3 |
| 14 | 异步任务/定时 | 无 | asynq+cron：文献/专利抓取、流水导入、报表生成、画像计算 | 作业编排、重试、可观测 | 🟠 | M2–M3 |
| 15 | 对象存储 | 无 | MinIO：申报附件、扫描件、合同正本、导出件 | 上传/下载、病毒扫描、生命周期 | 🟠 | M2 |
| 16 | 全文检索 | 无 | ES/OpenSearch（或 PG 全文，视规模）：项目/成果/政策检索 | 索引、同步、高亮、权限过滤 | 🟡 | M2 |
| 17 | OLAP/大数据 | 仅 D 层 DDL（dim/dwd/dws/ads） | ClickHouse + CDC（Debezium）+ ETL；大屏/画像/预测 | 数据平台、指标口径、ADS 建模 | 🟠 | M3 |
| 18 | AI 主线 | 契约占位（智能填表/风险/查重/评审） | svc-ai-gateway(Go)+本地 LLM(Qwen2.5/ChatGLM)+RAG+向量库；云通道经授权 | 模型服务、RAG 按域过滤、评测、防泄漏 | 🟠 | M2–M3 |
| 19 | 外部集成 | 无 | 财务(用友/金蝶)、OA(泛微/致远)、统一身份、WoS/CNKI/CNIPA/Crossref 标准对接 | 适配层、对账、降级、凭证管理 | 🔴 | M2 |
| 20 | 多租户/法人隔离 | DDL 列已具备，未强制 | 强制谓词或 PostgreSQL RLS + 法人边界；涉密域物理隔离 | 隔离实现、跨法人汇总(治理视图) | 🔴 | M1–M2 |
| 21 | 涉密与分级保护 | X 模块契约/DDL，无实现 | 涉密子系统独立部署、密级管控、离线模型分发、审计 | 隔离架构、密级流转、测评配合 | 🔴 | M2 |
| 22 | 安全加固 | CORS origin:true、无 TLS/CSRF/限流 | 网关 TLS、CSP、CSRF、限流、依赖漏洞治理、密钥管理(Secrets/Vault) | 安全基线、镜像扫描、SAST/DAST | 🔴 | M0–M1 |
| 23 | 可观测性 | logger:false + console | OTel 链路、Prometheus 指标、zap 结构化日志、告警分级 | 埋点、看板、SLO、值班路由 | 🟠 | M1 |
| 24 | 性能/SLO | 未度量 | P95<500ms 列表、1 万导出<30s、AI 首字节<2s、核心写 99.9% | 压测、容量、调优、限流降级 | 🟠 | M3 |
| 25 | 前端生产化 | 构建期内联 mock | 去 mock 真连 Go API；权限驱动 UI、表单校验、错误态、大列表虚拟化 | API 对接、RBAC 路由/按钮、性能 | 🟠 | M1–M2 |
| 26 | 测试与 CI/CD | 无 CI，仅 2 个脚本 | GitHub Actions/GitLab CI：单元+契约校验+连真实 PG 集成+关键 E2E+覆盖率门 | 流水线、制品、灰度发布 | 🔴 | M0 |
| 27 | 高可用/部署 | 单容器 | K8s 多副本、HPA、DB 主从+备份、连接池、蓝绿/金丝雀+特性开关 | 编排、故障演练、备份恢复 | 🟠 | M3 |
| 28 | 信创适配认证 | 无 | 麒麟/统信 OS、达梦/人大金仓、东方通/宝兰德、鲲鹏/海光；通过信创测评 | 适配、认证、性能基线 | 🟠 | M3 |

---

## 3. 关键落地设计（Go 特有）

本节把 §2 中🔴/🟠缺口收敛成可实施的 Go 侧设计要点，作为 M0/M1 工程起步的规格。

### 3.1 契约 → Go 代码骨架（oapi-codegen）

延续“契约即真源”，把 `design/*.openapi.yaml` 编译进代码，消除契约与实现漂移：

- 以 `design/` 为唯一输入，`oapi-codegen` 按模块生成分层产物：Gin `Handler` 接口 + `chi/gin` 路由注册、请求/响应 DTO（带 `json` tag 与 `go-playground/validator` 标签）、`StrictServer` 存根（未实现方法编译期报错，保证 249 操作不遗漏）。
- 生成物纳入版本库（或 CI 工件），人只写 `service`/`repository` 实现层；契约变更 → 重新生成 → 编译失败即“契约破坏”信号，等价于现有 `verify` 的 Go 版门禁。
- DDL 侧用 `sqlc` 从 `design/*.sql` + 手写查询生成类型安全仓储代码；OpenAPI 与 DDL 两套真源在 CI 里交叉校验（响应 DTO 字段 ⊆ 表列白名单）。

### 3.2 身份认证与授权

- **认证**：网关或 Gin 中间件校验 JWT（`golang-jwt/jwt`）；对接高校 CAS/OAuth2 单点，本地账号密码回退（bcrypt/argon2 哈希）；令牌短时效 + refresh，吊销走 Redis 黑名单。claims 携带 `user_id / tenant_id / legal_entity_id / security_level / roles`。
- **授权**：`Casbin` 双层——RBAC（角色→API/菜单/按钮）+ ABAC/数据域（法人 / 院所 / 项目三级可见范围）。策略模型入 DB，缓存进 Redis，变更失效。
- **数据域注入**：仓储层统一从上下文取 `tenant_id/legal_entity_id/security_level`，自动拼进查询谓词（见 3.7），业务代码不手写过滤，从根上防越权。
- **字段脱敏**：序列化层按角色/密级对身份证、手机号、金额账户等做掩码；敏感字段访问写审计（3.4）。

### 3.3 事务与领域服务

- 请求级本地事务封装：`repository` 持有 `*sql.Tx`，service 通过 `WithinTx(ctx, fn)` 编排跨表写入，杜绝“半成功”。
- 领域逻辑落 `service` 层：申报→评审→立项→经费→成果→转化的状态迁移用显式状态机（令牌 token 驱动，沿用 PRD 2.6 大写蛇形状态），校验前置条件与副作用（如经费扣减、预算控制、成果关联项目）。
- 跨服务/跨域副作用用 **Outbox**：业务写与事件写同库同事务提交，后台任务投递 Kafka，消费端幂等；确需跨库一致性再评估 **Saga/DTM**，单体阶段优先规避分布式事务。

### 3.4 幂等与单号

- **幂等**：写操作读取 `Idempotency-Key`，以 Redis 存请求指纹→首次结果缓存；命中直接回放，并发用 `SETNX` 抢占，替换现有进程内 Map（多副本安全）。
- **单号/序列**：建 `seq_prefix_registry`（登记 REQ/ORD/CON/OSC/SUP/SOSC/AST/DSP/EXF/LE… 前缀，与 PRD 2.11 README 注册表对齐，唯一来源）；取号用独立计数表行锁或 `UPDATE ... RETURNING`，保证并发唯一、按年/月重置、号段可预分配。业务码 `code` 由取号服务生成，不再用通用占位。成果(R)/人员(S)前缀须先登记再实现，避免漂移。

### 3.5 审计与合规留痕

- 横切审计中间件记录：操作人、数据域、API、请求摘要、结果、traceId、耗时、变更前后关键字段 diff；落 `sys_audit_log`（分区/按月），高价值敏感访问单独留痕。
- 审计写入走 Outbox 异步落库，不阻塞主流程；保留期与不可篡改（追加写 / 定期归档哈希锚定）对齐等保三级要求。

### 3.6 迁移与种子数据

- 用 `golang-migrate` 把 `design/*.sql` 拆成带版本号的 up/down 迁移纳入流水线；空库 initdb 仅用于本地/一次性演示，生产走迁移。
- 参考数据（`sys_dict` 字典、`policy_pack` 制度包、角色/权限/Casbin 策略基线、菜单）以种子迁移或幂等 seed 任务初始化，支持环境差异化（dev/uat/prod）。

### 3.7 多租户 / 法人隔离

- 所有含 `tenant_id/legal_entity_id` 的表，仓储层强制注入过滤谓词；可选用 **PostgreSQL Row-Level Security** 在 DB 端兜底（`SET LOCAL app.legal_entity_id`），防应用层遗漏。
- 涉密域（X 模块）走独立部署、独立库/实例、独立密级策略，与非密数据物理隔离；跨法人汇总仅经治理视图（脱敏聚合），不开明细跨域查询。

### 3.8 缓存 / 消息 / 定时任务

- `go-redis` 缓存字典、组织树、权限策略、大屏聚合结果；设失效与击穿防护（singleflight）。
- Kafka 承载领域事件、状态流转通知、CDC 触发下游 OLAP；消费端以 `(topic,partition,offset)` 或业务幂等键去重，配死信队列。
- `asynq`（Redis 队列）+ `robfig/cron` 编排文献/专利抓取、银行流水导入、报表生成、人员画像计算；任务带重试、超时、可观测指标。

### 3.9 可观测性

- `OpenTelemetry-Go` 贯穿 traceId（与响应体 traceId 字段对齐），`Prometheus` 暴露 QPS/时延/错误率/饱和度，`zap` 输出结构化 JSON 日志（含 traceId/user/数据域）。
- Gin 中间件统一埋点；关键业务（评审通过、经费拨付、涉密访问）打点自定义指标并配告警阈值与值班路由。

### 3.10 安全基线

- 收紧 CORS（关闭 `origin:true`，白名单化）；网关侧 TLS 终结、HSTS、CSP、CSRF（同站 Cookie + token）；`x/time/rate` + 网关限流。
- 依赖漏洞扫描（`govulncheck`）、镜像扫描、SAST；密钥/凭证集中管理（Vault / K8s Secret），国密场景用 `tjfoc/gmsm`（SM2/3/4）。

---

## 4. 里程碑路线图（M0–M3，12 个月）

节奏对齐 `PRODUCT_PLAN.md` 三阶段，前置一个 **M0 奠基**（把“能演示”变成“能安全上线的最小骨架”）。时间为相对月（M0=第 0–1 月，M1=第 2–6 月，M2=第 5–9 月，M3=第 9–12 月，存在并行重叠）。

### M0 · 奠基（0–1 月）— 骨架、门禁、安全底线

目标：Go 工程与流水线立起来，鉴权/迁移/中间件底座就绪，参考原型继续承担前端联调。

进入条件：契约稳定（`design/` 冻结基线）；技术栈定档（Gin + oapi-codegen + sqlc + pg）。

范围：

- 建 Go 工程骨架（按域分包、Gin + oapi-codegen 生成 249 路由存根、healthz、统一响应封装对齐现有 ApiResponse）。
- CI/CD 流水线：构建、`govulncheck`、单元/契约校验、连真实 PG 的集成测试、覆盖率门、制品与镜像。
- 认证授权骨架：JWT 中间件 + Casbin 模型 + 数据域上下文注入（先拦截、后逐域细化）。
- 迁移工具 `golang-migrate` 落地；compose 补 Redis/Kafka/MinIO（开发态）。
- 安全基线：CORS 白名单、限流、TLS 规划、密钥管理。

退出 DoD：Go 服务在 CI 下对 249 路由全部有生成存根；未鉴权请求被统一拦截；`migrate up/down` 可跑通空库→基线库；流水线绿且阻断违规合并。

### M1 · 核心业务（2–6 月）— 主线打通、去 mock

目标：P/E/F/R/G/A 核心域真实实现，前端切真后端，系统“可试运行”。

进入条件：M0 DoD 达成。

范围：

- 领域逻辑：申报→评审→立项→经费→成果→转化 主流程状态机 + 跨表事务（`WithinTx`）+ 副作用（预算控制、经费扣减）。
- 幂等外置（Redis + `Idempotency-Key`）、单号服务（`seq_prefix_registry`，先补齐 R/S 前缀登记）。
- 数据访问层（sqlc/GORM + pgx）接管 list/read/create/action 路由；软删与数据域强制谓词；敏感字段脱敏 + 审计落库。
- 缓存（字典/组织/权限）、领域事件（Kafka Outbox）。
- 种子数据（`sys_dict`/`policy_pack`/角色权限基线）。
- 前端：删 `installMock()`，权限驱动路由/按钮、表单校验接契约、错误态与大列表优化。
- 可观测：OTel + Prometheus + zap 全链路。

退出 DoD：核心域 E2E 用例通过（真实 PG，非 mock）；关键写操作幂等且有单号；越权访问被数据域谓词拦截并有审计；前端完全对接 Go API。

### M2 · 涉密、集成与 AI（5–9 月）— 边界扩张

目标：C/T/S/X 补齐，外部系统对接，对象存储/检索/AI 起步，涉密独立部署成形。

进入条件：M1 核心域稳定运行。

范围：

- C 合同 / T 转化 / S 人员团队 / X 涉密多法人 域实现。
- 外部集成：财务（用友/金蝶）、OA（泛微/致远）、统一身份（CAS）、文献/专利源（WoS/CNKI/CNIPA/Crossref）适配层 + 对账 + 降级 + 凭证管理。
- 对象存储 MinIO（附件/扫描件/合同正本/导出件）；全文检索（ES/OpenSearch 或 PG 全文）。
- 异步任务（asynq）：抓取、流水导入、报表、画像。
- svc-ai-gateway + 本地 LLM（Qwen2.5/ChatGLM）+ RAG（pgvector/Milvus，按数据域过滤、防泄漏）；智能填表/风险预警/查重/辅助评审落地首个场景。
- 涉密子系统独立部署与密级流转；启动等保/涉密测评准备（测评周期长，此时必须启动）。

退出 DoD：四域联调通过；至少 1 个外部集成端到端对账成功；AI 首场景可演示且敏感数据不外泄；涉密域物理隔离方案通过内部评审、测评材料就绪。

### M3 · 数据平台、性能与信创（9–12 月）— 生产级收口

目标：大数据两条主线之一（OLAP）建成，性能/高可用/信创/合规达标，具备正式生产条件。

进入条件：M2 主体功能稳定。

范围：

- OLAP：ClickHouse + CDC（Debezium）+ ETL，D 层 dim/dwd/dws/ads 建模，管理驾驶舱/大屏/趋势预测。
- 性能与 SLO：压测（P95<500ms 列表、1 万导出<30s、AI 首字节<2s、核心写 99.9%）、容量规划、调优、限流降级。
- 高可用：K8s 多副本 + HPA、DB 主从 + 备份恢复、连接池、蓝绿/金丝雀 + 特性开关、故障演练。
- 信创适配：麒麟/统信 OS、达梦/人大金仓（Go 驱动兼容路径回归）、东方通/宝兰德、鲲鹏 arm64（Go 交叉编译优势）；性能基线回归。
- 合规：等保三级测评整改、（如适用）涉密分级保护测评通过。

退出 DoD：SLO 达标且有压测报告；HA 故障演练通过（单点可自动恢复）；信创环境功能与性能回归通过；等保测评出具合格结论。

> 里程碑甘特（表格视图）见附录 C。

---

## 5. 人力与工作量粗估

按 M0–M3 并行节奏估算核心团队规模（人月为量级参考，非承诺；假设契约/PRD/DDL 已就绪这一既有优势）。

| 角色 | 规模 | 主要职责 | 峰值阶段 |
|---|---|---|---|
| Go 后端 | 4–6 | 域服务实现、数据访问、事务/幂等/单号、集成适配、AI 网关 | M1–M2 |
| 前端 | 2 | 去 mock 接真 API、RBAC 驱动 UI、大屏/报表可视化 | M1–M3 |
| 数据工程 | 2 | OLTP 迁移/调优、OLAP（ClickHouse/CDC/ETL）、指标口径 | M2–M3 |
| AI 工程 | 1–2 | LLM 私有化部署、RAG、智能填表/风险/评审场景 | M2–M3 |
| 测试/QA | 1–2 | 契约校验、集成/E2E、压测、质量门禁 | 全程 |
| 安全合规 | 1 | 鉴权/审计、等保三级、涉密测评、信创合规 | M2–M3 |
| DevOps/SRE | 1 | CI/CD、K8s、可观测、HA、信创环境交付 | M0、M3 |
| 产品/项目 | 1 | 需求细化、里程碑与验收、干系人协调 | 全程 |

峰值团队约 **12–16 人**，12 个月总投入量级约 **110–150 人月**。

Go 相对 Spring 的工作量影响：

- **省**：无 JVM 调优/容器内存规划、静态二进制部署简单、`arm64` 交叉编译使信创适配成本下降；`oapi-codegen`/`sqlc` 代码生成减少样板 CRUD；后期运维与云资源开销更低。
- **增（前期一次性）**：Go 无“微服务全家桶”，需自行组装网关/注册/配置/熔断/分布式事务等中立组件（M0 投入）；团队若从 Java 转型有学习曲线；生态里没有 Spring Security/Seata 级别的成熟一体化件，需以 Casbin/Outbox/DTM 组合替代并在 M0–M1 打稳地基。

---

## 6. 风险与缓解

| 风险 | 影响 | 概率 | 缓解 |
|---|---|---|---|
| Gin 非“全家桶”，需自建网关/注册/熔断/分布式事务等薄层 | M0 工期与一致性 | 中 | 用语言中立成熟件（APISIX/etcd/Casbin/gobreaker）；或评估 go-zero 一体化框架；单体阶段少引入分布式件 |
| 达梦 DM8 Go 驱动成熟度不及 JDBC | 信创落地受阻 | 中 | M1 起即开达梦兼容路径测试；优先走 PG 兼容语法；必要时经 `database/sql` + ODBC 或厂商 Go 驱动做适配层并回归 |
| 从 Java 转型 Go 的团队学习曲线 | 前期产出波动 | 中 | M0 小步骨架 + 代码生成降噪；内部规范与评审；关键模块结对 |
| 分布式事务复杂度高（Seata 无 Go 等价成熟件） | 数据一致性 | 中 | 优先本地事务 + Outbox/最终一致；确需再用 DTM；设计上尽量避免跨库写 |
| 信创性能基线未定 | M3 验收风险 | 中 | M1 引入鲲鹏 + 达梦环境做早期性能探测与基线回归，不留到收尾 |
| 涉密/等保测评周期长 | 上线时间 | 高 | M2 即启动测评准备与材料，独立部署架构提前评审，勿压到 M3 |
| Node→Go 迁移期“双真源”漂移（两套后端各改各的） | 契约失真、行为不一致 | 中 | 坚持 `design/` OpenAPI+DDL 为唯一真源；Go 由 oapi-codegen 生成，Node 参考后端仅服务前端 mock，不新增业务；逐路由切流、切完即下线对应 Node handler |
| 契约覆盖外的隐式业务规则（PRD/制度） | 实现遗漏 | 中 | 以 PRD 12 节与 §9 权限/§11 异常为准补测试；评审 checklist 对齐 |
| LLM 数据外泄/幻觉 | 合规与可信 | 中 | 本地模型默认 + 云通道经授权；RAG 按数据域过滤；输出走人工复核关卡与留痕 |

## 7. 从 Node 参考原型到 Go 生产的衔接

现有 Node 参考后端不是要“改造”，而是要被 Go 实现**逐路由替换**。过渡策略：

- **真源不变**：`design/*.openapi.yaml` 与 DDL 继续作为唯一契约/数据真源。Go 用 `oapi-codegen` + `sqlc` 直接消费，杜绝重写导致漂移。
- **契约一致性前移**：现有 `verify`（响应体对 200 schema 校验）思路迁入 Go CI——用生成的 DTO/validator 做同样门禁，`coverage`（路由↔表绑定审计）沿用为“实现进度看板”，每替换一个路由就把该 operationId 从“参考实现”标为“Go 实现”。
- **前端零改动切换**：前端本就“删 `installMock()` 即接真后端”。切换期可让网关按路由前缀把流量从 Node 参考后端灰度切到 Go 服务（先只读 list/read，再 create/action），逐域推进，前端只改 baseURL。
- **Node 参考后端生命周期**：M0–M1 继续承担前端联调与 mock 数据；每当 Go 接管一个模块，对应 Node 路由下线；全部 249 路由 + 领域逻辑由 Go 覆盖后，Node 后端归档为“契约测试夹具/演示 mock 服务”，不再承载业务规则。
- **数据库同源**：Go 与 Node 现都连同一 Postgres 库（A 路线），迁移工具落地后由 `golang-migrate` 统一管版本，避免两套 DDL 应用逻辑并存。

一句话：**契约冻结 → Go 生成骨架 → 按域实现并用 coverage 度量替换进度 → 网关按路由灰度切流 → Node 退居夹具**。

---

## 8. 立即可执行 Backlog（下一步）

按优先级列出 M0 起步即可开工、不依赖新决策的任务：

| 优先级 | 任务 | 产出 | 里程碑 |
|---|---|---|---|
| P0 | 初始化 Go 工程（按域分包 + Gin），配置 `oapi-codegen` 从 `design/` 生成 249 路由存根 | 可编译、路由全覆盖骨架 | M0 |
| P0 | 建 CI/CD：构建、`govulncheck`、契约校验、真实 PG 集成测试、覆盖率门 | 流水线绿、阻断违规合并 | M0 |
| P0 | JWT 中间件 + Casbin 模型 + 数据域上下文注入（拦截优先） | 未鉴权请求统一拦截 | M0 |
| P0 | `golang-migrate` 落地，把 `design/*.sql` 拆成 up/down 迁移 | 空库→基线库可重复 | M0 |
| P0 | compose 补 Redis/Kafka/MinIO（开发态） | 中间件本地可用 | M0 |
| P1 | `sqlc` 生成 list/read 仓储，P 用户与角色域端到端（真连 PG） | 首个真实域竖切 | M1 |
| P1 | Redis 幂等中间件 + `Idempotency-Key`；`seq_prefix_registry` 取号服务（先补 R/S 前缀登记） | 写幂等 + 并发唯一单号 | M1 |
| P1 | 审计中间件落 `sys_audit_log` + 敏感字段脱敏 | 越权/敏感访问留痕 | M1 |
| P1 | 前端删 `installMock()`，网关按路由灰度把只读流量切到 Go | 前端接真后端 | M1 |

> 建议：先做 P 模块（用户/角色/鉴权）作为竖切样板，验证“契约→oapi-codegen→Gin→sqlc→PG→前端”全链路，再横向复制到 E/F/R/G/A。

---

## 附录 A · Java → Go 详细对照表

| 层次 | Spring 生态 | Go 替代 | 说明 |
|---|---|---|---|
| HTTP | Spring MVC/WebFlux | Gin | 路由/中间件 |
| 服务治理 | Spring Cloud Alibaba | APISIX/Traefik + etcd/Consul + Viper | 网关+注册+配置 |
| 一体化替代 | — | go-zero（可选评估） | 若想要“全家桶”体验 |
| RPC | OpenFeign/Dubbo | grpc-go + resty | proto/HTTP |
| 熔断限流 | Sentinel | sony/gobreaker + x/time/rate | 进程内 + 网关 |
| 持久层 | MyBatis/JPA | sqlc / GORM + pgx | 类型安全优先 sqlc |
| 分布式事务 | Seata | Outbox/Saga/DTM | 优先本地事务 |
| 安全 | Spring Security | golang-jwt + Casbin | RBAC/ABAC |
| 校验 | Bean Validation | go-playground/validator + oapi-codegen | 契约联动 |
| 任务 | XxlJob | asynq + robfig/cron | 队列+定时 |
| 消息 | RocketMQ | Kafka（sarama/kafka-go） | 事件总线 |
| 缓存 | Redisson | go-redis | 主从/哨兵 |
| 可观测 | Micrometer/Sleuth | OTel-Go + Prometheus + zap | trace/metric/log |
| 国密 | 厂商 SDK | tjfoc/gmsm | SM2/3/4 |
| 数据库迁移 | Flyway/Liquibase | golang-migrate | 版本化 DDL |
| 代码生成 | 手写 | oapi-codegen + sqlc | 契约/SQL→代码 |

## 附录 B · Go 依赖清单（起步）

```
github.com/gin-gonic/gin                  // HTTP 框架
github.com/oapi-codegen/oapi-codegen/v2   // OpenAPI → Gin handler/DTO
github.com/sqlc-dev/sqlc                  // SQL → 类型安全 Go
github.com/jackc/pgx/v5                   // PostgreSQL 驱动
gorm.io/gorm                               // ORM（备选，配合达梦驱动）
github.com/golang-jwt/jwt/v5              // JWT
github.com/casbin/casbin/v2               // RBAC/ABAC
github.com/go-playground/validator/v10    // 校验
github.com/sony/gobreaker                 // 熔断
golang.org/x/time/rate                    // 限流
github.com/redis/go-redis/v9              // 缓存
github.com/segmentio/kafka-go             // Kafka（或 github.com/IBM/sarama）
github.com/hibiken/asynq                  // 异步任务
github.com/robfig/cron/v3                 // 定时
go.uber.org/zap                           // 结构化日志
go.opentelemetry.io/otel                  // 链路
github.com/prometheus/client_golang       // 指标
github.com/golang-migrate/migrate/v4      // 数据库迁移
github.com/tjfoc/gmsm                     // 国密 SM2/3/4
github.com/minio/minio-go/v7              // 对象存储
go-clickhouse (github.com/ClickHouse/clickhouse-go/v2) // OLAP
google.golang.org/grpc                    // 服务间 RPC
```

## 附录 C · 里程碑甘特（表格视图）

| 工作流 | M0 (0–1) | M1 (2–6) | M2 (5–9) | M3 (9–12) |
|---|---|---|---|---|
| Go 骨架 / 代码生成 | ████ | ▓ 持续演进 | | |
| CI/CD / 质量门禁 | ████ | ████ | ████ | ████ |
| 认证授权 / 数据域 | ████ | ▓ 逐域细化 | █ | █ |
| 迁移 / 种子数据 | ████ | ███ | | |
| 核心域(P/E/F/R/G/A) | | ████ | ▓ | |
| 事务/幂等/单号/审计 | | ████ | ▓ | |
| 缓存/消息/事件 | | ███ | ███ | |
| 合同/转化/人员/涉密(C/T/S/X) | | | ████ | ▓ |
| 外部集成(财务/OA/身份/文献) | | | ████ | |
| 对象存储/全文检索/异步任务 | | | ████ | ▓ |
| AI 网关/LLM/RAG | | | ███ | ███ |
| 前端去 mock / RBAC UI | | ████ | ███ | |
| OLAP/ClickHouse/CDC/大屏 | | | | ████ |
| 性能/SLO/压测 | | | ▓ | ████ |
| 高可用/K8s/备份 | | | ▓ | ████ |
| 信创适配(麒麟/达梦/鲲鹏) | | ▓ 早期探测 | | ████ |
| 等保三级/涉密测评 | | | █ 启动 | ████ 收口 |

（██ 主投期，▓ 收尾/并行）

---

*本文与 `PRODUCT_PLAN.md`（做什么）、`TECH_ARCHITECTURE.md`（架构愿景，后端语言选型以本文 Go+Gin 为准）、`PRD/` 与 `design/`（唯一契约真源）配套；实施时以 `design/` 契约冻结为起点，按 §4 里程碑推进，§8 Backlog 为 M0 首批工单。*
