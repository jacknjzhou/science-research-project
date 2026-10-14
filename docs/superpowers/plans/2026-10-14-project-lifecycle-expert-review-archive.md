# 项目全过程(E)+成果(R)真实化 · 专家评审(N)+科研档案(O)新建 实现计划

**目标：** 把 E 项目过程、R 科研成果两个已契约化模块做成真实 Go 垂直切片，并新建 N 专家评审/专家库（含随机/组合抽取引擎、回写 E/R 业务对象）与 O 独立科研档案（跨域案卷 + 四性检测 + 借阅/全文检索），首次引入 MinIO 对象存储。

**架构：** 复刻 P/U/V/M 已验证的垂直切片模式：契约(`design/*.openapi.yaml`) → DDL(`design/*.ddl.sql`) → `migrations/gen.go` 汇总建表 → sqlc 每模块独立引擎块生成 DAL → Go handler+store+mapper → Casbin+ABAC 鉴权 → 前端真实 API 接通(保留 mock curated override) → 契约/处理器/权限测试。E/R 表已存在，本轮是「给已存在的表建 handler」；N/O 需从零写契约+DDL+建表。跨模块写一律经被写模块导出的 store 方法（单一写者），不跨模块直接 UPDATE。

**技术栈：** Go 1.21.6 + Gin v1.10 + oapi-codegen（DTO/模型）+ sqlc v1.27.0（钉 `GOTOOLCHAIN=go1.23.4`、`GOMAXPROCS=1`）+ pgx/v5 + golang-migrate + golang-jwt/v5 + Casbin v2 + go-redis/v9 + zap + **minio-go/v7（新）**；前端 Vite4.5 + Vue3.4 + TS5.3 + Node16。

> 规格真源：`docs/superpowers/specs/2026-10-14-project-lifecycle-expert-review-archive-design.md`。本计划严格按其 §10 分相顺序（Phase 0→1→2→3→4→5）展开。

---

## 全局执行约定（每个任务都适用）

- **分支**：全程 `develop`。每完成一个任务 commit 一次；**禁止** `git add -A`/`git add .`（`docs/` 下有未跟踪竞品截图须保持未跟踪），逐文件 `git add <path>`。**禁止**推送/PR/合并，除非主人明确确认。
- **sqlc 生成命令**（任何 gen-sqlc 步骤统一用）：
  ```bash
  cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate
  ```
  **禁止** `go mod tidy`（会强拉需 go1.25 的 rogpeppe 依赖）；加依赖用定向 `go get <mod>@<ver>`。
- **可选过滤铁律**：所有 list 查询的可空过滤条件必须写成 `sqlc.narg('x')::type IS NULL OR col = sqlc.narg('x')::type`（生成 `*string`/`pgtype.*`），**不可**用 `($1::type IS NULL OR ...)`（会生成非空 ColumnN，空过滤退化为 `col=''` 返回 0 行）。
- **时间/金额映射**：TIMESTAMPTZ 列在 sqlc.yaml 用列级 override → `time.Time`/`*time.Time`；NUMERIC **保持** pgtype.Numeric 原生，在 mapper 用 `numDec()`/`numStrOrNil()` 转契约 string（勿在 sqlc 层钉 string，`SELECT *`/`RETURNING *` 回传 numeric OID 扫描 string 不安全）。
- **契约字节同步**：改 `design/*.openapi.yaml` 后必须 `cp` 到 `frontend/src/api/schema/` 同名文件（mock `?raw` 读前端副本），两套逐字节一致。
- **命名三向 1:1**：新屏须保证 `section id="v-<name>"` ↔ 路由 `name:'<name>'` ↔ App.vue 侧栏 `v:'<name>'` 三者一致。
- **无库/无 MinIO 宿主**：DB-gated 测试用 `ARK_TEST_DATABASE_URL` 缺省 SKIP；MinIO-gated 用 `ARK_S3_ENDPOINT` 缺省 SKIP；纯逻辑测（mapper、draw 引擎、四性检测）用假 pool/假 storage 接口，无需外部依赖。
- **测试运行**：单测 `cd backend-go && go test -race -count=1 ./...`；前端 `cd frontend && npx vue-tsc --noEmit && npm run build`。

---

## 文件结构映射（本计划创建/修改的全部文件与职责）

### 后端 · 平台底座（Phase 0）
- 修改 `backend-go/internal/config/config.go` — 加 S3 四字段 + env 读取。
- 创建 `backend-go/internal/platform/storage/storage.go` — `Storage` 接口（Put/Get/Presign/Remove）+ 类型。
- 创建 `backend-go/internal/platform/storage/minio.go` — minio-go 实现。
- 创建 `backend-go/internal/platform/storage/fake.go` — 内存假实现（单测/无 MinIO 兜底）。
- 修改 `backend-go/internal/router.go` — `RouterDeps.Storage` + 注册 E/R/N/O 四模块。
- 修改 `backend-go/cmd/server/main.go` — 初始化 storage（best-effort，失败置 nil）注入 Deps。
- 修改 `docker-compose.yml` — 加 `minio` 服务 + backend env + depends_on。

### 后端 · 域 E 真实化（Phase 1）
- 创建 `backend-go/db/schema/e_schema.sql` — E 表裁剪 schema（供 sqlc 解析）。
- 创建 `backend-go/db/query_e/*.sql`（`e_project.sql`/`e_task.sql`/`e_progress.sql`/`e_midcheck.sql`/`e_change.sql`/`e_final.sql`/`e_health.sql`）— 真实 SQL。
- 生成 `backend-go/internal/modules/project/store/*`（package `estore`）。
- 创建 `backend-go/internal/modules/project/{mapper.go,handler.go,routes.go,writeback.go}` — E 域 handler + 供 N 调用的导出方法。
- 创建 `backend-go/internal/modules/project/{contract_test.go,handler_test.go}` + `store/compile_test.go`。
- 创建 `backend-go/testdata/seed_e.sql`。
- 修改 `backend-go/sqlc.yaml` — 加 E 引擎块。
- 修改 `backend-go/Makefile` — drift 路径加 `internal/modules/project/store`。

### 后端 · 域 R 真实化（Phase 2）
- 创建 `backend-go/db/schema/r_schema.sql`、`backend-go/db/query_r/*.sql`。
- 生成 `backend-go/internal/modules/output/store/*`（package `rstore`）。
- 创建 `backend-go/internal/modules/output/{mapper.go,handler.go,routes.go,writeback.go}`（导出 `ConcludeOutputEval`）。
- 创建 `backend-go/internal/modules/output/{contract_test.go,handler_test.go}` + `store/compile_test.go`；`testdata/seed_r.sql`。
- 修改 `backend-go/sqlc.yaml`（R 块）、`Makefile`（drift 路径）。

### 后端 · 域 N 专家评审（Phase 3，新建）
- 创建 `design/15-专家与评审管理-N.detail.md`、`.ddl.sql`、`.openapi.yaml`。
- 修改 `design/00-common.sql` — `seq_prefix_registry` 追加 `EXR`/`RVW`。
- 创建 `backend-go/db/schema/n_schema.sql`、`backend-go/db/query_n/*.sql`。
- 生成 `backend-go/internal/modules/expertreview/store/*`（package `nstore`）。
- 创建 `backend-go/internal/modules/expertreview/{mapper.go,handler.go,expert.go,review.go,draw.go,writeback.go,routes.go}`。
- 创建 `backend-go/internal/modules/expertreview/{contract_test.go,handler_test.go,draw_test.go}` + `store/compile_test.go`；`testdata/seed_n.sql`。
- 修改 `backend-go/sqlc.yaml`（N 块）、`Makefile`、`internal/platform/auth/policy.csv`、`policy_test.go`、创建 `caps_expertreview_test.go`。
- 修改 `backend-go/internal/router.go`（注册 N）。

### 后端 · 域 O 科研档案（Phase 4，新建）
- 创建 `design/16-科研档案管理-O.detail.md`、`.ddl.sql`、`.openapi.yaml`。
- 修改 `design/00-common.sql` — 追加 `ARC`/`BORROW`。
- 创建 `backend-go/db/schema/o_schema.sql`、`backend-go/db/query_o/*.sql`。
- 生成 `backend-go/internal/modules/archive/store/*`（package `ostore`）。
- 创建 `backend-go/internal/modules/archive/{mapper.go,handler.go,document.go,archive.go,check.go,borrow.go,routes.go}`。
- 创建 `backend-go/internal/modules/archive/{contract_test.go,handler_test.go,check_test.go}` + `store/compile_test.go`；`testdata/seed_o.sql`。
- 修改 `backend-go/sqlc.yaml`（O 块）、`Makefile`、`policy.csv`、`policy_test.go`、创建 `caps_archive_test.go`、`internal/router.go`。

### 前端（Phase 1/2 接通 + Phase 3/4 新屏）
- 创建 `frontend/src/api/schema/15-*.yaml`、`16-*.yaml`（cp 副本）。
- 修改 `frontend/src/api/schema/index.ts` — `MODULE_CODES` 加 `'15':'N','16':'O'`。
- 修改 `frontend/src/views/ProjectsView.vue`、`ProjectView.vue` — E 真实 API 接通 + 甘特视图（Phase 1）。
- 创建 `frontend/src/views/OutputView.vue`、修改 `ClaimView.vue` — R 真实 API 接通（Phase 2）。
- 创建 `frontend/src/views/ExpertReviewView.vue` + `frontend/src/api/mock/overrides/expertreview.ts`（Phase 3）。
- 创建 `frontend/src/views/ArchiveView.vue` + `frontend/src/api/mock/overrides/archive.ts`（Phase 4）。
- 修改 `frontend/src/router/index.ts` — 加 `/expert-review`、`/archive`、`/output` 路由。
- 修改 `frontend/src/App.vue` — 侧栏加「专家与评审」「科研档案」「成果台账」导航项。

---

## Phase 0 · 对象存储基础设施（MinIO）

### 任务 0.1：config 增加 S3 字段

**文件：**
- 修改：`backend-go/internal/config/config.go`

- [ ] **步骤 1：加字段与读取**

在 `Config` struct 末尾（`AuthPolicyPath` 之后）加：

```go
	S3Endpoint   string
	S3AccessKey  string
	S3SecretKey  string
	S3Bucket     string
	S3UseSSL     bool
```

在 `Load()` return 前加读取：

```go
		S3Endpoint:  get("ARK_S3_ENDPOINT", ""),
		S3AccessKey: get("ARK_S3_ACCESS_KEY", "minioadmin"),
		S3SecretKey: get("ARK_S3_SECRET_KEY", "minioadmin"),
		S3Bucket:    get("ARK_S3_BUCKET", "ark-docs"),
		S3UseSSL:    get("ARK_S3_USE_SSL", "false") == "true",
```

- [ ] **步骤 2：编译验证**

运行：`cd backend-go && go build ./internal/config/...`
预期：exit 0

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/config/config.go
git commit -m "feat(config): 增加 MinIO/S3 配置字段"
```

### 任务 0.2：storage 接口 + 假实现

**文件：**
- 创建：`backend-go/internal/platform/storage/storage.go`
- 创建：`backend-go/internal/platform/storage/fake.go`
- 测试：`backend-go/internal/platform/storage/fake_test.go`

- [ ] **步骤 1：写失败的测试**

`fake_test.go`：

```go
package storage

import (
	"bytes"
	"context"
	"testing"
)

func TestFakeStorage_PutGetPresignRemove(t *testing.T) {
	f := NewFake()
	ctx := context.Background()
	if err := f.Put(ctx, "a/b.txt", bytes.NewReader([]byte("hello")), 5, "text/plain"); err != nil {
		t.Fatal(err)
	}
	rc, n, err := f.Get(ctx, "a/b.txt")
	if err != nil || n != 5 {
		t.Fatalf("Get err=%v n=%d", err, n)
	}
	buf := new(bytes.Buffer)
	buf.ReadFrom(rc)
	rc.Close()
	if buf.String() != "hello" {
		t.Fatalf("got %q", buf.String())
	}
	if u, err := f.PresignGet(ctx, "a/b.txt"); err != nil || u == "" {
		t.Fatalf("presign err=%v url=%q", err, u)
	}
	if err := f.Remove(ctx, "a/b.txt"); err != nil {
		t.Fatal(err)
	}
	if _, _, err := f.Get(ctx, "a/b.txt"); err == nil {
		t.Fatal("expected error after remove")
	}
}
```

- [ ] **步骤 2：运行验证失败**

运行：`cd backend-go && go test ./internal/platform/storage/ -run Fake -v`
预期：FAIL（`undefined: Storage` / `NewFake`）

- [ ] **步骤 3：写接口**

`storage.go`：

```go
package storage

import (
	"context"
	"io"
)

// Storage 抽象对象存储（MinIO/S3）。handler 只依赖接口，便于假实现单测与无 MinIO 兜底。
type Storage interface {
	Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error
	Get(ctx context.Context, key string) (io.ReadCloser, int64, error)
	PresignGet(ctx context.Context, key string) (string, error)
	Remove(ctx context.Context, key string) error
}
```

`fake.go`：

```go
package storage

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"sync"
)

// Fake 内存实现，供单测与无 MinIO 环境兜底。
type Fake struct {
	mu   sync.Mutex
	data map[string][]byte
}

func NewFake() *Fake { return &Fake{data: map[string][]byte{}} }

func (f *Fake) Put(_ context.Context, key string, r io.Reader, _ int64, _ string) error {
	b, err := io.ReadAll(r)
	if err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.data[key] = b
	return nil
}

func (f *Fake) Get(_ context.Context, key string) (io.ReadCloser, int64, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	b, ok := f.data[key]
	if !ok {
		return nil, 0, fmt.Errorf("storage: key %q not found", key)
	}
	return io.NopCloser(bytes.NewReader(b)), int64(len(b)), nil
}

func (f *Fake) PresignGet(_ context.Context, key string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if _, ok := f.data[key]; !ok {
		return "", fmt.Errorf("storage: key %q not found", key)
	}
	return "fake://" + key, nil
}

func (f *Fake) Remove(_ context.Context, key string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.data, key)
	return nil
}
```

- [ ] **步骤 4：运行验证通过**

运行：`cd backend-go && go test ./internal/platform/storage/ -run Fake -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/storage/storage.go backend-go/internal/platform/storage/fake.go backend-go/internal/platform/storage/fake_test.go
git commit -m "feat(storage): 对象存储接口与内存假实现"
```

### 任务 0.3：minio 实现 + compose 服务 + Deps 接线

**文件：**
- 创建：`backend-go/internal/platform/storage/minio.go`
- 修改：`backend-go/internal/router.go`
- 修改：`backend-go/cmd/server/main.go`
- 修改：`docker-compose.yml`

- [ ] **步骤 1：加依赖（定向 go get，禁 tidy）**

```bash
cd backend-go && go get github.com/minio/minio-go/v7@latest
```

- [ ] **步骤 2：写 minio 实现**

`minio.go`：

```go
package storage

import (
	"context"
	"io"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type MinIO struct {
	client *minio.Client
	bucket string
}

// NewMinIO 连接 MinIO 并确保 bucket 存在。失败返回 error（调用方决定降级为 nil）。
func NewMinIO(ctx context.Context, endpoint, accessKey, secretKey, bucket string, useSSL bool) (*MinIO, error) {
	c, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, err
	}
	found, err := c.BucketExists(ctx, bucket)
	if err != nil {
		return nil, err
	}
	if !found {
		if err := c.MakeBucket(ctx, bucket, minio.MakeBucketOptions{}); err != nil {
			return nil, err
		}
	}
	return &MinIO{client: c, bucket: bucket}, nil
}

func (m *MinIO) Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error {
	_, err := m.client.PutObject(ctx, m.bucket, key, r, size, minio.PutObjectOptions{ContentType: contentType})
	return err
}

func (m *MinIO) Get(ctx context.Context, key string) (io.ReadCloser, int64, error) {
	o, err := m.client.GetObject(ctx, m.bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, 0, err
	}
	st, err := o.Stat()
	if err != nil {
		o.Close()
		return nil, 0, err
	}
	return o, st.Size, nil
}

func (m *MinIO) PresignGet(ctx context.Context, key string) (string, error) {
	u, err := m.client.PresignedGetObject(ctx, m.bucket, key, time.Hour, nil)
	if err != nil {
		return "", err
	}
	return u.String(), nil
}

func (m *MinIO) Remove(ctx context.Context, key string) error {
	return m.client.RemoveObject(ctx, m.bucket, key, minio.RemoveObjectOptions{})
}
```

- [ ] **步骤 3：RouterDeps 加 Storage 并注册（暂只加字段，模块注册在各自 Phase）**

`router.go` 的 `RouterDeps` struct 加：

```go
	Storage storage.Storage // nil 时依赖对象存储的端点返回 50301
```

import 加 `"github.com/eplugger/ark/internal/platform/storage"`。

- [ ] **步骤 4：main.go best-effort 初始化**

在 `// 7) 装配 router` 之前插入：

```go
	// 6.5) 对象存储（MinIO）：未配置 endpoint 或连接失败 → 置 nil，依赖它的端点返回 50301。
	var store storage.Storage
	if cfg.S3Endpoint != "" {
		sctx, scancel := context.WithTimeout(context.Background(), 5*time.Second)
		mo, err := storage.NewMinIO(sctx, cfg.S3Endpoint, cfg.S3AccessKey, cfg.S3SecretKey, cfg.S3Bucket, cfg.S3UseSSL)
		scancel()
		if err != nil {
			l.Warn("MinIO 初始化失败，文件端点将返回 50301", zap.Error(err))
		} else {
			store = mo
		}
	}
```

并在 `internal.Build(internal.RouterDeps{ ... })` 里加 `Storage: store,`。import 加 `"github.com/eplugger/ark/internal/platform/storage"`。

- [ ] **步骤 5：docker-compose 加 minio 服务**

在 `services:` 下加（与 postgres/redis 同级）：

```yaml
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 5s
      retries: 10
```

backend 服务 `environment:` 加：

```yaml
      ARK_S3_ENDPOINT: minio:9000
      ARK_S3_ACCESS_KEY: minioadmin
      ARK_S3_SECRET_KEY: minioadmin
      ARK_S3_BUCKET: ark-docs
```

backend `depends_on:` 加 `minio: condition: service_healthy`。顶层 `volumes:` 加 `minio-data:`。

- [ ] **步骤 6：编译 + 提交**

运行：`cd backend-go && go build ./...`
预期：exit 0

```bash
git add backend-go/internal/platform/storage/minio.go backend-go/internal/router.go backend-go/cmd/server/main.go docker-compose.yml backend-go/go.mod backend-go/go.sum
git commit -m "feat(storage): MinIO 实现 + compose 服务 + Deps 接线"
```

---

## Phase 1 · 域 E 项目过程管理（真实化）

> E 表已由 `migrations/000001_init.up.sql` 建出（源自 `design/02-项目过程管理-E.ddl.sql`）。本相**不建表**，只建 sqlc 查询 + store + handler + 路由 + 权限 + 前端接通。列名/枚举以 `design/02-项目过程管理-E.ddl.sql` 为准；写 SQL 前先读该文件核对列。契约端点见规格 §0.2（15 个）。

### 任务 1.1：E 裁剪 schema + sqlc 引擎块

**文件：**
- 创建：`backend-go/db/schema/e_schema.sql`
- 修改：`backend-go/sqlc.yaml`

- [ ] **步骤 1：生成裁剪 schema**

`e_schema.sql` 只含 E 模块表（供 sqlc 解析，运行时打真库）。从 `migrations/000001_init.up.sql` 原样摘出以下 `CREATE TABLE`（含其列/CHECK，去掉 COMMENT/索引可选）：`E_PROJECT`、`E_TASK`、`E_MILESTONE`、`E_PROGRESS_REPORT`、`E_MID_CHECK`、`E_CHANGE_REQUEST`、`E_FINAL_ACCEPT`、`E_PROJECT_DOC`、`E_HEALTH_HISTORY`、`E_ARCHIVE_CHECKLIST`。

运行（提取语句，人工核对无遗漏）：

```bash
cd backend-go && awk '/CREATE TABLE E_(PROJECT|TASK|MILESTONE|PROGRESS_REPORT|MID_CHECK|CHANGE_REQUEST|FINAL_ACCEPT|PROJECT_DOC|HEALTH_HISTORY|ARCHIVE_CHECKLIST) /{p=1} p{print} p&&/^\);/{p=0}' migrations/000001_init.up.sql > db/schema/e_schema.sql
grep -c 'CREATE TABLE' db/schema/e_schema.sql   # 预期 10
```

- [ ] **步骤 2：sqlc.yaml 加 E 引擎块**

在 `sql:` 列表末尾追加（package `estore`，out `internal/modules/project/store`）：

