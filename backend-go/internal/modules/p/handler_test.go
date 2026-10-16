package p

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// 手工把数据域塞进 context（M0 阶段鉴权中间件尚未接入，见任务9）
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Next()
}

// runSeedP 幂等清 p_application 后执行 testdata/seed_p.sql；
// seed 提供 tenant=1 未删 2 行、tenant=2 1 行、tenant=1 已删 1 行，覆盖过滤测期望。
func runSeedP(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	if _, err := pool.Exec(ctx, `DELETE FROM p_application WHERE tenant_id IN (1,2)`); err != nil {
		t.Fatalf("清理 p_application 失败: %v", err)
	}
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "testdata", "seed_p.sql"))
	if err != nil {
		t.Fatalf("seed_p 读取失败: %v", err)
	}
	if _, err := pool.Exec(ctx, string(b)); err != nil {
		t.Fatalf("seed_p 执行失败: %v", err)
	}
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
	runSeedP(t, context.Background(), pool)
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomain)
	// Task 12 起 Register 不再自带 /api/v1 前缀，改由调用方分组提供，整路径仍为 /api/v1/apply/...
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool))
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

// runSeedGuideline 幂等清理并插入两条 tenant=1 指南（PUBLISHED + DRAFT）+ 一条 tenant=2，
// 覆盖租户隔离/状态过滤测期望。
func runSeedGuideline(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	if _, err := pool.Exec(ctx, `DELETE FROM p_guideline WHERE code LIKE 'GL-TEST-%'`); err != nil {
		t.Fatalf("清理 p_guideline 失败: %v", err)
	}
	seed := `
INSERT INTO p_guideline (tenant_id, code, status, creator_id, title, project_type,
                         funding_source, total_envelope, apply_end_at, publish_at)
VALUES (1, 'GL-TEST-1', 'PUBLISHED', 1, '测试指南一', '国家自然科学基金', '基金委', '500000.00',
        now() + interval '30 days', now()),
       (1, 'GL-TEST-2', 'DRAFT', 1, '测试指南二', '省部级', NULL, NULL, NULL, NULL),
       (2, 'GL-TEST-1', 'PUBLISHED', 2, '租户二指南', '横向委托', NULL, NULL, NULL, now());
`
	if _, err := pool.Exec(ctx, seed); err != nil {
		t.Fatalf("seed guideline 执行失败: %v", err)
	}
}

func newGuidelineTestEngine(t *testing.T) *gin.Engine {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	runSeedP(t, context.Background(), pool)
	runSeedGuideline(t, context.Background(), pool)
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomain)
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool))
	return e
}

func TestListGuidelines_Endpoint(t *testing.T) {
	e := newGuidelineTestEngine(t)

	// 1) 全量：tenant=1 仅 2 条（租户隔离）
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/guidelines", nil))
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
		t.Fatalf("列表结果不符(期望 tenant=1 共2条): %+v", env)
	}

	// 2) status=PUBLISHED 过滤 → 1 条
	w = httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/guidelines?status=PUBLISHED", nil))
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Data.Total != 1 {
		t.Fatalf("status 过滤不符: %+v", env.Data)
	}

	// 3) 字段形状：total_envelope 为 string、target_disciplines 为数组
	row := env.Data.List[0]
	if _, ok := row["total_envelope"].(string); !ok {
		t.Fatalf("total_envelope 非字符串: %#v", row["total_envelope"])
	}
	if _, ok := row["target_disciplines"].([]any); !ok {
		t.Fatalf("target_disciplines 非数组: %#v", row["target_disciplines"])
	}
}

func TestGetGuideline_404WhenMissing(t *testing.T) {
	e := newGuidelineTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/guidelines/999999", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("期望 404，实得 %d", w.Code)
	}
}

func TestUpsertGuideline_TwiceSameCode(t *testing.T) {
	e := newGuidelineTestEngine(t)
	body := `{"code":"GL-TEST-UP","title":"upsert 指南","project_type":"院自立项目",
	          "status":"PUBLISHED","total_envelope":"800000.00"}`
	// 第一次创建
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/apply/guidelines", strings.NewReader(body)))
	if w.Code != 200 {
		t.Fatalf("首次创建失败 HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int `json:"code"`
		Data struct {
			ID     int64  `json:"id"`
			Status string `json:"status"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Code != 0 || env.Data.ID == 0 {
		t.Fatalf("首次创建响应异常: %+v", env)
	}
	// 第二次同 code upsert：不新增行，返回同一 id
	w = httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/apply/guidelines", strings.NewReader(body)))
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Data.ID == 0 {
		t.Fatalf("二次 upsert 失败: %s", w.Body.String())
	}
	var cnt int
	if err := dbPool(context.Background(), t).QueryRow(context.Background(),
		`SELECT count(*) FROM p_guideline WHERE code = 'GL-TEST-UP' AND deleted = 0`).Scan(&cnt); err != nil {
		t.Fatal(err)
	}
	if cnt != 1 {
		t.Fatalf("同 code upsert 后期望 1 行，实得 %d", cnt)
	}
}

// dbPool 供断言直查测试库。
func dbPool(ctx context.Context, t *testing.T) *pgxpool.Pool {
	t.Helper()
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(ctx, u)
	if err != nil {
		t.Fatal(err)
	}
	return pool
}
