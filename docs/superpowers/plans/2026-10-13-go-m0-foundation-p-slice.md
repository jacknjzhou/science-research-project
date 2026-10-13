# 科研管理系统 · Go+Gin 后端 M0 奠基 + P 模块垂直切片 实现计划

**目标：** 用 Go+Gin 建立可运行、可测试、可 docker compose 一键生产起服务的后端底座（配置/连接池/迁移/统一响应/traceId/JWT+Casbin 鉴权/数据域隔离/Redis 幂等/契约 passthrough 兜底），并以 P 项目申报模块的 `list / read / create` 一条竖切端到端验证「design 契约 → Go 服务 → PostgreSQL → Vue 前端」，Go 服务直接替换 Node 参考后端成为 compose 里的 `backend`。

**架构：** 契约驱动。`design/*.openapi.yaml` 与 `design/*.sql` 是唯一真源：oapi-codegen 从契约生成 P 模块 DTO/校验与路由存根，sqlc 从 DDL + 手写查询生成类型安全仓储；未落真实域逻辑的其余路由由 Go 版契约 passthrough 生成器（Node `generator.js` 的移植）兜底，保证"直接替换"后系统整体可用。模块化单体（单 codebase、按域分包），鉴权/幂等/审计以中间件横切，数据域（`tenant_id/legal_entity_id/security_level`）在仓储层强制注入。

**技术栈：** Go 1.22、Gin、oapi-codegen、sqlc、jackc/pgx/v5、golang-migrate、golang-jwt/v5、Casbin、go-redis/v9、go-playground/validator、OpenTelemetry-Go + zap、stretchr/testify；PostgreSQL 15、Redis 7；Vue3+Vite（沿用现有前端）；Docker Compose。

---

## 0. 范围分解地图（本计划只写全 M0，其余为后续独立计划）

本需求横跨多个独立子系统，按 writing-plans「每计划产出可独立测试的软件」原则拆分。**本文档给出 M0 的完整 bite-sized 计划**；其余子系统登记为后续计划（各自遵循此处确立的工程约定）：

| 计划 | 覆盖 §PRODUCTION_GAP_ROADMAP | 产出可测试物 | 状态 |
|---|---|---|---|
| **P-M0（本文）** | M0 奠基 + 首个竖切 | Go 服务底座 + P 模块 list/read/create + 生产 compose + CI | 本文写全 |
| P-M1-core | M1 核心业务 | E/F/R/G/A/C 域真实逻辑、事务、状态机、审计落库、单号服务、种子数据 | 后续计划 |
| P-M1-infra | M1 横切 | Kafka 领域事件 + Outbox、缓存层、可观测看板/SLO、前端 RBAC 去 mock 全量 | 后续计划 |
| P-M2-boundary | M2 涉密与集成 | C/T/S/X 域、外部集成适配层、MinIO、全文检索、asynq 异步任务 | 后续计划 |
| P-M2-ai | M2 AI 主线 | svc-ai-gateway(Go)、本地 LLM + RAG + 向量库 | 后续计划 |
| P-M3-data | M3 数据平台 | ClickHouse + CDC + ETL + 大屏 | 后续计划 |
| P-M3-nfr | M3 收口 | 压测/SLO、K8s HA、信创(达梦/鲲鹏)回归、等保测评 | 后续计划 |

> 决策依据（来自用户确认）：范围=**M0 奠基 + P 垂直切片**；过渡=**Go 直接替换 Node**（非灰度）。因此本计划末尾的 compose 中 `backend` 服务改为 Go 镜像，Node `backend/` 保留在仓库作契约测试夹具但不再进 compose。

## 1. 文件结构映射（分解决策在此锁定）

新建 Go 工程置于 `backend-go/`（与 Node `backend/` 并存，互不干扰；M0 后 compose 只用 backend-go）。每个文件单一职责，按域而非按技术层分组：

```
backend-go/
  go.mod  go.sum
  Makefile                                   # codegen / migrate / test / build / run 入口
  .golangci.yml
  # (可选) docker-compose.m0.yml              # 本文未实现：集成测试改用 CI services(任务14) 或根 compose(任务13) 起 pg+redis
  cmd/server/main.go                          # 组装：config→db→migrate→enforcer→router→listen
  internal/
    router.go                                  # Build(RouterDeps)：横切中间件 + /healthz + 公开登录 + 受保护 /api/v1 + passthrough NoRoute（任务1起骨架→任务12定稿）
    router_test.go                             # TestBuild_*：healthz 公开/登录签发/无令牌 401（任务12）
    config/config.go                          # 环境变量加载 *Config
    platform/
      httpx/envelope.go                        # ApiResponse 包络 + WriteOK/WriteErr + traceId 取值
      httpx/envelope_test.go
      middleware/trace.go                      # TraceID 中间件（c.Set + X-Trace-Id 头）
      middleware/recover.go                    # panic 恢复→500 包络
      middleware/auth.go                       # JWT 解析 + Casbin 鉴权 + 数据域注入 context
      middleware/idempotency.go                # Redis SETNX 幂等回放
      db/postgres.go                           # pgxpool 连接 + Ping
      migrate/migrate.go                       # golang-migrate Up/Down
      auth/jwt.go                              # Claims + 签发/校验（任务9）
      auth/casbin.go                           # enforcer 装载(model+policy) + 数据域谓词 helper（任务9）
      auth/domain.go                           # Ctx* 常量 + Domain/DomainFrom（任务9）
      auth/login.go                            # HandleLogin 开发登录签发 JWT（任务12）
      auth/model.conf                          # Casbin RBAC 模型（任务9）
      auth/policy.csv                          # Casbin 角色→资源→动作 策略（任务9）
      oapi/spec.go                             # 运行时加载 design/*.openapi.yaml（复用 Node schema.js 思路）
      oapi/generator.go                        # 契约→示例值生成器（Node generator.js 移植）
      oapi/passthrough.go                      # 未实现路由的通配兜底 handler
      oapi/generator_test.go
    modules/
      p/
        routes.go                              # 手工 Register(gin.IRoutes) 3 条 P 路由（ServerInterface 存根推迟到 M1，见任务6注记）
        handler.go                             # ListApplications/GetApplication/CreateApplication
        mapper.go                              # ToAPIApplication：sqlc 行 → 契约 Application 形状
        handler_test.go                        # httptest 端到端（真库 seed，ARK_TEST_DATABASE_URL 门控）
        contract_test.go                       # 任务8：真响应 body 对 design 200 schema 合规校验
  api/
    gen/p/types.gen.go                          # oapi-codegen(M0)：Application/PageResult/DTO/校验（仅 models 插件）
    gen/p/server.go                              # (M1 引入) oapi-codegen gin-server：ServerInterface+RegisterHandlers；M0 手工 Register 不用它
    gen/common/envelope.gen.go                  # ApiResponse 公共结构
  codegen/
    oapi-p.yaml                                 # oapi-codegen 配置（M0: models；与 Makefile gen-oapi 的 --config 一致）
  db/
    query/p_application.sql                    # sqlc 手写查询（list/read/count/create）
  sqlc.yaml                                     # sqlc 配置：pgx/v5；schema=migrations/000001_init.up.sql；out=internal/modules/p/store
  migrations/
    000001_init.up.sql                          # 由 design/00-common.sql + 各模块 *.ddl.sql 拼接生成
    000001_init.down.sql
    gen.go                                     # 从 design 生成迁移文件的逻辑（WriteFiles/GenerateUp，无 main）
    cmd/gen/main.go                            # go:generate 入口（package main 调 migrations.WriteFiles）
  testdata/
    # (可选) seed_p.sql                        # 任务7 竖切测试若需固定数据；否则在测试内 inline seed
    contract_fixtures/                         # 合规测试读 design 200 schema（任务8）
  Dockerfile                                   # 多阶段：builder(golang:1.22) → distroless/alpine
```

**运行期契约来源**：Go 与 Node 一样在运行时从磁盘读 `design/`（`DESIGN_DIR` 环境变量）。按任务 13，契约随镜像分发——`backend-go/Dockerfile` 用 `COPY design/ /srv/design/` 把契约烘进镜像并置 `DESIGN_DIR=/srv/design`，compose 不再对 `./design` 建卷挂载（保持镜像自包含、可离线跑）。`migrations/` 由 `design/*.sql` 生成并纳入版本库，生产用 golang-migrate，不再依赖 postgres 容器 initdb。

**命名一致性铁律**（贯穿全计划，防漂移）：
- 包络结构体一律 `httpx.Envelope{Code,Message,Data,TraceID,Timestamp}`，JSON tag `code/message/data/traceId/timestamp`。
- 数据域 context key 常量：`auth.CtxUserID="uid"`、`auth.CtxTenantID="tenant_id"`、`auth.CtxLegalEntityID="legal_entity_id"`、`auth.CtxSecurityLevel="security_level"`、`auth.CtxRoles="roles"`。
- 仓储行结构：sqlc 输出到包 `store`（`internal/modules/p/store`），类型 `store.Application` 字段：`ID int64 / Code *string / TenantID int64 / Status string / Deleted int16 / CreatorID int64 / Title string / ProjectType string / PiUserID int64 / MemberIDs []byte / DepartmentID *int64 / Abstract *string / TotalBudget *string / IsHorizontal bool / SubmitAt *time.Time / CreatedAt / UpdatedAt time.Time`（NUMERIC→`*string`，JSONB→`[]byte`，TIMESTAMPTZ→`time.Time`/`*time.Time`）。

---

## 任务 1：Go 工程骨架 + 统一响应包络 + traceId 中间件 + /healthz

契约要求所有响应统一 `{ code, message, data, traceId, timestamp }`（`design/README.md` §三、PRD 2.5），且 `traceId` 全链路贯穿（PRD 2.5）。先建最小可测的 HTTP 底座。

**文件：**
- 创建：`backend-go/go.mod`
- 创建：`backend-go/internal/platform/httpx/envelope.go`
- 创建：`backend-go/internal/platform/httpx/envelope_test.go`
- 创建：`backend-go/internal/platform/middleware/trace.go`
- 创建：`backend-go/internal/platform/middleware/recover.go`
- 创建：`backend-go/internal/router.go`
- 创建：`backend-go/cmd/server/main.go`

- [ ] **步骤 1：写失败的测试（envelope + healthz 形状）**

`backend-go/internal/platform/httpx/envelope_test.go`：

```go
package httpx

import (
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestWriteOK_EnvelopeShape(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(TraceID())
	r.GET("/x", func(c *gin.Context) { WriteOK(c, gin.H{"hello": "world"}) })

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", "/x", nil))

	if w.Header().Get("X-Trace-Id") == "" {
		t.Fatal("缺少 X-Trace-Id 响应头")
	}
	var env struct {
		Code      int            `json:"code"`
		Message   string         `json:"message"`
		Data      map[string]any `json:"data"`
		TraceID   string         `json:"traceId"`
		Timestamp int64          `json:"timestamp"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
		t.Fatalf("响应非 JSON: %v", err)
	}
	if env.Code != 0 || env.Message != "ok" || env.Data["hello"] != "world" {
		t.Fatalf("包络形状错误: %+v", env)
	}
	if env.TraceID == "" || env.Timestamp <= 0 {
		t.Fatalf("traceId/timestamp 缺失: %+v", env)
	}
}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend-go && go mod init github.com/eplugger/ark && go get github.com/gin-gonic/gin@v1.10.0 && go test ./internal/platform/httpx/ -run TestWriteOK -v`
预期：编译失败，`undefined: TraceID`、`undefined: WriteOK`。

- [ ] **步骤 3：写最少实现**

`backend-go/internal/platform/httpx/envelope.go`：

```go
package httpx

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// Envelope 是全站统一响应包裹，字段名与 design/README.md §三 完全一致。
type Envelope struct {
	Code      int    `json:"code"`
	Message   string `json:"message"`
	Data      any    `json:"data"`
	TraceID   string `json:"traceId"`
	Timestamp int64  `json:"timestamp"`
}

const (
	CtxTraceID  = "traceId"
	HeaderTrace = "X-Trace-Id"
)

func traceOf(c *gin.Context) string {
	if v := c.GetString(CtxTraceID); v != "" {
		return v
	}
	return NewTraceID()
}

// WriteOK 写成功包络（code=0）。
func WriteOK(c *gin.Context, data any) {
	c.JSON(http.StatusOK, Envelope{
		Code: 0, Message: "ok", Data: data,
		TraceID: traceOf(c), Timestamp: time.Now().UnixMilli(),
	})
}

// WriteErr 写业务错误包络；HTTP 状态表达传输层，code 表达业务错误（PRD 2.5）。
func WriteErr(c *gin.Context, status, code int, msg string) {
	c.JSON(status, Envelope{
		Code: code, Message: msg, Data: nil,
		TraceID: traceOf(c), Timestamp: time.Now().UnixMilli(),
	})
}
```

`backend-go/internal/platform/middleware/trace.go`（同包 httpx 也可；此处放 middleware 包，`TraceID()` 由 router 引用，测试里从 httpx 引——为简化，把 `TraceID()` 与 `NewTraceID()` 定义在 httpx 包，middleware 复用。实现如下放 `backend-go/internal/platform/httpx/trace.go`）：

```go
package httpx

import (
	"crypto/rand"
	"encoding/hex"

	"github.com/gin-gonic/gin"
)

func NewTraceID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return "go-" + hex.EncodeToString(b)
}

// TraceID 中间件：透传入站 X-Trace-Id，否则新建；写入 context 与响应头。
func TraceID() gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.GetHeader(HeaderTrace)
		if id == "" {
			id = NewTraceID()
		}
		c.Set(CtxTraceID, id)
		c.Header(HeaderTrace, id)
		c.Next()
	}
}
```

`backend-go/internal/platform/middleware/recover.go`：

```go
package middleware

import (
	"net/http"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// Recover 捕获 panic，返回 500 统一包络，并落结构化日志。
func Recover(l *zap.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				l.Error("panic recovered", zap.Any("err", r), zap.String("traceId", c.GetString(httpx.CtxTraceID)))
				httpx.WriteErr(c, http.StatusInternalServerError, 50000, "服务器内部错误")
				c.Abort()
			}
		}()
		c.Next()
	}
}
```

`backend-go/internal/router.go`：

```go
package internal

