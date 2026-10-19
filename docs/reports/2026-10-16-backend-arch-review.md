# 后端方案架构与技术选型评估

> 日期：2026-10-16 · 范围：`backend-go`（ark，科研管理系统 Go 后端）
> 依据：go.mod、internal 全量布局、router.go、sqlc.yaml、migrations、middleware、本日开发实证

> ⚠️ **勘误（2026-10-16 评审后修订，见 `2026-10-16-backend-optimization-plan-review.md`）**
> 本报告 4 处判断经取证后失实，阅读时请以勘误为准：
> 1. **CI 并非生效中的质量资产**：13 次运行全部 failure，第一步 `gofmt` 即失败（32 个文件未格式化），`lint/单测/漂移/集成` 四层守卫**从未执行**。据此，第五节 R2/R5 的「已有守卫保护」相关推论不成立。
> 2. **R4 归因错误**：CI 的集成 job 用的是**空库**（且从未跑过），脏数据问题**只存在于本地**；且仓库内没有任何测试调用迁移，该 job 按现状运行必失败。
> 3. **P2 的「govulncheck 进 CI」与 P3「Makefile 收口」为冗余建议**：`make vuln/lint/drift/ci/codegen` 与 3 个 CI job 均已存在（缺的是「跑得起来」）。
> 4. **R2 附注「本地手动 psql」归因不准**：`cmd/server/main.go:42` 启动即 `migrate.Up`，生产路径正常；手动 psql 是**测试库缺迁移入口**的替代动作。
>
> 另有 6 个更高优先级问题见评审文档第三节（F1~F6），其中 F2 为本次会话引入的 CI 回归，已修复（commit `15dd156`）。

---

## 一、总体判断

**契约先行 + 竖切模块化的 Go 单体，选型现代且克制，工程质量高于同类内部系统平均水平。**
sqlc 类型安全的存储层、OpenAPI 契约校验测试、Casbin 三层授权、Redis 幂等中间件都是实打实落地的，不是纸面架构。

主要风险集中在四处：**passthrough 兜底绕过了整个鉴权链**（最严重）、**schema 双源漂移**、**事务/授权编排散落在 handler**、**测试共享真库产生的回归噪音**。

---

## 二、架构总览

```
cmd/server/main.go (107 行，纯装配)
  └─ internal/router.go Build()          ← 唯一组装点
       ├─ 横切：TraceID(zap) + Recover
       ├─ 公开：/healthz、/auth/login（bcrypt）
       ├─ /api/v1 组：JWT + Casbin → 幂等(Redis 24h) → 15 个业务模块
       └─ NoRoute → oapi.Passthrough     ← 未实现契约端点的样例兜底 ⚠️

modules/（按业务竖切，一域一包，互不 import 对方 store）
  p(申报) project(E 项目) funding(F 经费) output(R 成果)
  expertreview(N 评审) notify(NF 通知) archive(O 档案) activity
  performance(M 绩效) dataio(T 导入导出) dataops(D 大屏) sysadmin(U 管理域)

platform/（横切能力）
  auth(JWT+Casbin+policy.csv) middleware(Auth/Idempotency/Recover)
  oapi(自研 spec/generator/passthrough/validate) httpx(统一响应+错误码)
  db(pgxpool) storage(MinIO) llm(NewAPI OpenAI 兼容) approval migrate seeddemo

db/
  schema/*.sql（sqlc 摘录裁剪版）+ query_*/（9 个生成块）→ sqlc 1.27
migrations/（golang-migrate，000001~000015，真源）
```

**规模**：247 个 Go 文件，其中 81 个测试文件（≈33%）；15 个 migration；约 12 个业务竖切。

---

## 三、技术选型逐项评价

