package expertreview

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/eplugger/ark/internal/modules/output"
	"github.com/eplugger/ark/internal/modules/project"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// injectDomain：M0 测试里手工塞数据域（N handler 需 tenant_id + user_id 作 creator/actor）。
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxUserID, int64(100))
	c.Next()
}

// runSeedN 幂等清 N 域表（先子后父保外键顺序），再执行 testdata/seed_n.sql；
// seed 提供 4 位专家（含 PI user_id=100、"承担单位" org_name）供抽取回避用例反查。
func runSeedN(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	for _, trunc := range []string{
		`DELETE FROM n_review_fee WHERE tenant_id IN (1,2)`,
		`DELETE FROM n_review_score WHERE tenant_id IN (1,2)`,
		`DELETE FROM n_review_invitation WHERE tenant_id IN (1,2)`,
		`DELETE FROM n_review_task WHERE tenant_id IN (1,2)`,
		`DELETE FROM n_expert_group WHERE tenant_id IN (1,2)`,
		`DELETE FROM n_expert WHERE tenant_id IN (1,2)`,
	} {
		if _, err := pool.Exec(ctx, trunc); err != nil {
			t.Fatalf("清理失败 %q: %v", trunc, err)
		}
	}
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "testdata", "seed_n.sql"))
	if err != nil {
		t.Fatalf("seed_n 读取失败: %v", err)
	}
	if _, err := pool.Exec(ctx, string(b)); err != nil {
		t.Fatalf("seed_n 执行失败: %v", err)
	}
}

// newTestEngine：DB-gated。缺 ARK_TEST_DATABASE_URL → SKIP。注入 seed_n.sql 后可跑。
// N handler 需注入 E/R handler（回写依赖），此处一并构造共享同一 pool。
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
	runSeedN(t, context.Background(), pool)
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomain)
	api := e.Group("/api/v1")
	projH := project.NewHandler(pool)
	outH := output.NewHandler(pool)
	Register(api, NewHandler(pool, projH, outH))
	return e
}

func TestListExperts_ConformsToContract(t *testing.T) {
	e := newTestEngine(t)
	spec := mustSpec(t)
	op := spec.Find("GET", "/experts")
	dataSchema := oapi.ResolveDataSchema(op)

	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/experts?page=1&size=20", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if errs := oapi.Validate(env["data"], dataSchema); len(errs) > 0 {
		t.Fatalf("响应 data 不合契约: %v", errs)
	}
}

func TestGetExpert_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/experts/999999999", nil))
	if w.Code != 404 {
		t.Fatalf("期望 404，实得 %d body=%s", w.Code, w.Body.String())
	}
}

// TestDrawExperts_ExcludesAvoid 端到端验证抽取回避：建 OTHER 评审（避开 seed 中 user_id=100
// 的 PI 镜像专家与"承担单位"），固定 seed 抽取，读 detail 断言回避者不入名单。不触 E/R 回写。
func TestDrawExperts_ExcludesAvoid(t *testing.T) {
	e := newTestEngine(t)

	// 建单
	createBody := `{"biz_type":"OTHER","title":"抽取冒烟","plan_count":2,"draw_rule":{"field_tags":["物理"],"exclude_user_ids":[100],"exclude_orgs":["承担单位"]}}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/reviews", strings.NewReader(createBody))
	req.Header.Set("Content-Type", "application/json")
	e.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("建评审失败 HTTP %d body=%s", w.Code, w.Body.String())
	}
	var created struct {
		Data struct {
			ID int64 `json:"id"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &created)
	rid := created.Data.ID
	if rid == 0 {
		t.Fatal("建单未返回 id")
	}

	// 抽取（固定 seed 复现）
	w = httptest.NewRecorder()
	req = httptest.NewRequest("POST", "/api/v1/reviews/"+strconv.FormatInt(rid, 10)+"/draw", strings.NewReader(`{"seed":42}`))
	req.Header.Set("Content-Type", "application/json")
	e.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("抽取失败 HTTP %d body=%s", w.Code, w.Body.String())
	}

	// 读 detail 校验回避者未入名单
	w = httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/reviews/"+strconv.FormatInt(rid, 10)+"/detail", nil))
	if w.Code != 200 {
		t.Fatalf("detail 失败 HTTP %d body=%s", w.Code, w.Body.String())
	}
	if strings.Contains(w.Body.String(), `"expert_name":"PI镜像专家"`) ||
		strings.Contains(w.Body.String(), `"expert_name":"承担单位专家"`) {
		t.Fatalf("回避对象漏入名单: %s", w.Body.String())
	}
}
