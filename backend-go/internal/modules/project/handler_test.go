package project

import (
	"context"
	"encoding/json"
	"math/big"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	estore "github.com/eplugger/ark/internal/modules/project/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ---------- mapper 测试样例（contract_test.go 用） ----------

func newSampleProject() estore.Project {
	return estore.Project{
		ID: 1, Code: nil, TenantID: 1, Status: "EXECUTING",
		CreatedAt: time.Now().UTC(), UpdatedAt: time.Now().UTC(),
		Title: "示例项目", ProjectType: strPtr("NSFC"), PiUserID: 100,
		LegalEntityID: 1,
		TotalBudget:   pgtype.Numeric{Valid: true, Int: big.NewInt(100000)},
		HealthScore:   82, RiskLevel: "LOW", SecurityLevel: "INTERNAL",
	}
}

func newSampleMidCheck() estore.MidCheck {
	return estore.MidCheck{
		ID: 1, Code: nil, TenantID: 1, Status: "PENDING",
		CreatedAt: time.Now().UTC(), ProjectID: 1, CheckRound: 1,
		ExpertIds: []byte(`[101,102]`), ScoreDetail: nil,
	}
}

func strPtr(s string) *string { return &s }

// ---------- handler 测试脚手架（DB-gated） ----------

// M0 无鉴权中间件，测试里手工塞数据域（E handler 需 tenant_id + user_id 用作 pi_user_id）。
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxUserID, int64(1001))
	c.Next()
}

// injectDomainWithRoles 指定角色注入（管理员全量视角用例）。
func injectDomainWithRoles(roles ...string) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Set(auth.CtxTenantID, int64(1))
		c.Set(auth.CtxUserID, int64(1001))
		c.Set(auth.CtxRoles, roles)
		c.Next()
	}
}

// testPool 统一取测试库连接：未设置 ARK_TEST_DATABASE_URL 时 **skip**（CI 无库单测路径必须安全，
// 不得 panic/失败）；返回的连接由 t.Cleanup 关闭，避免多引擎用例泄漏连接池。
func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func newTestEngineWithRoles(t *testing.T, roles []string) *gin.Engine {
	t.Helper()
	pool := testPool(t)
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomainWithRoles(roles...))
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool))
	return e
}

func newTestEngine(t *testing.T) *gin.Engine {
	t.Helper()
	pool := testPool(t)
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomain)
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool))
	return e
}

// 依赖 testdata/seed_e.sql：tenant=1、pi_user_id=1001 未删 ≥1 条项目。
func TestListMyProjects_ConformsToContract(t *testing.T) {
	e := newTestEngine(t)
	spec := mustSpec(t)
	op := spec.Find("GET", "/project/mine")
	if op == nil {
		t.Fatal("未找到 GET /project/mine")
	}
	dataSchema := oapi.ResolveDataSchema(op)

	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/project/mine?page=1&size=20", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if errs := oapi.Validate(env["data"], dataSchema); len(errs) > 0 {
		t.Fatalf("响应 data 不合契约: %v", errs)
	}
}

func TestGetProject_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/project/999999999", nil))
	if w.Code != 404 {
		t.Fatalf("期望 404，实得 %d body=%s", w.Code, w.Body.String())
	}
}

// TestListMyProjects_AdminSeesAll：R-ADMIN 全量视角——total 应等于租户全部未删项目数，
// 且不少于纯 PI 视角（1001 名下）的 total。
func TestListMyProjects_AdminSeesAll(t *testing.T) {
	pool := testPool(t)
	var dbTotal int64
	if err := pool.QueryRow(context.Background(),
		"SELECT count(*) FROM e_project WHERE tenant_id=1 AND deleted=0").Scan(&dbTotal); err != nil {
		t.Fatal(err)
	}

	fetchTotal := func(e *gin.Engine) int64 {
		w := httptest.NewRecorder()
		e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/project/mine?page=1&size=50", nil))
		if w.Code != 200 {
			t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
		}
		var env struct {
			Data struct {
				Total int64 `json:"total"`
			} `json:"data"`
		}
		_ = json.Unmarshal(w.Body.Bytes(), &env)
		return env.Data.Total
	}

	staffTotal := fetchTotal(newTestEngine(t))
	adminTotal := fetchTotal(newTestEngineWithRoles(t, []string{"R-ADMIN"}))

	if adminTotal != dbTotal {
		t.Fatalf("admin total=%d 应等于库内未删项目数 %d", adminTotal, dbTotal)
	}
	if adminTotal < staffTotal {
		t.Fatalf("admin total=%d 不应少于 PI 视角 total=%d", adminTotal, staffTotal)
	}
}
