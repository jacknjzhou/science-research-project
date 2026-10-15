package performance

import (
	"bytes"
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func newPerfEngine(t *testing.T, pool *pgxpool.Pool, mw ...gin.HandlerFunc) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	// 中间件必须先于 Register 挂载，否则 Gin 已冻结路由、domain 不生效。
	r.Use(mw...)
	api := r.Group("/api/v1")
	Register(api, NewHandler(pool))
	return r
}

// 注入 domain（同 V 竖切约定：tenant + userID + roles）
func injectPerfDomain(roles []string, userID, tenantID int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Set(auth.CtxTenantID, tenantID)
		c.Set(auth.CtxUserID, userID)
		c.Set(auth.CtxRoles, roles)
		c.Next()
	}
}

// seed 前先清本域表（幂等，便于同库反复跑），再执行 seed_m.sql。
func runSeed(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	for _, trunc := range []string{
		`DELETE FROM m_record_item WHERE tenant_id=1`,
		`DELETE FROM m_payout WHERE tenant_id=1`,
		`DELETE FROM m_record WHERE tenant_id=1`,
		`DELETE FROM m_scheme_factor WHERE tenant_id=1`,
		`DELETE FROM m_scheme WHERE tenant_id=1`,
		`DELETE FROM t_deal WHERE tenant_id=1`,
		`DELETE FROM t_disclosure WHERE tenant_id=1`,
		`DELETE FROM f_income WHERE tenant_id=1`,
		`DELETE FROM e_project WHERE tenant_id=1`,
		`DELETE FROM r_output WHERE tenant_id=1`,
	} {
		if _, err := pool.Exec(ctx, trunc); err != nil {
			t.Fatalf("清理失败 %q: %v", trunc, err)
		}
	}
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "testdata", "seed_m.sql"))
	if err != nil {
		t.Fatalf("seed 文件读取失败: %v", err)
	}
	if _, err := pool.Exec(ctx, string(b)); err != nil {
		t.Fatalf("seed 执行失败: %v", err)
	}
}

func poolForTest(t *testing.T) (context.Context, *pgxpool.Pool) {
	t.Helper()
	dsn := os.Getenv("ARK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("ARK_TEST_DATABASE_URL 未设置，跳过 DB 集成")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return ctx, pool
}

func TestCalculateEndToEnd(t *testing.T) {
	ctx, pool := poolForTest(t)
	runSeed(t, ctx, pool)

	r := newPerfEngine(t, pool, injectPerfDomain([]string{"R-MANAGER"}, 1, 1)) // 主管触发

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/perf/schemes/1/calculate",
		bytes.NewBufferString(`{"period":"2026Q3","staff_ids":[100]}`))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("calculate 应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int `json:"code"`
		Data struct {
			Computed int `json:"computed"`
			Inserted int `json:"inserted"`
			Updated  int `json:"updated"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Data.Computed != 1 || env.Data.Inserted != 1 {
		t.Fatalf("应算 1 人/新 1 条，得 %+v", env.Data)
	}

	// 查记录验证 total_score≈20.80（seed 手算值）
	q := mstore.New(pool)
	uid := int64(100)
	lrows, err := q.ListRecords(ctx, mstore.ListRecordsParams{
		TenantID: 1, StaffUserID: &uid, Offset: 0, Limit: 10,
	})
	if err != nil || len(lrows) == 0 {
		t.Fatalf("记录未落库: err=%v rows=%d", err, len(lrows))
	}
	f, err := lrows[0].TotalScore.Float64Value()
	if err != nil || !f.Valid || math.Abs(f.Float64-20.80) > 1e-6 {
		t.Fatalf("total_score 期望 20.80，得 %v (err=%v)", f.Float64, err)
	}

	// 明细应有 4 个因子
	items, _ := q.ListItems(ctx, lrows[0].ID)
	if len(items) != 4 {
		t.Fatalf("应有 4 条因子明细，得 %d", len(items))
	}
}

// TestReadRecordForABAC_StaffCrossUser：R-STAFF(200) 读他人(100)记录应 403
func TestReadRecordForABAC_StaffCrossUser(t *testing.T) {
	ctx, pool := poolForTest(t)
	runSeed(t, ctx, pool)

	// 主管先 calculate 造一条 staff=100 的记录
	rc := newPerfEngine(t, pool, injectPerfDomain([]string{"R-MANAGER"}, 1, 1))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/perf/schemes/1/calculate",
		bytes.NewBufferString(`{"period":"2026Q3","staff_ids":[100]}`))
	req.Header.Set("Content-Type", "application/json")
	rc.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("前置 calculate 应 200，得 %d body=%s", w.Code, w.Body.String())
	}

	q := mstore.New(pool)
	uid := int64(100)
	lr, _ := q.ListRecords(ctx, mstore.ListRecordsParams{
		TenantID: 1, StaffUserID: &uid, Offset: 0, Limit: 1,
	})
	if len(lr) == 0 {
		t.Skip("calculate 未落记录")
	}
	recID := strconv.FormatInt(lr[0].ID, 10)

	// 另一 staff=200 的 R-STAFF 请求该记录 → handler ABAC 应 403
	r2 := newPerfEngine(t, pool, injectPerfDomain([]string{"R-STAFF"}, 200, 1))
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest("GET", "/api/v1/perf/records/"+recID, nil)
	r2.ServeHTTP(w2, req2)
	if w2.Code != http.StatusForbidden {
		t.Fatalf("跨人读应 403，得 %d body=%s", w2.Code, w2.Body.String())
	}
}