```yaml
  - engine: "postgresql"
    schema: "db/schema/e_schema.sql"
    queries: "db/query_e"
    gen:
      go:
        package: "estore"
        out: "internal/modules/project/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          E_PROJECT: Project
          E_TASK: Task
          E_MILESTONE: Milestone
          E_PROGRESS_REPORT: ProgressReport
          E_MID_CHECK: MidCheck
          E_CHANGE_REQUEST: ChangeRequest
          E_FINAL_ACCEPT: FinalAccept
          E_HEALTH_HISTORY: HealthHistory
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          - column: "E_PROJECT.created_at"
            go_type: "time.Time"
          - column: "E_PROJECT.updated_at"
            go_type: "time.Time"
          - column: "E_PROGRESS_REPORT.submitted_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "E_PROGRESS_REPORT.created_at"
            go_type: "time.Time"
          - column: "E_MID_CHECK.created_at"
            go_type: "time.Time"
          - column: "E_CHANGE_REQUEST.created_at"
            go_type: "time.Time"
          - column: "E_FINAL_ACCEPT.created_at"
            go_type: "time.Time"
          - column: "E_MILESTONE.due_date"
            go_type: { type: "pgtype.Date" }
          - column: "E_MILESTONE.actual_date"
            go_type: { type: "pgtype.Date" }
```

> 注意：E 表名大写，sqlc rename 键须与 schema 中字面表名一致（DDL 未加引号→实际入库小写，但 sqlc 解析的是 `e_schema.sql` 文本，用大写 `E_PROJECT` 作键即可，与生成物 model 名 `Project` 对应）。若 sqlc 对大小写敏感报错，改用小写键 `e_project` 并重生成。

### 任务 1.2：E 查询 SQL（含 narg 过滤）

**文件：**
- 创建：`backend-go/db/query_e/e_project.sql`
- 创建：`backend-go/db/query_e/e_task.sql`
- 创建：`backend-go/db/query_e/e_progress.sql`
- 创建：`backend-go/db/query_e/e_midcheck.sql`
- 创建：`backend-go/db/query_e/e_change.sql`
- 创建：`backend-go/db/query_e/e_final.sql`

- [ ] **步骤 1：e_project.sql**

```sql
-- name: ListMyProjects :many
SELECT * FROM E_PROJECT
WHERE deleted = 0 AND pi_user_id = sqlc.arg('pi_user_id')::bigint
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY updated_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountMyProjects :one
SELECT count(*) FROM E_PROJECT
WHERE deleted = 0 AND pi_user_id = sqlc.arg('pi_user_id')::bigint
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: GetProject :one
SELECT * FROM E_PROJECT WHERE id = $1 AND deleted = 0;

-- name: UpdateProjectStatus :exec
UPDATE E_PROJECT SET status = $2, updated_at = now() WHERE id = $1 AND deleted = 0;
```

- [ ] **步骤 2：e_task.sql（任务派工 + 里程碑）**

```sql
-- name: ListTasks :many
SELECT * FROM E_TASK WHERE project_id = sqlc.arg('project_id')::bigint AND deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
ORDER BY id;

-- name: GetTask :one
SELECT * FROM E_TASK WHERE id = $1 AND project_id = $2 AND deleted = 0;

-- name: UpdateTask :execrows
UPDATE E_TASK
SET status = sqlc.arg('status')::text,
    owner_user_id = sqlc.narg('owner_user_id')::bigint,
    progress_percent = sqlc.arg('progress_percent')::int,
    updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND project_id = sqlc.arg('project_id')::bigint AND deleted = 0;

-- name: ListMilestones :many
SELECT * FROM E_MILESTONE WHERE project_id = $1 AND deleted = 0 ORDER BY due_date NULLS LAST, id;
```

> `E_TASK.owner_user_id`/`progress_percent` 列名以 DDL 为准；若 `E_TASK` 无 `progress_percent`，去掉该行并改由里程碑加权算。执行前读 `design/02` 核对。

- [ ] **步骤 3：e_progress.sql**

```sql
-- name: CreateProgressReport :one
INSERT INTO E_PROGRESS_REPORT
  (code, tenant_id, status, creator_id, project_id, period, report_type, content_rich,
   progress_percent, issues_text, next_plan, attachment_ids)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'DRAFT',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint, sqlc.arg('period')::text,
   sqlc.arg('report_type')::text, sqlc.narg('content_rich')::text,
   sqlc.arg('progress_percent')::int, sqlc.narg('issues_text')::text, sqlc.narg('next_plan')::text,
   COALESCE(sqlc.narg('attachment_ids')::jsonb, '[]'::jsonb))
RETURNING *;

-- name: SubmitProgressReport :execrows
UPDATE E_PROGRESS_REPORT SET status='SUBMITTED', submitted_at=now(), updated_at=now()
WHERE id=$1 AND project_id=$2 AND status='DRAFT' AND deleted=0;
```

> `COALESCE(sqlc.narg(...)::jsonb, ...)` 位置参数会生成 `ColumnN`，handler 按生成物签名传参（记忆教训：COALESCE/cast 位置参数命名退化）。

- [ ] **步骤 4：e_midcheck.sql**

```sql
-- name: CreateMidCheck :one
INSERT INTO E_MID_CHECK
  (code, tenant_id, status, creator_id, project_id, check_round, check_date, plan_id, template_id, expert_ids)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'PLANNED',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint, sqlc.arg('check_round')::int,
   sqlc.narg('check_date')::date, sqlc.narg('plan_id')::bigint, sqlc.narg('template_id')::bigint,
   COALESCE(sqlc.narg('expert_ids')::jsonb, '[]'::jsonb))
RETURNING *;

-- name: GetMidCheck :one
SELECT * FROM E_MID_CHECK WHERE id = $1 AND deleted = 0;

-- name: SetMidCheckExperts :execrows
UPDATE E_MID_CHECK SET expert_ids = sqlc.arg('expert_ids')::jsonb,
  status = CASE WHEN status='PLANNED' THEN 'IN_REVIEW' ELSE status END, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: ConcludeMidCheck :execrows
UPDATE E_MID_CHECK SET status='CONCLUDED', conclusion = sqlc.arg('conclusion')::text,
  score_detail = sqlc.arg('score_detail')::jsonb, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;
```

- [ ] **步骤 5：e_change.sql**

```sql
-- name: CreateChangeRequest :one
INSERT INTO E_CHANGE_REQUEST
  (code, tenant_id, status, creator_id, project_id, change_type, old_value, new_value, reason)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'DRAFT',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint, sqlc.arg('change_type')::text,
   sqlc.narg('old_value')::jsonb, sqlc.narg('new_value')::jsonb, sqlc.narg('reason')::text)
RETURNING *;

-- name: ApproveChangeRequest :execrows
UPDATE E_CHANGE_REQUEST SET status='EFFECTIVE', updated_at=now()
WHERE id=$1 AND project_id=$2 AND status IN ('SUBMITTED','APPROVING') AND deleted=0;

-- name: GetChangeRequest :one
SELECT * FROM E_CHANGE_REQUEST WHERE id=$1 AND deleted=0;
```

> `E_CHANGE_REQUEST` 是否有 `new_value`/`reason` 列以 DDL 为准；缺则删对应列。

- [ ] **步骤 6：e_final.sql**

```sql
-- name: CreateFinalAccept :one
INSERT INTO E_FINAL_ACCEPT
  (code, tenant_id, status, creator_id, project_id, report_id, summary)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'APPLIED',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint,
   sqlc.narg('report_id')::bigint, sqlc.narg('summary')::text)
RETURNING *;

-- name: GetFinalAccept :one
SELECT * FROM E_FINAL_ACCEPT WHERE id = $1 AND deleted = 0;

-- name: ConcludeFinalAccept :execrows
UPDATE E_FINAL_ACCEPT SET status = sqlc.arg('status')::text, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;
```

> `E_FINAL_ACCEPT` 列（`report_id`/`summary` 等）以 DDL 为准核对。

### 任务 1.3：生成 DAL + 编译测试

**文件：**
- 生成：`backend-go/internal/modules/project/store/*`
- 测试：`backend-go/internal/modules/project/store/compile_test.go`

- [ ] **步骤 1：写编译测试**

`compile_test.go`：

```go
package estore

import "testing"

func TestModelsCompile(t *testing.T) {
	_ = Project{}
	_ = MidCheck{}
	_ = ProgressReport{}
	_ = FinalAccept{}
}
```

- [ ] **步骤 2：生成**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate
```
预期：`internal/modules/project/store/` 出现 `models.go`、`e_project.sql.go` 等。

- [ ] **步骤 3：编译 + 跑测试**

```bash
cd backend-go && go build ./internal/modules/project/... && go test ./internal/modules/project/store/ -run ModelsCompile -v
```
预期：PASS。若报字段/参数名不符，**以生成物为准**修正后续 mapper/handler 引用（勿改生成物）。

- [ ] **步骤 4：Commit**

```bash
git add backend-go/db/schema/e_schema.sql backend-go/sqlc.yaml backend-go/db/query_e backend-go/internal/modules/project/store
git commit -m "feat(E): sqlc 引擎块 + E 查询 + 生成 DAL"
```

### 任务 1.4：E mapper

**文件：**
- 创建：`backend-go/internal/modules/project/mapper.go`

- [ ] **步骤 1：写 mapper（对齐契约 snake_case）**

```go
package project

import (
	"encoding/json"
	"time"

	estore "github.com/eplugger/ark/internal/modules/project/store"
	"github.com/jackc/pgx/v5/pgtype"
)

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

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

func numDec(n pgtype.Numeric) string {
	if !n.Valid {
		return "0"
	}
	f, _, _ := n.Int64()
	if n.Int128 != nil || f == 0 && n.Exp != 0 {
		return n.Value() // 回落字符串
	}
	return strconv.FormatInt(f, 10)
}
```

> 上面 `numDec` 简化；实际复用 M 域 `performance/mapper.go` 里已验证的 `numDec`/`numStrOrNil` 实现，逐字拷入本文件（两包各自私有，勿跨包引用）。补 `import "strconv"`。

```go
func ToAPIProject(r estore.Project) map[string]any {
	return map[string]any{
		"id": r.ID, "code": ptrStr(r.Code), "tenant_id": r.TenantID, "status": r.Status,
		"title": r.Title, "project_type": ptrStr(r.ProjectType), "pi_user_id": r.PiUserID,
		"security_level": r.SecurityLevel, "deleted": r.Deleted,
		"created_at": fmtTime(r.CreatedAt), "updated_at": fmtTime(r.UpdatedAt),
	}
}

func ToAPITask(r estore.Task) map[string]any {
	return map[string]any{
		"id": r.ID, "project_id": r.ProjectID, "status": r.Status,
		"name": r.Name, "owner_user_id": r.OwnerUserID, "code": ptrStr(r.Code),
	}
}

func ToAPIMilestone(r estore.Milestone) map[string]any {
	return map[string]any{
		"id": r.ID, "project_id": r.ProjectID, "name": r.Name, "status": r.Status,
		"due_date": dateStr(r.DueDate), "actual_date": dateStr(r.ActualDate),
		"weight": numDec(r.Weight),
	}
}

func ToAPIMidCheck(r estore.MidCheck) map[string]any {
	return map[string]any{
		"id": r.ID, "code": ptrStr(r.Code), "project_id": r.ProjectID, "status": r.Status,
		"check_round": r.CheckRound, "check_date": dateStr(r.CheckDate),
		"expert_ids": jsonToAny(r.ExpertIds, []any{}), "conclusion": ptrStr(r.Conclusion),
		"score_detail": jsonToAny(r.ScoreDetail, nil),
	}
}

func ToAPIFinalAccept(r estore.FinalAccept) map[string]any {
	return map[string]any{
		"id": r.ID, "code": ptrStr(r.Code), "project_id": r.ProjectID, "status": r.Status,
	}
}

func ptrStr(s *string) any { if s == nil { return nil }; return *s }
func dateStr(d pgtype.Date) any { if !d.Valid { return nil }; return d.Time.Format("2006-01-02") }
```

> 字段名（`r.PiUserID`/`r.ProjectType`/`r.CheckRound`/`r.ExpertIds` 等）以 `store/models.go` 生成物为准，编译期校正。

### 任务 1.5：E handler（读 + 动作）

**文件：**
- 创建：`backend-go/internal/modules/project/handler.go`

- [ ] **步骤 1：Handler 结构 + 分页/可选参 helper**

复用 V 域 `activity/handler.go` 的 `pageArgs`/`optQuery`/`optInt64`（逐字拷入本包，改包名 `project`）。结构：

```go
package project