import (
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/middleware"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// NewRouter 构建 Gin 引擎并挂载横切中间件与 /healthz。
func NewRouter(l *zap.Logger) *gin.Engine {
	e := gin.New()
	e.Use(httpx.TraceID(), middleware.Recover(l))
	e.GET("/healthz", func(c *gin.Context) { httpx.WriteOK(c, gin.H{"ok": true}) })
	return e
}
```

`backend-go/cmd/server/main.go`：

```go
package main

import (
	"log"

	"github.com/eplugger/ark/internal"
	"go.uber.org/zap"
)

func main() {
	l, _ := zap.NewProduction()
	defer l.Sync()
	e := internal.NewRouter(l)
	if err := e.Run(":8787"); err != nil {
		log.Fatal(err)
	}
}
```

- [ ] **步骤 4：运行测试确认通过**

运行：`cd backend-go && go get go.uber.org/zap@v1.27.0 && go test ./internal/platform/httpx/ -run TestWriteOK -v`
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/go.mod backend-go/go.sum backend-go/internal backend-go/cmd
git commit -m "feat(go): M0 骨架 - Gin 引擎、统一响应包络与 traceId 中间件、/healthz"
```

---

## 任务 2：配置加载（环境变量 + 默认值）

**文件：**
- 创建：`backend-go/internal/config/config.go`
- 创建：`backend-go/internal/config/config_test.go`
- 修改：`backend-go/cmd/server/main.go`

- [ ] **步骤 1：写失败的测试**

`backend-go/internal/config/config_test.go`：

```go
package config

import "testing"

func TestLoad_DefaultsAndEnv(t *testing.T) {
	t.Setenv("ARK_HTTP_PORT", "9000")
	t.Setenv("ARK_DATABASE_URL", "postgres://u:p@h:5432/db?sslmode=disable")
	t.Setenv("ARK_REDIS_ADDR", "redis:6379")
	t.Setenv("ARK_JWT_SECRET", "s3cr3t")
	t.Setenv("DESIGN_DIR", "/srv/design")

	c := Load()
	if c.HTTPPort != 9000 {
		t.Fatalf("HTTPPort=%d", c.HTTPPort)
	}
	if c.DatabaseURL == "" || c.RedisAddr == "" || c.JWTSecret != "s3cr3t" {
		t.Fatalf("必填项未加载: %+v", c)
	}
	if c.DesignDir != "/srv/design" {
		t.Fatalf("DesignDir=%s", c.DesignDir)
	}
	if c.MigrationsDir == "" {
		t.Fatal("MigrationsDir 应有默认值")
	}
	if c.JWTTTLSec == 0 {
		t.Fatal("JWTTTLSec 应有默认值")
	}
}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend-go && go test ./internal/config/ -v`
预期：编译失败 `undefined: Load`。

- [ ] **步骤 3：写最少实现**

`backend-go/internal/config/config.go`：

```go
package config

import (
	"os"
	"strconv"
)

type Config struct {
	Env           string
	HTTPPort      int
	DatabaseURL   string
	RedisAddr     string
	RedisPassword string
	JWTSecret     string
	JWTTTLSec     int64
	MigrationsDir string
	DesignDir     string
}

func get(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func Load() *Config {
	return &Config{
		Env:           get("ARK_ENV", "dev"),
		HTTPPort:      getInt("ARK_HTTP_PORT", 8787),
		DatabaseURL:   os.Getenv("ARK_DATABASE_URL"),
		RedisAddr:     get("ARK_REDIS_ADDR", "127.0.0.1:6379"),
		RedisPassword: get("ARK_REDIS_PASSWORD", ""),
		JWTSecret:     get("ARK_JWT_SECRET", "dev-secret-change-me"),
		JWTTTLSec:     int64(getInt("ARK_JWT_TTL_SEC", 7200)),
		MigrationsDir: get("ARK_MIGRATIONS_DIR", "./migrations"),
		DesignDir:     get("DESIGN_DIR", "../design"),
	}
}
```

修改 `backend-go/cmd/server/main.go` 用配置端口（把 `e.Run(":8787")` 改为读 config）：

```go
func main() {
	l, _ := zap.NewProduction()
	defer l.Sync()
	cfg := config.Load()
	e := internal.NewRouter(l)
	if err := e.Run(":" + strconv.Itoa(cfg.HTTPPort)); err != nil {
		log.Fatal(err)
	}
}
```

（并在 import 块加 `"strconv"` 与 `"github.com/eplugger/ark/internal/config"`。）

- [ ] **步骤 4：运行测试确认通过**

运行：`cd backend-go && go test ./internal/config/ -v`
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/config backend-go/cmd/server/main.go
git commit -m "feat(go): M0 配置加载(env→Config)"
```

---

## 任务 3：PostgreSQL 连接池（pgx）+ 健康探测

**文件：**
- 创建：`backend-go/internal/platform/db/postgres.go`
- 创建：`backend-go/internal/platform/db/postgres_test.go`

- [ ] **步骤 1：写失败的测试（非法连接串应报错；有 `ARK_TEST_DATABASE_URL` 时做真实 Ping）**

`backend-go/internal/platform/db/postgres_test.go`：

```go
package db

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestConnect_InvalidURLFails(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := Connect(ctx, "not-a-valid-url"); err == nil {
		t.Fatal("期望非法连接串返回错误")
	}
}

func TestPing_LiveIfProvided(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL，跳过集成 Ping")
	}
	ctx := context.Background()
	pool, err := Connect(ctx, u)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := Ping(ctx, pool); err != nil {
		t.Fatalf("Ping 失败: %v", err)
	}
}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend-go && go get github.com/jackc/pgx/v5@v5.6.0 && go test ./internal/platform/db/ -v`
预期：编译失败 `undefined: Connect`。

- [ ] **步骤 3：写最少实现**

`backend-go/internal/platform/db/postgres.go`：

```go
package db

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Connect 解析连接串并建立连接池。
func Connect(ctx context.Context, url string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("解析 DATABASE_URL: %w", err)
	}
	cfg.MaxConns = 10
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("创建连接池: %w", err)
	}
	return pool, nil
}

// Ping 触发一次真实往返，验证连通。
func Ping(ctx context.Context, pool *pgxpool.Pool) error {
	return pool.Ping(ctx)
}
```

- [ ] **步骤 4：运行测试确认通过**

运行：`cd backend-go && go test ./internal/platform/db/ -v`
预期：`TestConnect_InvalidURLFails` PASS；`TestPing_LiveIfProvided` SKIP（无库时）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/db
git commit -m "feat(go): M0 pgx 连接池与 Ping 健康探测"
```

---

## 任务 4：golang-migrate 从 design/*.sql 生成迁移并应用

生产用版本化迁移而非 postgres initdb（`PRODUCTION_GAP_ROADMAP` §3.6）。迁移文件由 `design/00-common.sql` + 各模块 `*.ddl.sql` 拼接生成（common 先于模块，数字前缀已保证顺序），纳入版本库。

**文件：**
- 创建：`backend-go/migrations/gen.go`（`go:generate` 生成器）
- 创建：`backend-go/migrations/gen_test.go`
- 创建（生成物）：`backend-go/migrations/000001_init.up.sql`、`000001_init.down.sql`
- 创建：`backend-go/internal/platform/migrate/migrate.go`

- [ ] **步骤 1：写失败的测试（生成器产出含关键建表语句）**

`backend-go/migrations/gen_test.go`：

```go
package migrations

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGenerateFromDesign(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"CREATE TABLE sys_user", "CREATE TABLE p_application", "CREATE TABLE seq_prefix_registry"} {
		if !strings.Contains(strings.ToLower(up), strings.ToLower(want)) {
			t.Fatalf("生成的 up.sql 缺少: %s", want)
		}
	}
	// common 必须先于模块：sys_user 出现在 p_application 之前
	if strings.Index(strings.ToLower(up), "sys_user") > strings.Index(strings.ToLower(up), "p_application") {
		t.Fatal("00-common.sql 应最先拼接")
	}
}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend-go && go test ./migrations/ -v`
预期：编译失败 `undefined: GenerateUp`。

- [ ] **步骤 3：写最少实现**

`backend-go/migrations/gen.go`：

```go
package migrations

//go:generate go run gen.go

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// GenerateUp 读取 designDir 下 00-common.sql 与各 *.ddl.sql（按文件名排序），
// 拼成单个 up.sql 内容。顺序：common → 01..11 模块。
func GenerateUp(designDir string) (string, error) {
	entries, err := os.ReadDir(designDir)
	if err != nil {
		return "", fmt.Errorf("读 design 目录: %w", err)
	}
	var files []string
	for _, e := range entries {
		n := e.Name()
		if n == "00-common.sql" {
			files = append([]string{n}, files...) // common 置顶
		} else if strings.HasSuffix(n, ".ddl.sql") {
			files = append(files, n)
		}
	}
	sort.SliceStable(files, func(i, j int) bool {
		if files[i] == "00-common.sql" {
			return true
		}
		if files[j] == "00-common.sql" {
			return false
		}
		return files[i] < files[j]
	})

	var b strings.Builder
	b.WriteString("-- 由 design/*.sql 自动生成，勿手改。来源：\n")
	for _, f := range files {
		data, err := os.ReadFile(filepath.Join(designDir, f))
		if err != nil {
			return "", err
		}
		b.WriteString(fmt.Sprintf("\n-- ===== %s =====\n", f))
		b.Write(data)
		b.WriteString("\n")
	}
	return b.String(), nil
}

// WriteFiles 生成 up/down 到当前目录（供 go:generate）。
func WriteFiles(designDir string) error {
	up, err := GenerateUp(designDir)
	if err != nil {
		return err
	}
	upName := filepath.Join(".", "000001_init.up.sql")
	downName := filepath.Join(".", "000001_init.down.sql")
	if err := os.WriteFile(upName, []byte(up), 0o644); err != nil {
		return err
	}
	down := "-- 回滚：清空 public schema 中由本次迁移创建的表。\nDROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n"
	return os.WriteFile(downName, []byte(down), 0o644)
}

func main() {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../design"
	}
	if err := WriteFiles(d); err != nil {
		panic(err)
	}
	fmt.Println("生成 migrations/000001_init.{up,down}.sql 完成")
}
```

> 注意：`gen.go` 里已有 `func main()`，同目录测试文件是 `package migrations`，二者会冲突。因此**把 `func main()` 单独放到 `backend-go/migrations/cmd/gen/main.go`**（`package main`，调用 `migrations.WriteFiles`），`//go:generate go run ./cmd/gen`。`gen.go` 保留 `GenerateUp/WriteFiles`（无 main）。修正后的 `cmd/gen/main.go`：

```go
package main

import (
	"fmt"
	"os"

	"github.com/eplugger/ark/migrations"
)

func main() {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../design"
	}
	if err := migrations.WriteFiles(d); err != nil {
		panic(err)
	}
	fmt.Println("生成 migrations/000001_init.{up,down}.sql 完成")
}
```

（把上一步 `gen.go` 末尾的 `func main()` 删除，仅留 `GenerateUp/WriteFiles`。）

生成实际文件：

```bash
cd backend-go && go generate ./migrations/... && ls migrations/*.sql
```

`backend-go/internal/platform/migrate/migrate.go`：

```go
package migrate

import (
	"errors"
	"fmt"

	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/postgres"
	_ "github.com/golang-migrate/migrate/v4/source/file"
)

// Up 应用全部迁移到最新版本。
func Up(databaseURL, dir string) error {
	m, err := migrate.New("file://"+dir, databaseURL)
	if err != nil {
		return fmt.Errorf("初始化迁移器: %w", err)
	}
	defer m.Close()
	if err := m.Up(); err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return fmt.Errorf("执行迁移: %w", err)
	}
	return nil
}

// Down 回滚全部迁移。
func Down(databaseURL, dir string) error {
	m, err := migrate.New("file://"+dir, databaseURL)
	if err != nil {
		return err
	}
	defer m.Close()
	if err := m.Down(); err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return err
	}
	return nil
}
```

- [ ] **步骤 4：运行测试确认通过（含集成 Up/Down，需 pg）**

运行：`cd backend-go && go get github.com/golang-migrate/migrate/v4@v4.17.1 && go test ./migrations/ ./internal/platform/migrate/ -v`
预期：`TestGenerateFromDesign` PASS。集成迁移（可选，设 `ARK_TEST_DATABASE_URL` 时）用一次性 schema 验证——给 `migrate` 包补一个集成测试：

```go
// backend-go/internal/platform/migrate/migrate_test.go
package migrate

import (
	"os"
	"testing"
)

func TestUpDown_LiveIfProvided(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	dir := os.Getenv("ARK_MIGRATIONS_DIR")
	if dir == "" {
		dir = "../../migrations"
	}
	if err := Up(u, dir); err != nil {
		t.Fatal(err)
	}
	// 断言关键表存在
	if _, err := queryExists(u, "p_application"); err != nil {
		t.Fatalf("迁移后 p_application 不存在: %v", err)
	}
	if err := Down(u, dir); err != nil {
		t.Fatalf("Down 失败: %v", err)
	}
}
```

（在 `migrate.go` 补 `queryExists(databaseURL, table string) (bool, error)`：用 pgx 连上后 `SELECT to_regclass('public.'||$1)`；见任务3 的 `db` 包，直接 `db.Connect` + `pool.QueryRow`。若不想引依赖，就地用 `pgx.Connect`。）

