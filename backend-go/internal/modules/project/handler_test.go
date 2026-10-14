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

func newTestEngine(t *testing.T) *gin.Engine {
	t.Helper()
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
