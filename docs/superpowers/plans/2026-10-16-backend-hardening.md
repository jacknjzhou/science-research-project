# 后端加固实施计划（backend-hardening）

> 日期：2026-10-16 · 分支：develop（沿用项目惯例：逐任务 commit，禁止推送）
> 依据：`docs/reports/2026-10-16-backend-arch-review.md`（含勘误）+ `docs/reports/2026-10-16-backend-optimization-plan-review.md`
> 执行纪律：superpowers —— 每任务先验证「当前为 RED」再改，改完看 GREEN，逐任务提交；
> 完成前验证 = 计划内验收命令逐条跑，不接受「看起来好了」。

## 前置条件与基线（取证结论，2026-10-16）

| 事实 | 证据 |
|---|---|
| gofmt 未格式化文件 32 个 | `gofmt -l . \| wc -l` → 32 |
| CI go-version 1.22 × 3 处，go.mod 为 1.25 | `.github/workflows/go-ci.yml` |
| integration job 空库且无迁移步骤，注释与代码不符 | go-ci.yml L56-58 |
| drift 清单 Makefile 列 8 个 store，实际 10 个；CI 内联只列 `p/store` | `find internal/modules -type d -name store` → 10 |
| 手写事务 2 处（评审只提了 1 处） | `sysadmin/handler_page_grant.go:58`、`performance/handler.go:224` |
| Idempotency 对 GET/无 Key 直接放行、不触碰 Redis（nil 安全） | idempotency.go L39-48 |
| passthrough 兜底 `e.NoRoute(oapi.Passthrough(d.Spec))` 无鉴权 | router.go:103 |
| sqlc 直读完整 migrations 已两次记载失败（~394KB OOM + 表达式索引解析错） | sqlc.yaml 注释、o_schema.sql 注释 |

**环境注意**：本机 Docker 容器当前全停。凡验收涉及真库的任务（4/6/11 以后的集成回归），需先 `docker compose up -d`（仓库根 docker-compose.yml）；容器未起时这些验收降级为「无库单测全绿」，并在任务卡标记待补验。

**工作目录**：除 CI 文件外全部命令在 `backend-go/` 执行。

---

## 批次一：复活 CI 为真信号（P0′，约 0.5 天）

### 任务 1：gofmt 全量格式化（独立 commit，纯格式零语义）
- 执行：`cd backend-go && make fmt`
- 验证：`gofmt -l .` 输出为空；`go build ./...` 成功
- 提交：`git add -A && git commit -m "style: gofmt 全量格式化（32 文件，纯格式无语义变更）"`

### 任务 2：CI Go 版本对齐 go.mod（修 F5）
- 文件：`.github/workflows/go-ci.yml`
- 改动：3 处 `go-version: "1.22"` → `go-version: "1.25"`
- 验证：`grep -n "go-version" .github/workflows/go-ci.yml && grep -n "^go " backend-go/go.mod` 两处一致

### 任务 3：unit job 首关复用 Makefile（消除重复清单）
- 文件：`.github/workflows/go-ci.yml`
- 改动：`- name: gofmt` 步骤的 `run: test -z "$(gofmt -l .)"` → `run: make fmt-check`
- 验证：本地 `cd backend-go && make fmt-check` 退出码 0

### 任务 4：新增 cmd/migrateup（CI 集成与本地测试库共用迁移入口）
- 文件：`backend-go/cmd/migrateup/main.go`（新建，目录 cmd/ 下现有仅 server）
- 完整代码：
```go
// Command migrateup 对 ARK_DATABASE_URL 指向的库执行 golang-migrate Up。
// 供 CI 集成 job 与本地测试库初始化复用（与 cmd/server 启动迁移逻辑同源）。
package main

import (
	"log"

	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/platform/migrate"
)

func main() {
	cfg := config.Load()
	if cfg.DatabaseURL == "" {
		log.Fatal("ARK_DATABASE_URL 未设置")
	}
	if err := migrate.Up(cfg.DatabaseURL, cfg.MigrationsDir); err != nil {
		log.Fatalf("migrate up: %v", err)
	}
	log.Println("migrate up 完成")
}
```
- 验证（需 Postgres）：`ARK_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable go run ./cmd/migrateup` 首次成功、重复跑幂等成功