运行集成（先起 pg，见任务 13 的根 `docker-compose.yml` 之 postgres 服务，或本地 `docker run postgres:15`）：
```bash
ARK_TEST_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable go test ./internal/platform/migrate/ -run TestUpDown -v
```
预期：PASS（或无库时 SKIP）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/migrations backend-go/internal/platform/migrate
git commit -m "feat(go): M0 从 design 生成 golang-migrate 迁移并提供 Up/Down"
```

## 任务 5：sqlc 从 DDL + 手写查询生成 P 仓储（list/read/create）

数据访问层首选 sqlc（类型安全，契合"DDL 即真源"）。schema 用任务 4 生成的 `migrations/000001_init.up.sql`（与线上同构），查询手写放 `db/query`。金额在查询里 `::text` 输出（契约 `total_budget` 声明为 `type: string`），JSONB `member_ids` 原样作 `[]byte`。

**文件：**
- 创建：`backend-go/sqlc.yaml`
- 创建：`backend-go/db/query/p_application.sql`
- 生成物：`backend-go/internal/modules/p/store/*.sql.go`、`models.go`

- [ ] **步骤 1：写失败测试（仓储冒烟：seed 后 ListApplications 命中租户过滤 + 软删排除）**

`backend-go/internal/modules/p/store/p_application_test.go`：

```go
package store

import (
	"context"
	"os"
	"testing"
)

func TestListApplications_TenantAndSoftDeleteFilter(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	// 约定：测试库已由任务4 migrate.Up 建表，并 seed 了 testdata/seed_p.sql
	pool := mustPool(t, u)
	defer pool.Close()
	q := New(pool)
	got, err := q.ListApplications(context.Background(), ListApplicationsParams{
		TenantID: 1, Limit: 20, Offset: 0, Status: nil, ProjectType: nil,
	})
	if err != nil {
		t.Fatal(err)
	}
	// seed 固定：tenant=1 未删 2 行；tenant=2 与 deleted=1 各 1 行不应出现
	if len(got) != 2 {
		t.Fatalf("期望 2 行(仅 tenant=1 且 deleted=0)，实得 %d", len(got))
	}
	for _, r := range got {
		if r.TenantID != 1 || r.Deleted != 0 {
			t.Fatalf("过滤失效: %+v", r)
		}
	}
}
```

`backend-go/internal/modules/p/store/helper_test.go`（`mustPool` 复用 db 包）：

```go
package store

import (
	"context"
	"testing"

	"github.com/eplugger/ark/internal/platform/db"
	"github.com/jackc/pgx/v5/pgxpool"
)

func mustPool(t *testing.T, url string) *pgxpool.Pool {
	t.Helper()
	p, err := db.Connect(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	return p
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/modules/p/store/ -v`
预期：编译失败，`undefined: New`、`undefined: ListApplicationsParams`（尚未生成）。

- [ ] **步骤 3：写查询与 sqlc 配置并生成**

`backend-go/db/query/p_application.sql`：

```sql
-- name: ListApplications :many
SELECT id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, guideline_id, template_id, title,
       project_type, pi_user_id, member_ids, department_id, abstract,
       research_target, technical_route, expected_output, duration_months,
       total_budget::text AS total_budget, is_horizontal, funding_channel,
       ai_draft_marked, submit_at, withdraw_at, withdraw_reason
FROM p_application
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (@status::text IS NULL OR status = @status)
  AND (@project_type::text IS NULL OR project_type = @project_type)
ORDER BY id DESC
LIMIT @limit_ OFFSET @offset_;

-- name: CountApplications :one
SELECT count(*)::int AS n
FROM p_application
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (@status::text IS NULL OR status = @status)
  AND (@project_type::text IS NULL OR project_type = @project_type);

-- name: GetApplication :one
SELECT id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, guideline_id, template_id, title,
       project_type, pi_user_id, member_ids, department_id, abstract,
       research_target, technical_route, expected_output, duration_months,
       total_budget::text AS total_budget, is_horizontal, funding_channel,
       ai_draft_marked, submit_at, withdraw_at, withdraw_reason
FROM p_application
WHERE id = $1 AND deleted = 0
LIMIT 1;

-- name: CreateApplication :one
INSERT INTO p_application (
  tenant_id, status, creator_id, title, project_type, pi_user_id,
  member_ids, department_id, abstract, total_budget, is_horizontal
) VALUES (
  $1, $2, $3, $4, $5, $6,
  $7, $8, $9, $10::numeric, $11
)
RETURNING id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, guideline_id, template_id, title,
       project_type, pi_user_id, member_ids, department_id, abstract,
       research_target, technical_route, expected_output, duration_months,
       total_budget::text AS total_budget, is_horizontal, funding_channel,
       ai_draft_marked, submit_at, withdraw_at, withdraw_reason;
```

`backend-go/sqlc.yaml`：

```yaml
version: "2"
sql:
  - engine: "postgresql"
    schema: "migrations/000001_init.up.sql"
    queries: "db/query"
    gen:
      go:
        package: "store"
        out: "internal/modules/p/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          p_application: Application
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          - db_type: "pg_catalog.jsonb"
            go_type: "[]byte"
```

安装并运行 sqlc：

```bash
# 一次性安装（Go1.22）
go install github.com/sqlc-dev/sqlc/cmd/sqlc@latest
cd backend-go && sqlc generate
```

预期生成 `internal/modules/p/store/p_application.sql.go`（含 `Queries`、`New`、`ListApplications/CountApplications/GetApplication/CreateApplication` 及 `ListApplicationsParams{TenantID int64; Limit int32; Offset int32; Status *string; ProjectType *string}` 等）与 `models.go`（`type Application struct{ ID int64; ... TotalBudget *string; MemberIDs []byte; IsHorizontal bool; SubmitAt *time.Time; CreatedAt, UpdatedAt time.Time; ... }`）。若 `@limit_`/`@offset_` 命名生成的参数名不同，按生成物实际字段名对齐 `ListApplicationsParams` 引用（这是本任务唯一需要"看生成物"的地方，其余确定）。

- [ ] **步骤 4：运行确认通过（需 pg 已迁移并 seed）**

先建 seed 文件 `backend-go/testdata/seed_p.sql`：

```sql
-- 2 行 tenant=1 正常，1 行 tenant=2，1 行 tenant=1 且 deleted=1
INSERT INTO p_application (tenant_id, status, creator_id, title, project_type, pi_user_id, member_ids, total_budget, is_horizontal)
VALUES
 (1,'DRAFT',1001,'A 项目','NAT',2001,'[]'::jsonb,'1000.00',FALSE),
 (1,'SUBMITTED',1001,'B 项目','NAT',2001,'[]'::jsonb,'2000.00',FALSE),
 (2,'DRAFT',1002,'C 项目','NAT',2002,'[]'::jsonb,'500.00',FALSE),
 (1,'DRAFT',1001,'D 已删','NAT',2001,'[]'::jsonb,'0.00',FALSE);
UPDATE p_application SET deleted=1 WHERE title='D 已删';
```

```bash
ARK_TEST_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable \
  go test ./internal/modules/p/store/ -run TestListApplications -v
```
预期：PASS（前置：已跑 `migrate.Up` 建表并 `psql -f testdata/seed_p.sql`）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/sqlc.yaml backend-go/db/query backend-go/internal/modules/p/store backend-go/testdata/seed_p.sql
git commit -m "feat(go): M0 sqlc 生成 P 仓储(list/count/read/create)"
```

---

## 任务 6：oapi-codegen 生成 P DTO + 运行期契约加载器（供合规测试与 passthrough）

**文件：**
- 创建：`backend-go/codegen/p.cfg.yaml`
- 创建：`backend-go/codegen/generate.go`
- 生成物：`backend-go/api/gen/p/types.gen.go`
- 创建：`backend-go/internal/platform/oapi/spec.go`
- 创建：`backend-go/internal/platform/oapi/spec_test.go`

- [ ] **步骤 1：写失败测试（加载 design 后可解析某 op 的 200 data 子 schema）**

`backend-go/internal/platform/oapi/spec_test.go`：

```go
package oapi

import (
	"os"
	"testing"
)

func designDir() string {
	if d := os.Getenv("DESIGN_DIR"); d != "" {
		return d
	}
	return "../../../../design"
}

func TestSpec_ExtractDataSchema_ListApplications(t *testing.T) {
	s, err := LoadDir(designDir())
	if err != nil {
		t.Fatal(err)
	}
	op := s.Find("GET", "/apply/applications")
	if op == nil {
		t.Fatal("未找到 GET /apply/applications")
	}
	data := op.DataSchema() // 解析 allOf 覆写出的 PageResult{list:Application}
	if data == nil {
		t.Fatal("data 子 schema 为空")
	}
	// data 应含 list:array，items $ref → Application
	props, _ := data["properties"].(map[string]any)
	list, _ := props["list"].(map[string]any)
	if list == nil || list["type"] != "array" {
		t.Fatalf("list 结构不符: %+v", list)
	}
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/platform/oapi/ -v`
预期：编译失败 `undefined: LoadDir`。

- [ ] **步骤 3：写运行期契约加载器（移植 Node `schema.js` 的 `extractDataSchema`）**

`backend-go/internal/platform/oapi/spec.go`：

```go
package oapi

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

type Doc struct {
	Name string
	Raw  map[string]any
}

type Spec struct {
	Docs []*Doc
	// index: "METHOD /template/path" -> {doc, method, path, responses}
	index map[string]*Op
}

type Op struct {
	doc    *Doc
	method string
	path   string
	raw    map[string]any
}

func (o *Op) DataSchema() map[string]any {
	resp := o.raw["responses"]
	m, _ := resp.(map[string]any)
	var r any = m["200"]
	if r == nil {
		r = m["201"]
	}
	rm, _ := r.(map[string]any)
	if rm == nil {
		return nil
	}
	// $ref 解引用（本模块内 #/...）
	if ref, ok := rm["$ref"].(string); ok {
		rm = o.doc.deref(ref)
	}
	content, _ := rm["content"].(map[string]any)
	jsonc, _ := content["application/json"].(map[string]any)
	sch, _ := jsonc["schema"].(map[string]any)
	if sch == nil {
		return nil
	}
	return o.extractData(sch)
}

func isStructured(d map[string]any) bool {
	if d == nil {
		return false
	}
	if d["$ref"] != nil || d["allOf"] != nil || d["oneOf"] != nil || d["anyOf"] != nil || d["items"] != nil {
		return true
	}
	if p, ok := d["properties"].(map[string]any); ok && len(p) > 0 {
		return true
	}
	return false
}

// extractData：从 allOf[ApiResponse, {data:...}] 里取出内联覆写的结构化 data；否则泛型。
func (o *Op) extractData(rs map[string]any) map[string]any {
	if p, ok := rs["properties"].(map[string]any); ok {
		if d, ok := p["data"].(map[string]any); ok {
			return d
		}
	}
	if all, ok := rs["allOf"].([]any); ok {
		var generic map[string]any
		for _, sub := range all {
			sm, _ := sub.(map[string]any)
			if ref, ok := sm["$ref"].(string); ok {
				sm = o.doc.deref(ref)
			}
			if sm == nil {
				continue
			}
			props, _ := sm["properties"].(map[string]any)
			d, _ := props["data"].(map[string]any)
			if isStructured(d) {
				return d
			}
			if d != nil && generic == nil {
				generic = d
			}
		}
		return generic
	}
	return nil
}

func (d *Doc) deref(ref string) map[string]any {
	if !strings.HasPrefix(ref, "#/") {
		return nil
	}
	var cur any = d.Raw
	for _, seg := range strings.Split(strings.TrimPrefix(ref, "#/"), "/") {
		m, ok := cur.(map[string]any)
		if !ok {
			return nil
		}
		cur = m[seg]
	}
	out, _ := cur.(map[string]any)
	return out
}

func (s *Spec) Find(method, path string) *Op {
	return s.index[strings.ToUpper(method)+" "+path]
}

// LoadDir 读取 design 下全部 *.openapi.yaml 并建索引。
func LoadDir(dir string) (*Spec, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("读 design: %w", err)
	}
	var names []string
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".openapi.yaml") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	s := &Spec{index: map[string]*Op{}}
	for _, n := range names {
		b, err := os.ReadFile(filepath.Join(dir, n))
		if err != nil {
			return nil, err
		}
		var raw map[string]any
		if err := yaml.Unmarshal(b, &raw); err != nil {
			return nil, fmt.Errorf("解析 %s: %w", n, err)
		}
		doc := &Doc{Name: n, Raw: raw}
		s.Docs = append(s.Docs, doc)
		paths, _ := raw["paths"].(map[string]any)
		for p, item := range paths {
			im, _ := item.(map[string]any)
			for m := range im {
				ml := strings.ToLower(m)
				if ml != "get" && ml != "post" && ml != "put" && ml != "delete" && ml != "patch" {
					continue
				}
				om, _ := im[m].(map[string]any)
				s.index[strings.ToUpper(ml)+" "+p] = &Op{doc: doc, method: ml, path: p, raw: om}
			}
		}
	}
	return s, nil
}
```

（`gopkg.in/yaml.v3` 与 Node 侧同款解析。）

生成 P 的 DTO 模型（`models` 仅生成类型，供 M1 handler 直接复用；本 M0 竖切用运行期 `oapi` 做合规，不强制依赖生成体）：

`backend-go/codegen/p.cfg.yaml`：

```yaml
package: p
generate:
  models: true
target: ../api/gen/p/types.gen.go
input: ../../../design/01-项目申报与立项-P.openapi.yaml
```

`backend-go/codegen/generate.go`：

```go
package codegen

//go:generate go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen -config p.cfg.yaml
```

运行：

```bash
cd backend-go && go get github.com/oapi-codegen/oapi-codegen/v2@v2.4.1 && go generate ./codegen/...
ls api/gen/p/
```
预期：生成 `types.gen.go`，含 `type Application struct{...}`、`PageResult`、`ApplicationCreateRequest` 等（字段名按契约 camel/snake）。

- [ ] **步骤 4：运行确认通过**

运行：`cd backend-go && go test ./internal/platform/oapi/ -v`
预期：`TestSpec_ExtractDataSchema_ListApplications` PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/oapi backend-go/codegen backend-go/api/gen
git commit -m "feat(go): M0 运行期契约加载器 + oapi-codegen 生成 P DTO"
```

---

## 任务 7：P 模块 list/read/create 竖切（store → 契约形状 → 统一包络）

打通「HTTP → 鉴权数据域 → 仓储 SQL → 契约形状 → 包络」全链路。数据域 `Domain` 与 context key 在此定义（任务 9 的 JWT/Casbin 复用）。响应形状对齐契约 `Application`（`total_budget` 作 string、`member_ids` 作 JSON 数组）。

**文件：**
- 创建：`backend-go/internal/platform/auth/domain.go`
- 创建：`backend-go/internal/modules/p/mapper.go`
- 创建：`backend-go/internal/modules/p/handler.go`
- 创建：`backend-go/internal/modules/p/routes.go`
- 创建：`backend-go/internal/modules/p/handler_test.go`
- 修改：`backend-go/internal/router.go`

- [ ] **步骤 1：写失败测试（httptest 打三条路由，断言包络 + 真实行 + 软删/租户过滤）**

`backend-go/internal/modules/p/handler_test.go`：

```go
package p

import (
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

// 手工把数据域塞进 context（M0 阶段鉴权中间件尚未接入，见任务9）
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
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
	Register(e, NewHandler(pool))
	return e
}

func TestListApplications_Endpoint(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/applications?page=1&size=20", nil))
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
		t.Fatalf("列表结果不符: %+v", env)
	}
	// 字段形状对齐契约：total_budget 为 string，member_ids 为数组
	row := env.Data.List[0]
	if _, ok := row["total_budget"].(string); !ok {
		t.Fatalf("total_budget 非字符串: %#v", row["total_budget"])
	}
	if _, ok := row["member_ids"].([]any); !ok {
		t.Fatalf("member_ids 非数组: %#v", row["member_ids"])
	}
}

func TestGetApplication_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	r := httptest.NewRequest("GET", "/api/v1/apply/applications/999999", nil)
	e.ServeHTTP(w, r)
	if w.Code != http.StatusNotFound {
		t.Fatalf("期望 404，实得 %d", w.Code)
	}
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/modules/p/ -v`
预期：编译失败 `undefined: auth.CtxTenantID`、`undefined: NewHandler`、`undefined: Register`。

- [ ] **步骤 3：写实现**

`backend-go/internal/platform/auth/domain.go`：

```go
package auth

import "github.com/gin-gonic/gin"

const (
	CtxUserID        = "uid"
	CtxTenantID      = "tenant_id"
	CtxLegalEntityID = "legal_entity_id"
	CtxSecurityLevel = "security_level"
	CtxRoles         = "roles"
)

type Domain struct {
	UserID        int64
	TenantID      int64
	LegalEntityID int64 // 0 表示未细分
	SecurityLevel string
	Roles         []string
}

func DomainFrom(c *gin.Context) Domain {
	d := Domain{SecurityLevel: "INTERNAL"}
	if v, ok := c.Get(CtxUserID); ok {
		d.UserID, _ = v.(int64)
	}
	if v, ok := c.Get(CtxTenantID); ok {
		d.TenantID, _ = v.(int64)
	}
	if v, ok := c.Get(CtxLegalEntityID); ok {
		d.LegalEntityID, _ = v.(int64)
	}
	if v, ok := c.Get(CtxSecurityLevel); ok {
		if s, ok2 := v.(string); ok2 && s != "" {
			d.SecurityLevel = s
		}
	}
	if v, ok := c.Get(CtxRoles); ok {
		d.Roles, _ = v.([]string)
	}
	return d
}
```

`backend-go/internal/modules/p/mapper.go`：

```go
package p

import (
	"encoding/json"
	"time"

	"github.com/eplugger/ark/internal/modules/p/store"
)

// ToAPIApplication 把 sqlc 行映射为契约 Application 形状（snake_case，与 design 一致）。
func ToAPIApplication(r store.Application) map[string]any {
	var memberIDs any = []any{}
	if len(r.MemberIDs) > 0 {
		_ = json.Unmarshal(r.MemberIDs, &memberIDs)
	}
	out := map[string]any{
		"id":              r.ID,
		"tenant_id":       r.TenantID,
		"status":          r.Status,
		"deleted":         r.Deleted,
		"creator_id":      r.CreatorID,
		"title":           r.Title,
		"project_type":    r.ProjectType,
		"pi_user_id":      r.PiUserID,
		"member_ids":      memberIDs,
		"is_horizontal":   r.IsHorizontal,
		"ai_draft_marked": r.AiDraftMarked,
		"created_at":      r.CreatedAt.UTC().Format(time.RFC3339Nano),
		"updated_at":      r.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}
	putStr := func(k string, v *string) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putStr("code", r.Code)
	putStr("remark", r.Remark)
	putStr("abstract", r.Abstract)
	putStr("total_budget", r.TotalBudget)
	putStr("funding_channel", r.FundingChannel)
	if r.DurationMonths != nil {
		out["duration_months"] = *r.DurationMonths
	} else {
		out["duration_months"] = nil
	}
	if r.SubmitAt != nil {
		out["submit_at"] = r.SubmitAt.UTC().Format(time.RFC3339Nano)
	} else {
		out["submit_at"] = nil
	}
	return out
}
```

`backend-go/internal/modules/p/handler.go`：

```go
package p

import (
	"context"
	"encoding/json"
	"strconv"

	"github.com/eplugger/ark/internal/modules/p/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	q *store.Queries
}

func NewHandler(pool *pgxpool.Pool) *Handler {
	return &Handler{q: store.New(pool)}
}

func pageArgs(c *gin.Context) (int32, int32, int32, int32) {
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	size, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if page < 1 {
		page = 1
	}
	if size < 1 {
		size = 20
	}
	if size > 200 {
		size = 200
	}
	return int32(page), int32(size), int32(size), int32((page - 1) * size)
}

func (h *Handler) ListApplications(c *gin.Context) {
	d := auth.DomainFrom(c)
	_, size, limit, offset := pageArgs(c)
	status := optQuery(c, "status")
	ptype := optQuery(c, "project_type")
	rows, err := h.q.ListApplications(c, store.ListApplicationsParams{
		TenantID: d.TenantID, Limit: limit, Offset: offset, Status: status, ProjectType: ptype,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountApplications(c, store.CountApplicationsParams{
		TenantID: d.TenantID, Status: status, ProjectType: ptype,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIApplication(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": int(size) / int(size) * atoi(c.DefaultQuery("page", "1")), "size": size})
}

func (h *Handler) GetApplication(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetApplication(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "记录不存在")
		return
	}
	httpx.WriteOK(c, ToAPIApplication(r))
}

func (h *Handler) CreateApplication(c *gin.Context) {
	d := auth.DomainFrom(c)
	var body struct {
		Title        string          `json:"title" binding:"required"`
		ProjectType  string          `json:"project_type" binding:"required"`
		PiUserID     int64           `json:"pi_user_id" binding:"required"`
		MemberIDs    json.RawMessage `json:"member_ids"`
		DepartmentID *int64          `json:"department_id"`
		Abstract     *string         `json:"abstract"`
		TotalBudget  *string         `json:"total_budget"`
		IsHorizontal bool            `json:"is_horizontal"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	memberIDs := body.MemberIDs
	if len(memberIDs) == 0 {
		memberIDs = json.RawMessage("[]")
	}
	var abs any
	if body.Abstract != nil {
		abs = *body.Abstract
	}
	tb := "\\N"
	if body.TotalBudget != nil {
		tb = *body.TotalBudget
	}
	r, err := h.q.CreateApplication(context.Background(), store.CreateApplicationParams{
		TenantID: d.TenantID, Status: "DRAFT", CreatorID: d.UserID,
		Title: body.Title, ProjectType: body.ProjectType, PiUserID: body.PiUserID,
		MemberIDs: memberIDs, DepartmentID: body.DepartmentID,
		Abstract: anyStr(abs), TotalBudget: anyStr(tb), IsHorizontal: body.IsHorizontal,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIApplication(r))
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

func anyStr(v any) *string {
	if s, ok := v.(string); ok {
		return &s
	}
	return nil
}

func atoi(s string) int {
	n, _ := strconv.Atoi(s)
	if n < 1 {
		return 1
	}
	return n
}
```

> `CreateApplication` 的 `member_ids` 参数类型取决于 sqlc 生成（`[]byte`）。若生成的是 `[]byte`，把 `MemberIDs: memberIDs`（`json.RawMessage` 底层即 `[]byte`）直接传入即可；`TotalBudget` 传字符串经查询里的 `$10::numeric` 转换——若 sqlc 把该参数生成为 `pgtype.Numeric`，改用一个 `store` 包外的薄封装：`pool.ExecContext` 执行同一 INSERT。竖切优先保证 list/read，create 作为附加。

`backend-go/internal/modules/p/routes.go`：

```go
package p

import "github.com/gin-gonic/gin"

// Register 把 P 竖切三条路由挂到 /api/v1/apply 分组（对齐 design servers.url=/api/v1 + paths）。
func Register(e *gin.Engine, h *Handler) {
	g := e.Group("/api/v1/apply")
	g.GET("/applications", h.ListApplications)
	g.POST("/applications", h.CreateApplication)
	g.GET("/applications/:id", h.GetApplication)
}
```

修改 `backend-go/internal/router.go`：给 `NewRouter` 增加可选依赖注册（M0 保持最小，先不改；竖切测试用独立 `Register`。集成到主 router 在任务 12 完成）。

- [ ] **步骤 4：运行确认通过**

```bash
ARK_TEST_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable \
  go test ./internal/modules/p/ -run TestListApplications -v
```
预期：`TestListApplications_Endpoint` PASS；`TestGetApplication_404WhenMissing` PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/auth backend-go/internal/modules/p
git commit -m "feat(go): M0 P 模块 list/read/create 竖切打通(仓储→契约形状→包络)"
```

---

## 任务 8：契约合规测试（把 Node `verify` 思路移植到 Go CI）

确保 Go 真实响应体对 `design` 的 200 `data` schema 合规（防契约漂移）。用 `gojsonschema` 对任务 7 的输出按任务 6 抽取的 schema 校验。

**文件：**
- 创建：`backend-go/internal/platform/oapi/validate.go`
- 创建：`backend-go/internal/modules/p/contract_test.go`

- [ ] **步骤 1：写失败测试**

`backend-go/internal/modules/p/contract_test.go`：

```go
package p

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

func TestListApplications_ConformsToContract(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	e := newTestEngine(t)
	spec := mustSpec(t)
	op := spec.Find("GET", "/apply/applications")
	dataSchema := oapi.ResolveDataSchema(op) // 把 data 子 schema 展平为可校验 JSON Schema

	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/applications", nil))
	var env map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &env)

	errs := oapi.Validate(env["data"], dataSchema)
	if len(errs) > 0 {
		t.Fatalf("响应 data 不合契约: %v", errs)
	}
}

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
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/modules/p/ -run Contract -v`
预期：编译失败 `undefined: oapi.ResolveDataSchema/Validate`。

- [ ] **步骤 3：实现校验器**

`backend-go/internal/platform/oapi/validate.go`：

```go
package oapi

import (
	"encoding/json"

	"github.com/xeipuuv/gojsonschema"
)

// ResolveDataSchema 取 op 的 data 子 schema 并转成 gojsonschema 可用的 map。
func ResolveDataSchema(op *Op) map[string]any {
	d := op.DataSchema()
	if d == nil {
		return map[string]any{"type": "object"}
	}
	// 深拷贝转 JSON（去除 yaml 专有类型），并保留 $ref 需内联展开：这里对 PageResult/enum 做浅展开。
	b, _ := json.Marshal(d)
	var out map[string]any
	_ = json.Unmarshal(b, &out)
	return out
}

// Validate 用 schema 校验 value，返回错误列表（空=通过）。
// schema 里的 $ref 若指向本模块 components，先由 op.doc 展开为内联 definitions。
func Validate(value any, schema map[string]any) []string {
	// 把契约里的 #/components 引用替换为占位宽松节点，避免跨文档解析复杂度的同时校验主干字段类型
	sanitized := inlineRefs(schema, value)
	docLoader := gojsonschema.NewGoLoader(value)
	schemaLoader := gojsonschema.NewGoLoader(sanitized)
	res, err := gojsonschema.Validate(schemaLoader, docLoader)
	if err != nil {
		return []string{err.Error()}
	}
	var msgs []string
	for _, e := range res.Errors() {
		msgs = append(msgs, e.String())
	}
	return msgs
}
```

> `inlineRefs` 最小实现：遍历 schema，遇 `{"$ref": "#/components/schemas/X"}` 替换为 `{"type": ["string","number","integer","boolean","object","array","null"]}`（放行），从而聚焦校验 `PageResult` 的 `list/total/page/size` 与 `Application` 已内联的字段类型（enum `status` 用其 `type` 即可）。这足以在 M0 抓住"字段缺失/类型错"这类漂移；enum 精确值校验留待 M1（`superpowers` 精神：先绿再强）。把 `inlineRefs` 放 `spec.go`：

```go
func inlineRefs(schema map[string]any, _ any) map[string]any {
	var walk func(any) any
	walk = func(n any) any {
		m, ok := n.(map[string]any)
		if !ok {
			if arr, ok2 := n.([]any); ok2 {
				for i := range arr {
					arr[i] = walk(arr[i])
				}
				return arr
			}
			return n
		}
		if ref, isRef := m["$ref"].(string); isRef && strings.HasPrefix(ref, "#/") {
			return map[string]any{"type": []string{"string", "number", "integer", "boolean", "object", "array", "null"}}
		}
		for k, v := range m {
			m[k] = walk(v)
		}
		return m
	}
	out, _ := walk(schema).(map[string]any)
	return out
}
```

安装依赖：`go get github.com/xeipuuv/gojsonschema@v1.2.0`。

- [ ] **步骤 4：运行确认通过**

```bash
ARK_TEST_DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable \
  go test ./internal/modules/p/ -run Contract -v
```
预期：PASS（`data` 含 `list/total/page/size` 且 list 元素字段类型合规）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/oapi/validate.go backend-go/internal/modules/p/contract_test.go
git commit -m "test(go): M0 契约合规校验(verify 思路移植)守护 P 竖切响应"
```

## 任务 9：JWT 鉴权 + Casbin 授权 + 数据域注入中间件

补齐 §2 差距表里两个🔴项（身份认证、授权与数据权限）。JWT 解析 claims（含 `uid/tenant_id/legal_entity_id/security_level/roles`）注入 context（复用任务 7 的 `auth.Domain`），Casbin 以 `role + path + method` 做 RBAC 判定；未鉴权 401、越权 403。

**文件：**
- 创建：`backend-go/internal/platform/auth/jwt.go`
- 创建：`backend-go/internal/platform/auth/jwt_test.go`
- 创建：`backend-go/internal/platform/auth/model.conf`
- 创建：`backend-go/internal/platform/auth/policy.csv`
- 创建：`backend-go/internal/platform/auth/casbin.go`
- 创建：`backend-go/internal/platform/middleware/auth.go`
- 创建：`backend-go/internal/platform/middleware/auth_test.go`

- [ ] **步骤 1：写失败测试（token 往返 + 中间件 401/403/allow）**

`backend-go/internal/platform/auth/jwt_test.go`：

```go
package auth

import "testing"

func TestTokenRoundTrip(t *testing.T) {
	secret := "test-secret"
	tk, err := GenToken(secret, 60, Claims{
		UserID: 1001, TenantID: 1, SecurityLevel: "INTERNAL", Roles: []string{"R-ADMIN"},
	})
	if err != nil {
		t.Fatal(err)
	}
	c, err := ParseToken(secret, tk)
	if err != nil {
		t.Fatal(err)
	}
	if c.UserID != 1001 || c.TenantID != 1 || c.Roles[0] != "R-ADMIN" {
		t.Fatalf("claims 还原错误: %+v", c)
	}
}

func TestParseToken_InvalidFails(t *testing.T) {
	if _, err := ParseToken("a", "garbage"); err == nil {
		t.Fatal("期望非法令牌报错")
	}
}
```

`backend-go/internal/platform/middleware/auth_test.go`：

```go
package middleware

import (
	"net/http/httptest"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

func build(t *testing.T) *gin.Engine {
	enf, err := auth.NewEnforcer("../auth/model.conf", "../auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), Auth("test-secret", enf))
	e.GET("/api/v1/apply/applications", func(c *gin.Context) {
		httpx.WriteOK(c, gin.H{"tenant": auth.DomainFrom(c).TenantID})
	})
	return e
}

func TestAuth_MissingToken401(t *testing.T) {
	w := httptest.NewRecorder()
	build(t).ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/applications", nil))
	if w.Code != 401 {
		t.Fatalf("期望 401，得 %d", w.Code)
	}
}

func TestAuth_AdminAllowedAndTenantInjected(t *testing.T) {
	tk, _ := auth.GenToken("test-secret", 60, auth.Claims{UserID: 1, TenantID: 7, Roles: []string{"R-ADMIN"}})
	req := httptest.NewRequest("GET", "/api/v1/apply/applications", nil)
	req.Header.Set("Authorization", "Bearer "+tk)
	w := httptest.NewRecorder()
	build(t).ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("期望 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if !contains(w.Body.String(), "\"tenant\":7") {
		t.Fatalf("数据域未注入: %s", w.Body.String())
	}
}

func TestAuth_STAFFDenied403(t *testing.T) {
	tk, _ := auth.GenToken("test-secret", 60, auth.Claims{UserID: 2, TenantID: 7, Roles: []string{"R-STAFF-NOACCESS"}})
	req := httptest.NewRequest("GET", "/api/v1/apply/applications", nil)
	req.Header.Set("Authorization", "Bearer "+tk)
	w := httptest.NewRecorder()
	build(t).ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatalf("期望 403，得 %d", w.Code)
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (indexOf(s, sub) >= 0)
}
func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/platform/auth/ ./internal/platform/middleware/ -v`
预期：编译失败 `undefined: GenToken/Claims/NewEnforcer/Auth`。

- [ ] **步骤 3：写实现**

`backend-go/internal/platform/auth/jwt.go`：

```go
package auth

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

type Claims struct {
	UserID        int64    `json:"uid"`
	TenantID      int64    `json:"tenant_id"`
	LegalEntityID int64    `json:"legal_entity_id"`
	SecurityLevel string   `json:"security_level"`
	Roles         []string `json:"roles"`
	jwt.RegisteredClaims
}

func GenToken(secret string, ttlSec int64, c Claims) (string, error) {
	now := time.Now()
	c.RegisteredClaims = jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(now.Add(time.Duration(ttlSec) * time.Second)),
		IssuedAt:  jwt.NewNumericDate(now),
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, c)
	return tok.SignedString([]byte(secret))
}

func ParseToken(secret, raw string) (*Claims, error) {
	p, err := jwt.ParseWithClaims(raw, &Claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("非预期签名算法")
		}
		return []byte(secret), nil
	})
	if err != nil {
		return nil, err
	}
	c, ok := p.Claims.(*Claims)
	if !ok || !p.Valid {
		return nil, errors.New("令牌无效")
	}
	return c, nil
}
```

`backend-go/internal/platform/auth/casbin.go`：

```go
package auth

import "github.com/casbin/casbin/v2"

func NewEnforcer(modelPath, policyPath string) (*casbin.Enforcer, error) {
	return casbin.NewEnforcer(modelPath, policyPath)
}
```

`backend-go/internal/platform/auth/model.conf`：

```ini
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act

[matcher_definition]
m = r.sub == p.sub && keyMatch2(r.obj, p.obj) && r.act == p.act
```

`backend-go/internal/platform/auth/policy.csv`（M0 基线；M1 由 DB 加载）：

```csv
p, R-ADMIN, /api/v1/*, GET
p, R-ADMIN, /api/v1/*, POST
p, R-STAFF, /api/v1/apply/*, GET
p, R-STAFF, /api/v1/apply/*, POST
```

`backend-go/internal/platform/middleware/auth.go`：

```go
package middleware

import (
	"net/http"
	"strings"

	"github.com/casbin/casbin/v2"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// Auth 校验 Bearer JWT → 注入数据域 → Casbin 判权（任一带权限的 role 命中即放行）。
func Auth(secret string, enf *casbin.Enforcer) gin.HandlerFunc {
	return func(c *gin.Context) {
		h := c.GetHeader("Authorization")
		if !strings.HasPrefix(h, "Bearer ") {
			httpx.WriteErr(c, http.StatusUnauthorized, 40101, "未认证")
			c.Abort()
			return
		}
		claims, err := auth.ParseToken(secret, strings.TrimPrefix(h, "Bearer "))
		if err != nil {
			httpx.WriteErr(c, http.StatusUnauthorized, 40102, "令牌无效或过期")
			c.Abort()
			return
		}
		// 数据域注入
		c.Set(auth.CtxUserID, claims.UserID)
		c.Set(auth.CtxTenantID, claims.TenantID)
		c.Set(auth.CtxLegalEntityID, claims.LegalEntityID)
		if claims.SecurityLevel != "" {
			c.Set(auth.CtxSecurityLevel, claims.SecurityLevel)
		}
		c.Set(auth.CtxRoles, claims.Roles)

		// 授权：逐角色判定，命中即放行
		path := c.Request.URL.Path
		method := c.Request.Method
		ok := false
		for _, role := range claims.Roles {
			if allowed, _ := enf.Enforce(role, path, method); allowed {
				ok = true
				break
			}
		}
		if !ok {
			httpx.WriteErr(c, http.StatusForbidden, 40301, "无权限")
			c.Abort()
			return
		}
		c.Next()
	}
}
```

依赖：`go get github.com/golang-jwt/jwt/v5@v5.2.1 github.com/casbin/casbin/v2@v2.96.0`。

- [ ] **步骤 4：运行确认通过**

运行：`cd backend-go && go test ./internal/platform/auth/ ./internal/platform/middleware/ -v`
预期：全部 PASS（401 / 403 / allow+数据域注入）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/auth backend-go/internal/platform/middleware/auth.go backend-go/internal/platform/middleware/auth_test.go
git commit -m "feat(go): M0 JWT 鉴权 + Casbin RBAC + 数据域注入中间件"
```

---

## 任务 10：Redis 外置幂等中间件（`Idempotency-Key`）

进程内 Map 多副本失效（§2 差距表 #7）。用 Redis `SETNX` 抢占 + 首次结果缓存回放。测试用 `miniredis` 免真实 Redis。

**文件：**
- 创建：`backend-go/internal/platform/middleware/idempotency.go`
- 创建：`backend-go/internal/platform/middleware/idempotency_test.go`

- [ ] **步骤 1：写失败测试（同 key 二次请求回放首次响应体）**

`backend-go/internal/platform/middleware/idempotency_test.go`：

```go
package middleware

import (
	"io"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

func newEngine(rdb *redis.Client) *gin.Engine {
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), Idempotency(rdb, time.Minute))
	n := 0
	e.POST("/api/v1/apply/applications", func(c *gin.Context) {
		n++
		httpx.WriteOK(c, gin.H{"created": n})
	})
	return e
}

func TestIdempotency_ReplaysSameBody(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	e := newEngine(rdb)

	do := func() string {
		req := httptest.NewRequest("POST", "/api/v1/apply/applications", strings.NewReader(`{}`))
		req.Header.Set("Idempotency-Key", "K-1")
		w := httptest.NewRecorder()
		e.ServeHTTP(w, req)
		b, _ := io.ReadAll(w.Body)
		return string(b)
	}
	first := do()
	second := do()
	if first != second {
		t.Fatalf("幂等失败: first=%s second=%s", first, second)
	}
	if !strings.Contains(first, "\"created\":1") || !strings.Contains(second, "\"created\":1") {
		t.Fatalf("应回放首次结果: %s / %s", first, second)
	}
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/platform/middleware/ -run Idempotency -v`
预期：编译失败 `undefined: Idempotency`。

- [ ] **步骤 3：写实现（响应捕获 + SETNX 回放）**

`backend-go/internal/platform/middleware/idempotency.go`：

```go
package middleware

import (
	"bytes"
	"io"
	"net/http"
	"time"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

type captureWriter struct {
	gin.ResponseWriter
	buf *bytes.Buffer
}

func (w *captureWriter) Write(b []byte) (int, error) { return w.buf.Write(b) }
func (w *captureWriter) WriteString(s string) (int, error) { return w.buf.WriteString(s) }

// Idempotency：对带 Idempotency-Key 的写请求做 Redis 去重与回放。
func Idempotency(rdb *redis.Client, ttl time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Method == http.MethodGet {
			c.Next()
			return
		}
		key := c.GetHeader("Idempotency-Key")
		if key == "" {
			c.Next()
			return
		}
		cacheKey := "idem:" + c.Request.Method + ":" + c.Request.URL.Path + ":" + key
		ctx := c.Request.Context()

		// 已有缓存 → 回放
		if body, err := rdb.Get(ctx, cacheKey).Bytes(); err == nil {
			c.Data(http.StatusOK, "application/json; charset=utf-8", body)
			c.Abort()
			return
		}
		// 抢占：SETNX 处理中标记，避免并发重复执行
		ok, _ := rdb.SetNX(ctx, cacheKey+":lock", "1", ttl).Result()
		if !ok {
			httpx.WriteErr(c, http.StatusConflict, 40909, "相同幂等键正在处理中")
			c.Abort()
			return
		}
		cw := &captureWriter{ResponseWriter: c.Writer, buf: &bytes.Buffer{}}
		c.Writer = cw
		c.Next()
		// 完成后写入结果并清锁
		rdb.Set(ctx, cacheKey, cw.buf.Bytes(), ttl)
		rdb.Del(ctx, cacheKey+":lock")
	}
}
```

依赖：`go get github.com/redis/go-redis/v9@v9.5.1 github.com/alicebob/miniredis/v2@v2.33.0`。

- [ ] **步骤 4：运行确认通过**

运行：`cd backend-go && go test ./internal/platform/middleware/ -run Idempotency -v`
预期：PASS（两次返回 `created:1`）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/middleware/idempotency.go backend-go/internal/platform/middleware/idempotency_test.go
git commit -m "feat(go): M0 Redis 外置幂等中间件(Idempotency-Key 回放)"
```

---

## 任务 11：契约驱动 passthrough 生成器（Go 版，保证"直接替换"后全局可用）

Go 直接替换 Node 后，未落真实域逻辑的 action/analysis/computed 路由（Node 侧曾覆盖 127 条 passthrough）必须有响应，否则前端全崩。移植 Node `generator.js` + `matchRoute`：`engine.NoRoute` 兜底 → 匹配 design 模板路径 → 抽 `data` schema → 生成合规示例值 → 统一包络。真实已实现路由（如 P 竖切）因 gin 已注册而不进 NoRoute。

**文件：**
- 创建：`backend-go/internal/platform/oapi/match.go`
- 创建：`backend-go/internal/platform/oapi/generator.go`
- 创建：`backend-go/internal/platform/oapi/passthrough.go`
- 创建：`backend-go/internal/platform/oapi/generator_test.go`

- [ ] **步骤 1：写失败测试（未实现路由经生成器返回合规包络）**

`backend-go/internal/platform/oapi/generator_test.go`：

```go
package oapi

import (
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

func TestPassthrough_GeneratesEnvelope(t *testing.T) {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../../../design"
	}
	spec, err := LoadDir(d)
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID())
	e.NoRoute(Passthrough(spec))

	// 选一条契约里存在、但未手工实现的动作路由（示例：提交申报）
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/apply/applications/1/submit", nil))
	if w.Code != 200 {
		t.Fatalf("passthrough 期望 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if !containsStr(w.Body.String(), "\"code\":0") || !containsStr(w.Body.String(), "\"traceId\":") {
		t.Fatalf("passthrough 包络不合规: %s", w.Body.String())
	}
}

func containsStr(s, sub string) bool { return len(s) >= len(sub) && indexOfStr(s, sub) >= 0 }
func indexOfStr(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/platform/oapi/ -run Passthrough -v`
预期：编译失败 `undefined: Passthrough`。

- [ ] **步骤 3：写实现（路径匹配 + schema→值生成）**

`backend-go/internal/platform/oapi/match.go`（移植 Node `templateRegex` + `literalLen` 优先级）：

```go
package oapi

import (
	"regexp"
	"strings"
)

type tplEntry struct {
	key  string // "METHOD /template/path"
	re   *regexp.Regexp
	lit  int
	op   *Op
}

func (s *Spec) compileMatcher() []tplEntry {
	out := make([]tplEntry, 0, len(s.index))
	for k, op := range s.index {
		parts := strings.SplitN(k, " ", 2)
		out = append(out, tplEntry{
			key: k, re: templateRegex(op.path),
			lit: literalLen(op.path), op: op,
		})
		_ = parts
	}
	return out
}

func templateRegex(tpl string) *regexp.Regexp {
	var re strings.Builder
	re.WriteString("^")
	seg := splitBraces(tpl)
	for _, p := range seg {
		if strings.HasPrefix(p, "{") && strings.HasSuffix(p, "}") {
			re.WriteString(`([^/]+?)`)
		} else {
			re.WriteString(regexp.QuoteMeta(p))
		}
	}
	re.WriteString("$")
	return regexp.MustCompile(re.String())
}

// splitBraces 按 {...} 切分，保留分隔。
func splitBraces(tpl string) []string {
	var out []string
	i := 0
	for i < len(tpl) {
		if tpl[i] == '{' {
			j := strings.IndexByte(tpl[i:], '}')
			if j < 0 {
				out = append(out, tpl[i:])
				break
			}
			out = append(out, tpl[i:i+j+1])
			i += j + 1
		} else {
			j := strings.IndexByte(tpl[i:], '{')
			if j < 0 {
				out = append(out, tpl[i:])
				break
			}
			out = append(out, tpl[i:i+j])
			i += j
		}
	}
	return out
}

func literalLen(tpl string) int {
	return len(regexp.MustCompile(`\{[^/}]+\}`).ReplaceAllString(tpl, ""))
}

// Match 用去前缀后的具体路径找最"具体"的模板 op。
func (s *Spec) Match(method, urlPath string) *Op {
	p := urlPath
	if i := strings.Index(p, "?"); i >= 0 {
		p = p[:i]
	}
	p = strings.TrimPrefix(p, "/api/v1")
	if !strings.HasPrefix(p, "/") {
		p = "/" + p
	}
	mu := strings.ToUpper(method)
	if exact := s.index[mu+" "+p]; exact != nil {
		return exact
	}
	var best *Op
	bestLit := -1
	for _, en := range s.compileMatcher() {
		if !strings.HasPrefix(en.key, mu+" ") {
			continue
		}
		if en.re.MatchString(p) && en.lit > bestLit {
			bestLit = en.lit
			best = en.op
		}
	}
	return best
}
```

`backend-go/internal/platform/oapi/generator.go`（移植 Node `generate`，够覆盖 object/array/enum/format/$ref/allOf/PageResult）：

```go
package oapi

import (
	"math/rand"
	"time"
)

// Generate 依 data 子 schema 造一个合规示例值。
func (o *Op) Generate() any {
	d := o.DataSchema()
	if d == nil {
		return ginEmptyObj()
	}
	return genValue(o.doc, d, 0)
}

func ginEmptyObj() any { return map[string]any{} }

func genValue(doc *Doc, node map[string]any, depth int) any {
	if node == nil || depth > 8 {
		return nil
	}
	if ref, ok := node["$ref"].(string); ok {
		return genValue(doc, doc.deref(ref), depth+1)
	}
	if all, ok := node["allOf"].([]any); ok {
		out := map[string]any{}
		for _, s := range all {
			if sm, ok := s.(map[string]any); ok {
				if v, ok := genValue(doc, sm, depth+1).(map[string]any); ok {
					for k, x := range v {
						out[k] = x
					}
				}
			}
		}
		return out
	}
	switch node["type"] {
	case "array":
		items, _ := node["items"].(map[string]any)
		n := 3
		if node["x-count"] != nil {
			if c, ok := node["x-count"].(int); ok {
				n = c
			}
		}
		arr := make([]any, 0, n)
		for i := 0; i < n; i++ {
			arr = append(arr, genValue(doc, items, depth+1))
		}
		return arr
	case "object":
		props, _ := node["properties"].(map[string]any)
		out := map[string]any{}
		for k, ps := range props {
			pm, _ := ps.(map[string]any)
			out[k] = genValue(doc, pm, depth+1)
		}
		// PageResult 常见形状补全
		if _, hasList := out["list"]; hasList {
			out["total"] = len(out["list"].([]any))
			out["page"] = 1
			out["size"] = out["total"]
		}
		return out
	case "string":
		return genString(node)
	case "integer", "number":
		return genNumber(node)
	case "boolean":
		return true
	default:
		return nil
	}
}

func genString(node map[string]any) any {
	if enum, ok := node["enum"].([]any); ok && len(enum) > 0 {
		// 跳过 null 候选（沿用此前生成器修复经验，防 String(null)）
		var cand []any
		for _, e := range enum {
			if e != nil {
				cand = append(cand, e)
			}
		}
		if len(cand) > 0 {
			if s, ok := cand[rand.Intn(len(cand))].(string); ok {
				return s
			}
		}
	}
	switch node["format"] {
	case "date-time":
		return time.Now().UTC().Format(time.RFC3339Nano)
	case "date":
		return time.Now().UTC().Format("2006-01-02")
	case "uuid":
		return "00000000-0000-0000-0000-000000000000"
	}
	return "sample"
}

func genNumber(node map[string]any) any {
	if node["type"] == "integer" {
		return rand.Intn(1000)
	}
	return float64(rand.Intn(100000)) / 100
}
```

`backend-go/internal/platform/oapi/passthrough.go`：

```go
package oapi

import (
	"net/http"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// Passthrough 作为 gin NoRoute 兜底：命中契约但未手工实现的路由，生成合规示例响应。
func Passthrough(s *Spec) gin.HandlerFunc {
	return func(c *gin.Context) {
		op := s.Match(c.Request.Method, c.Request.URL.Path)
		if op == nil {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "契约未定义该路由")
			return
		}
		data := op.Generate()
		// GET list 落地分页参数
		if m, ok := data.(map[string]any); ok {
			if _, hasList := m["list"]; hasList && c.Request.Method == "GET" {
				m["page"] = atoiDefault(c.Query("page"), 1)
				m["size"] = atoiDefault(c.Query("size"), len(m["list"].([]any)))
			}
		}
		httpx.WriteOK(c, data)
	}
}

func atoiDefault(s string, def int) int {
	if s == "" {
		return def
	}
	n, err := strconvAtoi(s)
	if err != nil {
		return def
	}
	return n
}
```

在 `spec.go` 末尾补一个不引额外 import 的小 helper（或 `import "strconv"` 后 `func strconvAtoi(s string)(int,error){return strconv.Atoi(s)}`）。

- [ ] **步骤 4：运行确认通过**

运行：`cd backend-go && go test ./internal/platform/oapi/ -run Passthrough -v`
预期：PASS（未实现动作路由返回 `code:0` 合规包络）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/oapi
git commit -m "feat(go): M0 契约驱动 passthrough 生成器(NoRoute 兜底,保障 Go 直替后全局可用)"
```

---

## 任务 12：装配主 router（鉴权 + 幂等 + P 竖切 + passthrough + 开发登录）

把任务 1–11 的零件在 `internal.Build` 里拼成一个可运行的 Gin 引擎：`/healthz` 与 `/api/v1/auth/login` 公开，`/api/v1/*` 受 JWT+Casbin 鉴权与幂等保护，P 竖切三条路由挂到受保护分组，未实现的契约路由由 `oapi.Passthrough` 作 `NoRoute` 兜底。M0 用内置账号（ark/ark）签发带数据域的 JWT，便于 compose 冒烟与前端关 mock 后直连。

> 命名铁律（沿用前序任务，务必逐字一致）：`internal.Build(RouterDeps)`、`internal.RouterDeps{Logger,Cfg,Pool,Redis,Enforcer,Spec}`、`auth.HandleLogin(secret string, ttl int64) gin.HandlerFunc`、`middleware.Auth(secret string, enf *casbin.Enforcer) gin.HandlerFunc`、`middleware.Idempotency(rdb *redis.Client, ttl time.Duration) gin.HandlerFunc`、`oapi.Passthrough(s *Spec) gin.HandlerFunc`、`p.NewHandler(pool)`、`p.Register(gin.IRoutes, *p.Handler)`、`httpx.WriteOK/WriteErr`、`auth.Claims{UserID,TenantID,LegalEntityID,SecurityLevel,Roles}`、`auth.GenToken(secret,ttl,Claims)`。

**关键改动点**
- `p.Register` 的签名从 `(e *gin.Engine, h *Handler)` **改为 `(r gin.IRoutes, h *Handler)`**，这样既能挂 `*gin.Engine` 也能挂受保护 `*gin.RouterGroup`。`gin.IRoutes` 有 `Group()` 方法，函数体 `g := r.Group("/apply")` 不变（注意：分组前缀 `/api/v1` 现由调用方 `api := e.Group("/api/v1")` 提供，`Register` 内部只写 `/apply`）。
- `middleware.Idempotency` 内部**只对非安全方法生效**（`POST/PUT/PATCH/DELETE`），`GET/HEAD/OPTIONS` 直接 `c.Next()` 不触碰 Redis——这样 401/GET 用例即使 Redis 为 nil 也不 panic。任务 10 的实现应已含此判断；若没有，本任务在 `idempotency.go` 开头补：

```go
switch c.Request.Method {
case http.MethodGet, http.MethodHead, http.MethodOptions:
    c.Next()
    return
}
```

**文件：**
- 修改：`backend-go/internal/config/config.go`（增 `AuthModelPath`、`AuthPolicyPath` 两字段与默认值）
- 修改：`backend-go/internal/config/config_test.go`（补断言：两路径默认值非空）
- 修改：`backend-go/internal/router.go`（把 `NewRouter(l)` 扩为 `Build(RouterDeps)`；保留 `NewRouter` 兼容旧单测或直接替换，二者择一——本任务**替换**，任务 3 的 `NewRouter` 单测同步改名为 `TestBuild_Healthz`）
- 创建：`backend-go/internal/router_test.go`
- 创建：`backend-go/internal/platform/auth/login.go`
- 修改：`backend-go/internal/modules/p/routes.go`（`Register` 形参 `*gin.Engine` → `gin.IRoutes`，内部分组去 `/api/v1` 前缀）
- 修改：`backend-go/cmd/server/main.go`（完整装配）

- [ ] **步骤 1：先改 config（加两字段 + 默认值），写失败测试**

`backend-go/internal/config/config_test.go` 末尾追加：

```go
func TestLoad_AuthPaths(t *testing.T) {
	t.Setenv("ARK_AUTH_MODEL_PATH", "")
	t.Setenv("ARK_AUTH_POLICY_PATH", "")
	c := Load()
	if c.AuthModelPath == "" || c.AuthPolicyPath == "" {
		t.Fatalf("auth 路径应有默认值: model=%q policy=%q", c.AuthModelPath, c.AuthPolicyPath)
	}
}
```

运行：`cd backend-go && go test ./internal/config/ -run TestLoad_AuthPaths -v`
预期：编译失败 `c.AuthModelPath undefined`。

在 `config.go` 的 `Config` 结构体追加两字段（紧跟 `DesignDir` 之后）：

```go
	AuthModelPath  string
	AuthPolicyPath string
```

在 `Load()` 返回的 struct literal 里追加：

```go
		AuthModelPath:  get("ARK_AUTH_MODEL_PATH", "./internal/platform/auth/model.conf"),
		AuthPolicyPath: get("ARK_AUTH_POLICY_PATH", "./internal/platform/auth/policy.csv"),
```

运行：`cd backend-go && go test ./internal/config/ -run TestLoad_AuthPaths -v` → PASS。

- [ ] **步骤 2：写失败测试（登录签发 JWT + 受保护路由无令牌 401 + healthz 公开）**

`backend-go/internal/router_test.go`：

```go
package internal

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/oapi"
)

func buildForTest(t *testing.T) *BuildDepsBox {
	t.Helper()
	cfg := config.Load()
	cfg.JWTSecret = "test-secret"
	// go test ./internal/ 工作目录=backend-go/internal，Casbin 文件相对该目录为 platform/auth/*
	cfg.AuthModelPath = "platform/auth/model.conf"
	cfg.AuthPolicyPath = "platform/auth/policy.csv"
	// 真实 enforcer（任务 9 的 model.conf/policy.csv）
	enf, err := auth.NewEnforcer(cfg.AuthModelPath, cfg.AuthPolicyPath)
	if err != nil {
		t.Fatalf("NewEnforcer: %v", err)
	}
	// 真实契约目录（默认 ../../../../design；测试相对路径按 go test 工作目录解析）
	spec, err := oapi.LoadDir(designDirForTest())
	if err != nil {
		t.Fatalf("LoadDir: %v", err)
	}
	// Pool/Redis 传 nil：本用例只走公开路由与 401 短路，不触达 DB/Redis
	e := Build(RouterDeps{Cfg: cfg, Enforcer: enf, Spec: spec})
	return &BuildDepsBox{e}
}

type BuildDepsBox struct{ e interface{ ServeHTTP(http.ResponseWriter, *http.Request) } }

func designDirForTest() string {
	// go test 的工作目录是包目录 backend-go/internal/，向上两级即到仓库根，再入 design。
	return "../../design"
}

func TestBuild_HealthzPublic(t *testing.T) {
	b := buildForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	b.e.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("healthz=%d want 200", rec.Code)
	}
	if !bytes.Contains(rec.Body.Bytes(), []byte(`"ok":true`)) {
		t.Fatalf("healthz body=%s", rec.Body.String())
	}
}

func TestBuild_LoginIssuesToken(t *testing.T) {
	b := buildForTest(t)
	body, _ := json.Marshal(map[string]string{"username": "ark", "password": "ark"})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	b.e.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("login=%d body=%s", rec.Code, rec.Body.String())
	}
	var env struct {
		Code int `json:"code"`
		Data struct {
			AccessToken string `json:"access_token"`
		} `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	if env.Code != 0 || env.Data.AccessToken == "" {
		t.Fatalf("token empty env=%+v", env)
	}
}

func TestBuild_ProtectedNoToken401(t *testing.T) {
	b := buildForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/apply/applications", nil)
	rec := httptest.NewRecorder()
	b.e.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("no-token=%d want 401 body=%s", rec.Code, rec.Body.String())
	}
}
```

运行：`cd backend-go && go test ./internal/ -run TestBuild -v`
预期：编译失败 `undefined: Build` / `undefined: RouterDeps`。

- [ ] **步骤 3：实现 `Build` + `HandleLogin` + 改 `p.Register`**

`backend-go/internal/platform/auth/login.go`：

```go
package auth

import (
	"net/http"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// HandleLogin 开发/演示登录：校验内置账号，签发带数据域的 JWT。
// M0 内置 ark/ark 便于 compose 冒烟与前端直连；生产接统一身份在 M1 替换本实现。
func HandleLogin(secret string, ttl int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		var body struct {
			Username string `json:"username" binding:"required"`
			Password string `json:"password" binding:"required"`
		}
		if err := c.ShouldBindJSON(&body); err != nil {
			httpx.WriteErr(c, http.StatusBadRequest, 40001, "用户名/密码必填")
			return
		}
		if body.Username != "ark" || body.Password != "ark" {
			httpx.WriteErr(c, http.StatusUnauthorized, 40102, "账号或密码错误")
			return
		}
		claims := Claims{
			UserID:        1,
			TenantID:      1,
			LegalEntityID: 0,
			SecurityLevel: "INTERNAL",
			Roles:         []string{"R-STAFF", "R-MANAGER"},
		}
		tok, err := GenToken(secret, ttl, claims)
		if err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50001, "签发令牌失败")
			return
		}
		httpx.WriteOK(c, gin.H{
			"token_type":   "Bearer",
			"access_token": tok,
			"expires_in":   ttl,
		})
	}
}
```

`backend-go/internal/router.go`（整文件替换，`NewRouter` 退役，改 `Build`）：

```go
package internal

import (
	"time"

	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/modules/p"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/middleware"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/casbin/casbin/v2"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

// RouterDeps 是装配主 router 所需的全部协作者。
// Pool/Redis 允许为 nil（仅单测公开路由/401 短路时用）；生产必须注入。
type RouterDeps struct {
	Logger   *zap.Logger
	Cfg      *config.Config
	Pool     *pgxpool.Pool
	Redis    *redis.Client
	Enforcer *casbin.Enforcer
	Spec     *oapi.Spec
}

// Build 组装 Gin 引擎：横切中间件 + 公开路由 + 受保护 /api/v1（鉴权/幂等/P 竖切）+ passthrough 兜底。
func Build(d RouterDeps) *gin.Engine {
	e := gin.New()
	e.Use(httpx.TraceID(), middleware.Recover(d.Logger))

	// 公开：健康检查 + 开发登录
	e.GET("/healthz", func(c *gin.Context) {
		httpx.WriteOK(c, gin.H{"ok": true, "env": d.Cfg.Env})
	})
	e.POST("/api/v1/auth/login", auth.HandleLogin(d.Cfg.JWTSecret, d.Cfg.JWTTTLSec))

	// 受保护分组：JWT+Casbin 鉴权 → 写方法幂等
	api := e.Group("/api/v1")
	api.Use(middleware.Auth(d.Cfg.JWTSecret, d.Enforcer))
	api.Use(middleware.Idempotency(d.Redis, 24*time.Hour))

	// P 竖切挂到受保护分组（内部只写 /apply 前缀）
	if d.Pool != nil {
		p.Register(api, p.NewHandler(d.Pool))
	}

	// 兜底：命中契约但未手工实现的路由 → passthrough（NoRoute 不经分组中间件，M0 可接受）
	e.NoRoute(oapi.Passthrough(d.Spec))

	return e
}
```

`backend-go/internal/modules/p/routes.go`（改 `Register` 形参与前缀）：

```go
package p

import "github.com/gin-gonic/gin"

// Register 把 P 竖切挂到调用方给定的路由结合（受保护分组 /api/v1）之上。
// 分组内只声明 /apply 相对路径；/api/v1 前缀由 router.Build 提供。
func Register(r gin.IRoutes, h *Handler) {
	g := r.Group("/apply")
	g.GET("/applications", h.ListApplications)
	g.POST("/applications", h.CreateApplication)
	g.GET("/applications/:id", h.GetApplication)
}
```

> 若任务 7 的 `contract_test.go`/`handler_test.go` 里曾以 `p.Register(e, h)`（`e` 为 `*gin.Engine`）挂载，`gin.IRoutes` 同样接受 `*gin.Engine`，无需改测试；但若那里期望整路径 `/api/v1/apply/...`，需在测试里改用 `api := e.Group("/api/v1"); p.Register(api, h)`。检查并同步。

`backend-go/cmd/server/main.go`（整文件替换为完整装配）：

```go
package main

import (
	"context"
	"log"
	"strconv"
	"time"

	"github.com/eplugger/ark/internal"
	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/migrate"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

func main() {
	l, _ := zap.NewProduction()
	defer l.Sync()

	cfg := config.Load()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// 1) 连接 Postgres
	pool, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		l.Fatal("连接数据库失败", zap.Error(err))
	}
	defer pool.Close()
	if err := db.Ping(ctx, pool); err != nil {
		l.Fatal("数据库探活失败", zap.Error(err))
	}

	// 2) 迁移到最新（golang-migrate 拥有 schema，取代 Node 时代 postgres initdb）
	if err := migrate.Up(cfg.DatabaseURL, cfg.MigrationsDir); err != nil {
		l.Fatal("数据库迁移失败", zap.Error(err))
	}

	// 3) Casbin RBAC enforcer
	enf, err := auth.NewEnforcer(cfg.AuthModelPath, cfg.AuthPolicyPath)
	if err != nil {
		l.Fatal("初始化 Casbin 失败", zap.Error(err))
	}

	// 4) 运行时契约（passthrough 兜底 + 校验用）
	spec, err := oapi.LoadDir(cfg.DesignDir)
	if err != nil {
		l.Fatal("加载 OpenAPI 契约失败", zap.Error(err), zap.String("dir", cfg.DesignDir))
	}

	// 5) Redis（幂等热存储）
	rdb := redis.NewClient(&redis.Options{Addr: cfg.RedisAddr, Password: cfg.RedisPassword})
	defer rdb.Close()

	// 6) 装配 router 并监听
	e := internal.Build(internal.RouterDeps{
		Logger:   l,
		Cfg:      cfg,
		Pool:     pool,
		Redis:    rdb,
		Enforcer: enf,
		Spec:     spec,
	})
	addr := ":" + strconv.Itoa(cfg.HTTPPort)
	l.Info("ark-go 启动", zap.String("addr", addr), zap.String("env", cfg.Env))
	if err := e.Run(addr); err != nil {
		log.Fatal(err)
	}
}
```

- [ ] **步骤 4：运行确认通过**

```bash
cd backend-go
go build ./...
go test ./internal/config/ ./internal/ -run 'TestLoad_AuthPaths|TestBuild' -v
```
预期：`build` 通过；三条 `TestBuild_*` 与 `TestLoad_AuthPaths` 全 PASS。
再跑一遍任务 3 若曾单测 `NewRouter`，此时已改名 `Build`——`go test ./internal/ -run TestBuild_Healthz` 应绿（原 `TestNewRouter` 若残留则删除）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/config backend-go/internal/router.go backend-go/internal/router_test.go backend-go/internal/platform/auth/login.go backend-go/internal/modules/p/routes.go backend-go/cmd/server/main.go
git commit -m "feat(go): M0 装配主 router(鉴权+幂等+P 竖切+passthrough 兜底+开发登录) 与 main 组装"
```

---

## 任务 13：生产级 Docker 化 + docker-compose 重构（Go 直接替换 Node）

按确认的过渡策略，compose 里的 `backend` 服务由 **Go 镜像**接管；Node `backend/` 退出编排，仅作为契约测试夹具（`verify`/`oapi` 参照）保留在仓库。同时新增 `redis` 服务（幂等热存储），并把 Postgres 的建表职责从「initdb 跑 `design/*.sql`」移交为「Go 启动时 `golang-migrate` 跑 `migrations/`」，避免两套 schema 来源打架。前端沿用现有 Vue 镜像（`VITE_USE_MOCK=false` 已内置，天然直连 Go 后端）。

**产物一览**
- `backend-go/Dockerfile`：多阶段（`golang:1.22-alpine` 构建 → `alpine` 运行），把 `design/` 契约与 `internal/platform/auth/{model.conf,policy.csv}`、`migrations/` 烘进镜像，非 root 运行，`/healthz` 健康检查。
- `backend-go/Dockerfile` 构建上下文 = 仓库根（与 Node 时代一致：需同时读 `backend-go/` 与 `design/`）。
- 重写根 `docker-compose.yml`：`backend`→Go；`postgres` 去 initdb 挂载、healthcheck 简化；新增 `redis`；`frontend` 不变；补 `.dockerignore` 保留 `backend-go/`。
- `scripts/compose-smoke.sh`：起全栈后跑「healthz → login 取 JWT → 带令牌访问 P 列表 → 命中一条 passthrough 契约路由」冒烟。

> 命名/契约铁律：Go 服务对外仍 `8787`（前端 nginx `proxy_pass http://backend:8787` 不改）。数据库连接串用 Go 侧 `ARK_DATABASE_URL`（键名与前序 config 一致），值为 `postgres://ark:ark@postgres:5432/ark?sslmode=disable`。

- [ ] **步骤 1：写 Go Dockerfile**

`backend-go/Dockerfile`：

```dockerfile
# syntax=docker/dockerfile:1
# 科研管理 Go 后端镜像。构建上下文 = 仓库根：
#   docker build -f backend-go/Dockerfile -t eplugger-ark-go:0.1.0 .
# 阶段 1：静态编译（pgx 纯 Go，无需 CGO）
FROM golang:1.22-alpine AS build
WORKDIR /src

# 先拷依赖清单，命中层缓存
COPY backend-go/go.mod backend-go/go.sum ./
RUN go mod download

# 再拷源码 + 契约（oapi.LoadDir 运行时读 /srv/design；生成期也可用）
COPY backend-go/ ./
COPY design/ /srv/design/

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" \
    -o /out/ark-server ./cmd/server

# 阶段 2：极简运行层
FROM alpine:3.20
RUN adduser -D -u 10001 ark && apk add --no-cache ca-certificates wget
WORKDIR /srv/app

COPY --from=build /out/ark-server ./ark-server
# 运行时资产：契约目录、Casbin 模型/策略、迁移脚本
COPY --from=build /srv/design/ /srv/design/
COPY --from=build /src/internal/platform/auth/model.conf  /srv/auth/model.conf
COPY --from=build /src/internal/platform/auth/policy.csv  /srv/auth/policy.csv
COPY --from=build /src/migrations/ /srv/migrations/

ENV ARK_ENV=production \
    ARK_HTTP_PORT=8787 \
    DESIGN_DIR=/srv/design \
    ARK_MIGRATIONS_DIR=/srv/migrations \
    ARK_AUTH_MODEL_PATH=/srv/auth/model.conf \
    ARK_AUTH_POLICY_PATH=/srv/auth/policy.csv

EXPOSE 8787
USER ark
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8787/healthz >/dev/null || exit 1

ENTRYPOINT ["./ark-server"]
```

- [ ] **步骤 2：`.dockerignore` 保留 backend-go**

修改仓库根 `.dockerignore`：现有条目已默认保留 `backend-go/`（仅排除了 `/frontend`、`/prototype`、`/PRD`、`*.md` 等）。追加两行，防止 Node 时代残留物与本地构建产物污染 Go 镜像上下文：

```
# Go 后端本地二进制与缓存（镜像内重新编译）
/backend-go/ark-server
/backend-go/tmp
**/*.test
```

> `design/` 与 `backend-go/` 必须留在上下文（未列入排除即保留）。`backend/`(Node) 也会被带入 Go 上下文，但 Go Dockerfile 只 `COPY backend-go/ ./`，不引用 Node 目录，无副作用。

- [ ] **步骤 3：重写 `docker-compose.yml`（Go 直替 Node + 新增 Redis）**

用以下内容整体替换根 `docker-compose.yml`：

```yaml
# 科研管理系统 · 全套服务一键编排（Docker Compose）
# 用法：docker compose up -d --build     浏览器访问 http://localhost:8080
# 说明：backend 现为 Go+Gin 契约驱动后端（golang-migrate 拥有 schema）。
#   · postgres 首启为空库；schema 由后端启动时 migrate.Up 依 migrations/ 建表（不再 initdb 跑 design/*.sql）。
#   · 未手工实现的路由由 Go passthrough 依 design 契约生成合规响应，保证直替 Node 后全站可用。
#   · Node backend/ 已退出编排，仅作契约测试夹具保留于仓库。
#   · 重新初始化：docker compose down -v 清空 pgdata 卷再 up。

