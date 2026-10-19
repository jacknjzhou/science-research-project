# 优化方案评审：`2026-10-16-backend-arch-review.md` 是否够好？

> 评审日期：2026-10-16 · 评审对象：同目录 `2026-10-16-backend-arch-review.md` 的「风险清单 + 行动建议」
> 方法：superpowers 工程纪律（证据优于声称 / 降低复杂度优先 / TDD 不可跳过 / 系统化优先 / 完成前验证）
> 结论一句话：**方向对，事实基础有 4 处失实，且漏掉了比原清单更严重的 6 个问题；P0 方案有更小更安全的替代。**

---

## 一、评审方法与判定口径

| 纪律 | 本次具体做法 | 判定口径（三关） |
|---|---|---|
| 证据优于声称 | 每条建议逐条用命令/API 取证，不接受「显然」 | ① 事实核验（有可复现命令） |
| 降低复杂度是首要目标 | 同一目标必给「最小改动解」再给「完整解」 | ② 是否最小（改动行数/新增概念数） |
| TDD 不可跳过 | 每条优化必须能写出一条**当前为 RED** 的测试 | ③ 有无可执行验收 |
| 系统化优先于临场 | 失败逐层归因（CI 红 → job → step → 文件 → 行） | — |
| 完成前验证 | 不设「看起来好了」，只设可复制粘贴的验收命令 | — |

---

## 二、原报告事实核验：4 处失实（含证据）

| # | 原报告表述 | 取证 | 实际 | 判定 |
|---|---|---|---|---|
| 1 | 「CI 工程质量高」隐含把 `drift`/`lint`/`vuln` 当**已生效资产** | `api.github.com/.../actions/runs` → **13 次运行全部 failure**，最新 5 次（run#9~#13）全 failure；run#13 jobs → `gofmt` **failure**，`vet`/`golangci-lint`/单测/集成/漂移**全部 skipped** | CI 的第一步就失败，**后面所有守卫从未执行过** | ❌ **失实（最严重）** |
| 2 | R4「集成测试全部打同一个库，每次回归都要人工甄别噪音」 | `grep -rn "migrate" --include="*_test.go"` → **仓库内无任何测试调用迁移**；`db.Connect` 不迁移；`go-ci.yml` integration job 用空库 + 注释声称「测试内 migrate.Up」 | 脏数据问题**只存在于本地**；CI 那边是**空库跑集成测试 = 设计上必失败**，且因 `needs: unit` 从未真正跑过 | ⚠️ **范围/归因双错** |
| 3 | P2「govulncheck 进 CI」；P3「Makefile 收口 migrate/sqlc/build」 | `cat Makefile` → 已有 `fmt-check/vet/lint/cover/ci/vuln/drift/codegen/test-integration`；`.github/workflows/go-ci.yml` 已有 3 个 job | 已存在 | ❌ **冗余建议** |
| 4 | R2 附注「本地开发靠手动 psql 应用迁移，流程脆」 | `cmd/server/main.go:42` → 启动即 `migrate.Up(cfg.DatabaseURL, cfg.MigrationsDir)` | 生产路径没问题；手动 psql 是**测试库没有迁移入口**的替代动作 | ⚠️ **归因错，真问题在 3.3** |

---

## 三、原报告漏掉的 6 个问题（优先级更高）

| 编号 | 发现 | 证据 | 影响 |
|---|---|---|---|
| **F1** | **CI 自 10-15 起持续全红**；`gofmt -l .` 列出 **32 个未格式化文件**（含本会话改过的 `internal/modules/project/handler.go`） | run#9~#13 全 failure；`gofmt -l .` → 32 行 | 一切「CI 保护」叙事失效；lint/单测/漂移/集成四层守卫**从未跑过** |
| **F2** | **我自己的 commit `dc9dba8` 引入第二处红灯**：`TestListMyProjects_AdminSeesAll` 直接 `db.Connect(os.Getenv(...))`，无 skip 门控 → CI 无库单测路径**必失败** | 无 `ARK_TEST_DATABASE_URL` 跑 `go test ./internal/modules/project/` → `--- FAIL` + `dial unix ... no such file` | 即使修好 gofmt，CI 仍红 |
| **F3** | **集成 job 从未执行过**，且其注释与代码不符（注释说测试内跑迁移，实际没有任何测试跑迁移） | jobs API：integration job `conclusion: skipped`, `steps: []` | 修好 F1/F2 后，集成 job 会在 `relation "e_project" does not exist` 上失败——**必须补迁移步骤** |
| **F4** | **漂移守卫自己在漂移**：`Makefile` 的 `drift` 列 8 个 store 目录（漏 `funding/store`、`notify/store`）；CI 的 `contract-drift` job 内联只列 `p/store`（漏 9 个） | `find internal/modules -type d -name store` → 10 个；两处清单互不相同 | 正是原报告 R2 抱怨的「双源」同型问题，出现在守卫自身 |
| **F5** | CI `go-version: "1.22"` 与 `go.mod` 的 `go 1.25` 不一致 | `go-ci.yml` vs `go.mod` | 依赖 toolchain 自动下载，构建环境不可复现 |
| **F6** | `make gen-sqlc`（钉 `GOTOOLCHAIN=go1.23.4`）**在本机已不可用**；本会话只能用官方预编译二进制生成 | 本会话实证：`GOTOOLCHAIN=go1.23.4 go run ... sqlc@v1.27.0` → cgo/`strchrnul` 编译失败；改用 `/tmp/sqlc-bin/sqlc` 成功 | 代码生成路径没有可复现的单一入口；`make drift`/`make codegen` 在 macOS 上跑不通 |

