package output

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	rstore "github.com/eplugger/ark/internal/modules/output/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func testCtx() context.Context { return context.Background() }

func strReader(s string) io.Reader { return strings.NewReader(s) }

// poolForTest 同 funding/dataio 约定：ARK_TEST_DATABASE_URL 缺省 SKIP。
func poolForTest(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("ARK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("ARK_TEST_DATABASE_URL 未设置，跳过 DB 集成")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatalf("parse dsn: %v", err)
	}
	cfg.MaxConns = 2
	pool, err := pgxpool.NewWithConfig(testCtx(), cfg)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

// runSeed 幂等清插 R 域种子（seed_r.sql 自带前置 DELETE 清理）。
func runSeed(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "testdata", "seed_r.sql"))
	if err != nil {
		t.Fatalf("seed 文件读取失败: %v", err)
	}
	if _, err := pool.Exec(testCtx(), string(b)); err != nil {
		t.Fatalf("seed 执行失败: %v", err)
	}
}

// newOutputEngine 构建测试引擎并注入 domain（uid/tenant/roles）。
func newOutputEngine(t *testing.T, pool *pgxpool.Pool, uid, tenant int64) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(auth.CtxUserID, uid)
		c.Set(auth.CtxTenantID, tenant)
		c.Set(auth.CtxRoles, []string{"R-LEADER"})
		c.Next()
	})
	Register(r.Group("/api/v1"), NewHandler(pool))
	return r
}

func doGet(r *gin.Engine, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
	return w
}

func doPost(r *gin.Engine, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", path, strReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	return w
}

// dataOf 解析信封 data 为 map。
func dataOf(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var env struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("data 解析失败: %v body=%s", err, string(body))
	}
	return env.Data
}

// pushSeed 直插推送项；dedup_key 与 normTitleHash 同算法（sha256(lower(trim(title))) hex）。
func pushSeed(t *testing.T, pool *pgxpool.Pool, tenant int64, typ, sourceDB, title string, year int32) int64 {
	t.Helper()
	sum := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(title))))
	dk := hex.EncodeToString(sum[:])
	var id int64
	err := pool.QueryRow(testCtx(),
		`INSERT INTO R_PUSH_ITEM (tenant_id, type, source_db, title, year, dedup_key)
		 VALUES ($1,$2,$3,$4,$5,$6) RETURNING id`,
		tenant, typ, sourceDB, title, year, dk).Scan(&id)
	if err != nil {
		t.Fatalf("pushSeed: %v", err)
	}
	return id
}

// extractPushID 从 /push-items 列表 JSON 按标题精确匹配找 id。
func extractPushID(body, title string) int64 {
	var env struct {
		Data struct {
			List []struct {
				ID    int64  `json:"id"`
				Title string `json:"title"`
			} `json:"list"`
		} `json:"data"`
	}
	_ = json.Unmarshal([]byte(body), &env)
	for _, it := range env.Data.List {
		if it.Title == title {
			return it.ID
		}
	}
	return 0
}

var _ = rstore.Output{} // 保持 rstore 引用（helper 扩展位）