### 任务 5：Makefile drift 清单动态化（修 F4 双源）
- 文件：`backend-go/Makefile`
- 改动：drift 目标前加一行，diff 清单改用变量：
```make
STORE_DIRS := $(shell find internal/modules -type d -name store | sort)
```
原 `git diff --exit-code -- internal/modules/p/store ... api/gen ...` 中的硬编码 store 列表替换为 `$(STORE_DIRS)`，保留 `api/gen migrations/000001_init.up.sql migrations/000001_init.down.sql`
- 验证：`make drift` 全绿（同时验证任务 4 后 codegen 产物无漂移）

### 任务 6：CI integration job 补迁移步骤 + 修注释（修 F3）
- 文件：`.github/workflows/go-ci.yml`
- 改动：
  - 删除与代码不符的注释「迁移由测试内 migrate.Up 依 migrations/ 建表（空库起步）」
  - integration tests 步骤前插入：
```yaml
      - name: migrate test database
        run: ARK_DATABASE_URL=$ARK_TEST_DATABASE_URL go run ./cmd/migrateup
```
（注意：migrateup 读 `ARK_DATABASE_URL`，CI 环境变量是 `ARK_TEST_DATABASE_URL`，须显式中转）
- 验证：本地等价命令（空库场景）`docker compose up -d` 后对新建空库跑 migrateup + `make test-integration`

### 任务 7：CI contract-drift job 复用 make drift（消除 CI 内联清单）
- 文件：`.github/workflows/go-ci.yml`
- 改动：`assert no drift` 步骤整段替换为 `run: make drift`
- 验证：`make drift` 本地全绿（任务 5 已验）；确认 go-ci.yml 中不再出现 store 目录硬编码

### 任务 8：批次一回归 + 提交
- 验证：`cd backend-go && make ci`（fmt-check/vet/lint/test）全绿
- 提交：任务 2-7 合并一个 commit：`ci: 复活 CI——Go 1.25 对齐、fmt-check 复用、cmd/migrateup、drift 动态清单`
- 注：CI 真绿需推送后确认（本项目禁止推送，由用户决定推送时机）

---

## 批次二：passthrough 鉴权链（P0 安全，约 0.5 天）

### 任务 9：确认测试靶点（取证，不写码）
- 验证 1（未实现路由存在）：`grep -rn "patents\|ai-fill" backend-go/internal/modules/output/` 应无 `api.*patents` 路由注册
- 验证 2（契约已定义）：`grep -rn "patents" backend-go/../design/*.openapi.yaml` 确认 `GET /output/patents`、`POST /patents/{id}/fees` 存在
- 验证 3（403 靶点）：ark 测试用户角色为 R-STAFF/R-MANAGER（router_test.go L101 佐证）；policy.csv 中二者均无 `DELETE /api/v1/output/*` 授权 → 用 `DELETE /api/v1/output/1` 做 403 靶点
- 若验证 2 失败，501 用例改用契约中其他「未实现 + R-MANAGER 可写」端点（候选：`POST /push-items/{id}/import`）

### 任务 10：写 4 条 RED 测试（先红后绿，TDD）
- 文件：`backend-go/internal/router_test.go`（追加）
- 完整代码：
```go
// —— passthrough 鉴权链（NoRoute 挂 Auth+Idempotency 后的语义）——

func loginForTest(t *testing.T, e *gin.Engine) string {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"username": "ark", "password": "ark"})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("login=%d body=%s", rec.Code, rec.Body.String())
	}
	var env struct {
		Data struct {
			AccessToken string `json:"access_token"`
		} `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	return env.Data.AccessToken
}

func TestPassthrough_NoToken_401(t *testing.T) {
	e := buildForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/output/patents", nil)
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("no-token=%d want 401 body=%s", rec.Code, rec.Body.String())
	}
}

func TestPassthrough_TokenNoPolicy_403(t *testing.T) {
	e := buildForTest(t)
	tok := loginForTest(t, e)
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/output/1", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("no-policy=%d want 403 body=%s", rec.Code, rec.Body.String())
	}
}

func TestPassthrough_WriteMethod_501(t *testing.T) {
	e := buildForTest(t)
	tok := loginForTest(t, e)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/patents/p1/fees", bytes.NewReader([]byte(`{}`)))
	req.Header.Set("Authorization", "Bearer "+tok)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotImplemented {
		t.Fatalf("write=%d want 501 body=%s", rec.Code, rec.Body.String())
	}
}

