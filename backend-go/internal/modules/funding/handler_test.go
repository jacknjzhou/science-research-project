package funding

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// newFundingEngine 构建测试引擎（中间件先于 Register 挂载）。
func newFundingEngine(t *testing.T, pool *pgxpool.Pool, mw ...gin.HandlerFunc) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(mw...)
	api := r.Group("/api/v1")
	Register(api, NewHandler(pool))
	return r
}

// injectDomain 注入 domain（同 V/M 竖切约定：tenant + userID + roles）。
func injectDomain(roles []string, userID, tenantID int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Set("uid", userID)
		c.Set("tenant_id", tenantID)
		c.Set("roles", roles)
		c.Next()
	}
}

// poolForTest 同 performance 约定：ARK_TEST_DATABASE_URL 缺省 SKIP。
func poolForTest(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("ARK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("ARK_TEST_DATABASE_URL 未设置，跳过 DB 集成")
	}
	pool, err := pgxpool.New(testCtx(), dsn)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

// runSeed 幂等清插本域数据。
func runSeed(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "testdata", "seed_f.sql"))
	if err != nil {
		t.Fatalf("seed 文件读取失败: %v", err)
	}
	if _, err := pool.Exec(testCtx(), string(b)); err != nil {
		t.Fatalf("seed 执行失败: %v", err)
	}
}

func doGet(r *gin.Engine, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", path, nil)
	r.ServeHTTP(w, req)
	return w
}

func doPost(r *gin.Engine, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", path, strReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	return w
}