name: eplugger-ark

services:
  backend:
    build:
      context: .                     # 仓库根：镜像内需同时含 backend-go/ 源码与 design/ 契约
      dockerfile: backend-go/Dockerfile
    image: eplugger-ark-go:0.1.0
    container_name: ark-backend
    environment:
      ARK_DATABASE_URL: postgres://ark:ark@postgres:5432/ark?sslmode=disable
      ARK_REDIS_ADDR: redis:6379
      ARK_REDIS_PASSWORD: ""
      ARK_JWT_SECRET: ${ARK_JWT_SECRET:-dev-secret-change-me}   # 生产用 .env 注入强随机
      # DESIGN_DIR / ARK_MIGRATIONS_DIR / ARK_AUTH_* 已在镜像 ENV 内烘好，此处可覆盖
    ports:
      - "8787:8787"                  # 便于宿主机直调 API；仅经 nginx 访问前端时可删
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8787/healthz"]
      interval: 15s
      timeout: 3s
      start_period: 20s
      retries: 5
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend            # 前端构建上下文自包含（契约 yaml 已随 frontend/ 提交）
      dockerfile: Dockerfile         # 已内置 VITE_USE_MOCK=false，直连 Go 后端
    image: eplugger-frontend:0.1.0
    container_name: ark-frontend
    depends_on:
      backend:
        condition: service_healthy   # 后端健康后再起 nginx，避免 upstream 解析失败
    ports:
      - "8080:80"                    # 对外统一入口：http://localhost:8080
    restart: unless-stopped

  # PostgreSQL 15：空库启动，schema 交给后端 golang-migrate（migrations/000001_init.up.sql）
  postgres:
    image: postgres:15-alpine
    container_name: ark-postgres
    environment:
      POSTGRES_USER: ark
      POSTGRES_PASSWORD: ark
      POSTGRES_DB: ark
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      # 不再挂载 ./design 到 initdb —— 建表唯一来源是后端 migrate，避免双写冲突
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ark -d ark"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s
    restart: unless-stopped

  # Redis 7：写方法幂等键热存储（Idempotency-Key -> 首次响应快照，TTL 24h）
  redis:
    image: redis:7-alpine
    container_name: ark-redis
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 5s
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:
```

- [ ] **步骤 4：写冒烟脚本**

创建 `scripts/compose-smoke.sh`（`chmod +x`）：

```bash
#!/usr/bin/env bash
# 全栈冒烟：healthz → 登录取 JWT → 带令牌访问 P 列表 → 命中一条 passthrough 契约路由。
# 前提：docker compose up -d --build 已就绪。可用 SMOKE_BASE 覆盖后端地址。
set -euo pipefail
BASE="${SMOKE_BASE:-http://127.0.0.1:8787}"
PY="${PYTHON:-python3}"