---

## 四、逐项更优方案

### 4.1 P0 passthrough 鉴权 —— 原建议「迁入组内注册」过重，改「NoRoute 链式挂载」

| | 内容 |
|---|---|
| 原建议 | 把兜底从 NoRoute 改为在 `/api/v1` 组内注册（`api.Any("/*path")` + spec 匹配） |
| **更优** | **直接给 NoRoute 挂中间件链**——`NoRoute(handlers ...HandlerFunc)` 本身就是变参（gin.go:298 已核验），且 `middleware.Auth` 只依赖 `c.Request.URL.Path` + Casbin `keyMatch`，**不依赖 gin 路由树**，天然可在 NoRoute 上下文工作 |
| 为什么更好 | 改 1 处、3 行；不需要 `api.Any` 通配（会和既有静态路由注册顺序产生新风险）、不需要改 spec 匹配逻辑 → **新增概念数 0** |
| 额外价值（原报告没有） | ① 未实现的**写方法**（POST/PUT/DELETE/PATCH）应返回 **501**，而不是伪造 200「写成功」；② 响应加 `X-Ark-Stub: 1` 头，调用方可判真假；③ `ARK_PASSTHROUGH=0` 生产可整体关闭 |
| RED 验收 | `TestPassthrough_NoToken_401` / `TestPassthrough_TokenNoPolicy_403` / `TestPassthrough_WriteMethod_501` / `TestPassthrough_GetWithAuth_200AndStubHeader`（当前第一条即 RED：无 token 也返回 200） |

```go
// internal/router.go —— 当前
e.NoRoute(oapi.Passthrough(d.Spec))
// 修订
e.NoRoute(
    middleware.Auth(d.Cfg.JWTSecret, d.Enforcer),
    middleware.Idempotency(d.Redis, 24*time.Hour),
    oapi.Passthrough(d.Spec), // 内部：写方法 → 501；命中的响应加 X-Ark-Stub: 1
)
```

### 4.2 P0′ 恢复 CI 为「真信号」（新增项，优先级在原清单全部之上）

内容的正确性依赖守卫，守卫已死 → **先复活信号，再谈其他优化**。

| 任务 | 动作 | 验收 |
|---|---|---|
| a | `gofmt -w` 32 个文件（**纯格式，零语义**），单独一个 commit（便于 review 归档） | `gofmt -l .` 输出为空 |
| b | 已提交的 F2 修复（`testPool(t)` 统一 skip 门控）| 无库路径 SKIP、有库路径 PASS（**已在本轮完成**：commit `15dd156`） |
| c | CI 集成 job 补迁移步骤（见 4.3） | integration job 首次真正执行并绿 |
| d | CI 首关加 `make fmt-check`（复用 Makefile，避免又一份内联命令——同一纪律：**消除重复清单**） | — |

> 建议：本地加 `make ci` 到提交流程（或 pre-push hook），避免「本地全绿、CI 红两天没人知道」。

### 4.3 让集成 job 真的能跑（新增）

| | 内容 |
|---|---|
| 事实 | 测试不跑迁移；CI 用空库；注释说反了（F3） |
| **更优方案** | 新增 `cmd/migrateup`（约 10 行，复用既有 `platform/migrate.Up`，与 `cmd/server` 同风格）→ CI step: `go run ./cmd/migrateup`；**同一个工具顺带解决本地测试库**（R4 的正解） |
| 为什么不用 `migrate` CLI | 引入新依赖（golang-migrate CLI 二进制）→ 与「复用已有代码」比是额外概念；`platform/migrate` 已在仓库里 |
| RED 验收 | 对空库跑集成测试 → `relation "e_project" does not exist`（当前必现）；加迁移步骤后绿 |
| 顺带 | 删掉 CI 文件中与代码不符的注释（注释与代码不一致是认知债，比缺注释更有害） |