import (
	"net/http"
	"strconv"

	estore "github.com/eplugger/ark/internal/modules/project/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct{ q *estore.Queries }

func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: estore.New(pool)} }
```

- [ ] **步骤 2：ListMyProjects**

```go
func (h *Handler) ListMyProjects(c *gin.Context) {
	d := auth.DomainFrom(c)
	_, _, limit, offset := pageArgs(c)
	rows, err := h.q.ListMyProjects(c, estore.ListMyProjectsParams{
		PiUserID: d.UserID, Limit: limit, Offset: offset,
		Status: optQuery(c, "status"), ProjectType: optQuery(c, "project_type"), Kw: optQuery(c, "kw"),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountMyProjects(c, estore.CountMyProjectsParams{
		PiUserID: d.UserID, Status: optQuery(c, "status"), ProjectType: optQuery(c, "project_type"), Kw: optQuery(c, "kw"),
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIProject(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": dPage(c), "size": dSize(c)})
}
```

> 参数名 `PiUserID/Limit/Offset/Status/ProjectType/Kw` 以生成物 `e_project.sql.go` 的 Params struct 为准。`dPage/dSize` 从 `pageArgs` 返回值取（补两个小 helper 或直接返回 page,size）。

- [ ] **步骤 3：GetProject / ListTasks / ListMilestones**

```go
func (h *Handler) GetProject(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetProject(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "项目不存在")
		return
	}
	httpx.WriteOK(c, ToAPIProject(r))
}

func (h *Handler) ListTasks(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, err := h.q.ListTasks(c, estore.ListTasksParams{ProjectID: id, Status: optQuery(c, "status")})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToAPITask(r))
	}
	httpx.WriteOK(c, gin.H{"list": out})
}
```

- [ ] **步骤 4：动作端点（progress-report / mid-check / change / final）**

各写一个方法，模式：绑定 body → 校验状态机 → 调 store → `WriteOK`。示例 `CreateMidCheck`：

```go
type midCheckBody struct {
	CheckRound int     `json:"check_round" binding:"required"`
	CheckDate  *string `json:"check_date"`
	PlanID     *int64  `json:"plan_id"`
	TemplateID *int64  `json:"template_id"`
}

func (h *Handler) CreateMidCheck(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b midCheckBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "参数错误")
		return
	}
	// 项目须存在
	if _, err := h.q.GetProject(c, id); err != nil {
		httpx.WriteErr(c, 404, 40401, "项目不存在")
		return
	}
	r, err := h.q.CreateMidCheck(c, estore.CreateMidCheckParams{
		Code: nil, TenantID: d.TenantID, CreatorID: d.UserID, ProjectID: id,
		CheckRound: int32(b.CheckRound), CheckDate: parseDatePtr(b.CheckDate),
		PlanID: b.PlanID, TemplateID: b.TemplateID, ExpertIds: nil,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIMidCheck(r))
}
```

> `CreateProgressReport`/`CreateChangeRequest`/`CreateFinalAccept`/`UpdateTask` 同构：绑定 body → 调对应 store → mapper → WriteOK。`UpdateTask` 用 `:execrows`，`n,err :=` 判定 0 行→40401。`SubmitProgressReport`/`ApproveChangeRequest` 校验状态机，非法迁移→`httpx.WriteErr(c,409,40901,"状态不允许")`。补 `parseDatePtr(*string) pgtype.Date` helper（RFC3339 或 `2006-01-02` 解析，失败返回 `pgtype.Date{}`）。

- [ ] **步骤 5：编译**

```bash
cd backend-go && go build ./internal/modules/project/...
```
预期：exit 0（字段/参数名以生成物为准校正）。

### 任务 1.6：E writeback（供 N 调用的导出方法）

**文件：**
- 创建：`backend-go/internal/modules/project/writeback.go`

- [ ] **步骤 1：导出方法**

```go
package project

import (
	"context"
	"encoding/json"

	estore "github.com/eplugger/ark/internal/modules/project/store"
)

// SetMidCheckExperts 供 N 域回填中检专家 user_id 数组（单一写者：E 拥有 E_MID_CHECK）。
func (h *Handler) SetMidCheckExperts(ctx context.Context, midCheckID int64, expertUserIDs []int64) error {
	b, _ := json.Marshal(expertUserIDs)
	_, err := h.q.SetMidCheckExperts(ctx, estore.SetMidCheckExpertsParams{ID: midCheckID, ExpertIds: b})
	return err
}

// ConcludeMidCheck 写中检结论并把项目状态推进（CONTINUE→EXECUTING/CORRECT→CORRECTING/TERMINATE→TERMINATED）。
func (h *Handler) ConcludeMidCheck(ctx context.Context, midCheckID, projectID int64, conclusion string, scoreDetail any) error {
	b, _ := json.Marshal(scoreDetail)
	if _, err := h.q.ConcludeMidCheck(ctx, estore.ConcludeMidCheckParams{ID: midCheckID, Conclusion: conclusion, ScoreDetail: b}); err != nil {
		return err
	}
	projStatus := map[string]string{"CONTINUE": "EXECUTING", "CORRECT": "CORRECTING", "TERMINATE": "TERMINATED"}[conclusion]
	if projStatus == "" {
		return nil
	}
	return h.q.UpdateProjectStatus(ctx, estore.UpdateProjectStatusParams{ID: projectID, Status: projStatus})
}

// ConcludeFinalAccept 写结题技术轨结论（APPROVED/REJECTED/NEED_SUPPLEMENT）。
func (h *Handler) ConcludeFinalAccept(ctx context.Context, finalAcceptID int64, status string) error {
	_, err := h.q.ConcludeFinalAccept(ctx, estore.ConcludeFinalAcceptParams{ID: finalAcceptID, Status: status})
	return err
}
```

> 参数结构体字段名以生成物为准。`ConcludeMidCheck` 的 `ScoreDetail jsonb` 若生成 `[]byte` 直接传 `b`。

- [ ] **步骤 2：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/project/... && git add backend-go/internal/modules/project/handler.go backend-go/internal/modules/project/mapper.go backend-go/internal/modules/project/writeback.go && git commit -m "feat(E): handler + mapper + 供 N 回写的导出方法"
```

### 任务 1.7：E 路由 + 主 router 注册

**文件：**
- 创建：`backend-go/internal/modules/project/routes.go`
- 修改：`backend-go/internal/router.go`

- [ ] **步骤 1：routes.go**

```go
package project

import "github.com/gin-gonic/gin"

// Register 挂 E 竖切到受保护分组（/api/v1 前缀由 router.Build 提供）。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/project/mine", h.ListMyProjects)
	r.GET("/project/:id", h.GetProject)
	r.GET("/project/:id/tasks", h.ListTasks)
	r.PUT("/project/:id/tasks/:taskId", h.UpdateTask)
	r.POST("/project/:id/progress-report", h.CreateProgressReport)
	r.POST("/project/:id/mid-check", h.CreateMidCheck)
	r.POST("/project/:id/change-request", h.CreateChangeRequest)
	r.POST("/project/:id/change-request/:changeId/approve", h.ApproveChangeRequest)
	r.POST("/project/:id/final-accept", h.CreateFinalAccept)
}
```

> 未列端点（`health-score`/`risk-warnings`/`trace`/`archive-checklist`）本轮**保留 passthrough**（NoRoute 兜底），符合规格 §3.2。gin `:changeId` 与契约 `{changeId}` 一致。

- [ ] **步骤 2：router.go 注册**

import 加 `"github.com/eplugger/ark/internal/modules/project"`；在 `if d.Pool != nil {` 块内加：

```go
		project.Register(api, project.NewHandler(d.Pool))
```

- [ ] **步骤 3：编译 + 冒烟**

```bash
cd backend-go && go build ./...
```
预期：exit 0。

### 任务 1.8：E 权限（policy.csv + caps 测试）

**文件：**
- 修改：`backend-go/internal/platform/auth/policy.csv`
- 测试：`backend-go/internal/platform/auth/caps_project_test.go`

- [ ] **步骤 1：policy.csv 追加 p 规则**

```
p, R-STAFF, /api/v1/project/mine, GET
p, R-STAFF, /api/v1/project/*, GET
p, R-STAFF, /api/v1/project/*/tasks/*, PUT
p, R-STAFF, /api/v1/project/*/progress-report, POST
p, R-STAFF, /api/v1/project/*/mid-check, POST
p, R-STAFF, /api/v1/project/*/change-request, POST
p, R-STAFF, /api/v1/project/*/final-accept, POST
p, R-MANAGER, /api/v1/project/*, GET
p, R-MANAGER, /api/v1/project/*/change-request/*/approve, POST
p, R-MANAGER, /api/v1/project/*/mid-check, POST
p, R-LEADER, /api/v1/project/*, GET
p, R-LEADER, /api/v1/project/*/change-request/*/approve, POST
p, R-FINANCE, /api/v1/project/*, GET
p, R-AUDITOR, /api/v1/project/*, GET
```

> R-ADMIN 已由 `/api/v1/*` 通配覆盖（沿用既有）。keyMatch2 `*`→`.*` 跨段，`/api/v1/project/*` 命中所有子路径。

- [ ] **步骤 2：caps_project_test.go**

```go
package auth

import "testing"

func TestCapsProject(t *testing.T) {
	enf := mustEnforcer(t)
	staff := BuildCaps(enf, []string{"R-STAFF"})
	if !hasCap(staff, "/api/v1/project/mine GET") {
		t.Fatalf("R-STAFF 缺 project/mine GET，caps=%v", staff)
	}
	mgr := BuildCaps(enf, []string{"R-MANAGER"})
	if !hasCap(mgr, "/api/v1/project/*/change-request/*/approve POST") {
		t.Fatalf("R-MANAGER 缺变更审批")
	}
}
```

> `mustEnforcer`/`hasCap` 若既有 policy_test 已定义则复用；否则在本文件内定义局部 helper（加载 model.conf + policy.csv），勿与既有测试重名冲突（记忆教训：caps_v_test 未定义 hasCapSuffix）。

- [ ] **步骤 3：跑测试 + Commit**

```bash
cd backend-go && go test ./internal/platform/auth/ -run CapsProject -v && git add backend-go/internal/platform/auth/policy.csv backend-go/internal/platform/auth/caps_project_test.go && git commit -m "feat(E): Casbin 权限规则 + caps 派生测试"
```

### 任务 1.9：E 契约 + 处理器测试

**文件：**
- 测试：`backend-go/internal/modules/project/contract_test.go`
- 测试：`backend-go/internal/modules/project/handler_test.go`

- [ ] **步骤 1：contract_test（无库，结构对齐）**

沿用 V 域 `activity/contract_test.go` 的「构造 store 模型 → mapper → 断言 key 集/类型」模式，对 `ToAPIProject`/`ToAPIMidCheck` 断言含契约要求字段（`id/code/status/title/pi_user_id/expert_ids` 等）。

- [ ] **步骤 2：handler_test（DB-gated）**

```go
func TestListMyProjects_DB(t *testing.T) {
	pool := testPool(t) // 读 ARK_TEST_DATABASE_URL，缺省 t.Skip
	// 用 seed_e.sql 建 1 项目（pi_user_id=100），以该用户 Domain 调 ListMyProjects，断言 total>=1
}
```

> `testPool` helper 复用既有 DB-gated 测试约定（缺 env 即 SKIP）。

- [ ] **步骤 3：跑无库测 + Commit**

```bash
cd backend-go && go test ./internal/modules/project/ -run Contract -v && git add backend-go/internal/modules/project/contract_test.go backend-go/internal/modules/project/handler_test.go backend-go/testdata/seed_e.sql && git commit -m "test(E): 契约结构 + DB-gated 处理器测试 + seed"
```

（`seed_e.sql` 见任务 1.10。）

### 任务 1.10：E 种子数据

**文件：**
- 创建：`backend-go/testdata/seed_e.sql`

- [ ] **步骤 1：写 seed（tenant=1, pi=100）**

```sql
INSERT INTO E_PROJECT (code, tenant_id, status, creator_id, title, project_type, pi_user_id, security_level)
VALUES ('PRJ-2026-0001', 1, 'EXECUTING', 100, '量子调控基础研究', '青年基金项目', 100, 'INTERNAL');
-- 取回 id 用于子表：
-- INSERT INTO E_MILESTONE (tenant_id, status, creator_id, project_id, name, due_date, weight) VALUES ...
-- INSERT INTO E_TASK (tenant_id, status, creator_id, project_id, name, owner_user_id) VALUES ...
```

> 因 `id GENERATED ALWAYS`，子表用 `(SELECT id FROM E_PROJECT WHERE code='PRJ-2026-0001')` 作 project_id。补 2 里程碑 + 2 任务 + 1 中检（PLANNED）供前端/集成演示。列名以 DDL 为准。

### 任务 1.11：前端 E 接通 + 甘特视图

**文件：**
- 修改：`frontend/src/views/ProjectsView.vue`
- 修改：`frontend/src/views/ProjectView.vue`

- [ ] **步骤 1：ProjectsView 真实 API**

把列表数据源从 mock 常量改为 `const { rows, total } = await list<Project>('/project/mine', { page, size, status, kw })`（`import { list } from '@/api/client'`）。`Project` interface 字段对齐契约（snake_case）。保留 curated override 供无后端演示（override key `"GET /project/mine"`）。

- [ ] **步骤 2：ProjectView 详情 + 甘特**

`api.get<ProjectDetail>('/project/' + id)` + `list<Task>('/project/'+id+'/tasks')` + 里程碑 `api.get('/project/'+id+'/tasks')`（若里程碑并入详情返回则免单独调）。甘特：用 `E_MILESTONE.due_date/actual_date/status` 在 `<template>` 内联渲染 CSS 条（`position:relative` 容器 + 每里程碑一条 `left/width` 按日期区间百分比），不引第三方库。

- [ ] **步骤 3：typecheck + build**

```bash
cd frontend && npx vue-tsc --noEmit && VITE_USE_MOCK=true npm run build
```
预期：双 exit 0。

- [ ] **步骤 4：Commit**

```bash
git add frontend/src/views/ProjectsView.vue frontend/src/views/ProjectView.vue
git commit -m "feat(E-frontend): 项目列表/详情接通真实 API + 里程碑甘特视图"
```

### 任务 1.12：drift 路径扩展（E）

**文件：**
- 修改：`backend-go/Makefile:63`

- [ ] **步骤 1：drift 目标加 E store 路径**

把 `git diff --exit-code --` 后的路径列表加 `internal/modules/project/store`（TAB 缩进保持）。

- [ ] **步骤 2：验证零漂移**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate && git diff --exit-code -- internal/modules/project/store
```
预期：exit 0（无 diff）。若宿主 sqlc OOM，据已提交生成物 + 编译通过判定无漂移（记忆教训），记录并继续。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/Makefile && git commit -m "chore(E): drift 守卫纳入 project/store"
```

---

## Phase 2 · 域 R 科研成果管理（真实化）

> R 表已建出（源自 `design/04-科研成果管理-R.ddl.sql`）。列/枚举以该文件为准。契约 15 端点（规格 §0.2）：真实化 list/read/create/action；`aiFill`/`aiDedup`/`refreshCited`/`exportOutputs` 保留 passthrough（登记后续）。

### 任务 2.1：R 裁剪 schema + sqlc 引擎块

**文件：**
- 创建：`backend-go/db/schema/r_schema.sql`
- 修改：`backend-go/sqlc.yaml`

- [ ] **步骤 1：生成裁剪 schema**

```bash
cd backend-go && awk '/CREATE TABLE R_(OUTPUT|PAPER_EXT|PATENT_EXT|SOFTWARE_EXT|STANDARD_EXT|AWARD_EXT|BOOK_EXT|CLAIM_RECORD|OUTPUT_PROJECT|METRIC_SNAPSHOT|DATASET) /{p=1} p{print} p&&/^\);/{p=0}' migrations/000001_init.up.sql > db/schema/r_schema.sql
grep -c 'CREATE TABLE' db/schema/r_schema.sql   # 预期 11
```

- [ ] **步骤 2：sqlc.yaml 加 R 引擎块**

```yaml
  - engine: "postgresql"
    schema: "db/schema/r_schema.sql"
    queries: "db/query_r"
    gen:
      go:
        package: "rstore"
        out: "internal/modules/output/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          R_OUTPUT: Output
          R_PAPER_EXT: PaperExt
          R_PATENT_EXT: PatentExt
          R_CLAIM_RECORD: ClaimRecord
          R_OUTPUT_PROJECT: OutputProject
          R_METRIC_SNAPSHOT: MetricSnapshot
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          - column: "R_OUTPUT.created_at"
            go_type: "time.Time"
          - column: "R_OUTPUT.updated_at"
            go_type: "time.Time"
          - column: "R_CLAIM_RECORD.created_at"
            go_type: "time.Time"
```

> 其余 `R_*_EXT` 表若本轮 create 只落主表 + 对应扩展表，按需补 rename 键。

### 任务 2.2：R 查询 SQL

**文件：**
- 创建：`backend-go/db/query_r/r_output.sql`
- 创建：`backend-go/db/query_r/r_claim.sql`
- 创建：`backend-go/db/query_r/r_link.sql`

- [ ] **步骤 1：r_output.sql**

```sql
-- name: ListOutputs :many
SELECT * FROM R_OUTPUT
WHERE deleted = 0
  AND (sqlc.narg('output_type')::text IS NULL OR output_type = sqlc.narg('output_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('claim_status')::text IS NULL OR claim_status = sqlc.narg('claim_status')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY updated_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountOutputs :one
SELECT count(*) FROM R_OUTPUT
WHERE deleted = 0
  AND (sqlc.narg('output_type')::text IS NULL OR output_type = sqlc.narg('output_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('claim_status')::text IS NULL OR claim_status = sqlc.narg('claim_status')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: GetOutput :one
SELECT * FROM R_OUTPUT WHERE id = $1 AND deleted = 0;

-- name: CreateOutput :one
INSERT INTO R_OUTPUT
  (code, tenant_id, status, claim_status, creator_id, output_type, title, title_en,
   authors, external_author_names, affiliations, source, title_hash, security_level)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'CLAIMED', 'CLAIMED',
   sqlc.arg('creator_id')::bigint, sqlc.arg('output_type')::text, sqlc.arg('title')::text,
   sqlc.narg('title_en')::text, COALESCE(sqlc.narg('authors')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('external_author_names')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('affiliations')::jsonb,'[]'::jsonb), sqlc.arg('source')::text,
   sqlc.narg('title_hash')::text, sqlc.narg('security_level')::text)
RETURNING *;

-- name: ConcludeOutputEval :execrows
UPDATE R_OUTPUT SET status = sqlc.arg('status')::text, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;
```

> `CreateOutput` 的 status/claim_status 初值以契约/DDL 默认与业务规则为准（手工新建=已认领）。`R_OUTPUT` 实际列以 DDL 核对，缺列删对应 INSERT 项。

- [ ] **步骤 2：r_claim.sql（认领/拒绝/非我 + 待认领）**

```sql
-- name: ListPendingClaim :many
SELECT * FROM R_OUTPUT
WHERE deleted = 0 AND claim_status IN ('UNCLAIMED','PENDING','DOUBTFUL')
  AND authors @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('user_id')::bigint))
ORDER BY created_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: SetClaimStatus :execrows
UPDATE R_OUTPUT SET claim_status = sqlc.arg('claim_status')::text,
  status = sqlc.arg('status')::text, is_claimed = sqlc.arg('is_claimed')::bool, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: InsertClaimRecord :one
INSERT INTO R_CLAIM_RECORD (tenant_id, creator_id, output_id, action, actor_user_id, note)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('creator_id')::bigint, sqlc.arg('output_id')::bigint,
  sqlc.arg('action')::text, sqlc.arg('actor_user_id')::bigint, sqlc.narg('note')::text)
RETURNING *;
```

> `authors @> jsonb_build_array(...)` 依赖 `authors` GIN 索引；若 DDL 无该索引，退化为 handler 层过滤或 `EXISTS(SELECT 1 FROM jsonb_array_elements(authors) e WHERE (e->>'user_id')::bigint = @user_id)`。列名以 DDL 为准。

- [ ] **步骤 3：r_link.sql（关联项目）**

```sql
-- name: LinkProject :exec
INSERT INTO R_OUTPUT_PROJECT (tenant_id, creator_id, output_id, project_id)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('creator_id')::bigint,
  sqlc.arg('output_id')::bigint, sqlc.arg('project_id')::bigint)
ON CONFLICT DO NOTHING;

-- name: ListOutputProjects :many
SELECT project_id FROM R_OUTPUT_PROJECT WHERE output_id = $1 AND deleted = 0;
```

> `R_OUTPUT_PROJECT` 是否有唯一约束/`deleted` 列以 DDL 为准；无 `deleted` 去掉该条件。

### 任务 2.3：生成 DAL + 编译测试

**文件：**
- 生成：`backend-go/internal/modules/output/store/*`
- 测试：`backend-go/internal/modules/output/store/compile_test.go`

- [ ] **步骤 1：compile_test.go**

```go
package rstore

import "testing"

func TestModelsCompile(t *testing.T) {
	_ = Output{}
	_ = ClaimRecord{}
}
```

- [ ] **步骤 2：生成 + 编译**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate && go build ./internal/modules/output/... && go test ./internal/modules/output/store/ -run ModelsCompile -v
```
预期：PASS。字段名以生成物为准。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/db/schema/r_schema.sql backend-go/sqlc.yaml backend-go/db/query_r backend-go/internal/modules/output/store
git commit -m "feat(R): sqlc 引擎块 + R 查询 + 生成 DAL"
```

### 任务 2.4：R mapper + handler

**文件：**
- 创建：`backend-go/internal/modules/output/mapper.go`
- 创建：`backend-go/internal/modules/output/handler.go`

- [ ] **步骤 1：mapper**

复用 V/E 同款 `fmtTime/jsonToAny/ptrStr` helper（拷入 `output` 包）。`ToAPIOutput`：

```go
func ToAPIOutput(r rstore.Output) map[string]any {
	return map[string]any{
		"id": r.ID, "code": ptrStr(r.Code), "tenant_id": r.TenantID, "status": r.Status,
		"claim_status": r.ClaimStatus, "output_type": r.OutputType, "title": r.Title,
		"title_en": ptrStr(r.TitleEn), "authors": jsonToAny(r.Authors, []any{}),
		"external_author_names": jsonToAny(r.ExternalAuthorNames, []any{}),
		"affiliations": jsonToAny(r.Affiliations, []any{}), "source": r.Source,
		"is_claimed": r.IsClaimed, "security_level": r.SecurityLevel,
		"created_at": fmtTime(r.CreatedAt), "updated_at": fmtTime(r.UpdatedAt),
	}
}
```

- [ ] **步骤 2：handler（list/read/create/claim/reject/markNotMine/link）**

`Handler{q *rstore.Queries}` + `NewHandler(pool)`。`ListOutputs`/`GetOutput`/`ListMyOutputs`/`ListPendingClaim`/`CreateOutput`/`ClaimOutputs`/`RejectOutputs`/`MarkNotMine`/`LinkProjects`。批量认领入参 `{ids:[...], note}` 循环 `SetClaimStatus`+`InsertClaimRecord`。示例：

```go
func (h *Handler) ClaimOutputs(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		IDs  []int64 `json:"ids" binding:"required"`
		Note *string `json:"note"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "参数错误")
		return
	}
	for _, id := range b.IDs {
		if _, err := h.q.SetClaimStatus(c, rstore.SetClaimStatusParams{ID: id, ClaimStatus: "CLAIMED", Status: "CLAIMED", IsClaimed: true}); err != nil {
			httpx.WriteErr(c, 500, 50001, "认领失败")
			return
		}
		_, _ = h.q.InsertClaimRecord(c, rstore.InsertClaimRecordParams{TenantID: d.TenantID, CreatorID: d.UserID, OutputID: id, Action: "CLAIM", ActorUserID: d.UserID, Note: b.Note})
	}
	httpx.WriteOK(c, gin.H{"claimed": len(b.IDs)})
}
```

> `aiFill`/`aiDedup`/`refreshCited`/`exportOutputs` **不写 handler**，由 NoRoute passthrough 兜底。

- [ ] **步骤 3：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/output/... && git add backend-go/internal/modules/output/mapper.go backend-go/internal/modules/output/handler.go && git commit -m "feat(R): mapper + handler（list/read/create/claim/link）"
```

### 任务 2.5：R writeback（供 N 调用）

**文件：**
- 创建：`backend-go/internal/modules/output/writeback.go`

- [ ] **步骤 1：导出 ConcludeOutputEval**

```go
package output

import (
	"context"

	rstore "github.com/eplugger/ark/internal/modules/output/store"
)

// ConcludeOutputEval 供 N 域回写成果评价结论（pass→ASSIGNED_TO_PROJECT/认定；fail→退回）。
func (h *Handler) ConcludeOutputEval(ctx context.Context, outputID int64, pass bool) error {
	status := "REJECTED"
	if pass {
		status = "CLAIMED"
	}
	_, err := h.q.ConcludeOutputEval(ctx, rstore.ConcludeOutputEvalParams{ID: outputID, Status: status})
	return err
}
```

> 目标 status token 以 `R_OUTPUT.status` CHECK 枚举为准（读 DDL 选合法值）。

- [ ] **步骤 2：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/output/... && git add backend-go/internal/modules/output/writeback.go && git commit -m "feat(R): 供 N 回写的 ConcludeOutputEval"
```

### 任务 2.6：R 路由 + 主 router 注册

**文件：**
- 创建：`backend-go/internal/modules/output/routes.go`
- 修改：`backend-go/internal/router.go`

- [ ] **步骤 1：routes.go**

```go
package output

import "github.com/gin-gonic/gin"