| 选型 | 版本 | 评价 | 替代方案对比 |
|---|---|---|---|
| **Gin** | 1.10 | ✅ 稳妥。生态成熟、团队熟悉、性能足够。NoRoute 兜底路由的用法是其灵活性体现 | chi（更贴 net/http 标准）、echo；无换的必要 |
| **pgx v5 + sqlc 1.27** | 5.6.0 | ✅ 本方案最大亮点。SQL 即代码、编译期类型安全、零反射。pgtype 直接暴露是把双刃剑（JSON 序列化 Numeric 踩过坑） | GORM（运行时反射、N+1 难控）、ent（多一层抽象，SQL 不可控）；单库 + SQL 密集场景 sqlc 明显更优 |
| **golang-migrate** | 4.17 | ✅ 标准选择。但**本地开发靠手动 psql 应用 + 手动推进 schema_migrations 版本**（000014/000015 均如此），流程脆 | atlas、goose；建议至少在 Makefile 收口 |
| **Casbin** | 2.135 | ✅ policy.csv 静态策略 + 三层授权（路由 meta / policy / caps）。RBAC 模型够用；策略在线编辑（粒度②）是已知深水区 | 自研 RBAC 表；Casbin 的 matcher 调试成本略高但值得 |
| **golang-jwt v5** | 5.3 | ✅ 标准库级选择 | — |
| **自研 oapi 契约件**（spec/generator/passthrough/validate，gojsonschema） | — | ⚠️ 有创意也有代价。契约校验测试（响应 data 对 schema）是质量护城河；但 passthrough 兜底是双刃剑（见风险 R1/R9） | oapi-codegen（生成 server stub，无样例兜底语义） |
| **Redis + 自研幂等中间件** | 9.5.1 | ✅ captureWriter 同时写底层与 buf，注释里明确修正了原稿缺陷，工程意识好 | — |
| **MinIO** | 7.0.66 | ✅ 接口 `storage.Storage` 抽象 + nil 降级 50301，无 MinIO 宿主仍可编译路由 | S3 兼容，换云不换码 |
| **zap** | 1.27 | ✅ 结构化日志 + TraceID 中间件 | 缺 metrics/OTel（见 R7） |
| **excelize / ledongthuc-pdf** | 2.8.1 | ✅ T13 导入导出、任务书解析够用；pdf 库能力弱（纯解析），已用 LLM 补 | — |
| **LLM（NewAPI OpenAI 兼容）** | — | ✅ 未配置自动降级（AI 审核 → REVIEW、任务书 → 人工），依赖降级设计好 | — |
| **Go 1.25** | — | ⚠️ 激进；x/crypto v0.23 偏旧（ssh CVE-2024-45337 修复于 0.31，虽未用 ssh 也应例行升级） | — |

**依赖面总体干净**：直接依赖 13 个，无 ORM、无 DI 框架、无重量级全家桶——克制是这个后端最值得保持的气质。

---

## 四、架构亮点

1. **契约是真源，且被测试强制**。`contract_test.go` 逐端点校验响应 schema；「DDL/契约为真源」写进注释铁律。前后端联调争议基本为零。
2. **竖切模块 + 单一写者模式**。N（评审）不直接改 E/R 表，经 `expertreview.NewHandler(pool, projH, outH)` 注入回调写者；notify 作为 Notifier 接口注入 funding/project——模块间依赖全部走显式接口，可拆性保留了。
3. **软降级链完整**。LLM 未配置→降级、MinIO 缺失→50301、字典拉取失败→前端 fallback、grants 失败→静态 meta.roles。单机演示与生产形态都跑得起来。
4. **幂等中间件设计正确**（写方法全组覆盖、响应缓存回放、24h TTL）。
5. **sqlc 多块生成绕开 wazero OOM** 的工程决策（schema 摘录裁剪）虽是权宜之计，但被文档化了（sqlc.yaml 注释）。

---

## 五、风险与短板（按严重度）

### R1 · passthrough 鉴权旁路（P0，安全）
`e.NoRoute(oapi.Passthrough(d.Spec))` 挂在引擎根上，**注释自己承认「不经分组中间件」**——所有命中契约但未手工实现的端点（ai-fill、export、metrics、patents、push-items 等 20+ 个）**无需 JWT、不走 Casbin、不进幂等**，直接返回样例数据。当前是演示态可接受，但：① 无鉴权即可探测全契约面；② 任何一个 passthrough 端点被「临时」依赖，就是权限洞。
**建议**：把兜底从 NoRoute 改为在 `/api/v1` 组内注册（`api.Any("/*path")` + spec 匹配），让它天然吃到 Auth/Casbin/幂等；工作量的半天的量级。

### R2 · schema 双源漂移（P1，正确性）
sqlc 吃的是 `db/schema/*.sql` 手工摘录，migrations 才是真源。000014 加列、000015 建表都要**人肉同步两处**，漏一次就是「本地能编译、CI/新环境跑不起来」或反向。这是本日开发中最费心的机械劳动。
**建议**：摘录由 migrations 自动派生（构建脚本 `cat migrations/*.up.sql | 过滤非 DDL 噪音` 生成 schema 摘录），删掉手工维护。