### 4.4 schema 单源 —— 原建议「cat migrations 过滤」是自制解析器，先 spike 再定

| 方案 | 做法 | 代价 | 评价 |
|---|---|---|---|
| **A（首选）** | sqlc 直接吃 `migrations/` 目录（sqlc 原生识别 golang-migrate 命名），删掉 `db/schema/*.sql` | 30 分钟 spike：改 `sqlc.yaml` 的 `schema:` 指向目录跑一次 | 若能解析 → 概念数 -1（少一套 schema），最彻底 |
| B（回退） | 临时容器起 PG → `migrate up` → `pg_dump --schema-only` 派生 `db/schema/*.sql` | 需要一个 make 脚本 | 权威（来自真库），但要引 pg_dump |
| C（兜底） | 维持手工摘录，但把 `db/schema` 纳入 `drift` 的 diff 清单 | 最小 | 只防「改了 migrations 忘了改摘录」的显性漂移 |

> 原报告的「cat migrations | 过滤噪音」= 自制 SQL 解析/裁剪器，脆弱且不可验证 → **不推荐**。
> 决策门：A 的 spike 结果二选一（A 成功 → A；失败 → B），并写一份 5 行 ADR 记录理由。

### 4.5 漂移清单动态化（消 F4）

```make
STORE_DIRS := $(shell find internal/modules -type d -name store | sort)
drift: codegen
	@$(GO) build ./...
	@git diff --exit-code -- $(STORE_DIRS) api/gen db/schema \
	    migrations/000001_init.up.sql migrations/000001_init.down.sql
```
CI 侧**删掉内联 diff 清单**，改为直接 `make drift`（消除 Makefile/CI 双源，这正是 F4 的根因）。

### 4.6 事务 helper —— 用 sqlc 自带的 `WithTx`，别自造抽象

证据：`internal/modules/funding/store/db.go:28` 已生成 `func (q *Queries) WithTx(tx pgx.Tx) *Queries`。

```go
// internal/platform/db/tx.go（新，~25 行）
func WithTx(ctx context.Context, pool *pgxpool.Pool, fn func(*store.Queries) error) error {
    tx, err := pool.Begin(ctx); if err != nil { return err }
    defer func() { if err != nil { _ = tx.Rollback(ctx) } }()
    if err = fn(store.New(tx).WithTx(tx)); err != nil { return err }
    return tx.Commit(ctx)
}
```
验收（现成安全网）：把 `handler_page_grant.go` 的手写事务迁移过去，`TestPageGrantLifecycle` 必须保持绿——**行为等价替换，测试不改**。

### 4.7 本地测试库隔离 —— template database，不引 testcontainers

| 方案 | 评价 |
|---|---|
| **template DB（推荐）** | `ark_tpl`（migrate up 一次）→ 每轮 `CREATE DATABASE ark_test_<epoch> TEMPLATE ark_tpl` → 跑测试 → DROP。毫秒级、零新依赖、CI/本地同一脚本 |
| testcontainers | CI 已 hermetic（空库+迁移），本地再拉容器 = 额外依赖与启动成本 → **YAGNI** |
| 事务回滚法（BEGIN/ROLLBACK） | 与「测试内多连接/httptest 引擎」不兼容，不适用 |

验收命令：`make test-integration` **连续执行两次均全绿**（当前第二次因脏数据 RED——已实证）。

### 4.8 代码生成工具链可复现（F6）

```make
SQLC_VERSION := 1.27.0
tools/sqlc:
	@curl -sL https://downloads.sqlc.dev/sqlc_$(SQLC_VERSION)_$(OS)_$(ARCH).tar.gz | tar -xz -C tools
gen-sqlc: tools/sqlc
	./tools/sqlc generate
```
去掉 `GOTOOLCHAIN` 依赖（它在本机已证明不可行），钉版本 + 校验和；CI 同样用二进制，保证「生成结果与机器无关」。

### 4.9 观测性与依赖（在原 P2 基础上纠偏）

| 项 | 纠偏 |
|---|---|
| Prometheus 指标 | 标签必须用 `c.FullPath()`（gin 路由模板）而非原始 path；**NoRoute 下 `FullPath()` 为空** → 需归一到 `unmatched`，否则 UUID/ID 会把标签基数打爆。**与 4.1 有耦合 → 先做 4.1 再做指标** |
| pprof | 独立端口或 `ARK_ENABLE_PPROF=1` 门控，不与业务端口同暴露 |
| govulncheck | CI 中**钉版本**（现状 `@latest` 破坏可复现性）；建议 `continue-on-error: false` + 月度升级窗口 |
| CI Go 版本 | 与 `go.mod` 对齐（`1.25`），或显式声明支持的最低版本并下调 `go.mod`（二选一，写进 README） |