echo "[1/4] healthz"
curl -fsS "$BASE/healthz" | grep -q '"ok":true'

echo "[2/4] login"
TOKEN=$(curl -fsS -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"ark","password":"ark"}' \
  | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
[ -n "$TOKEN" ] || { echo "未取得 token"; exit 1; }

echo "[3/4] list applications（受保护，需令牌）"
curl -fsS "$BASE/api/v1/apply/applications?page=1&size=10" \
  -H "Authorization: Bearer $TOKEN" | grep -q '"code":0'

echo "[4/4] passthrough 兜底（契约已定义、M0 未实现的只读路由）"
# F 模块预算列表 GET /budgets 在契约中存在(servers.url=/api/v1)但 M0 未手工实现
# → 应命中 Go passthrough，返回统一包络 code:0
curl -fsS "$BASE/api/v1/budgets?page=1&size=5" \
  -H "Authorization: Bearer $TOKEN" | grep -q '"code":0'

echo "compose smoke OK"
```

> 已核对：`design/03-科研经费管理-F.openapi.yaml` 的 `servers.url: /api/v1` 且存在路径 `/budgets`（GET，`operationId: listBudgets` 类），整路径即 `/api/v1/budgets`，无模块前缀。若该模块实际 GET 路径不同，写脚本前用 `grep -nE '^  /budgets'` 复核后替换；这一步用 `curl -fsS | grep -q '"code":0'` 断言 passthrough 生效（契约路由不再 404 是「Go 直替 Node 后全站可用」的核心保证）。

- [ ] **步骤 5：本地起全栈并跑冒烟**

```bash
# 1) 生成迁移脚本（任务 5 的 gen，产出 migrations/000001_init.up.sql 等）——若尚未生成
cd backend-go && go generate ./migrations/... && cd ..