func TestPassthrough_GetWithAuth_200AndStubHeader(t *testing.T) {
	e := buildForTest(t)
	tok := loginForTest(t, e)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/output/patents", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("stub-get=%d want 200 body=%s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("X-Ark-Stub") != "1" {
		t.Fatalf("缺 X-Ark-Stub 头")
	}
}
```
- 验证（RED）：`go test -run TestPassthrough ./internal/` → 第 1/2/4 条失败（当前 401 用例拿到 200；403 拿到 200；Stub 头不存在），第 3 条按任务 9 取证结果预期红
- 依赖：Redis 传 nil 安全已取证（GET 直接放行；POST 无 Idempotency-Key 直接放行，idempotency.go L39-48）

### 任务 11：NoRoute 挂中间件链（3 行改动）
- 文件：`backend-go/internal/router.go` L102-103
- 改动：替换为：
```go
	// 兜底：命中契约但未手工实现的路由 → passthrough。
	// NoRoute 不继承分组中间件，故显式挂 Auth+Idempotency（gin NoRoute 本身是变参，
	// middleware.Auth 只依赖 URL.Path + Casbin keyMatch，不依赖路由树，天然可在此工作）。
	// passthrough 目标从此受 JWT/Casbin/幂等约束；写方法在 Passthrough 内返回 501。
	e.NoRoute(
		middleware.Auth(d.Cfg.JWTSecret, d.Enforcer),
		middleware.Idempotency(d.Redis, 24*time.Hour),
		oapi.Passthrough(d.Spec, d.Cfg.PassthroughEnabled),
	)
```
- 验证：`go test -run "TestPassthrough_NoToken|TestPassthrough_TokenNoPolicy" ./internal/` → 2 条转绿；另 2 条仍红
- 已知行为变更（可接受）：未匹配的任意路径（如 /favicon.ico）从 404 变 401；`go test ./...` 回归时若有用例假设 404，按新语义修正用例

### 任务 12：Passthrough 写方法 501 + X-Ark-Stub + env 门控
- 文件 1：`backend-go/internal/platform/oapi/passthrough.go` — 整体替换为：
```go
package oapi

import (
	"net/http"
	"strconv"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// Passthrough 作为 gin NoRoute 兜底：命中契约但未手工实现的路由，依 design 生成合规示例响应。
// 挂载于 NoRoute 的 Auth+Idempotency 之后，语义标记：
//   - 命中契约的响应一律带 X-Ark-Stub: 1 头（调用方可判真假数据）；
//   - 未实现的写方法（POST/PUT/DELETE/PATCH）返回 501，不伪造「写成功」；
//   - enabled=false（ARK_PASSTHROUGH=0，生产推荐）时整体关闭，未实现端点一律 404。
func Passthrough(s *Spec, enabled bool) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !enabled {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "端点未实现")
			return
		}
		op := s.Match(c.Request.Method, c.Request.URL.Path)
		if op == nil {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "契约未定义该路由")
			return
		}
		switch c.Request.Method {
		case http.MethodPost, http.MethodPut, http.MethodDelete, http.MethodPatch:
			c.Header("X-Ark-Stub", "1")
			httpx.WriteErr(c, http.StatusNotImplemented, 50101, "端点未实现（passthrough 不模拟写操作）")
			return
		}
		data := op.Generate()
		// GET 列表路由落地真实分页参数（page/size 取查询串，缺省回退生成值）
		if m, ok := data.(map[string]any); ok {
			if list, hasList := m["list"].([]any); hasList && c.Request.Method == "GET" {
				m["page"] = atoiDefault(c.Query("page"), 1)
				m["size"] = atoiDefault(c.Query("size"), len(list))
			}
		}
		c.Header("X-Ark-Stub", "1")
		httpx.WriteOK(c, data)
	}
}

