package output

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	rstore "github.com/eplugger/ark/internal/modules/output/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
)

// ---------- mapper 测试样例（contract_test.go 用） ----------

func newSampleOutput() rstore.Output {
	return rstore.Output{
		ID: 1, Code: nil, TenantID: 1, Status: "PENDING_CLAIM",
		CreatedAt: time.Now().UTC(), UpdatedAt: time.Now().UTC(),
		OutputType: "PAPER", Title: "示例成果", Source: "MANUAL",
		Authors:     []byte(`[{"user_id":100,"name":"张三","order":1}]`),
		ClaimStatus: "PENDING", IsClaimed: false,
		LegalEntityID: 1, SecurityLevel: "INTERNAL",
	}
}

func newSampleClaimRecord() rstore.ClaimRecord {
	return rstore.ClaimRecord{
		ID: 1, TenantID: 1, Status: "DONE", OutputID: 100, UserID: 100,
		Action: "CLAIM", Reason: nil, BatchID: nil,
		CreatedAt: time.Now().UTC(), UpdatedAt: time.Now().UTC(), ActionAt: time.Now().UTC(),
	}
}

// ---------- handler 测试脚手架（DB-gated） ----------

// M0 无鉴权中间件，测试里手工塞数据域（R handler 需 tenant_id + user_id 用作 creator/claim actor）。
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxUserID, int64(100))
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

// TestListOutputs_ConformsToContract 依赖 testdata/seed_r.sql：tenant=1 存在未删成果。
func TestListOutputs_ConformsToContract(t *testing.T) {
	e := newTestEngine(t)
	spec := mustSpec(t)
	op := spec.Find("GET", "/output")
	if op == nil {
		t.Fatal("未找到 GET /output")
	}
	dataSchema := oapi.ResolveDataSchema(op)

	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/output?page=1&size=20", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if errs := oapi.Validate(env["data"], dataSchema); len(errs) > 0 {
		t.Fatalf("响应 data 不合契约: %v", errs)
	}
}

func TestGetOutput_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/output/999999999", nil))
	if w.Code != 404 {
		t.Fatalf("期望 404，实得 %d body=%s", w.Code, w.Body.String())
	}
}