func Register(r gin.IRoutes, h *Handler) {
	r.GET("/output", h.ListOutputs)
	r.POST("/output", h.CreateOutput)
	r.GET("/output/mine", h.ListMyOutputs)
	r.GET("/output/pending-claim", h.ListPendingClaim)
	r.POST("/output/claim", h.ClaimOutputs)
	r.POST("/output/reject", h.RejectOutputs)
	r.POST("/output/mark-not-mine", h.MarkNotMine)
	r.GET("/output/:id", h.GetOutput)
	r.POST("/output/:id/projects", h.LinkProjects)
}
```

> 静态段 `mine`/`pending-claim`/`claim`/`reject`/`mark-not-mine` 先于 `:id` 注册；gin 静态优先于参数段，无冲突。`ai-fill`/`ai-dedup`/`export`/`patents`/`metrics` 留 passthrough。

- [ ] **步骤 2：router.go 注册**

import 加 `"github.com/eplugger/ark/internal/modules/output"`；`if d.Pool != nil {` 内加 `output.Register(api, output.NewHandler(d.Pool))`。

- [ ] **步骤 3：编译**

```bash
cd backend-go && go build ./...
```
预期：exit 0。

### 任务 2.7：R 权限

**文件：**
- 修改：`backend-go/internal/platform/auth/policy.csv`
- 测试：`backend-go/internal/platform/auth/caps_output_test.go`

- [ ] **步骤 1：policy.csv 追加**

```
p, R-STAFF, /api/v1/output, GET
p, R-STAFF, /api/v1/output, POST
p, R-STAFF, /api/v1/output/mine, GET
p, R-STAFF, /api/v1/output/pending-claim, GET
p, R-STAFF, /api/v1/output/claim, POST
p, R-STAFF, /api/v1/output/reject, POST
p, R-STAFF, /api/v1/output/mark-not-mine, POST
p, R-STAFF, /api/v1/output/*, GET
p, R-MANAGER, /api/v1/output/*, GET
p, R-MANAGER, /api/v1/output/*/projects, POST
p, R-LEADER, /api/v1/output/*, GET
p, R-AUDITOR, /api/v1/output/*, GET
```

- [ ] **步骤 2：caps_output_test.go**

```go
package auth

import "testing"

func TestCapsOutput(t *testing.T) {
	enf := mustEnforcer(t)
	staff := BuildCaps(enf, []string{"R-STAFF"})
	if !hasCap(staff, "/api/v1/output/claim POST") {
		t.Fatalf("R-STAFF 缺 output/claim POST")
	}
}
```

- [ ] **步骤 3：跑测试 + Commit**

```bash
cd backend-go && go test ./internal/platform/auth/ -run CapsOutput -v && git add backend-go/internal/platform/auth/policy.csv backend-go/internal/platform/auth/caps_output_test.go && git commit -m "feat(R): Casbin 权限 + caps 测试"
```

### 任务 2.8：R 测试 + seed

**文件：**
- 测试：`backend-go/internal/modules/output/contract_test.go`、`handler_test.go`
- 创建：`backend-go/testdata/seed_r.sql`

- [ ] **步骤 1：contract_test**

构造 `rstore.Output` → `ToAPIOutput` → 断言含 `id/status/claim_status/output_type/title/authors` 且 `authors` 为数组。

- [ ] **步骤 2：handler_test（DB-gated）**

`testPool` → seed 一条 `R_OUTPUT`（authors 含 user 100）→ `ListPendingClaim` 断言命中 → `ClaimOutputs` 后 `claim_status=CLAIMED`。

- [ ] **步骤 3：seed_r.sql**

```sql
INSERT INTO R_OUTPUT (code, tenant_id, status, claim_status, creator_id, output_type, title, authors, source, is_claimed, security_level)
VALUES ('R-2026-0001', 1, 'PENDING_CLAIM', 'PENDING', 100, 'PAPER', '基于拓扑量子态的调控方法',
  '[{"user_id":100,"name":"张三","order":1,"is_corresponding":true}]'::jsonb, 'MANUAL', FALSE, 'INTERNAL');
```

> `output_type`/`source` token 以 DDL CHECK 为准核对。

- [ ] **步骤 4：跑无库测 + Commit**

```bash
cd backend-go && go test ./internal/modules/output/ -run Contract -v && git add backend-go/internal/modules/output/contract_test.go backend-go/internal/modules/output/handler_test.go backend-go/testdata/seed_r.sql && git commit -m "test(R): 契约 + DB-gated 处理器测试 + seed"
```

### 任务 2.9：前端 R 接通（OutputView 新屏 + ClaimView）

**文件：**
- 创建：`frontend/src/views/OutputView.vue`
- 修改：`frontend/src/views/ClaimView.vue`
- 修改：`frontend/src/router/index.ts`
- 修改：`frontend/src/App.vue`

- [ ] **步骤 1：OutputView.vue**

成果台账：`list<Output>('/output', {page,size,output_type,status,kw})` + 新建抽屉（`api.post('/output', body)`）。`section id="v-output"`。字段 snake_case，JSONB 数组直接渲染。

- [ ] **步骤 2：ClaimView 真实 API**

`list<Output>('/output/pending-claim')` + 认领 `api.post('/output/claim',{ids})` / 拒绝 `api.post('/output/reject',{ids})` / 非我 `api.post('/output/mark-not-mine',{ids})`。

- [ ] **步骤 3：路由**

`frontend/src/router/index.ts` 在 `claim` 路由后加：

```ts
  { path: '/output', name: 'output', meta: { zh: '成果台账', en: 'OUTPUTS', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }, component: () => import('@/views/OutputView.vue') },
```

- [ ] **步骤 4：侧栏**

`App.vue` 的 `groups` 中在合适分组加 `{ v: 'output', ic: '◈', label: '成果台账', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }`。

- [ ] **步骤 5：typecheck + build + Commit**

```bash
cd frontend && npx vue-tsc --noEmit && VITE_USE_MOCK=true npm run build
git add frontend/src/views/OutputView.vue frontend/src/views/ClaimView.vue frontend/src/router/index.ts frontend/src/App.vue
git commit -m "feat(R-frontend): 成果台账新屏 + 认领接通真实 API"
```

### 任务 2.10：drift 路径扩展（R）

**文件：**
- 修改：`backend-go/Makefile:63`

- [ ] **步骤 1：drift 加 R store 路径**

`git diff --exit-code --` 列表加 `internal/modules/output/store`。

- [ ] **步骤 2：验证 + Commit**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate && git diff --exit-code -- internal/modules/output/store
git add backend-go/Makefile && git commit -m "chore(R): drift 守卫纳入 output/store"
```

---

## Phase 3 · 域 N 专家与评审管理（新建）

> 新建域。先写契约 + DDL（DDL 经 `migrations/gen.go` 汇总建表），再 sqlc + store + handler + 抽取引擎 + 回写 + 权限 + 前端。表前缀 `n_`，package `nstore`，dir `internal/modules/expertreview/`。

### 任务 3.1：N DDL

**文件：**
- 创建：`design/15-专家与评审管理-N.ddl.sql`

- [ ] **步骤 1：写 DDL（通用列内联，对齐 00-common/01-P 风格）**

```sql
-- ============================================================
-- 15 · 专家与评审管理（模块 N）
-- PG15；达梦差异：IDENTITY/JSONB/TIMESTAMPTZ 需适配（见 00-common 注记）
-- 跨模块仅存 *_id 逻辑外键，不建物理 FK（同模块内可建）
-- ============================================================

CREATE TABLE n_expert (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'CANDIDATE'
                    CHECK (status IN ('CANDIDATE','ACTIVE','SUSPENDED','BLACKLIST')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  name              VARCHAR(64)  NOT NULL,
  gender            VARCHAR(8),
  title             VARCHAR(64),
  education         VARCHAR(32),
  org_name          VARCHAR(128),
  dept              VARCHAR(128),
  phone             VARCHAR(32),
  email             VARCHAR(128),
  user_id           BIGINT,                                   -- 逻辑→sys_user（本院专家），可空=纯外部
  source            VARCHAR(16)  NOT NULL DEFAULT 'EXTERNAL'
                    CHECK (source IN ('INTERNAL','EXTERNAL')),
  field_tags        JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 研究领域标签数组
  expertise_level   VARCHAR(16)  NOT NULL DEFAULT 'EXPERT'
                    CHECK (expertise_level IN ('JUNIOR','SENIOR','EXPERT')),
  avoid_orgs        JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 回避单位名列表
  avoid_person_ids  JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 回避人员 user_id 列表
  bank_account      JSONB,                                     -- 评审费收款信息（走 X 加密治理）
  cv_doc_ids        JSONB        NOT NULL DEFAULT '[]'::jsonb, -- O 域 document id
  last_review_at    TIMESTAMPTZ,
  review_count      INT          NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uk_n_expert_code ON n_expert(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_n_expert_tenant_status ON n_expert(tenant_id, status);
CREATE INDEX idx_n_expert_field ON n_expert USING GIN (field_tags);
CREATE INDEX idx_n_expert_user ON n_expert(user_id);

CREATE TABLE n_expert_group (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  name              VARCHAR(128) NOT NULL,
  criteria          JSONB        NOT NULL DEFAULT '{}'::jsonb,
  expert_ids        JSONB        NOT NULL DEFAULT '[]'::jsonb
);
CREATE UNIQUE INDEX uk_n_group_name ON n_expert_group(tenant_id, name) WHERE deleted = 0;

CREATE TABLE n_review_task (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','DRAWN','INVITING','QUORUM','IN_REVIEW','COLLECTING','CONCLUDED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  biz_type          VARCHAR(24)  NOT NULL
                    CHECK (biz_type IN ('MID_CHECK','FINAL_ACCEPT','OUTPUT_EVAL','PROJECT_APPLY','OTHER')),
  target_type       VARCHAR(32),
  target_id         BIGINT,                                    -- 逻辑→E_MID_CHECK/E_FINAL_ACCEPT/R_OUTPUT id
  project_id        BIGINT,                                    -- 逻辑→E_PROJECT（回避判定用）
  title             VARCHAR(256) NOT NULL,
  review_method     VARCHAR(16)  NOT NULL DEFAULT 'RANDOM'
                    CHECK (review_method IN ('RANDOM','COMBINATION','MANUAL')),
  plan_count        INT          NOT NULL DEFAULT 3,
  draw_rule         JSONB        NOT NULL DEFAULT '{}'::jsonb, -- {field_tags,min_title,org_diversity,exclude_user_ids,exclude_orgs}
  conclusion        VARCHAR(16),
  score_summary     JSONB,
  drawn_at          TIMESTAMPTZ,
  started_at        TIMESTAMPTZ,
  concluded_at      TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_n_task_code ON n_review_task(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_n_task_project ON n_review_task(project_id, biz_type);
CREATE INDEX idx_n_task_target ON n_review_task(target_type, target_id);
CREATE INDEX idx_n_task_tenant_status ON n_review_task(tenant_id, status);

CREATE TABLE n_review_invitation (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  task_id           BIGINT       NOT NULL REFERENCES n_review_task(id),
  expert_id         BIGINT       NOT NULL REFERENCES n_expert(id),
  seat_no           INT          NOT NULL DEFAULT 0,
  avoid_hit         BOOLEAN      NOT NULL DEFAULT FALSE,
  response          VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (response IN ('PENDING','ACCEPT','DECLINE','EXPIRED')),
  invited_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  responded_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_n_invite ON n_review_invitation(task_id, expert_id);
CREATE INDEX idx_n_invite_task ON n_review_invitation(task_id, response);

CREATE TABLE n_review_score (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  task_id           BIGINT       NOT NULL REFERENCES n_review_task(id),
  expert_id         BIGINT       NOT NULL REFERENCES n_expert(id),
  target_type       VARCHAR(32),
  target_id         BIGINT,
  dimension_scores  JSONB        NOT NULL DEFAULT '[]'::jsonb,
  total_score       NUMERIC(10,2) NOT NULL DEFAULT 0,
  comment           TEXT,
  status            VARCHAR(16)  NOT NULL DEFAULT 'SUBMITTED' CHECK (status IN ('SUBMITTED','ABSTAIN')),
  submitted_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_n_score ON n_review_score(task_id, expert_id);

CREATE TABLE n_review_fee (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'UNPAID' CHECK (status IN ('UNPAID','PAID')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  task_id           BIGINT       NOT NULL REFERENCES n_review_task(id),
  expert_id         BIGINT       NOT NULL REFERENCES n_expert(id),
  amount            NUMERIC(18,2) NOT NULL,
  pay_channel       VARCHAR(32),
  paid_at           TIMESTAMPTZ,
  voucher_code      VARCHAR(64)                                  -- 逻辑→F 凭证
);
CREATE UNIQUE INDEX uk_n_fee ON n_review_fee(task_id, expert_id) WHERE deleted = 0;
```

- [ ] **步骤 2：登记前缀**

修改 `design/00-common.sql` 的 `seq_prefix_registry` INSERT，在 `('PAY','绩效发放','M','v1.0',TRUE);` 前把该行结尾分号改逗号，追加：

```sql
  ('EXR','专家','N','v1.0',TRUE),
  ('RVW','评审任务','N','v1.0',TRUE),
```

- [ ] **步骤 3：Commit**

```bash
git add design/15-专家与评审管理-N.ddl.sql design/00-common.sql
git commit -m "feat(N): 专家与评审 DDL + 前缀登记(EXR/RVW)"
```

### 任务 3.2：N 契约 + 前端副本

**文件：**
- 创建：`design/15-专家与评审管理-N.openapi.yaml`
- 创建：`design/15-专家与评审管理-N.detail.md`
- 创建：`frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml`（cp 副本）

- [ ] **步骤 1：openapi.yaml（tag: expertreview）**

servers.url `/api/v1`。`components` 复用 `ApiResponse`/`PageResult`（与既有模块同款 $ref 结构）。路径与 schema 严格对齐 §5.1/§5.2：

```
/experts                GET(listExperts) POST(createExpert)
/experts/{id}           GET(getExpert) PUT(updateExpert) DELETE(deleteExpert)
/experts/{id}/status    POST(setExpertStatus)
/reviews                GET(listReviews) POST(createReview)
/reviews/{id}           GET(getReview) DELETE(cancelReview)
/reviews/{id}/draw      POST(drawExperts)
/reviews/{id}/invite    POST(inviteExperts)
/reviews/{id}/accept    POST(acceptInvitation)
/reviews/{id}/decline   POST(declineInvitation)
/reviews/{id}/start     POST(startReview)
/reviews/{id}/scores    POST(submitScore)
/reviews/{id}/conclude  POST(concludeReview)
/reviews/{id}/fees      POST(generateFees)
/reviews/{id}/detail    GET(getReviewDetail)   # 含 invitations + scores
```

schema `Expert`：`id:int64, code:string|null, tenant_id:int64, status:enum[CANDIDATE,ACTIVE,SUSPENDED,BLACKLIST], name:string, gender:string|null, title:string|null, org_name:string|null, user_id:int64|null, source:enum[INTERNAL,EXTERNAL], field_tags:array, expertise_level:enum[JUNIOR,SENIOR,EXPERT], avoid_orgs:array, avoid_person_ids:array, security_level:enum[PUBLIC,INTERNAL,SECRET,TOP_SECRET], created_at:string, updated_at:string`。
schema `ReviewTask`：`id, code, biz_type:enum[MID_CHECK,FINAL_ACCEPT,OUTPUT_EVAL,PROJECT_APPLY,OTHER], target_type:string|null, target_id:int64|null, project_id:int64|null, title, review_method:enum[RANDOM,COMBINATION,MANUAL], plan_count:int, draw_rule:object, status:enum[DRAFT,DRAWN,INVITING,QUORUM,IN_REVIEW,COLLECTING,CONCLUDED,CANCELLED], conclusion:string|null, score_summary:object|null, security_level`。
schema `Invitation`：`id, task_id, expert_id, expert_name:string|null, seat_no, response:enum[PENDING,ACCEPT,DECLINE,EXPIRED]`。
schema `Score`：`id, task_id, expert_id, dimension_scores:array, total_score:string(NUMERIC), status`。
列表端点 `data` 用 `allOf:[ApiResponse, {data:PageResult<Expert>}]`（typed list，参照 M 的 PageResult 写法；注意 R/S 模块 pinned PageResult 的坑——N 用通用 items，勿钉死）。

- [ ] **步骤 2：detail.md**

写 §5 的表/端点/状态机/权限说明（供 PRD 交叉引用），格式对齐 `design/*.detail.md` 既有风格。

- [ ] **步骤 3：cp 前端副本 + 字节校验**

```bash
cp design/15-专家与评审管理-N.openapi.yaml frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml
diff -q design/15-专家与评审管理-N.openapi.yaml frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml && echo SYNC_OK
```
预期：`SYNC_OK`。

- [ ] **步骤 4：Commit**

```bash
git add design/15-专家与评审管理-N.openapi.yaml design/15-专家与评审管理-N.detail.md frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml
git commit -m "feat(N): OpenAPI 契约 + detail + 前端副本同步"
```

### 任务 3.3：N sqlc 引擎块 + 查询

**文件：**
- 创建：`backend-go/db/schema/n_schema.sql`
- 创建：`backend-go/db/query_n/n_expert.sql`、`n_review.sql`、`n_score.sql`
- 修改：`backend-go/sqlc.yaml`

- [ ] **步骤 1：n_schema.sql**

```bash
cd backend-go && awk '/CREATE TABLE n_(expert|expert_group|review_task|review_invitation|review_score|review_fee) /{p=1} p{print} p&&/^\);/{p=0}' migrations/000001_init.up.sql > db/schema/n_schema.sql
```

> 前提：任务 3.3 前须先 `cd backend-go && go generate ./migrations/...` 让新 DDL 进 `000001_init.up.sql`（见任务 3.3 步骤 4）。若尚未生成，直接从 `design/15-…-N.ddl.sql` 拷表定义到 `n_schema.sql`。

- [ ] **步骤 2：sqlc.yaml 加 N 块**

```yaml
  - engine: "postgresql"
    schema: "db/schema/n_schema.sql"
    queries: "db/query_n"
    gen:
      go:
        package: "nstore"
        out: "internal/modules/expertreview/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          n_expert: Expert
          n_expert_group: ExpertGroup
          n_review_task: ReviewTask
          n_review_invitation: Invitation
          n_review_score: Score
          n_review_fee: ReviewFee
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          - column: "n_expert.created_at"
            go_type: "time.Time"
          - column: "n_expert.updated_at"
            go_type: "time.Time"
          - column: "n_expert.last_review_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "n_review_task.created_at"
            go_type: "time.Time"
          - column: "n_review_task.updated_at"
            go_type: "time.Time"
          - column: "n_review_task.drawn_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "n_review_task.started_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "n_review_task.concluded_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "n_review_score.total_score"
            go_type: "pgtype.Numeric"
          - column: "n_review_fee.amount"
            go_type: "pgtype.Numeric"
```

- [ ] **步骤 3：查询 SQL**

`n_expert.sql`：

```sql
-- name: ListExperts :many
SELECT * FROM n_expert WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source')::text IS NULL OR source = sqlc.narg('source')::text)
  AND (sqlc.narg('kw')::text IS NULL OR name ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountExperts :one
SELECT count(*) FROM n_expert WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source')::text IS NULL OR source = sqlc.narg('source')::text)
  AND (sqlc.narg('kw')::text IS NULL OR name ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: GetExpert :one
SELECT * FROM n_expert WHERE id = $1 AND deleted = 0;

-- name: ActiveExpertsForDraw :many
SELECT * FROM n_expert WHERE deleted = 0 AND status = 'ACTIVE';

-- name: CreateExpert :one
INSERT INTO n_expert
  (code, tenant_id, status, creator_id, security_level, name, gender, title, education,
   org_name, dept, phone, email, user_id, source, field_tags, expertise_level, avoid_orgs, avoid_person_ids)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, sqlc.arg('status')::text, sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('name')::text, sqlc.narg('gender')::text,
   sqlc.narg('title')::text, sqlc.narg('education')::text, sqlc.narg('org_name')::text, sqlc.narg('dept')::text,
   sqlc.narg('phone')::text, sqlc.narg('email')::text, sqlc.narg('user_id')::bigint,
   COALESCE(sqlc.narg('source')::text,'EXTERNAL'), COALESCE(sqlc.narg('field_tags')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('expertise_level')::text,'EXPERT'), COALESCE(sqlc.narg('avoid_orgs')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('avoid_person_ids')::jsonb,'[]'::jsonb))
RETURNING *;

-- name: UpdateExpert :execrows
UPDATE n_expert SET name=sqlc.arg('name')::text, title=sqlc.narg('title')::text,
  org_name=sqlc.narg('org_name')::text, field_tags=sqlc.arg('field_tags')::jsonb,
  avoid_orgs=sqlc.arg('avoid_orgs')::jsonb, avoid_person_ids=sqlc.arg('avoid_person_ids')::jsonb,
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: SetExpertStatus :execrows
UPDATE n_expert SET status=sqlc.arg('status')::text, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: SoftDeleteExpert :execrows
UPDATE n_expert SET deleted=1, updated_at=now() WHERE id=$1 AND deleted=0;
```

`n_review.sql`：

```sql
-- name: ListReviews :many
SELECT * FROM n_review_task WHERE deleted = 0
  AND (sqlc.narg('biz_type')::text IS NULL OR biz_type = sqlc.narg('biz_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountReviews :one
SELECT count(*) FROM n_review_task WHERE deleted = 0
  AND (sqlc.narg('biz_type')::text IS NULL OR biz_type = sqlc.narg('biz_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text);

-- name: GetReviewTask :one
SELECT * FROM n_review_task WHERE id = $1 AND deleted = 0;

-- name: CreateReviewTask :one
INSERT INTO n_review_task
  (code, tenant_id, status, creator_id, security_level, biz_type, target_type, target_id, project_id,
   title, review_method, plan_count, draw_rule)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'DRAFT', sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('biz_type')::text, sqlc.narg('target_type')::text,
   sqlc.narg('target_id')::bigint, sqlc.narg('project_id')::bigint, sqlc.arg('title')::text,
   COALESCE(sqlc.narg('review_method')::text,'RANDOM'), sqlc.arg('plan_count')::int,
   COALESCE(sqlc.narg('draw_rule')::jsonb,'{}'::jsonb))
RETURNING *;

-- name: UpdateReviewStatus :execrows
UPDATE n_review_task SET status=sqlc.arg('status')::text, updated_at=now()
  WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: ConcludeReviewTask :execrows
UPDATE n_review_task SET status='CONCLUDED', conclusion=sqlc.arg('conclusion')::text,
  score_summary=sqlc.arg('score_summary')::jsonb, concluded_at=now(), updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: InsertInvitation :one
INSERT INTO n_review_invitation (tenant_id, task_id, expert_id, seat_no, avoid_hit, response)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('task_id')::bigint, sqlc.arg('expert_id')::bigint,
  sqlc.arg('seat_no')::int, sqlc.arg('avoid_hit')::bool, sqlc.arg('response')::text) RETURNING *;

-- name: ListInvitations :many
SELECT i.*, e.name AS expert_name FROM n_review_invitation i
JOIN n_expert e ON e.id = i.expert_id
WHERE i.task_id = $1 ORDER BY i.seat_no;

-- name: RespondInvitation :execrows
UPDATE n_review_invitation SET response=sqlc.arg('response')::text, responded_at=now()
WHERE task_id=sqlc.arg('task_id')::bigint AND expert_id=sqlc.arg('expert_id')::bigint;

-- name: CountAccepted :one
SELECT count(*) FROM n_review_invitation WHERE task_id=$1 AND response='ACCEPT';
```

`n_score.sql`：

```sql
-- name: UpsertScore :one
INSERT INTO n_review_score (tenant_id, task_id, expert_id, target_type, target_id, dimension_scores, total_score, comment, status)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('task_id')::bigint, sqlc.arg('expert_id')::bigint,
  sqlc.narg('target_type')::text, sqlc.narg('target_id')::bigint, sqlc.arg('dimension_scores')::jsonb,
  sqlc.arg('total_score')::numeric, sqlc.narg('comment')::text, 'SUBMITTED')
ON CONFLICT (task_id, expert_id) DO UPDATE
SET dimension_scores=EXCLUDED.dimension_scores, total_score=EXCLUDED.total_score,
    comment=EXCLUDED.comment, status='SUBMITTED', submitted_at=now()
RETURNING *;

-- name: ListScores :many
SELECT * FROM n_review_score WHERE task_id=$1 ORDER BY expert_id;

-- name: CountScores :one
SELECT count(*) FROM n_review_score WHERE task_id=$1 AND status='SUBMITTED';
```

- [ ] **步骤 4：生成迁移 + schema + DAL**

```bash
cd backend-go && go generate ./migrations/... && awk '/CREATE TABLE n_(expert|expert_group|review_task|review_invitation|review_score|review_fee) /{p=1} p{print} p&&/^\);/{p=0}' migrations/000001_init.up.sql > db/schema/n_schema.sql && grep -c 'CREATE TABLE' db/schema/n_schema.sql
GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate
```
预期：schema 6 表；`internal/modules/expertreview/store/` 生成。

- [ ] **步骤 5：compile_test + 编译 + Commit**

`store/compile_test.go`：`_ = Expert{}; _ = ReviewTask{}; _ = Invitation{}; _ = Score{}`。

```bash
cd backend-go && go build ./internal/modules/expertreview/... && go test ./internal/modules/expertreview/store/ -run ModelsCompile -v
git add backend-go/db/schema/n_schema.sql backend-go/sqlc.yaml backend-go/db/query_n backend-go/internal/modules/expertreview/store migrations/000001_init.up.sql migrations/000001_init.down.sql
git commit -m "feat(N): sqlc 引擎块 + 查询 + 生成 DAL + 迁移重建"
```

### 任务 3.4：N mapper + expert handler

**文件：**
- 创建：`backend-go/internal/modules/expertreview/mapper.go`
- 创建：`backend-go/internal/modules/expertreview/expert.go`

- [ ] **步骤 1：mapper**

复用 `fmtTime/jsonToAny/ptrStr/numDec` helper（拷入 `expertreview` 包）。`ToAPIExpert`/`ToAPIReviewTask`/`ToAPIInvitation`/`ToAPIScore`，字段对齐 §3.2 契约 schema。`ToAPIExpert` 含 `field_tags/avoid_orgs/avoid_person_ids/cv_doc_ids`（数组）。

- [ ] **步骤 2：expert.go（CRUD handler）**

`Handler{q *nstore.Queries, e *project.Handler, r *output.Handler}` + `NewHandler(pool, e, r)`（e/r 供回写；见任务 3.6）。`ListExperts`/`GetExpert`/`CreateExpert`（分配 code `EXR-年-序`）/`UpdateExpert`/`DeleteExpert`（软删）/`SetExpertStatus`（校验目标 status ∈ 枚举）。

### 任务 3.5：N 抽取引擎（核心）

**文件：**
- 创建：`backend-go/internal/modules/expertreview/draw.go`
- 测试：`backend-go/internal/modules/expertreview/draw_test.go`

- [ ] **步骤 1：写失败的纯逻辑测试（不依赖 DB）**

`draw_test.go`：

```go
package expertreview

import "testing"

type cand struct {
	ExpertID int64
	UserID   int64
	OrgName  string
	Fields   []string
	AvoidOrg []string
	AvoidUsr []int64
}

func TestDrawExcludesAvoidAndDeterministic(t *testing.T) {
	pool := []cand{
		{1, 201, "A大学", []string{"物理"}, nil, nil},
		{2, 202, "B所", []string{"物理"}, nil, nil},
		{3, 100, "C公司", []string{"物理"}, nil, nil}, // 与项目 PI 同 user_id → 回避
		{4, 204, "承担单位", []string{"物理"}, nil, nil},
	}
	rule := drawRule{FieldTags: []string{"物理"}, ExcludeUserIDs: []int64{100}, ExcludeOrgs: []string{"承担单位"}}
	got := drawExperts(pool, rule, 2, 42) // seed=42
	if len(got) != 2 {
		t.Fatalf("want 2 got %d (%v)", len(got), got)
	}
	for _, id := range got {
		if id == 3 || id == 4 {
			t.Fatalf("回避对象漏入: %d", id)
		}
	}
	// 确定性：同 seed 两次一致
	if a, b := drawExperts(pool, rule, 2, 42), drawExperts(pool, rule, 2, 42); fmt.Sprint(a) != fmt.Sprint(b) {
		t.Fatalf("非确定性: %v vs %v", a, b)
	}
}
```

（补 `import "fmt"`）

- [ ] **步骤 2：运行验证失败**

运行：`cd backend-go && go test ./internal/modules/expertreview/ -run DrawExcludes -v`
预期：FAIL（`undefined: drawRule/drawExperts`）

- [ ] **步骤 3：写 draw.go**

```go
package expertreview

import "math/rand"

type drawRule struct {
	FieldTags      []string `json:"field_tags"`
	MinTitle       string   `json:"min_title"`
	OrgDiversity   bool     `json:"org_diversity"`
	ExcludeUserIDs []int64  `json:"exclude_user_ids"`
	ExcludeOrgs    []string `json:"exclude_orgs"`
}

type candidate struct {
	ExpertID int64
	UserID   int64
	OrgName  string
	Fields   []string
}

func contains(ss []string, s string) bool {
	for _, x := range ss {
		if x == s {
			return true
		}
	}
	return false
}
func containsI64(is []int64, v int64) bool {
	for _, x := range is {
		if x == v {
			return true
		}
	}
	return false
}

// eligible 判定候选是否通过领域匹配 + 回避（单位/人员/本人 user_id）。
func eligible(c candidate, rule drawRule, avoidOrgs []string, avoidUserIDs []int64) bool {
	if len(rule.FieldTags) > 0 {
		hit := false
		for _, f := range rule.FieldTags {
			if contains(c.Fields, f) {
				hit = true
				break
			}
		}
		if !hit {
			return false
		}
	}
	if contains(rule.ExcludeOrgs, c.OrgName) || contains(avoidOrgs, c.OrgName) {
		return false
	}
	if c.UserID != 0 && (containsI64(rule.ExcludeUserIDs, c.UserID) || containsI64(avoidUserIDs, c.UserID)) {
		return false
	}
	return true
}

// drawExperts 过滤回避 → 洗牌（seed 确定性）→ 取 n；OrgDiversity 时按单位去重优先。
func drawExperts(pool []candidate, rule drawRule, n int, seed int64) []int64 {
	var ok []candidate
	for _, c := range pool {
		if eligible(c, rule, nil, nil) {
			ok = append(ok, c)
		}
	}
	rnd := rand.New(rand.NewSource(seed))
	rnd.Shuffle(len(ok), func(i, j int) { ok[i], ok[j] = ok[j], ok[i] })
	if rule.OrgDiversity {
		seen := map[string]bool{}
		var dedup []candidate
		for _, c := range ok {
			if !seen[c.OrgName] {
				seen[c.OrgName] = true
				dedup = append(dedup, c)
			}
		}
		// 不足则回填其余
		for _, c := range ok {
			if len(dedup) >= n {
				break
			}
			if !containsID(dedup, c.ExpertID) {
				dedup = append(dedup, c)
			}
		}
		ok = dedup
	}
	if n > len(ok) {
		n = len(ok)
	}
	out := make([]int64, 0, n)
	for _, c := range ok[:n] {
		out = append(out, c.ExpertID)
	}
	return out
}

func containsID(cs []candidate, id int64) bool {
	for _, c := range cs {
		if c.ExpertID == id {
			return true
		}
	}
	return false
}
```

- [ ] **步骤 4：运行验证通过**

运行：`cd backend-go && go test ./internal/modules/expertreview/ -run DrawExcludes -v`
预期：PASS

- [ ] **步骤 5：handler 侧 DrawExperts 端点（DB→纯函数→落库）**

`review.go` 里 `DrawExperts(c)`：读 `ActiveExpertsForDraw` → 构造 `[]candidate`（解析 `field_tags`）→ 从 `draw_rule` + 项目成员（`project_id` 的 PI/成员 user_id 经 E 查询或逻辑外键快照）算 `avoidUserIDs/avoidOrgs` → `drawExperts` → 逐个 `InsertInvitation(response=PENDING)`，被回避者 `avoid_hit=true` 落审计 → `UpdateReviewStatus(DRAWN)`。seed 取 `time.Now().UnixNano()`（或 body 传 seed 便于复现测试）。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/modules/expertreview/draw.go backend-go/internal/modules/expertreview/draw_test.go backend-go/internal/modules/expertreview/mapper.go backend-go/internal/modules/expertreview/expert.go
git commit -m "feat(N): 专家 mapper/CRUD + 抽取引擎(回避+确定性)"
```

### 任务 3.6：N 评审流程 handler + 回写集成

**文件：**
- 创建：`backend-go/internal/modules/expertreview/review.go`
- 创建：`backend-go/internal/modules/expertreview/writeback.go`

- [ ] **步骤 1：review.go（create/invite/accept/decline/start/score/conclude/cancel/detail）**

`CreateReview`（分配 `RVW-年-序`）；`InviteExperts`（DRAWN→INVITING，调 `h.e.SetMidCheckExperts` 回填已接受/拟邀专家 user_id，仅 biz_type=MID_CHECK）；`Accept/Decline`（`RespondInvitation`，`CountAccepted` 达 `plan_count` 法定人数→QUORUM）；`StartReview`（QUORUM→IN_REVIEW）；`SubmitScore`（`UpsertScore`，`CountScores`==accepted→COLLECTING）；`ConcludeReview`（汇总→`ConcludeReviewTask`→调回写）；`GetReviewDetail`（task + invitations + scores）。

- [ ] **步骤 2：writeback.go（调 E/R 导出方法）**

```go
package expertreview

import "context"

// concludeWriteback 按 biz_type 回写被评审对象（经被写模块导出的单一写者方法）。
func (h *Handler) concludeWriteback(ctx context.Context, bizType string, targetID, projectID int64, conclusion string, summary any) error {
	switch bizType {
	case "MID_CHECK":
		return h.e.ConcludeMidCheck(ctx, targetID, projectID, conclusion, summary)
	case "FINAL_ACCEPT":
		status := map[string]string{"PASS": "APPROVED", "REJECT": "REJECTED", "SUPPLEMENT": "NEED_SUPPLEMENT"}[conclusion]
		return h.e.ConcludeFinalAccept(ctx, targetID, status)
	case "OUTPUT_EVAL":
		return h.r.ConcludeOutputEval(ctx, targetID, conclusion == "PASS")
	}
	return nil
}
```

- [ ] **步骤 3：Handler 依赖 project/output**

`NewHandler(pool *pgxpool.Pool, e *project.Handler, r *output.Handler) *Handler`；import `project`/`output` 包。方法签名须与任务 1.6/2.5 导出方法**逐字一致**（`SetMidCheckExperts(ctx,int64,[]int64)`、`ConcludeMidCheck(ctx,midCheckID,projectID int64,conclusion string,scoreDetail any)`、`ConcludeFinalAccept(ctx,int64,string)`、`ConcludeOutputEval(ctx,int64,bool)`）。

- [ ] **步骤 4：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/expertreview/... && git add backend-go/internal/modules/expertreview/review.go backend-go/internal/modules/expertreview/writeback.go && git commit -m "feat(N): 评审流程 handler + E/R 回写集成"
```

### 任务 3.7：N 路由 + 主 router 注册

**文件：**
- 创建：`backend-go/internal/modules/expertreview/routes.go`
- 修改：`backend-go/internal/router.go`

- [ ] **步骤 1：routes.go**

```go
package expertreview

import "github.com/gin-gonic/gin"

func Register(r gin.IRoutes, h *Handler) {
	r.GET("/experts", h.ListExperts)
	r.POST("/experts", h.CreateExpert)
	r.GET("/experts/:id", h.GetExpert)
	r.PUT("/experts/:id", h.UpdateExpert)
	r.DELETE("/experts/:id", h.DeleteExpert)
	r.POST("/experts/:id/status", h.SetExpertStatus)
	r.GET("/reviews", h.ListReviews)
	r.POST("/reviews", h.CreateReview)
	r.GET("/reviews/:id", h.GetReview)
	r.DELETE("/reviews/:id", h.CancelReview)
	r.GET("/reviews/:id/detail", h.GetReviewDetail)
	r.POST("/reviews/:id/draw", h.DrawExperts)
	r.POST("/reviews/:id/invite", h.InviteExperts)
	r.POST("/reviews/:id/accept", h.AcceptInvitation)
	r.POST("/reviews/:id/decline", h.DeclineInvitation)
	r.POST("/reviews/:id/start", h.StartReview)
	r.POST("/reviews/:id/scores", h.SubmitScore)
	r.POST("/reviews/:id/conclude", h.ConcludeReview)
	r.POST("/reviews/:id/fees", h.GenerateFees)
}
```

- [ ] **步骤 2：router.go 注册（传 project/output handler）**

`if d.Pool != nil {` 块内，确保 project/output handler 先构造再传给 N：

```go
		projH := project.NewHandler(d.Pool)
		outH := output.NewHandler(d.Pool)
		project.Register(api, projH)
		output.Register(api, outH)
		expertreview.Register(api, expertreview.NewHandler(d.Pool, projH, outH))
```

> 替换任务 1.7/2.6 里各自单行注册为上述集中构造（避免重复注册）。import 加 `expertreview`。

- [ ] **步骤 3：编译 + Commit**

```bash
cd backend-go && go build ./... && git add backend-go/internal/modules/expertreview/routes.go backend-go/internal/router.go && git commit -m "feat(N): 路由 + 主 router 注册(注入 project/output 依赖)"
```

### 任务 3.8：N 权限

**文件：**
- 修改：`backend-go/internal/platform/auth/policy.csv`
- 测试：`backend-go/internal/platform/auth/caps_expertreview_test.go`

- [ ] **步骤 1：policy.csv 追加**

```
p, R-MANAGER, /api/v1/experts/*, GET
p, R-MANAGER, /api/v1/experts, POST
p, R-MANAGER, /api/v1/experts/*, PUT
p, R-MANAGER, /api/v1/experts/*, DELETE
p, R-MANAGER, /api/v1/experts/*/status, POST
p, R-MANAGER, /api/v1/reviews/*, GET
p, R-MANAGER, /api/v1/reviews, POST
p, R-MANAGER, /api/v1/reviews/*/draw, POST
p, R-MANAGER, /api/v1/reviews/*/invite, POST
p, R-MANAGER, /api/v1/reviews/*/start, POST
p, R-MANAGER, /api/v1/reviews/*/conclude, POST
p, R-MANAGER, /api/v1/reviews/*/fees, POST
p, R-LEADER, /api/v1/reviews/*, GET
p, R-LEADER, /api/v1/reviews/*/conclude, POST
p, R-EXPERT, /api/v1/reviews/*/accept, POST
p, R-EXPERT, /api/v1/reviews/*/decline, POST
p, R-EXPERT, /api/v1/reviews/*/scores, POST
p, R-AUDITOR, /api/v1/experts/*, GET
p, R-AUDITOR, /api/v1/reviews/*, GET
```

- [ ] **步骤 2：caps_expertreview_test.go**

```go
package auth

import "testing"

func TestCapsExpertReview(t *testing.T) {
	enf := mustEnforcer(t)
	exp := BuildCaps(enf, []string{"R-EXPERT"})
	if !hasCap(exp, "/api/v1/reviews/*/scores POST") {
		t.Fatalf("R-EXPERT 缺打分权限")
	}
	mgr := BuildCaps(enf, []string{"R-MANAGER"})
	if !hasCap(mgr, "/api/v1/reviews/*/draw POST") {
		t.Fatalf("R-MANAGER 缺抽取权限")
	}
}
```

- [ ] **步骤 3：跑测试 + Commit**

```bash
cd backend-go && go test ./internal/platform/auth/ -run CapsExpertReview -v && git add backend-go/internal/platform/auth/policy.csv backend-go/internal/platform/auth/caps_expertreview_test.go && git commit -m "feat(N): Casbin 权限 + caps 测试"
```

### 任务 3.9：N 测试 + seed

**文件：**
- 测试：`backend-go/internal/modules/expertreview/contract_test.go`、`handler_test.go`
- 创建：`backend-go/testdata/seed_n.sql`

- [ ] **步骤 1：contract_test**：构造 `nstore.Expert`→`ToAPIExpert`→断言含 `id/name/status/field_tags(数组)/avoid_orgs(数组)`。

- [ ] **步骤 2：handler_test（DB-gated）**：seed 4 专家（1 与项目 PI 同 user_id）→ 建 MID_CHECK 评审任务 → `DrawExperts` 断言回避者不入名单、名单数=plan_count → `AcceptInvitation` 全接受→QUORUM → `SubmitScore`→`ConcludeReview`→断言 `E_MID_CHECK.expert_ids`/`status=CONCLUDED`/`E_PROJECT.status` 被回写（依赖 Phase1 方法）。

- [ ] **步骤 3：seed_n.sql**：4 条 `n_expert`（ACTIVE，field_tags 含"物理"，其中一条 user_id=100 模拟 PI 回避）。

- [ ] **步骤 4：跑无库测 + Commit**

```bash
cd backend-go && go test ./internal/modules/expertreview/ -run 'Contract|Draw' -v && git add backend-go/internal/modules/expertreview/contract_test.go backend-go/internal/modules/expertreview/handler_test.go backend-go/testdata/seed_n.sql && git commit -m "test(N): 契约 + 抽取 + DB-gated 回写集成测试 + seed"
```

### 任务 3.10：N 前端

**文件：**
- 创建：`frontend/src/views/ExpertReviewView.vue`
- 创建：`frontend/src/api/mock/overrides/expertreview.ts`
- 修改：`frontend/src/router/index.ts`
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/api/schema/index.ts`