---

## 五、修订后的执行路线（superpowers 7 步映射）

| 步 | 动作 | 产出 |
|---|---|---|
| 1 头脑风暴/规格 | 已在本评审完成：方案 A/B 的选择门、写方法 501 的语义、YAGNI 清单 | 本文档 |
| 2 隔离工作区 | `git worktree add ../ark-opt feat/backend-hardening`（develop 保持可发布） | worktree |
| 3 写实施计划 | 每个任务 2-5 分钟、含精确路径与验收命令（下方样例） | `docs/superpowers/plans/2026-10-16-backend-hardening.md` |
| 4 子代理执行 | 每任务一个全新子代理；两段式评审（先规格符合度 → 再代码质量） | 任务级 PR/commit |
| 5 TDD | 严守 RED→GREEN：先写失败测试（如 `TestPassthrough_NoToken_401`），看它红，再改代码 | 每条优化的红→绿记录 |
| 6 代码评审 | 每 2 个任务一次对照评审，Critical 阻断 | 评审记录 |
| 7 收尾 | `make ci` + `make drift` + 集成两次全绿 + CI 真绿截图 | 合并决定 |

**任务粒度样例（P0 passthrough，共 5 个任务）**

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| 1 | 写 4 条 RED 测试（无 token/无策略/写方法/带头） | `internal/router_test.go`（新增用例） | 4 红 |
| 2 | NoRoute 挂 Auth+Idempotency 链 | `internal/router.go` | 前 2 条转绿，后 2 条仍红 |
| 3 | 写方法返回 501 | `internal/platform/oapi/passthrough.go` | 第 3 条绿 |
| 4 | 响应加 `X-Ark-Stub` + env 门控 | 同上 + `internal/config` | 4 条全绿 |
| 5 | 回归：`go test ./...`（无库）+`make ci` | — | 全绿 |

**工作量（修订后）**：CI 恢复 0.5d → passthrough 0.5d → 集成迁移 0.25d → drift/工具链 0.5d → schema spike 0.5d → WithTx 0.5d → 本地 test-db 0.5d → 观测性 1d ≈ **4.25 天**，但前 1.25 天就把「CI 可信」拿回来，后续每一项都可被守卫保护。

---

## 六、明确不做（YAGNI）

- ❌ testcontainers（CI 已隔离，本地 template DB 足够）
- ❌ 自研 migrations 解析/裁剪器（4.4 方案 A/B 二选一即可）
- ❌ 自造事务框架（用 sqlc `WithTx`）
- ❌ ORM / DI 容器 / 微服务拆分 / 消息队列（原报告结论维持）
- ❌ 为「完整性」把 `pending-claim`/`output/mine` 改成全量（语义是「我的」，改了反而是错）

---

## 七、附录：证据复现命令

```bash
# F1：CI 全红 + gofmt 阻塞
curl -s "https://api.github.com/repos/jacknjzhou/science-research-project/actions/runs?per_page=5" | grep -E '"conclusion"|"run_number"'
curl -s "https://api.github.com/repos/jacknjzhou/science-research-project/actions/runs/38894304529/jobs" | grep -E '"name"|"conclusion"' | head -20
cd backend-go && gofmt -l . | wc -l        # → 32

# F2/F3：测试不跑迁移 + 我的测试非 skip-safe
grep -rn "migrate" --include="*_test.go" internal/ | grep -v platform/migrate   # → 无输出
go test -count=1 ./internal/modules/project/   # 修复前 FAIL；修复后 → 全部 SKIP + PASS

# F4/F5/F6
find internal/modules -type d -name store | sort   # 10 个 vs Makefile drift 列 8 个
grep -n "go-version" ../.github/workflows/go-ci.yml; grep -n "^go " go.mod
GOTOOLCHAIN=go1.23.4 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate   # 本机编译失败

# 环境现状（评审时）
docker ps   # → 空：Postgres/后端/前端容器当前均未运行，localhost:8787 不可达
```

---

**一句话给结论**：原报告的**风险方向是对的，但把「已存在的设施」当资产、把「从未运行的守卫」当保护**；更优的工程实践是——**先用最小改动（1 行中间件链）修安全洞，再用最小动作（gofmt + skip 门控 + 一条迁移命令）把 CI 复活成真信号**，其余优化在这个信号保护下按 TDD 逐项推进。