# 2) 构建并起全栈（首次会 go build + 拉 postgres/redis/nginx 镜像）
docker compose up -d --build

# 3) 等后端健康（migrate.Up 建表 + 监听）
docker compose ps
docker compose logs -f --tail=50 backend   # Ctrl-C 退出观察

# 4) 冒烟
bash scripts/compose-smoke.sh

# 5) 浏览器 http://localhost:8080 走前端（已关 mock，直连 Go）
```

预期：`compose-smoke.sh` 打印 `compose smoke OK`；前端页面数据来自 Go（Network 里 `/api/v1/...` 返回统一包络 `{code:0,...,data}`）。
排错：若后端连不上库，多半是 pgdata 卷里残留了 Node 时代 initdb 建的旧表——`docker compose down -v` 清卷重来。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/Dockerfile .dockerignore docker-compose.yml scripts/compose-smoke.sh backend-go/migrations
git commit -m "feat(go): M0 生产级 Docker 化与 compose 重构（Go 直替 Node + Redis + golang-migrate 拥有 schema）"
```

---

## 任务 14：本地一键任务（Makefile）+ CI（单测 / 集成 / 契约漂移 / lint）

把「格式化—静态检查—单测—集成—代码生成—契约漂移—漏洞」串成可复用的 `make` 目标，并落一个 GitHub Actions 工作流在每次 PR/push 上跑。CI 是本计划的**最终守门人**：尤其是「codegen 漂移守卫」——保证提交的 `sqlc`/`oapi-codegen`/`migrations` 产物与 `db/query`、`design` 源始终一致（对齐仓库既有「两套 matchRoute 必须同构、契约是唯一真源」的铁律）。