- [ ] **步骤 1：MODULE_CODES**

`frontend/src/api/schema/index.ts` 的 `MODULE_CODES` 加 `'15':'N'`。

- [ ] **步骤 2：ExpertReviewView.vue**

Tab 式（专家库 / 评审任务 / 打分与结论 / 评审费），`section id="v-expert-review"`。抽取面板：选方法/拟抽数/规则→`api.post('/reviews/'+id+'/draw')`→预览 `api.get('/reviews/'+id+'/detail')`。字段 snake_case；`total_score/amount` 走 `toNum`。按钮 `v-perm`/角色门控（打分仅 R-EXPERT，抽取/结论 R-MANAGER）。

- [ ] **步骤 3：路由**

`frontend/src/router/index.ts` 在 `performance` 路由后加：

```ts
  { path: '/expert-review', name: 'expert-review', meta: { zh: '专家与评审', en: 'EXPERT REVIEW', roles: ['R-EXPERT', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }, component: () => import('@/views/ExpertReviewView.vue') },
```

> 注意与既有 `/review`（P 申报评审工作台）区分，勿复用名 `review`。

- [ ] **步骤 4：侧栏**

`App.vue` `groups` 加 `{ v: 'expert-review', ic: '✦', label: '专家与评审', roles: ['R-EXPERT', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }`。

- [ ] **步骤 5：override**

`overrides/expertreview.ts` 导出 `overrides` 映射（`"GET /experts"`、`"GET /reviews"`、`"GET /reviews/{id}/detail"` 演示数据），经 `import.meta.glob` 自动合并（无需改 index.ts）。

- [ ] **步骤 6：typecheck + build + Commit**

```bash
cd frontend && npx vue-tsc --noEmit && VITE_USE_MOCK=true npm run build
git add frontend/src/views/ExpertReviewView.vue frontend/src/api/mock/overrides/expertreview.ts frontend/src/router/index.ts frontend/src/App.vue frontend/src/api/schema/index.ts
git commit -m "feat(N-frontend): 专家与评审屏 + 路由 + 侧栏 + override"
```

### 任务 3.11：drift 路径扩展（N）

**文件：**
- 修改：`backend-go/Makefile:63`

- [ ] **步骤 1-2：drift 加 `internal/modules/expertreview/store` + 验证 + Commit**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate && git diff --exit-code -- internal/modules/expertreview/store
git add backend-go/Makefile && git commit -m "chore(N): drift 守卫纳入 expertreview/store"
```

## Phase 4 · 域 O 科研档案管理（新建）

> 新建域，且**首次真正接线对象存储**（Phase 0 的 `storage.Storage`）。先写契约 + DDL（DDL 经 `migrations/gen.go` 汇总建表），再 sqlc + ostore + storage 上传/下载 + 四性检测 + handler + routes + policy + 前端。表前缀 `o_`，package `ostore`，dir `internal/modules/archive/`。O 是**跨域独立档案库**：以「案卷」为单位，`source_module + source_id` 指回任意来源对象；与 E 域内 `E_PROJECT_DOC`/`E_ARCHIVE_CHECKLIST`（项目过程内文档）边界清晰、不重叠（规格 §6.0）。

### 任务 4.1：O DDL

**文件：**
- 创建：`design/16-科研档案管理-O.ddl.sql`
- 修改：`design/00-common.sql`

- [ ] **步骤 1：写 DDL（通用列内联，对齐 00-common/01-P 风格；索引一律 `idx_o_`/`uk_o_` 前缀避免跨模块同名冲突；子表建在同模块父表之后避免前向引用）**

```sql
-- ============================================================
-- 16 · 科研档案管理（模块 O）
-- PG15；达梦差异：IDENTITY/JSONB/TIMESTAMPTZ/GIN/to_tsvector 需适配（见 00-common 注记）
-- 跨模块仅存 source_module + source_id 逻辑外键，不建物理 FK（同模块内 o_* 可建）
-- 全文检索依赖 00-common §0 已前置 CREATE EXTENSION pg_trgm
-- ============================================================