### R3 · 事务与编排散落 handler（P1，演进性）
无 service 层，handler 直接 `h.q.Xxx`；首个事务先例（page-grant 先删后插）以「Handler 持 pool」方式落地——这个先例会扩散。授权判断、通知触发、事务边界、业务校验混在同一层，handler 会越来越肥。
**建议**：不必引完整 service 层，但事务应收口为 `platform/db.WithTx(ctx, pool, func(q *store.Queries) error)` 一类 helper，handler 只描述流程。

### R4 · 本地测试库污染（P1，效率）〔勘误：范围仅限本地〕
**本地**开发把集成测试打在同一个 `ark` 库上，历史脏数据已实际造成 notify/p 包「与本改动无关」的失败（本日 stash 验证过）。**CI 侧不受影响**（用空库），但 CI 的集成 job 因缺少迁移步骤从未成功运行过。
**建议**：新增 `cmd/migrateup` 复用既有 `platform/migrate.Up`；本地用 template database（`CREATE DATABASE ... TEMPLATE`）每轮起干净库。验收 = 连续两次 `make test-integration` 全绿。

### R5 · 依赖健康（P2）
x/crypto v0.23（2024-06）落后约一年半；`go 1.25` + 最新依赖混搭，建议开 govulncheck 进 CI 例行扫。

### R6 · 软删靠纪律（P2）
`deleted = 0` 全靠每条 SQL 手写；漏写即数据泄漏到列表。视图层（Postgres VIEW）或 sqlc 查询模板可以兜底，但当前规模靠 review 也能接受。

### R7 · 观测性半成品（P2）
有 zap + TraceID，无 Prometheus metrics、无慢查询日志、无 pprof 开关。上生产前应补：请求时长/错误率直方图 + `/debug/pprof`（env 门控）。

### R8 · 分页/错误码约定良好但未全部收口
httpx 统一了 `{code, message, data}` 信封与 4 位业务码（40001/40901/50001…），但个别 handler 仍手写 `gin.H`。小问题，例行 review 即可。

---

## 六、单体 vs 微服务：当前选择正确

团队 1-2 人、单 PostgreSQL、演示 + 中型生产场景——**单体是唯一正确答案**，且本方案的单体做成了「模块化单体」：竖切清晰、模块间只经接口通信、passthrough/单一写者等机制天然留了拆分缝。**不建议**为「架构先进性」引入微服务/消息队列；若未来拆分，F（经费）与 N（评审）是最独立的两个竖切，Notifier/Notifiee 接口就是现成的防腐层。

---

## 七、行动建议

| 优先级 | 事项 | 量级 |
|---|---|---|
| **P0** | passthrough 迁入 `/api/v1` 组内注册，吃上 Auth/Casbin/幂等；顺手清点 passthrough 端点清单 〔勘误：更优做法是给 `NoRoute` 挂中间件链，3 行即可，见评审 §4.1〕 | 0.5 天 |
| **P0′** | 〔勘误新增〕恢复 CI 为真信号：`gofmt -w` 32 文件 + CI 集成 job 补迁移步骤 + CI 改用 `make fmt-check`/`make drift` | 0.75 天 |
| **P1** | schema 摘录从 migrations 自动派生，消除双源 〔勘误：先 spike「sqlc 直读 migrations 目录」，失败则用 pg_dump 派生；原「cat 过滤」方案不可取〕 | 0.5 天 |
| **P1** | `db.WithTx` 事务 helper，事务不再经 Handler.pool 裸写 〔勘误：直接用 sqlc 生成的 `q.WithTx(tx)`〕 | 0.5 天 |
| **P1** | 本地测试库模板化隔离（`cmd/migrateup` + template DB），让集成测试连续两次绿 〔勘误：不引 testcontainers〕 | 0.5 天 |
| **P1** | 〔勘误新增〕drift 清单动态化（`find` 列举 store 目录）+ CI 复用 `make drift`，消除 F4 双源 | 0.25 天 |
| **P1** | 〔勘误新增〕`gen-sqlc` 改用预编译二进制（当前 Makefile 目标在本机不可用） | 0.25 天 |
| **P2** | 依赖例行升级（x/crypto 优先）；vuln 钉版本并接入 CI；CI go 版本与 go.mod 对齐 | 1 天 |
| **P2** | Prometheus 指标 + pprof（标签用 `FullPath()`、NoRoute 归一 `unmatched`；pprof 独立门控） | 1 天 |

**一句话结论**：这套后端的底子（sqlc + 契约校验 + 竖切 + 克制依赖）值得长期投入，四个 P0/P1 补完后可以放心从演示态走向生产态。