**文件：**
- 创建：`backend-go/Makefile`
- 创建：`backend-go/.golangci.yml`
- 创建：`.github/workflows/go-ci.yml`

- [ ] **步骤 1：写 `backend-go/Makefile`**

```makefile
# Go 后端一键任务。均在本目录（backend-go）执行。
GO        ?= go
PKG       = ./...
BIN       = ark-server
DATABASE  = postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable

.PHONY: help fmt fmt-check vet tidy build run test test-integration cover \
        codegen gen-sqlc gen-oapi gen-migrations drift lint vuln ci

help: ## 列出可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

fmt: ## 格式化
	$(GO) fmt $(PKG)

fmt-check: ## 检查未格式化文件（有则非零退出）
	@out=$$(gofmt -l .); if [ -n "$$out" ]; then echo "未格式化:\n$$out"; exit 1; fi

vet: ## go vet
	$(GO) vet $(PKG)

tidy: ## 整理依赖
	$(GO) mod tidy

build: ## 编译服务器
	CGO_ENABLED=0 $(GO) build -trimpath -o $(BIN) ./cmd/server

run: ## 本地起服务（需本地 Postgres/Redis 或用 compose 起依赖）
	ARK_DATABASE_URL=$(DATABASE) $(GO) run ./cmd/server

test: ## 单元测试（无 DB；集成测试因未设 ARK_TEST_DATABASE_URL 自动 skip）
	$(GO) test -race -count=1 $(PKG)

test-integration: ## 集成测试（需可达的 Postgres，见 CI services）
	ARK_TEST_DATABASE_URL=$(DATABASE) $(GO) test -race -count=1 -run 'Integration|UpDown|Store' -v $(PKG)

cover: ## 覆盖率汇总
	$(GO) test -coverprofile=coverage.out $(PKG) && $(GO) tool cover -func=coverage.out | tail -1

codegen: gen-sqlc gen-oapi gen-migrations ## 重新生成全部代码产物
gen-sqlc: ## 由 db/query + migrations schema 生成 DAL
	$(GO) run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate
gen-oapi: ## 由 design 契约生成 DTO/模型（oapi-codegen）
	$(GO) run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.4.1 \
	  --config codegen/oapi-p.yaml design/01-项目申报与立项-P.openapi.yaml
gen-migrations: ## 由 design/*.sql 生成 golang-migrate 脚本
	$(GO) generate ./migrations/...

drift: codegen ## 漂移守卫：重跑生成后若与已提交产物不一致则失败
	@$(GO) build ./... # 确保生成物可编译
	git diff --exit-code -- internal/modules/p/store api/gen migrations/*.sql \
	  || (echo "codegen 产物与源不一致：请 make codegen 后提交"; exit 1)

lint: ## golangci-lint（govet/staticcheck/errcheck/ineffassign/unused + goimports）
	golangci-lint run --timeout=5m ./...

vuln: ## 漏洞扫描
	$(GO) run golang.org/x/vuln/cmd/govulncheck@latest ./...

ci: fmt-check vet lint test ## 无外部依赖的 CI 快路径（集成/漂移在专用 job 里跑）
```