CREATE TABLE o_document (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'UPLOADING'
                    CHECK (status IN ('UPLOADING','STORED','MISSING')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  name              VARCHAR(256) NOT NULL,
  doc_type          VARCHAR(64),                               -- mime / 扩展名
  size_bytes        BIGINT,
  bucket            VARCHAR(64),                               -- MinIO bucket
  object_key        VARCHAR(512),                              -- MinIO object key
  checksum_sha256   VARCHAR(64),                               -- 真实性校验源
  uploader_id       BIGINT,
  uploaded_at       TIMESTAMPTZ,
  source_module     VARCHAR(8),                                -- E/R/F/P/G/V/N/O…（可空=独立上传）
  source_id         BIGINT,                                    -- 逻辑→来源对象 id
  text_content      TEXT                                       -- 抽取正文，供全文检索
);
CREATE UNIQUE INDEX uk_o_doc_key ON o_document(tenant_id, bucket, object_key) WHERE deleted = 0 AND object_key IS NOT NULL;
CREATE UNIQUE INDEX uk_o_doc_code ON o_document(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_o_doc_source ON o_document(source_module, source_id);
CREATE INDEX idx_o_doc_tenant_status ON o_document(tenant_id, status);
CREATE INDEX idx_o_doc_fts ON o_document USING GIN (to_tsvector('simple', coalesce(text_content,'')));
CREATE INDEX idx_o_doc_trgm ON o_document USING GIN (text_content gin_trgm_ops);

CREATE TABLE o_archive (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                               -- ARC-年-序
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'PENDING_SUBMIT'
                    CHECK (status IN ('PENDING_SUBMIT','SUBMITTED','CHECKING','PASSED','ARCHIVED','REJECTED','DESTROYED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  title             VARCHAR(256) NOT NULL,
  archive_type      VARCHAR(24)  NOT NULL DEFAULT 'OTHER'
                    CHECK (archive_type IN ('PROJECT','OUTPUT','EXPENSE','CONTRACT','ACTIVITY','OTHER')),
  source_module     VARCHAR(8),
  source_id         BIGINT,
  source_code       VARCHAR(64),
  owner_dept_id     BIGINT,                                    -- 逻辑→sys_org
  retention_years   INT          NOT NULL DEFAULT 10,
  submitter_id      BIGINT,
  submit_at         TIMESTAMPTZ,
  archivist_id      BIGINT,
  filed_at          TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_o_arc_code ON o_archive(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_o_arc_tenant_status ON o_archive(tenant_id, status);
CREATE INDEX idx_o_arc_source ON o_archive(source_module, source_id);
CREATE INDEX idx_o_arc_type ON o_archive(tenant_id, archive_type);

CREATE TABLE o_archive_item (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  archive_id        BIGINT       NOT NULL REFERENCES o_archive(id),
  doc_id            BIGINT       REFERENCES o_document(id),   -- 可空 = 缺
  status            VARCHAR(16)  NOT NULL DEFAULT 'MISSING'
                    CHECK (status IN ('MISSING','FILLED','CHECKED')),
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  category_code     VARCHAR(64)  NOT NULL,                      -- 门类，sys_dict
  category_name     VARCHAR(128),
  required          BOOLEAN      NOT NULL DEFAULT TRUE,
  sort_no           INT          NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uk_o_item ON o_archive_item(archive_id, category_code);
CREATE INDEX idx_o_item_archive ON o_archive_item(archive_id, status);

CREATE TABLE o_archive_check (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  archive_id        BIGINT       NOT NULL REFERENCES o_archive(id),
  result            VARCHAR(8)   NOT NULL DEFAULT 'WARN'
                    CHECK (result IN ('PASS','FAIL','WARN')),
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  check_type        VARCHAR(16)  NOT NULL
                    CHECK (check_type IN ('AUTHENTICITY','INTEGRITY','USABILITY','SECURITY')),
  detail            JSONB        NOT NULL DEFAULT '{}'::jsonb,
  checked_at        TIMESTAMPTZ,
  checker_id        BIGINT
);
CREATE UNIQUE INDEX uk_o_check ON o_archive_check(archive_id, check_type);
CREATE INDEX idx_o_check_archive ON o_archive_check(archive_id);

CREATE TABLE o_borrow (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                               -- BORROW-年-序
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'SUBMITTED'
                    CHECK (status IN ('SUBMITTED','APPROVED','REJECTED','RETURNED','EXPIRED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  archive_id        BIGINT       NOT NULL REFERENCES o_archive(id),
  borrower_user_id  BIGINT       NOT NULL,
  purpose           VARCHAR(512),
  borrow_type       VARCHAR(16)  NOT NULL DEFAULT 'READ'
                    CHECK (borrow_type IN ('READ','COPY')),
  approved_by       BIGINT,
  approved_at       TIMESTAMPTZ,
  due_at            TIMESTAMPTZ,
  returned_at       TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_o_borrow_code ON o_borrow(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_o_borrow_archive ON o_borrow(archive_id, status);
CREATE INDEX idx_o_borrow_user ON o_borrow(borrower_user_id, status);
```

- [ ] **步骤 2：登记前缀**

修改 `design/00-common.sql` 的 `seq_prefix_registry` INSERT，在 `('RVW','评审任务','N','v1.0',TRUE),` 之后追加（沿用任务 3.1 的追加位置，保持列表尾项以分号结束）：

```sql
  ('ARC','科研档案','O','v1.0',TRUE),
  ('BORROW','借阅申请','O','v1.0',TRUE),
```

- [ ] **步骤 3：Commit**

```bash
git add design/16-科研档案管理-O.ddl.sql design/00-common.sql
git commit -m "feat(O): 科研档案 DDL(五表+全文索引) + 前缀登记(ARC/BORROW)"
```

### 任务 4.2：O 契约 + 前端副本

**文件：**
- 创建：`design/16-科研档案管理-O.openapi.yaml`
- 创建：`design/16-科研档案管理-O.detail.md`
- 创建：`frontend/src/api/schema/16-科研档案管理-O.openapi.yaml`（cp 副本）

- [ ] **步骤 1：openapi.yaml（tag: archive）**

`servers.url` = `/api/v1`。`components` 复用 `ApiResponse`/`PageResult`。路径（与 §6.2 逐字对齐）：

```
/documents              POST(uploadDocument)   # multipart/form-data: file + 元数据
/documents/{id}         GET(getDocument) DELETE(deleteDocument)
/documents/{id}/download GET(downloadDocument)  # 返回 presigned URL（data:{url}）
/documents/search       GET(searchDocuments)    # 全文检索，q/limit/offset
/archives               GET(listArchives) POST(createArchive)
/archives/{id}          GET(getArchive) PUT(updateArchive) DELETE(deleteArchive)
/archives/{id}/items    GET(listItems) POST(addItem)           # add body{category_code,category_name,required,sort_no}
/archives/{id}/items/{itemId}            PUT(fillItem) DELETE(deleteItem)   # fill body{doc_id}
/archives/{id}/ingest   POST(ingestSource)                     # 从来源模块抓取文档建 item（body{category_code,doc_id}）
/archives/{id}/submit   POST(submitArchive)                    # PENDING_SUBMIT/REJECTED → SUBMITTED
/archives/{id}/check    POST(checkArchive)                     # SUBMITTED → CHECKING → 写四性 → PASSED/REJECTED
/archives/{id}/file     POST(fileArchive)                      # PASSED → ARCHIVED
/archives/{id}/destroy  POST(destroyArchive)                   # ARCHIVED → DESTROYED，body{reason}
/borrows                GET(listBorrows) POST(createBorrow)    # create body{archive_id,purpose,borrow_type,due_at}
/borrows/{id}/approve   POST(approveBorrow)
/borrows/{id}/reject    POST(rejectBorrow)
/borrows/{id}/return    POST(returnBorrow)
```

schema `Document`：`id:int64, code:string|null, tenant_id:int64, status:enum[UPLOADING,STORED,MISSING], name:string, doc_type:string|null, size_bytes:int64|null, bucket:string|null, object_key:string|null, checksum_sha256:string|null, source_module:string|null, source_id:int64|null, security_level:enum[PUBLIC,INTERNAL,SECRET,TOP_SECRET], uploaded_at:string|null, created_at:string`（`text_content` 不外泄，仅检索用；检索命中的片段走 `searchDocuments` 的 `snippet` 字段）。
schema `Archive`：`id, code, title, archive_type:enum[PROJECT,OUTPUT,EXPENSE,CONTRACT,ACTIVITY,OTHER], source_module:string|null, source_id:int64|null, source_code:string|null, owner_dept_id:int64|null, retention_years:int, status:enum[PENDING_SUBMIT,SUBMITTED,CHECKING,PASSED,ARCHIVED,REJECTED,DESTROYED], security_level, submitter_id:int64|null, submit_at:string|null, archivist_id:int64|null, filed_at:string|null, created_at, updated_at`。
schema `ArchiveItem`：`id, archive_id, category_code, category_name:string|null, required:boolean, doc_id:int64|null, status:enum[MISSING,FILLED,CHECKED], sort_no:int`。
schema `ArchiveCheck`：`id, archive_id, check_type:enum[AUTHENTICITY,INTEGRITY,USABILITY,SECURITY], result:enum[PASS,FAIL,WARN], detail:object, checked_at:string|null, checker_id:int64|null`。
schema `Borrow`：`id, code, archive_id, archive_title:string|null, borrower_user_id:int64, purpose:string|null, borrow_type:enum[READ,COPY], status:enum[SUBMITTED,APPROVED,REJECTED,RETURNED,EXPIRED], approved_by:int64|null, approved_at:string|null, due_at:string|null, returned_at:string|null, created_at`。

列表端点 `data` 用 `allOf:[ApiResponse, {data:PageResult<Document|Archive|Borrow>}]`（typed list，参照 M；**勿钉死 `PageResult.items`**，O 内多实体列表，保持通用 items）。`check` 端点返回 `data:{list:[ArchiveCheck], passed:boolean}`。`download` 返回 `data:{url:string, expires_at:string}`。上传/删除/动作端点返回 `ApiResponse`（`data` 为对应实体或 `{ok:true}`）。

- [ ] **步骤 2：detail.md**

写 §6 的表/端点/状态机/四性检测算法/权限/与 E 边界说明，格式对齐 `design/*.detail.md` 既有风格。

- [ ] **步骤 3：cp 前端副本 + 字节校验**

```bash
cp design/16-科研档案管理-O.openapi.yaml frontend/src/api/schema/16-科研档案管理-O.openapi.yaml
diff -q design/16-科研档案管理-O.openapi.yaml frontend/src/api/schema/16-科研档案管理-O.openapi.yaml && echo SYNC_OK
```
预期：`SYNC_OK`。

- [ ] **步骤 4：Commit**

```bash
git add design/16-科研档案管理-O.openapi.yaml design/16-科研档案管理-O.detail.md frontend/src/api/schema/16-科研档案管理-O.openapi.yaml
git commit -m "feat(O): OpenAPI 契约 + detail + 前端副本同步"
```

### 任务 4.3：O sqlc 引擎块 + 查询

**文件：**
- 创建：`backend-go/db/schema/o_schema.sql`
- 创建：`backend-go/db/query_o/o_document.sql`、`o_archive.sql`、`o_borrow.sql`
- 修改：`backend-go/sqlc.yaml`

- [ ] **步骤 1：o_schema.sql**

```bash
cd backend-go && awk '/CREATE TABLE o_(document|archive|archive_item|archive_check|borrow) /{p=1} p{print} p&&/^\);/{p=0}' migrations/000001_init.up.sql > db/schema/o_schema.sql
```

> 前提：先 `cd backend-go && go generate ./migrations/...` 让新 O DDL 进 `000001_init.up.sql`（`migrations/gen.go` 按文件名排序、00-common 最先、剥离 ClickHouse OLAP 段）。若尚未生成，直接从 `design/16-…-O.ddl.sql` 拷五表定义到 `o_schema.sql`。**`to_tsvector`/`gin_trgm_ops` 表达式索引 sqlc 不解析其函数也无妨**——sqlc 只看列，索引行会被忽略；若 sqlc 对表达式索引报错，删除 `o_schema.sql` 中两条 `idx_o_doc_fts`/`idx_o_doc_trgm` 索引行（仅影响 sqlc 解析，不影响迁移真源）。

- [ ] **步骤 2：sqlc.yaml 加 O 块**

```yaml
  - engine: "postgresql"
    schema: "db/schema/o_schema.sql"
    queries: "db/query_o"
    gen:
      go:
        package: "ostore"
        out: "internal/modules/archive/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          o_document: Document
          o_archive: Archive
          o_archive_item: ArchiveItem
          o_archive_check: ArchiveCheck
          o_borrow: Borrow
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          - column: "o_document.created_at"
            go_type: "time.Time"
          - column: "o_document.updated_at"
            go_type: "time.Time"
          - column: "o_document.uploaded_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "o_document.size_bytes"
            go_type: { type: "int64", pointer: true }
          - column: "o_archive.created_at"
            go_type: "time.Time"
          - column: "o_archive.updated_at"
            go_type: "time.Time"
          - column: "o_archive.submit_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "o_archive.filed_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "o_borrow.created_at"
            go_type: "time.Time"
          - column: "o_borrow.updated_at"
            go_type: "time.Time"
          - column: "o_borrow.approved_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "o_borrow.due_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "o_borrow.returned_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "o_archive_check.checked_at"
            go_type: { type: "time.Time", pointer: true }
          - column: "o_archive_check.detail"
            go_type: "[]byte"
```

- [ ] **步骤 3：查询 SQL**

`o_document.sql`（全文检索用 `ts_rank` + `plainto_tsquery`；可选过滤一律 `sqlc.narg`）：

```sql
-- name: ListDocuments :many
SELECT * FROM o_document WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source_module')::text IS NULL OR source_module = sqlc.narg('source_module')::text)
  AND (sqlc.narg('source_id')::bigint IS NULL OR source_id = sqlc.narg('source_id')::bigint)
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: SearchDocuments :many
SELECT *, ts_rank(to_tsvector('simple', coalesce(text_content,'')), plainto_tsquery('simple', sqlc.arg('q')::text)) AS rank,
       ts_headline('simple', coalesce(text_content,''), plainto_tsquery('simple', sqlc.arg('q')::text), 'MaxFragments=2,MinWords=8,MaxWords=18') AS snippet
FROM o_document
WHERE deleted = 0 AND status = 'STORED'
  AND to_tsvector('simple', coalesce(text_content,'')) @@ plainto_tsquery('simple', sqlc.arg('q')::text)
ORDER BY rank DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: GetDocument :one
SELECT * FROM o_document WHERE id = $1 AND deleted = 0;

-- name: CreateDocument :one
INSERT INTO o_document
  (code, tenant_id, status, creator_id, security_level, name, doc_type, size_bytes,
   bucket, object_key, checksum_sha256, uploader_id, uploaded_at, source_module, source_id, text_content)
VALUES
  (sqlc.narg('code')::text, sqlc.arg('tenant_id')::bigint, sqlc.arg('status')::text, sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('name')::text, sqlc.narg('doc_type')::text,
   sqlc.narg('size_bytes')::bigint, sqlc.narg('bucket')::text, sqlc.narg('object_key')::text,
   sqlc.narg('checksum_sha256')::text, sqlc.narg('uploader_id')::bigint,
   COALESCE(sqlc.narg('uploaded_at')::timestamptz, now()),
   sqlc.narg('source_module')::text, sqlc.narg('source_id')::bigint, sqlc.narg('text_content')::text)
RETURNING *;

-- name: SetDocumentStatus :execrows
UPDATE o_document SET status = sqlc.arg('status')::text, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: SoftDeleteDocument :execrows
UPDATE o_document SET deleted = 1, status = 'MISSING', updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: CountDocuments :one
SELECT count(*) FROM o_document WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source_module')::text IS NULL OR source_module = sqlc.narg('source_module')::text);
```

`o_archive.sql`：

```sql
-- name: ListArchives :many
SELECT * FROM o_archive WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('archive_type')::text IS NULL OR archive_type = sqlc.narg('archive_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountArchives :one
SELECT count(*) FROM o_archive WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('archive_type')::text IS NULL OR archive_type = sqlc.narg('archive_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: GetArchive :one
SELECT * FROM o_archive WHERE id = $1 AND deleted = 0;

-- name: CreateArchive :one
INSERT INTO o_archive
  (code, tenant_id, status, creator_id, security_level, title, archive_type,
   source_module, source_id, source_code, owner_dept_id, retention_years)
VALUES
  (sqlc.narg('code')::text, sqlc.arg('tenant_id')::bigint, 'PENDING_SUBMIT', sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('title')::text,
   COALESCE(sqlc.narg('archive_type')::text,'OTHER'), sqlc.narg('source_module')::text,
   sqlc.narg('source_id')::bigint, sqlc.narg('source_code')::text, sqlc.narg('owner_dept_id')::bigint,
   COALESCE(sqlc.narg('retention_years')::int, 10))
RETURNING *;

-- name: UpdateArchive :execrows
UPDATE o_archive SET title=sqlc.arg('title')::text, archive_type=sqlc.arg('archive_type')::text,
  retention_years=sqlc.arg('retention_years')::int, security_level=sqlc.arg('security_level')::text,
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0 AND status IN ('PENDING_SUBMIT','REJECTED');

-- name: SoftDeleteArchive :execrows
UPDATE o_archive SET deleted=1, modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0 AND status IN ('PENDING_SUBMIT','REJECTED');

-- name: SetArchiveStatus :execrows
UPDATE o_archive SET status=sqlc.arg('status')::text,
  submitter_id=COALESCE(sqlc.narg('submitter_id')::bigint, submitter_id),
  submit_at=COALESCE(sqlc.narg('submit_at')::timestamptz, submit_at),
  archivist_id=COALESCE(sqlc.narg('archivist_id')::bigint, archivist_id),
  filed_at=COALESCE(sqlc.narg('filed_at')::timestamptz, filed_at),
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0
  AND status = sqlc.narg('from_status')::text;   -- 乐观并发：仅当前态匹配才迁移

-- name: ListItems :many
SELECT * FROM o_archive_item WHERE archive_id = $1 ORDER BY sort_no ASC, id ASC;

-- name: GetItem :one
SELECT * FROM o_archive_item WHERE id = $1 AND archive_id = $2;

-- name: CreateItem :one
INSERT INTO o_archive_item(tenant_id, archive_id, category_code, category_name, required, doc_id, status, sort_no)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('archive_id')::bigint, sqlc.arg('category_code')::text,
  sqlc.narg('category_name')::text, COALESCE(sqlc.narg('required')::bool, TRUE), sqlc.narg('doc_id')::bigint,
  CASE WHEN sqlc.narg('doc_id')::bigint IS NULL THEN 'MISSING' ELSE 'FILLED' END,
  COALESCE(sqlc.narg('sort_no')::int, 0))
RETURNING *;

-- name: FillItem :execrows
UPDATE o_archive_item SET doc_id=sqlc.arg('doc_id')::bigint, status='FILLED'
WHERE id=sqlc.arg('id')::bigint AND archive_id=sqlc.arg('archive_id')::bigint;

-- name: DeleteItem :execrows
DELETE FROM o_archive_item WHERE id=sqlc.arg('id')::bigint AND archive_id=sqlc.arg('archive_id')::bigint;

-- name: ListRequiredItems :many
SELECT * FROM o_archive_item WHERE archive_id = $1 AND required = TRUE;

-- name: UpsertCheck :one
INSERT INTO o_archive_check(tenant_id, archive_id, check_type, result, detail, checked_at, checker_id)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('archive_id')::bigint, sqlc.arg('check_type')::text,
  sqlc.arg('result')::text, sqlc.arg('detail')::jsonb, now(), sqlc.narg('checker_id')::bigint)
ON CONFLICT (archive_id, check_type) DO UPDATE
  SET result=EXCLUDED.result, detail=EXCLUDED.detail, checked_at=now(), checker_id=EXCLUDED.checker_id
RETURNING *;

-- name: ListChecks :many
SELECT * FROM o_archive_check WHERE archive_id = $1 ORDER BY check_type ASC;
```

`o_borrow.sql`：

```sql
-- name: ListBorrows :many
SELECT * FROM o_borrow WHERE deleted = 0
  AND (sqlc.narg('borrower_user_id')::bigint IS NULL OR borrower_user_id = sqlc.narg('borrower_user_id')::bigint)
  AND (sqlc.narg('archive_id')::bigint IS NULL OR archive_id = sqlc.narg('archive_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountBorrows :one
SELECT count(*) FROM o_borrow WHERE deleted = 0
  AND (sqlc.narg('borrower_user_id')::bigint IS NULL OR borrower_user_id = sqlc.narg('borrower_user_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text);

-- name: GetBorrow :one
SELECT * FROM o_borrow WHERE id = $1 AND deleted = 0;

-- name: CreateBorrow :one
INSERT INTO o_borrow(code, tenant_id, status, creator_id, archive_id, borrower_user_id, purpose, borrow_type, due_at)
VALUES (sqlc.narg('code')::text, sqlc.arg('tenant_id')::bigint, 'SUBMITTED', sqlc.arg('creator_id')::bigint,
  sqlc.arg('archive_id')::bigint, sqlc.arg('borrower_user_id')::bigint, sqlc.narg('purpose')::text,
  COALESCE(sqlc.narg('borrow_type')::text,'READ'), sqlc.narg('due_at')::timestamptz)
RETURNING *;

-- name: SetBorrowStatus :execrows
UPDATE o_borrow SET status=sqlc.arg('status')::text,
  approved_by=COALESCE(sqlc.narg('approved_by')::bigint, approved_by),
  approved_at=COALESCE(sqlc.narg('approved_at')::timestamptz, approved_at),
  returned_at=COALESCE(sqlc.narg('returned_at')::timestamptz, returned_at),
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0 AND status = sqlc.narg('from_status')::text;
```

- [ ] **步骤 4：生成 DAL + 编译测试**

先重跑迁移汇总，再生成：

```bash
cd backend-go && go generate ./migrations/... && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate
```

创建 `backend-go/internal/modules/archive/store/compile_test.go`：

```go
package ostore

import "testing"

func TestStoreCompiles(t *testing.T) {
	_ = Document{}
	_ = Archive{}
	_ = ArchiveItem{}
	_ = ArchiveCheck{}
	_ = Borrow{}
}
```

运行：`cd backend-go && go build ./internal/modules/archive/store/... && go test ./internal/modules/archive/store/ -run Compiles -v`
预期：PASS（若 `SearchDocuments` 的 `rank/snippet` 计算列类型推断异常，给该查询两列加 `AS rank::float4`、`AS snippet::text` 显式 cast，重生成）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/db/schema/o_schema.sql backend-go/db/query_o backend-go/sqlc.yaml backend-go/internal/modules/archive/store
git commit -m "feat(O): sqlc O 引擎块 + 查询(全文检索/清单/四性/借阅) + DAL 生成"
```

### 任务 4.4：O mapper + Handler 结构（含 Storage）

**文件：**
- 创建：`backend-go/internal/modules/archive/mapper.go`
- 创建：`backend-go/internal/modules/archive/handler.go`

- [ ] **步骤 1：mapper**

复用 `fmtTime/jsonToAny/ptrStr/numDec/numStrOrNil/timePtrStr`（拷入 `archive` 包）。`ToAPIDocument`（**不输出 `text_content`**）、`ToAPIArchive`、`ToAPIArchiveItem`、`ToAPIArchiveCheck`（`detail` 走 `jsonToAny`）、`ToAPIBorrow`。字段对齐 §4.2 契约 schema；时间列 `*time.Time`→`timePtrStr`（nil→JSON null）。

- [ ] **步骤 2：Handler 结构（唯一持 Storage 的模块 handler）**

```go
package archive

import (
	ostore "github.com/eplugger/ark/internal/modules/archive/store"
	"github.com/eplugger/ark/internal/platform/storage"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	q     *ostore.Queries
	store storage.Storage // 可为 nil：依赖它的端点返回 50301
}

func NewHandler(pool *pgxpool.Pool, s storage.Storage) *Handler {
	return &Handler{q: ostore.New(pool), store: s}
}
```

同包补 `pageArgs/optQuery/optInt64/dPage/dSize`（逐字拷 `activity/handler.go`，改包名）。`guardStorage(c)` helper：`if h.store == nil { httpx.WriteErr(c, 503, 50301, "对象存储不可用"); return false }; return true`。

- [ ] **步骤 3：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/archive/... && git add backend-go/internal/modules/archive/mapper.go backend-go/internal/modules/archive/handler.go && git commit -m "feat(O): mapper + Handler(注入 storage.Storage)"
```

### 任务 4.5：O 文档端点（MinIO 上传/下载/删除/检索）

**文件：**
- 创建：`backend-go/internal/modules/archive/document.go`

- [ ] **步骤 1：UploadDocument（multipart → 计算 sha256 → Put → 落库）**

`guardStorage` 先行。`c.FormFile("file")` 打开 → 读字节算 `sha256`（`crypto/sha256`，`hex.EncodeToString`）→ 构造 `objectKey := fmt.Sprintf("tenant/%d/%d-%s", d.TenantID, time.Now().UnixNano(), filepath.Base(hdr.Filename))` → `h.store.Put(c, objectKey, bytes.NewReader(b), size, hdr.Header.Get("Content-Type"))` → `CreateDocument(status=STORED, checksum_sha256, bucket=cfg bucket, object_key, size_bytes, doc_type=ext/mime, source_module/source_id 可选, text_content 可选（本轮不接解析服务，由 body 传或留空）)` → `WriteOK(ToAPIDocument)`。bucket 从 `h.bucket`（NewHandler 时若接口未暴露 bucket，用常量 `ark-docs` 或 `RouterDeps` 透传；本计划用包级常量 `defaultBucket="ark-docs"`，与 compose 一致）。

- [ ] **步骤 2：DownloadDocument（presign）**

`guardStorage` → `GetDocument` → `h.store.PresignGet(c, doc.ObjectKey)` → `WriteOK(gin.H{"url":u,"expires_at":time.Now().Add(15*time.Minute).UTC().Format(time.RFC3339)})`。

- [ ] **步骤 3：DeleteDocument（软删 + 尽力删对象）**

`guardStorage` → `SoftDeleteDocument`（0 行→40401）→ 尽力 `h.store.Remove(c, doc.ObjectKey)`（删除对象失败仅记日志，不回滚软删）→ `WriteOK({ok:true})`。

- [ ] **步骤 4：SearchDocuments（全文检索）**

`h.q.SearchDocuments(c, ostore.SearchDocumentsParams{Q: kw, Limit, Offset})` → 每条 `ToAPIDocument(r.Document 内嵌列)` + 附 `snippet`、`rank`（生成物的计算列）→ `WriteOK(gin.H{"list":out,"total":len(out),"page":...,"size":...})`。空 `q` → 40001。

- [ ] **步骤 5：GetDocument（单读）**

`GetDocument` → `WriteOK(ToAPIDocument)`；0 命中→40401。

- [ ] **步骤 6：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/archive/... && git add backend-go/internal/modules/archive/document.go && git commit -m "feat(O): 文档端点(上传→sha256→MinIO / presign 下载 / 软删 / 全文检索)"
```

### 任务 4.6：O 案卷 CRUD + 门类清单 + 摄取

**文件：**
- 创建：`backend-go/internal/modules/archive/archive.go`

- [ ] **步骤 1：CRUD**

`ListArchives`/`GetArchive`/`CreateArchive`（分配 `ARC-年-序`，走 `seq` 或 `code=nil` 由 handler 组装——沿用 V/M 的 code 分配法）/`UpdateArchive`（`UpdateArchive :execrows`，0 行→40901「状态不允许编辑」或 40401「不存在」，依查询返回判定）/`DeleteArchive`（软删，仅 PENDING_SUBMIT/REJECTED）。

- [ ] **步骤 2：门类清单 items**

`ListItems`/`AddItem`（`CreateItem`，required 缺 doc→MISSING；带 doc→FILLED）/`FillItem`（`doc_id` 非空且文档须 STORED）/`DeleteItem`。`IngestSource`：body `{category_code, doc_id}`，等价于 AddItem（来源模块文档挂入案卷），便于 E/N/E/R 归档时引用已上传 document。

- [ ] **步骤 3：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/archive/... && git add backend-go/internal/modules/archive/archive.go && git commit -m "feat(O): 案卷 CRUD + 门类清单 + 来源摄取"
```

### 任务 4.7：O 四性检测（核心，纯逻辑可测）

**文件：**
- 创建：`backend-go/internal/modules/archive/check.go`
- 测试：`backend-go/internal/modules/archive/check_test.go`

- [ ] **步骤 1：写失败的纯逻辑测试**

`check_test.go`（无 DB、无 MinIO，喂组装好的事实）：

```go
package archive

import "testing"

func TestFourPropertiesIntegrityFailWhenRequiredMissing(t *testing.T) {
	res := evaluateFourProperties(facts{
		RequiredTotal: 3, RequiredFilled: 2,
		Docs:       []docFact{{Expected: "aa", Got: "aa", Usable: true}},
		SecurityOK: true,
	})
	if byType(res, "INTEGRITY").Result != "FAIL" {
		t.Fatalf("required 缺应 INTEGRITY FAIL，得 %+v", byType(res, "INTEGRITY"))
	}
}

func TestFourPropertiesAuthenticityFailOnChecksumMismatch(t *testing.T) {
	res := evaluateFourProperties(facts{
		RequiredTotal: 1, RequiredFilled: 1,
		Docs:       []docFact{{Expected: "abc", Got: "xyz", Usable: true}},
		SecurityOK: true,
	})
	if byType(res, "AUTHENTICITY").Result != "FAIL" {
		t.Fatalf("checksum 不符应 AUTHENTICITY FAIL")
	}
}

func TestFourPropertiesAllPass(t *testing.T) {
	res := evaluateFourProperties(facts{
		RequiredTotal: 2, RequiredFilled: 2,
		Docs:       []docFact{{Expected: "a", Got: "a", Usable: true}, {Expected: "b", Got: "b", Usable: true}},
		SecurityOK: true,
	})
	for _, want := range []string{"AUTHENTICITY", "INTEGRITY", "USABILITY", "SECURITY"} {
		if byType(res, want).Result != "PASS" {
			t.Fatalf("%s 应 PASS，得 %+v", want, byType(res, want))
		}
	}
	if !allPassed(res) {
		t.Fatalf("allPassed 应为 true")
	}
}
```

> `byType`/`allPassed` 由 `check.go`（生产）提供，本测试文件不重复定义。

- [ ] **步骤 2：运行验证失败**

运行：`cd backend-go && go test ./internal/modules/archive/ -run FourProperties -v`
预期：FAIL（`undefined: evaluateFourProperties/facts/docFact/checkResult`）

- [ ] **步骤 3：写 check.go**

```go
package archive

import (
	"crypto/sha256"
	"encoding/hex"
)

type docFact struct {
	DocID     int64
	Expected  string // 期望 sha256（存于 o_document.checksum_sha256）
	Got       string // 实取对象算出的 sha256（hex 小写）
	Usable    bool   // 格式可读（doc_type 命中可解析白名单 或 text_content 非空）
}

type facts struct {
	RequiredTotal  int
	RequiredFilled int
	Docs           []docFact
	SecurityOK     bool // 案卷密级在操作人 clearance 内
}

type checkResult struct {
	CheckType string
	Result    string // PASS/FAIL/WARN
	Detail    map[string]any
}

func sha256hex(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

// evaluateFourProperties 纯函数：给定事实算四性。authenticity 用 hex-equal（Got 由调用方
// 对 MinIO 取回字节算得，此处仅比较，避免 DB/存储耦合）。
func evaluateFourProperties(f facts) []checkResult {
	// 真实性
	authRes, authBad := "PASS", []int64{}
	for _, d := range f.Docs {
		if d.Expected != "" && d.Expected != d.Got {
			authRes = "FAIL"
			authBad = append(authBad, d.DocID)
		}
	}
	// 完整性
	integRes := "PASS"
	if f.RequiredFilled < f.RequiredTotal {
		integRes = "FAIL"
	}
	// 可用性：全部可读=PASS；部分不可读=WARN；全不可用或无件=FAIL
	unusable := 0
	for _, d := range f.Docs {
		if !d.Usable {
			unusable++
		}
	}
	usaRes := "PASS"
	switch {
	case len(f.Docs) == 0 || unusable == len(f.Docs):
		usaRes = "FAIL"
	case unusable > 0:
		usaRes = "WARN"
	}
	// 安全性
	secRes := "PASS"
	if !f.SecurityOK {
		secRes = "FAIL"
	}
	return []checkResult{
		{"AUTHENTICITY", authRes, map[string]any{"mismatch_doc_ids": authBad, "checked": len(f.Docs)}},
		{"INTEGRITY", integRes, map[string]any{"required_total": f.RequiredTotal, "required_filled": f.RequiredFilled}},
		{"USABILITY", usaRes, map[string]any{"total": len(f.Docs), "unusable": unusable}},
		{"SECURITY", secRes, map[string]any{"security_ok": f.SecurityOK}},
	}
}

// allPassed 供 handler 判定 CHECKING→PASSED/REJECTED；测试亦复用（故定义在生产文件，非 _test.go）。
func allPassed(res []checkResult) bool {
	for _, r := range res {
		if r.Result != "PASS" {
			return false
		}
	}
	return true
}

// byType 同置于生产文件 check.go，供 handler 取单项结果、测试亦复用。
func byType(res []checkResult, typ string) checkResult {
	for _, r := range res {
		if r.CheckType == typ {
			return r
		}
	}
	return checkResult{}
}
```

> `allPassed`/`byType` 定义在 `check.go`（生产），`check_test.go` 仅写三条断言用例、直接调用二者，**不在测试文件重复定义**（避免同包重复声明编译错误）。

- [ ] **步骤 4：运行验证通过**

运行：`cd backend-go && go test ./internal/modules/archive/ -run FourProperties -v`
预期：PASS

- [ ] **步骤 5：handler CheckArchive（DB+Storage→facts→写 check→状态迁移）**

`CheckArchive(c)`：`GetArchive`（须 status∈{SUBMITTED,CHECKING}，否则先置 CHECKING）→ `guardStorage` → `ListRequiredItems`（算 RequiredTotal/Filled）→ `ListItems` 过滤 FILLED 的 `doc_id` → 逐 `GetDocument` → `h.store.Get` 取字节算 `sha256hex(string(b))` 作 Got、`doc.Usable = docTypeUsable(doc_type) || text_content 非空` → `SecurityOK = d.SecurityLevel 在 clearance 内（本轮：案卷非 TOP_SECRET 或操作人含 R-ADMIN）` → `evaluateFourProperties` → 逐条 `UpsertCheck` → 全 PASS 则 `SetArchiveStatus(archiveID, PASSED, from_status=CHECKING)`，否则 `SetArchiveStatus(REJECTED, from_status=CHECKING)` → `WriteOK(gin.H{"list":checks,"passed":all})`。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/modules/archive/check.go backend-go/internal/modules/archive/check_test.go
git commit -m "feat(O): 四性检测(真实性/完整性/可用性/安全性) 纯逻辑 + 落库 + 状态迁移"
```

### 任务 4.8：O 状态机动作 + 借阅

**文件：**
- 修改：`backend-go/internal/modules/archive/archive.go`（加 submit/file/destroy）
- 创建：`backend-go/internal/modules/archive/borrow.go`

- [ ] **步骤 1：案卷流转动作**

`SubmitArchive`：`SetArchiveStatus(SUBMITTED, from_status∈{PENDING_SUBMIT,REJECTED})`（`submitter_id/submit_at` 填当前用户/时间；非法态→40901）。`FileArchive`：`SetArchiveStatus(ARCHIVED, from_status=PASSED)`，`archivist_id/filed_at` 填（仅 R-ADMIN/R-MANAGER）。`DestroyArchive`：body `{reason}`，`SetArchiveStatus(DESTROYED, from_status=ARCHIVED)`，`remark` 记 reason（仅 R-ADMIN，留痕）。

- [ ] **步骤 2：borrow.go**

`CreateBorrow`（分配 `BORROW-年-序`，archive 须 ARCHIVED，否则 40901）/`ListBorrows`（`borrower_user_id=自己` 或 R-ADMIN 看全部）/`ApproveBorrow`（`SetBorrowStatus(APPROVED, from=SUBMITTED)`，`approved_by/approved_at`，仅 R-ADMIN/R-MANAGER）/`RejectBorrow`（→REJECTED）/`ReturnBorrow`（APPROVED→RETURNED，`returned_at`）/逾期测（读 `due_at` < now 且 APPROVED→可 `SetBorrowStatus(EXPIRED)`；本轮 `ListBorrows` 返回时由 handler 现算标记，不建定时任务）。

- [ ] **步骤 3：编译 + Commit**

```bash
cd backend-go && go build ./internal/modules/archive/... && git add backend-go/internal/modules/archive/archive.go backend-go/internal/modules/archive/borrow.go && git commit -m "feat(O): 案卷提交/入库/销毁状态机 + 借阅申请审批归还"
```

### 任务 4.9：O 路由 + 主 router 注册

**文件：**
- 创建：`backend-go/internal/modules/archive/routes.go`
- 修改：`backend-go/internal/router.go`

- [ ] **步骤 1：routes.go（静态段先于 `:id`；`items/:itemId` 在 `/items` 之后）**

```go
package archive

import "github.com/gin-gonic/gin"

func Register(r gin.IRoutes, h *Handler) {
	r.POST("/documents", h.UploadDocument)
	r.GET("/documents/search", h.SearchDocuments) // 静态段，注册在 :id 之前
	r.GET("/documents/:id", h.GetDocument)
	r.DELETE("/documents/:id", h.DeleteDocument)
	r.GET("/documents/:id/download", h.DownloadDocument)
	r.GET("/archives", h.ListArchives)
	r.POST("/archives", h.CreateArchive)
	r.GET("/archives/:id", h.GetArchive)
	r.PUT("/archives/:id", h.UpdateArchive)
	r.DELETE("/archives/:id", h.DeleteArchive)
	r.GET("/archives/:id/items", h.ListItems)
	r.POST("/archives/:id/items", h.AddItem)
	r.POST("/archives/:id/items/:itemId", h.FillItem) // PUT 语义用 POST 亦可；此处保留 RESTful PUT
	r.DELETE("/archives/:id/items/:itemId", h.DeleteItem)
	r.POST("/archives/:id/ingest", h.IngestSource)
	r.POST("/archives/:id/submit", h.SubmitArchive)
	r.POST("/archives/:id/check", h.CheckArchive)
	r.POST("/archives/:id/file", h.FileArchive)
	r.POST("/archives/:id/destroy", h.DestroyArchive)
	r.GET("/borrows", h.ListBorrows)
	r.POST("/borrows", h.CreateBorrow)
	r.POST("/borrows/:id/approve", h.ApproveBorrow)
	r.POST("/borrows/:id/reject", h.RejectBorrow)
	r.POST("/borrows/:id/return", h.ReturnBorrow)
}
```

> `FillItem` 契约为 PUT；Gin 注册须 `r.PUT("/archives/:id/items/:itemId", h.FillItem)`（上面注释保留说明，实际按契约动词 PUT 注册）。静态 `/documents/search` 必须在 `/documents/:id` 之前，否则被 `:id` 吞并。

- [ ] **步骤 2：router.go 注册（注入 d.Storage）**

把任务 3.7 的集中注册块扩展为：

```go
		projH := project.NewHandler(d.Pool)
		outH := output.NewHandler(d.Pool)
		project.Register(api, projH)
		output.Register(api, outH)
		expertreview.Register(api, expertreview.NewHandler(d.Pool, projH, outH))
		archive.Register(api, archive.NewHandler(d.Pool, d.Storage))
```

import 加 `archive`。`d.Storage` 为 nil 时 handler 仍注册，端点内 `guardStorage` 返回 50301（保证无 MinIO 宿主全站可编译/可路由）。

- [ ] **步骤 3：编译 + Commit**

```bash
cd backend-go && go build ./... && git add backend-go/internal/modules/archive/routes.go backend-go/internal/router.go && git commit -m "feat(O): 档案路由 + 主 router 注册(注入 storage)"
```

### 任务 4.10：O 权限

**文件：**
- 修改：`backend-go/internal/platform/auth/policy.csv`
- 测试：`backend-go/internal/platform/auth/caps_archive_test.go`

- [ ] **步骤 1：policy.csv 追加**

复用既有 `R-ADMIN`/`R-MANAGER`/`R-AUDITOR`（本轮不新增 `R-ARCHIVIST`，避免角色枚举漂移，规格 §6.3）：

```
p, R-MANAGER, /api/v1/documents, POST
p, R-MANAGER, /api/v1/documents/*, GET
p, R-MANAGER, /api/v1/documents/search, GET
p, R-MANAGER, /api/v1/archives/*, GET
p, R-MANAGER, /api/v1/archives, POST
p, R-MANAGER, /api/v1/archives/*, PUT
p, R-MANAGER, /api/v1/archives/*/submit, POST
p, R-MANAGER, /api/v1/archives/*/check, POST
p, R-MANAGER, /api/v1/archives/*/items, POST
p, R-MANAGER, /api/v1/archives/*/ingest, POST
p, R-MANAGER, /api/v1/borrows, POST
p, R-ADMIN, /api/v1/archives/*/file, POST
p, R-ADMIN, /api/v1/archives/*/destroy, POST
p, R-ADMIN, /api/v1/archives/*/check, POST
p, R-ADMIN, /api/v1/documents/*, DELETE
p, R-ADMIN, /api/v1/archives/*, DELETE
p, R-ADMIN, /api/v1/borrows/*/approve, POST
p, R-ADMIN, /api/v1/borrows/*/reject, POST
p, R-ADMIN, /api/v1/borrows/*, GET
p, R-AUDITOR, /api/v1/archives/*, GET
p, R-AUDITOR, /api/v1/documents/search, GET
```

- [ ] **步骤 2：caps_archive_test.go**

```go
package auth

import "testing"

func TestCapsArchive(t *testing.T) {
	enf := mustEnforcer(t)
	mgr := BuildCaps(enf, []string{"R-MANAGER"})
	if !hasCap(mgr, "/api/v1/archives/*/check POST") {
		t.Fatalf("R-MANAGER 缺四性检测权限")
	}
	if hasCap(mgr, "/api/v1/archives/*/file POST") {
		t.Fatalf("R-MANAGER 不应有入库权限")
	}
	adm := BuildCaps(enf, []string{"R-ADMIN"})
	if !hasCap(adm, "/api/v1/archives/*/file POST") {
		t.Fatalf("R-ADMIN 缺入库权限")
	}
	if !hasCap(adm, "/api/v1/borrows/*/approve POST") {
		t.Fatalf("R-ADMIN 缺借阅审批权限")
	}
}
```

- [ ] **步骤 3：跑测试 + Commit**

```bash
cd backend-go && go test ./internal/platform/auth/ -run CapsArchive -v && git add backend-go/internal/platform/auth/policy.csv backend-go/internal/platform/auth/caps_archive_test.go && git commit -m "feat(O): Casbin 权限 + caps 测试(入库/销毁限 R-ADMIN)"
```

### 任务 4.11：O 测试 + seed

**文件：**
- 测试：`backend-go/internal/modules/archive/contract_test.go`、`handler_test.go`
- 创建：`backend-go/testdata/seed_o.sql`

- [ ] **步骤 1：contract_test（无库）**

构造 `ostore.Document`/`Archive`/`ArchiveCheck`→`ToAPIDocument`/`ToAPIArchive`/`ToAPIArchiveCheck`→断言 `ToAPIDocument` **不含 `text_content`**、含 `checksum_sha256/object_key/status`；`ToAPIArchiveCheck` 含 `check_type/result/detail(对象)`；`ToAPIArchive` 含 `status/archive_type/retention_years`。

- [ ] **步骤 2：handler_test（DB + fake storage，缺 env SKIP）**

用 `storage.NewFake()` 注入 `NewHandler(pool, fake)`：上传一段已知字节 → `sha256hex` 断言落库一致 → `DownloadDocument` 得非空 url；建案卷 + 3 required item（填 2）→ `CheckArchive` 断言 `INTEGRITY=FAIL`、整体 `REJECTED`；补齐第 3 件（同一 doc 保证 checksum 命中）→ 再 `CheckArchive`→`PASSED`→`FileArchive`→`ARCHIVED`→`CreateBorrow`→`ApproveBorrow`→`ReturnBorrow` 全链路。DB 门控同 Phase1/2（`ARK_TEST_DATABASE_URL` 缺省 `t.Skip`），额外 `if fake==nil` 不需要（fake 恒可用），但真实 MinIO 集成测用 `ARK_S3_ENDPOINT` 缺省 SKIP。

- [ ] **步骤 3：seed_o.sql**

2 条 `o_document`（STORED，一条带 text_content "卷积神经网络 医学影像 分割"，一条 "项目结题报告 经费决算"）、1 条 `o_archive`（ARCHIVED, archive_type=PROJECT, source_module='E', source_code='PRJ-2024-0001'）、3 条 `o_archive_item`（required, 2 FILLED 1 MISSING）、对应 `o_archive_check`（4 条 PASS）。

- [ ] **步骤 4：跑无库测 + Commit**

```bash
cd backend-go && go test ./internal/modules/archive/ -run 'Contract|FourProperties' -v && git add backend-go/internal/modules/archive/contract_test.go backend-go/internal/modules/archive/handler_test.go backend-go/testdata/seed_o.sql && git commit -m "test(O): 契约 + 四性 + DB/fake-storage 端到端借阅链路测试 + seed"
```

### 任务 4.12：O 前端

**文件：**
- 创建：`frontend/src/views/ArchiveView.vue`
- 创建：`frontend/src/api/mock/overrides/archive.ts`
- 修改：`frontend/src/router/index.ts`
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/api/schema/index.ts`

- [ ] **步骤 1：MODULE_CODES**

`frontend/src/api/schema/index.ts` 的 `MODULE_CODES` 加 `'16':'O'`。

- [ ] **步骤 2：ArchiveView.vue**

Tab 式（案卷台账 / 四性检测 / 全文检索 / 借阅），`section id="v-archive"`。① 台账：列表 + 状态/门类筛选 + 新建 + 摄取来源 + 提交/检测/入库/销毁动作（按角色门控，入库/销毁 `hasAnyRole(['R-ADMIN'])`）。② 四性检测：`api.post('/archives/'+id+'/check')` → 四类结果卡片（PASS/FAIL/WARN 徽章 + detail）。③ 全文检索：输入关键词→`api.get('/documents/search',{params:{q}})`→命中 `snippet` 高亮 + 下载（`api.get('/documents/'+id+'/download')` 拿 url）。④ 借阅：我的借阅列表 + 新建 + 审批（R-ADMIN）。字段 snake_case；金额本域无；时间直接展示。上传用 `FormData` 直连 `POST /documents`（mock 环境走 curated override 假成功）。

- [ ] **步骤 3：路由**

`frontend/src/router/index.ts` 在 `expert-review` 路由后加：

```ts
  { path: '/archive', name: 'archive', meta: { zh: '科研档案', en: 'ARCHIVE', roles: ['R-ADMIN', 'R-MANAGER', 'R-AUDITOR'] }, component: () => import('@/views/ArchiveView.vue') },
```

- [ ] **步骤 4：侧栏**

`App.vue` `groups` 在「专家与评审」所在组追加 `{ v: 'archive', ic: '⌘', label: '科研档案', roles: ['R-ADMIN', 'R-MANAGER', 'R-AUDITOR'] }`（与 `expert-review` 同组相邻；保持 `NavGroup[]` 结构 `{t,items:[{v,ic,label,roles}]}` 不变）。

- [ ] **步骤 5：override**

`overrides/archive.ts` 导出 `overrides`（`"GET /archives"`、`"GET /documents/search"`、`"GET /archives/{id}/items"`、`"POST /archives/{id}/check"`、`"GET /borrows"` 演示数据），经 `import.meta.glob` 自动合并（无需改 index.ts）。

- [ ] **步骤 6：typecheck + build + Commit**

```bash
cd frontend && npx vue-tsc --noEmit && VITE_USE_MOCK=true npm run build
git add frontend/src/views/ArchiveView.vue frontend/src/api/mock/overrides/archive.ts frontend/src/router/index.ts frontend/src/App.vue frontend/src/api/schema/index.ts
git commit -m "feat(O-frontend): 科研档案屏(台账/四性/检索/借阅) + 路由 + 侧栏 + override"
```

### 任务 4.13：drift 路径扩展（O）

**文件：**
- 修改：`backend-go/Makefile:63`

- [ ] **步骤 1-2：drift 加 `internal/modules/archive/store` + 验证 + Commit**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate && git diff --exit-code -- internal/modules/archive/store
git add backend-go/Makefile && git commit -m "chore(O): drift 守卫纳入 archive/store"
```

## Phase 5 · 收口（全量一致性与验证）

> 四域实现完成后统一收口：全量 codegen 漂移归零、全量测试、前端构建、命名三向、契约字节同步、passthrough 登记。任一失败回到对应 Phase 修复后重跑本相。

### 任务 5.1：全量 codegen + drift 归零

**文件：**
- 校验：`backend-go/Makefile:63`（drift 路径清单）

- [ ] **步骤 1：确认 drift 路径已含全部 8 个 store**

`backend-go/Makefile:63` 的 `git diff --exit-code --` 路径须覆盖：

```
internal/modules/p/store internal/modules/sysadmin/store internal/modules/activity/store internal/modules/performance/store internal/modules/project/store internal/modules/output/store internal/modules/expertreview/store internal/modules/archive/store api/gen migrations/000001_init.up.sql migrations/000001_init.down.sql
```

（Phase 1/2/3/4 已逐个追加 project/output/expertreview/archive；此处核对无遗漏。）

- [ ] **步骤 2：跑全量 codegen（迁移汇总 + oapi + sqlc）**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 GOMAXPROCS=1 make codegen
```
预期：`gen-migrations`→`gen-oapi`→`gen-sqlc` 均 exit 0；`design/*.sql` 经 `migrations/gen.go` 汇总进 `000001_init.up.sql`（O 五表在 E/R 之后、按文件名 16 排序；ClickHouse OLAP 段被 `stripNonPostgres` 剔除）。

- [ ] **步骤 3：drift 守卫零 diff**

```bash
cd backend-go && make drift
```
预期：exit 0（无 `codegen 产物与已提交产物不一致`）。若有 diff，说明某 Phase 生成后漏 commit 生成物——补 commit 该生成物再重跑。

- [ ] **步骤 4：Commit（若 codegen 顺带刷新了生成物）**

```bash
git add backend-go/migrations backend-go/api/gen backend-go/internal/modules backend-go/Makefile
git commit -m "chore(P5): 全量 codegen 漂移归零" --allow-empty
```

### 任务 5.2：全量后端测试

- [ ] **步骤 1：无库/无 MinIO 全量单测（DB/S3-gated 自动 SKIP）**

```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 go test -race -count=1 ./...
```
预期：0 FAIL。mapper/contract/draw/四性检测 等纯逻辑测全跑；`handler_test`（需 `ARK_TEST_DATABASE_URL`）与真实 MinIO 集成测（需 `ARK_S3_ENDPOINT`）在无环境时 SKIP。

- [ ] **步骤 2（备库/备 MinIO 环境）：集成测全绿**

```bash
cd backend-go && docker compose up -d postgres minio && \
  ARK_TEST_DATABASE_URL=postgres://ark:ark@localhost:5432/ark?sslmode=disable \
  ARK_S3_ENDPOINT=localhost:9000 ARK_S3_ACCESS_KEY=minioadmin ARK_S3_SECRET_KEY=minioadmin ARK_S3_BUCKET=ark-docs \
  GOTOOLCHAIN=go1.23.4 go test -count=1 ./internal/modules/... ./internal/platform/storage/...
```
预期：E/R/N/O 四域 `handler_test` + storage 端到端 + N 回写 E_MID_CHECK + O 借阅全链路 PASS。

### 任务 5.3：passthrough 登记（满足 DoD #1）

**文件：**
- 创建：`docs/superpowers/plans/2026-10-14-passthrough-registry.md`

- [ ] **步骤 1：列出本轮明确保留 NoRoute passthrough 的端点及理由**

按下表写登记表（契约内但本轮不做真实实现的端点，由 `oapi.Passthrough` NoRoute 兜底返回通用样例，非 404）：

```
E：/health-score、/risk-warnings、/trace、/archive-checklist —— 计算型/聚合 DTO（规格 §3.2）
R：/outputs/ai-fill、/outputs/ai-dedup、/outputs/export、/metrics/refresh-cited —— AI/导出/外部抓取（规格 §4.2，AI 与导出延后）
N：无（本域端点全真实化）
O：无（本域端点全真实化；无 MinIO 宿主时依赖存储端点运行期返回 50301，非 passthrough）
```

> 校验口径：`GET /api/v1/_db`（若沿用 Node 时代的覆盖率路由则等价核对 Go 注册表）或 grep `router.Build` 注册集合与 `design/0{2,4},15,16` 契约 `paths` 差集，逐条确认为上表所列，无漏网业务端点。

- [ ] **步骤 2：Commit**

```bash
git add docs/superpowers/plans/2026-10-14-passthrough-registry.md
git commit -m "docs(P5): passthrough 登记表(计算型/AI/导出端点延后)"
```

### 任务 5.4：契约字节同步复核

- [ ] **步骤 1：四份新契约 design ↔ frontend 逐字节一致**

```bash
for f in "02-项目过程管理-E" "04-科研成果管理-R" "15-专家与评审管理-N" "16-科研档案管理-O"; do
  diff -q "design/${f}.openapi.yaml" "frontend/src/api/schema/${f}.openapi.yaml" && echo "SYNC_OK ${f}"
done
```
预期：四行 `SYNC_OK`。E/R 若前几相未单独 cp 则在此补 `cp` 再校验。

- [ ] **步骤 2：Commit（如有补同步）**

```bash
git add frontend/src/api/schema/15-专家与评审管理-N.openapi.yaml frontend/src/api/schema/16-科研档案管理-O.openapi.yaml
git commit -m "chore(P5): 契约前端副本字节同步复核" --allow-empty
```

### 任务 5.5：前端 typecheck + build

- [ ] **步骤 1：类型检查 + mock 构建**

```bash
cd frontend && npx vue-tsc --noEmit && VITE_USE_MOCK=true npm run build
```
预期：两条命令 exit 0；`dist/` 含 `ActivityView`/`PerformanceView` 之外的 `OutputView`/`ExpertReviewView`/`ArchiveView` 懒加载 chunk。

- [ ] **步骤 2：切真后端构建冒烟（关 mock）**

```bash
cd frontend && VITE_USE_MOCK=false npm run build
```
预期：exit 0（`VITE_USE_MOCK` 是构建期内联变量，关 mock 后主包应显著小于开 mock 版，因 mock 依赖被条件 dynamic import 拆出）。

### 任务 5.6：命名三向 1:1 校验

- [ ] **步骤 1：三新屏 section↔route↔sidebar grep**

```bash
cd frontend && for n in output expert-review archive; do
  a=$(grep -rl "id=\"v-${n}\"" src/views | wc -l)
  b=$(grep -c "name: '${n}'" src/router/index.ts)
  c=$(grep -c "v: '${n}'" src/App.vue)
  echo "${n}: section=${a} route=${b} sidebar=${c}"
done
```
预期：每行 `section=1 route=1 sidebar=1`。任一为 0 → 补 `views/*.vue` 的 `<section id>`、router `name`、App.vue 侧栏 `v` 三者之一。

- [ ] **步骤 2：MODULE_CODES 完整性**

```bash
cd frontend && grep -oE "'(15|16)':\s*'[NO]'" src/api/schema/index.ts
```
预期：同时出现 `'15':'N'`、`'16':'O'`。

- [ ] **步骤 3：Commit（若补了命名）**

```bash
git add frontend/src/views frontend/src/router/index.ts frontend/src/App.vue frontend/src/api/schema/index.ts
git commit -m "chore(P5): 命名三向 1:1 与 MODULE_CODES 校验收口" --allow-empty
```

### 任务 5.7：全链路冒烟（compose，可选但推荐）

- [ ] **步骤 1：起全栈（postgres + redis + minio + go backend + frontend）**

```bash
docker compose up -d --build
sleep 5 && curl -fsS localhost:8787/healthz && curl -fsS localhost:8787/api/v1/experts -H "Authorization: Bearer <token>" | head -c 400
```
预期：`/healthz` 报 db/storage 状态；带合法 JWT 时 `/api/v1/experts`、`/api/v1/archives` 返回 `code:0` 真实分页；无 MinIO 时 `/documents` 上传返回 `code:50301`。前端 `VITE_USE_MOCK=false` 构建产物指向 Go:8787，三新屏出真实数据。

---

## 自审（写后内联检查，对照规格 §0–§12）

**1. 规格覆盖：**
- §3 域 E → Phase 1（1.1 schema/sqlc、1.3 DAL、1.4 mapper/handler、1.5 writeback、1.6 routes、1.7 注册、1.8 policy、1.9 tests、1.10 前端接通+甘特、1.11-1.12 seed/drift）。回写方法 `SetMidCheckExperts/ConcludeMidCheck/ConcludeFinalAccept` 在 1.5 导出、3.6 调用，签名逐字一致。
- §4 域 R → Phase 2（含 `ConcludeOutputEval` 导出，2.5；AI/export passthrough 保留并登记于 5.3）。
- §5 域 N → Phase 3（DDL 3.1、契约 3.2、sqlc 3.3、mapper 3.4、抽取引擎 3.5、流程+回写 3.6、routes 3.7、policy 3.8、tests 3.9、前端 3.10、drift 3.11）。
- §6 域 O → Phase 4（DDL+前缀 4.1、契约 4.2、sqlc 4.3、mapper+Handler(storage) 4.4、文档端点 4.5、案卷/清单/摄取 4.6、四性检测 4.7、状态机+借阅 4.8、routes 4.9、policy 4.10、tests 4.11、前端 4.12、drift 4.13）。
- §7 MinIO → Phase 0（config 0.1、Storage 接口+fake 0.2、minio 实现+compose+best-effort 接线 0.3）。
- §8 跨模块数据流 → 1.5/2.5 导出 + 3.6 回写 + O 摄取 E/R 文档（4.6 `IngestSource`）。
- §9 测试策略 → 各 Phase 的 contract/handler/pure-logic 测 + 5.2 全量。缺口：无（§9 列的四类测均有对应任务）。

**2. 占位符扫描：** 全文无 TBD/TODO/「稍后实现」。所有 SQL/handler 关键片段给出可执行代码；`guardStorage`/`evaluateFourProperties`/`drawExperts` 三个核心逻辑均为完整实现。个别「参照既有」项（mapper helper、pageArgs、code 分配）均指向具体源文件逐字拷贝，非悬空。

**3. 类型一致性：**
- 回写四方法签名跨 1.5/2.5/3.6 一致：`SetMidCheckExperts(ctx,int64,[]int64)`、`ConcludeMidCheck(ctx,midCheckID,projectID int64,conclusion string,scoreDetail any)`、`ConcludeFinalAccept(ctx,int64,string)`、`ConcludeOutputEval(ctx,int64,bool)`。
- `NewHandler` 构造：project/output=`NewHandler(pool)`；expertreview=`NewHandler(pool, e, r)`；archive=`NewHandler(pool, storage)`；router 5.7/3.7/4.9 注册处一致。
- 契约枚举 token 与 DDL CHECK 集合逐一对齐（E_MID_CHECK conclusion CONTINUE/CORRECT/TERMINATE；O archive 七态；borrow 五态；check 四类）。
- package 名：estore/rstore/nstore/ostore；dir `internal/modules/{project,output,expertreview,archive}/store`。
- 前缀：EXR/RVW（N）/ ARC/BORROW（O）经 00-common 登记，与既有无冲突（EXP 属 F 报销，故用 EXR）。

**4. 模糊点已定：** 档案员角色复用 R-ADMIN/R-MANAGER（4.10，不新增枚举）；O 上传 bucket 用包级常量 `ark-docs`（与 compose 一致，4.5）；FillItem 按契约用 PUT 注册（4.9）；逾期借阅由 ListBorrows 现算标记，不建定时任务（4.8）；`allPassed/byType` 置于生产 check.go 防重复声明（4.7）。

---

## 完成定义（DoD）

1. E/R 契约「真实化」类端点全部由真实 Go handler+store 提供；N/O 全域端点真实；AI/export/computed 端点保留 passthrough 并登记（5.3）。
2. `make drift` 零 diff；四份新契约 `design/*.openapi.yaml` ↔ `frontend/src/api/schema/` 字节同步（5.4）。
3. 后端全量 `go test -race`（无库/S3 SKIP）0 FAIL；备库+备 MinIO 环境集成测全绿；N 回写、O 四性检测、抽取确定性单测通过（5.2）。
4. 前端 `vue-tsc` + `VITE_USE_MOCK=true build` + `VITE_USE_MOCK=false build` 三 exit 0；E/R 接通 + N/O/R 三新屏；命名三向 1:1 grep 通过；`MODULE_CODES` 含 15/16（5.5/5.6）。
5. MinIO 经 compose 起服务，`/documents` 上传→下载→presign→删除端到端可用；无 MinIO 宿主时上传端点返回 50301（5.7）。
6. `seq_prefix_registry` 登记 EXR/RVW/ARC/BORROW（3.1/4.1）。
7. 每任务一 commit、全在 develop、**不推送**；推送/PR/合并须主人明确确认（Phase A 铁律）。

---

## 执行移交

计划已保存到 `docs/superpowers/plans/2026-10-14-project-lifecycle-expert-review-archive.md`（Phase 0→5，共 56 个 bite-sized 任务）。两种执行方式：

**1. 子 Agent 驱动（推荐）** — 用 `superpowers-subagent-dev`，每个任务派新 subagent 实现、任务间两阶段审查，上下文干净、迭代快；适合本计划这种「任务边界清晰、量大、跨模块有严格签名契约」的场景。

**2. 顺序执行** — 本 session 按 Phase 0→5 任务顺序逐批实现，每任务后跑验证，完成调用 `superpowers-finishing-branch` 收口。

选哪种？（无论哪种：全程 develop 分支、逐任务 commit、不自动推送。）