func atoiDefault(s string, def int) int {
	if s == "" {
		return def
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return n
}
```
- 文件 2：`backend-go/internal/config/config.go` — Config 结构体加字段 `PassthroughEnabled bool`，Load() 加 `PassthroughEnabled: get("ARK_PASSTHROUGH", "1") != "0",`
- 验证：`go test -run TestPassthrough ./internal/` → 4 条全绿

### 任务 13：批次二回归 + 提交
- 验证：`go build ./...` + `go test ./...`（无库路径全绿/SKIP）；重点观察既有 contract/契约类用例是否有「未匹配路径期望 404」的假设需修正
- 提交：`feat: passthrough 纳入鉴权链——NoRoute 挂 Auth+Idempotency，写方法 501，X-Ark-Stub 标记，ARK_PASSTHROUGH 门控`

---

## 批次三：代码生成工具链可复现（F6，约 0.25 天）

### 任务 14：gen-sqlc 改预编译二进制
- 文件 1：`backend-go/Makefile` — gen-sqlc 目标替换为：
```make
SQLC_VERSION := 1.27.0
SQLC_OS      := $(shell go env GOOS)
SQLC_ARCH    := $(shell go env GOARCH)

tools/sqlc: ## 下载钉版本 sqlc 预编译二进制（GOTOOLCHAIN go run 方式本机已实证不可行）
	mkdir -p tools
	curl -sL https://downloads.sqlc.dev/sqlc_$(SQLC_VERSION)_$(SQLC_OS)_$(SQLC_ARCH).tar.gz | tar -xz -C tools sqlc

gen-sqlc: tools/sqlc ## 由 db/query + schema 生成 DAL（sqlc 预编译二进制，与机器无关）
	./tools/sqlc generate
```
（删除原 GOTOOLCHAIN 注释块，保留 sqlc.yaml 路径说明部分）
- 文件 2：`backend-go/.gitignore` — 追加一行 `tools/`
- 验证：`make gen-sqlc` 成功且生成物无变化；`make drift` 全绿

### 任务 15：批次三提交
- 提交：`build: gen-sqlc 改用钉版本预编译二进制，代码生成路径可复现`

---

## 批次四：事务收口 WithTx（P1，约 0.5 天）

### 任务 16：新增 platform/db/tx.go
- 文件：`backend-go/internal/platform/db/tx.go`（新建）
- 设计说明：评审原稿签名 `func(*store.Queries) error` 不可行——各模块 store 是独立包独立 Queries 类型，单一签名无法覆盖；改为传裸 `pgx.Tx`，由 handler 内用现成的 `q.WithTx(tx)` 绑定（两处现场已在用），零新概念：
```go
package db

import (
	"context"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// WithTx 在事务中执行 fn：Begin → fn → Commit；fn 出错或 Commit 失败自动 Rollback。
// fn 内用各模块 sqlc 生成物 q.WithTx(tx) 构造绑定事务的 Queries。
// 纪律：handler 不再手写 Begin/Rollback/Commit（sysadmin/performance 两处收口于此）。
func WithTx(ctx context.Context, pool *pgxpool.Pool, fn func(tx pgx.Tx) error) error {
	tx, err := pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { if err != nil { _ = tx.Rollback(ctx) } }()
	if err = fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
```
- 验证：`go build ./...`

### 任务 17：迁移 sysadmin SavePageGrants（行为等价替换）
- 文件：`backend-go/internal/modules/sysadmin/handler_page_grant.go` L58-80
- 改动：Begin/defer Rollback/Commit 手写块替换为：
```go
	err = db.WithTx(c, h.pool, func(tx pgx.Tx) error {
		qtx := h.q.WithTx(tx)
		if _, err := qtx.DeleteAllPageGrants(c, d.TenantID); err != nil {
			return fmt.Errorf("清除旧授予: %w", err)
		}
		for _, g := range b.Grants {
			if err := qtx.InsertPageGrant(c, store.InsertPageGrantParams{
				TenantID: d.TenantID, PageName: g.PageName, RoleCode: g.RoleCode,
			}); err != nil {
				return fmt.Errorf("写入授予 %s: %w", g.PageName, err)
			}
		}
		return nil
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50011, "替换失败："+err.Error())
		return
	}
```
- 已知语义收敛（可接受，仅错误路径）：原 50010/50011/50012/50013 四码合并为 50011 + wrap 原因；happy path 行为不变
- 安全网：`TestPageGrantLifecycle` 保持绿且**测试不改**
- 验证（需库）：`ARK_TEST_DATABASE_URL=... go test -run TestPageGrantLifecycle -count=1 ./internal/modules/sysadmin/`

### 任务 18：迁移 performance ActivateScheme
- 文件：`backend-go/internal/modules/performance/handler.go` L224-246
- 改动：同款替换（SupersedeActiveInScope + ActivateScheme 两步进 fn，返回 wrap 错误；错误码 40901/50002 语义在 fn 内区分：业务冲突返回可识别标记或统一收敛为 40901「启用失败」，执行时按现用例断言取齐）
- 验证：`go build ./...` + 该模块集成用例（需库）

### 任务 19：批次四回归 + 提交
- 验证：`go test ./...` 全绿/SKIP；确认 `grep -rn "pool.Begin" internal/modules/` → 无输出
- 提交：`refactor: 事务收口 platform/db.WithTx，handler 不再手写 Begin/Commit`

---

## 批次五：schema 单源 spike（决策门，约 0.5 天）

### 任务 20：spike——sqlc 直读 migrations
- 步骤：
  1. 临时把 `sqlc.yaml` 第一块 `schema:` 改为 `"migrations"`
  2. `make gen-sqlc`，记录结果（预期：wazero OOM 或表达式索引解析失败——sqlc.yaml 与 o_schema.sql 注释已两次记载同类失败）
  3. `git checkout -- sqlc.yaml` 恢复
- 决策门：
  - 意外成功 → 另立计划逐块迁移（超出本计划范围）
  - 失败（预期）→ 任务 21
- 产出：无论成败，写 `backend-go/docs/adr/0001-schema-single-source.md`（≤10 行）：结论 + 证据（命令与报错摘要）+ 后续纪律（新增迁移须同步对应 db/schema 摘录，drift diff 已覆盖 db/schema 变更可见性）

### 任务 21：按 spike 结论收尾 + 提交
- 预期路径（A 失败）：维持手工摘录 + ADR 文档化；不建自制 SQL 裁剪器（评审已否决）
- 提交：`docs: ADR 0001 schema 单源 spike 结论`

---

## 批次六：本地集成测试干净库（P1，约 0.5 天）

### 任务 22：make test-fresh（每轮从空库起跑）
- 设计简化说明：评审建议 template DB（毫秒级起库）；实测 15 个迁移在空库上 <5s，**直接每轮空库 + migrateup 更简单**（少一个模板库生命周期要管理），同等隔离保证——从简（superpowers：复杂度冒头就砍）
- 文件 1：`backend-go/scripts/test-fresh.sh`（新建）：
```bash
#!/usr/bin/env bash
# 从干净库跑集成测试：建库 → migrate → test → drop（trap 兜底清理）。
# 消除本地共享 ark 库脏数据噪音（R4）；验收 = 连续两次全绿。
set -euo pipefail
HOST_URL="postgres://ark:ark@127.0.0.1:5432"
TEST_DB="ark_test_$(date +%s)"
psql "$HOST_URL/postgres" -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS $TEST_DB" -c "CREATE DATABASE $TEST_DB"
trap 'psql "$HOST_URL/postgres" -c "DROP DATABASE IF EXISTS $TEST_DB"' EXIT
export ARK_DATABASE_URL="$HOST_URL/$TEST_DB?sslmode=disable"
go run ./cmd/migrateup
ARK_TEST_DATABASE_URL="$ARK_DATABASE_URL" go test -race -count=1 -run 'Integration|UpDown|Store' ./...
```
- 文件 2：`backend-go/Makefile` — 追加目标并登记 .PHONY：
```make
test-fresh: ## 集成测试（每轮干净库：建库→迁移→测试→清理）
	@bash scripts/test-fresh.sh
```
- 验证：`chmod +x scripts/test-fresh.sh && make test-fresh`

### 任务 23：批次六验收（完成前验证）
- 验证：`make test-fresh && make test-fresh` **连续两次全绿**（当前第二次因脏数据必红——已实证）
- 提交：`test: test-fresh 干净库集成测试，消除本地共享库脏数据噪音`

---

## 批次七（P2，第二批，待前六批合入后另立细化计划）

- Prometheus 指标：标签用 `c.FullPath()`，NoRoute 归一 `unmatched`（**依赖批次二完成**，否则 UUID 路径打爆标签基数）
- pprof：`ARK_ENABLE_PPROF=1` 门控，独立暴露
- govulncheck 进 CI 且**钉版本**（现状 @latest 不可复现）；CI go 版本已在任务 2 对齐

## 明确不做（YAGNI，承评审 §六）

- ❌ testcontainers（test-fresh 足够）
- ❌ 自制 migrations 解析/裁剪器（spike 二选一，失败则文档化纪律）
- ❌ 泛型事务框架（WithTx 传 pgx.Tx，用 sqlc 现成 WithTx 绑定）
- ❌ ORM / DI / 微服务 / 消息队列
- ❌ 把 pending-claim / output/mine 改全量（语义是「我的」）

## 总验收（全部批次完成后）

1. `gofmt -l .` 为空；`make ci` 全绿
2. `go test ./...`（无库）全绿/SKIP
3. `make test-fresh` 连续两次全绿
4. `make drift` 全绿；`grep -rn "pool.Begin" internal/modules/` 无输出
5. `go test -run TestPassthrough ./internal/` 4 条全绿
6. CI 真绿：推送后 GitHub Actions 13 次全红 → 全绿（用户执行推送时确认）