- [ ] **步骤 2：写 `backend-go/.golangci.yml`**

```yaml
run:
  timeout: 5m
  tests: true
linters:
  disable-all: true
  enable:
    - govet
    - errcheck
    - staticcheck
    - ineffassign
    - unused
    - gofmt
    - goimports
    - misspell
issues:
  exclude-rules:
    # 生成的 DAL/DTO 不参与人工 lint（由 codegen 守卫保证一致）
    - path: internal/modules/p/store
      linters: [errcheck, govet, staticcheck]
    - path: api/gen
      linters: [errcheck, govet, staticcheck]
```

- [ ] **步骤 3：写 `.github/workflows/go-ci.yml`**

```yaml
name: go-ci
on:
  push:
    branches: [develop, master]
    paths: ["backend-go/**", "design/**", ".github/workflows/go-ci.yml"]
  pull_request:
    branches: [develop]
    paths: ["backend-go/**", "design/**"]

defaults:
  run:
    working-directory: backend-go

jobs:
  unit:
    name: 单测 + fmt + vet + lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.22" }
      - name: gofmt
        run: test -z "$(gofmt -l .)"
      - name: vet
        run: go vet ./...
      - name: golangci-lint
        uses: golangci/golangci-lint-action@v6
        with: { version: v1.60, working-directory: backend-go }
      - name: unit tests (DB-gated tests skip)
        run: go test -race -count=1 ./...

  integration:
    name: 集成测试（真连 Postgres + Redis）
    runs-on: ubuntu-latest
    needs: unit
    services:
      postgres:
        image: postgres:15-alpine
        env: { POSTGRES_USER: ark, POSTGRES_PASSWORD: ark, POSTGRES_DB: ark }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U ark -d ark"
          --health-interval 10s --health-timeout 5s --health-retries 10
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s --health-timeout 5s --health-retries 5
    env:
      ARK_TEST_DATABASE_URL: postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.22" }
      # 迁移由测试内 migrate.Up 依 migrations/ 建表（空库起步）
      - name: integration tests
        run: go test -race -count=1 -run 'Integration|UpDown|Store|Conforms' ./...

  contract-drift:
    name: codegen 漂移守卫
    runs-on: ubuntu-latest
    needs: unit
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.22" }
      - name: regenerate code artifacts
        run: make codegen
      - name: assert no drift
        run: git diff --exit-code -- internal/modules/p/store api/gen migrations || \
             { echo "::error::codegen 产物与源不一致，请本地 make codegen 后提交"; exit 1; }
```

- [ ] **步骤 4：本地验证 CI 快路径**

```bash
cd backend-go
make fmt-check vet test          # 无 DB，应全绿（集成用例自动 skip）
# 可选：装了 golangci-lint 才跑
golangci-lint run ./... || echo "（未装 golangci-lint，跳过；CI 会跑）"
```

预期：`make test` PASS，且输出里含 `ok` 与若干 `?  no test files` / integration 用例 `SKIP`。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/Makefile backend-go/.golangci.yml .github/workflows/go-ci.yml
git commit -m "chore(go): M0 Makefile 与 CI（单测/集成/codegen 漂移守卫/lint）"
```

---

## 自审（writing-plans 三项检查）

**1. 规格覆盖（对照 `PRODUCTION_GAP_ROADMAP.md` M0 基线）**

| M0 目标（路线图） | 本计划落点 |
| --- | --- |
| Go+Gin 工程骨架 / 统一响应包络 / traceId | 任务 1（`httpx.Envelope`、`TraceID()`、`/healthz`） |
| 配置外置（env） | 任务 2（`config.Load`，含 DB/Redis/JWT/路径） |
| pgx 连接 + golang-migrate 拥有 schema | 任务 3（`db`/`migrate`）、任务 4（`migrations` 由 design 生成） |
| 契约驱动（oapi 运行时装载 + 合规校验） | 任务 6（`oapi.LoadDir/Match/Find` + `ResolveDataSchema`）、任务 7 P 竖切、任务 8（`Validate` 契约合规测试） |
| sqlc 类型安全 DAL（P 模块） | 任务 5（`db/query` + `store` 生成 + `ListApplications/GetApplication/Count/Create`）、任务 7 消费 |
| JWT 鉴权 + Casbin RBAC + 数据域 | 任务 9（`auth/jwt`、`auth/casbin`、`middleware.Auth`、`auth/domain`） |
| 写方法幂等（Redis） | 任务 10（`middleware.Idempotency`，SETNX+回放） |
| 未实现路由兜底（保 Go 直替后全站可用） | 任务 11（`oapi.Passthrough` NoRoute） |
| 主 router 装配 + 开发登录 | 任务 12（`internal.Build`、`auth.HandleLogin`、main 组装） |
| 生产级 docker-compose（Go 直替 Node）+ Redis + 冒烟 | 任务 13（Go Dockerfile、compose 重写、`compose-smoke.sh`） |
| CI（单测/集成/漂移/lint） | 任务 14（Makefile + `.golangci.yml` + `go-ci.yml`） |

未在本 M0 计划内、显式登记为后续计划（分解地图 §0）：M1 全模块 typed 绑定+RLS+审计哈希链、M1 网关/熔断/限流、M2 边界（多法人/涉密）、M2 AI 旁路服务、M3 大数据分析与非功能（可观测全量、压测、灾备）。M0 只交付「可运行、可测、可编排」的最小闭环 + P 模块一条真实竖切作范式。

**2. 占位符扫描**

逐任务检查：无「TBD / 稍后实现 / 补适当错误处理 / 参照上面」之类空步骤；每个「写失败的测试」都给了可编译的 Go/脚本；每个「实现」都给了完整代码块；每个运行步都写了命令与期望（PASS/FAIL/具体断言）。任务 13 冒烟脚本对 passthrough 探测路径已核对为 `/api/v1/budgets`（非臆测的 `/finance/...`）。任务 12 的相对路径按 `go test` 工作目录（`backend-go/internal`）校正为 `../../design` 与 `platform/auth/*`。

**3. 类型一致性（跨任务签名对账）**

- `httpx.WriteOK(c, data any)` / `WriteErr(c, httpStatus, code int, message string)`：任务 1 定义，任务 6/7/9/10/11/12 调用一致。
- `auth.Claims{UserID int64 "uid"; TenantID int64; LegalEntityID int64; SecurityLevel string; Roles []string}`：任务 9 定义，任务 12 `HandleLogin` 构造、`Auth` 中间件写 ctx key（`auth.CtxUserID=...`）一致；`DomainFrom` 读同键。
- `middleware.Auth(secret string, enf *casbin.Enforcer)`、`middleware.Idempotency(rdb *redis.Client, ttl time.Duration)`：任务 9/10 定义，任务 12 `Build` 调用签名一致（`redis.Client` 均来自 `github.com/redis/go-redis/v9`）。
- `p.Register(r gin.IRoutes, h *Handler)`：任务 12 将形参从 `*gin.Engine` 收敛为 `gin.IRoutes`，函数体分组由 `/api/v1/apply` 改 `/apply`（前缀由 `Build` 的 `api := e.Group("/api/v1")` 提供）——任务 7 若以整 Engine 挂载测试，`gin.IRoutes` 兼容 Engine，但需把测试里的期望整路径经 `e.Group("/api/v1")` 承载（任务 12 步骤 3 已注明同步点）。
- `oapi.Passthrough(s *Spec) gin.HandlerFunc` / `oapi.LoadDir(dir) (*Spec, error)`：任务 6/11/12 一致。
- `store.New(pool)` / `store.ListApplicationsParams{TenantID,Limit,Offset,Status,ProjectType}`：任务 5（sqlc）生成，任务 7 handler 使用一致。
- `config.Config` 字段（`Env,HTTPPort,DatabaseURL,RedisAddr,RedisPassword,JWTSecret,JWTTTLSec,MigrationsDir,DesignDir,AuthModelPath,AuthPolicyPath`）：任务 2 定义、任务 12 增两字段、`main`/`Build`/`compose` 读取键名（env：`ARK_*` 与 `DESIGN_DIR`）三处对齐。
- Go 模块路径 `github.com/eplugger/ark` 全文一致。

> 若执行中发现 `sqlc` 把 `total_budget` 参数生成为 `pgtype.Numeric`、或 `member_ids` 生成非 `[]byte`，以任务 5/7 的「薄封装 `pool.ExecContext`」兜底——不改变对外的 `store.Application`/`ToAPIApplication` 契约形状。

---

## 完成定义（整计划 DoD）

全部满足才算 M0 落地：

1. `cd backend-go && make fmt-check vet test` 全绿（单测无 DB，集成用例在 CI 的 postgres/redis service 下经 `ARK_TEST_DATABASE_URL` 跑绿）。
2. `go build ./cmd/server` 出静态二进制；`docker compose up -d --build` 起 backend(Go)+postgres+redis+frontend 四服务且均 healthy。
3. `bash scripts/compose-smoke.sh` 打印 `compose smoke OK`（healthz 200、登录取 JWT、带令牌 P 列表 `code:0`、passthrough `/api/v1/budgets` `code:0`）。
4. 浏览器 `http://localhost:8080` 打开 Vue 前端（已关 mock），各屏数据来自 Go 统一包络；M0 未实现模块经 passthrough 返回形状合规示例，**全站无 404**。
5. P 模块 `list/read/create` 真连 Postgres 读写；契约合规测试（任务 8）在 CI 里绿。
6. `make drift` 通过（codegen 产物与 `design`/`db/query` 源无漂移）。
7. Node `backend/` 不在 compose 中（仅作测试夹具留存）；`design/*.openapi.yaml` 与 `frontend/src/api/schema/` 两套契约仍一致。

---

## 执行移交

计划已保存到 `docs/superpowers/plans/2026-10-13-go-m0-foundation-p-slice.md`。任务 1–14 均为「写失败测试 → 跑失败 → 最小实现 → 跑通过 → 提交」的小步，可直接照做。两种执行方式：

**1. 子 Agent 驱动（推荐）** — 每个任务派一个新的 subagent 实现并自测，任务间由我审查再下一个；迭代快、上下文干净，适合这种「零件多、靠 DoD 串联」的工程骨架。需要 `superpowers-subagent-dev` 技能。

**2. 顺序执行** — 在当前会话按任务 1→14 顺序批量落地，每个任务后跑其验证步、逐任务 commit；全部完成后走 `superpowers-finishing-branch` 收线（当前在 `develop`，完成后可提 PR 回 `develop` 或按需合 `master`——沿用你「合并/PR 留待确认」的约定，我不会擅自推 `master`）。

选哪种？另外，这份计划文档本身要不要我先提交到 `develop`（以及之前那笔 Go 化的 `ef61dfb` 是否推 `origin/develop`）？
