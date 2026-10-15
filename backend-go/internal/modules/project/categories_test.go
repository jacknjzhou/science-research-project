package project

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// fakeNotifier 记录触达调用并落库 sys_notification（T21 扫描测试用：去重依赖未读通知存在）。
type fakeNotifier struct {
	pool  *pgxpool.Pool
	jobID int64
	pushed []string
}

func (f *fakeNotifier) Push(ctx context.Context, tenantID, userID int64, typ, title, content, bizRef string) {
	if f.pool != nil {
		_, _ = f.pool.Exec(ctx,
			`INSERT INTO sys_notification (tenant_id, user_id, typ, title, content, biz_ref) VALUES ($1,$2,$3,$4,$5,$6)`,
			tenantID, userID, typ, title, content, bizRef)
	}
	f.pushed = append(f.pushed, typ+"|"+title)
}

// TestCategoryCRUD：创建 → 列表 → 更新 → 被引用禁删 40902 → 空闲删除 OK。
func TestCategoryCRUD(t *testing.T) {
	pool := poolForE(t)
	r := newRolesEngine(t, pool, []string{"R-MANAGER"})
	ts := time.Now().UnixNano()

	// 创建（带中检/结项窗口）
	w := ePost(r, "/api/v1/project-categories", fmt.Sprintf(
		`{"code":"CAT-%d","name":"T21 国家重点","level":"NATIONAL","mgmt_fee_pct":"10.00",
		  "midcheck_from":"2026-01-01","midcheck_to":"2026-12-31","closing_from":"2027-01-01","closing_to":"2027-06-30"}`, ts))
	if w.Code != 200 {
		t.Fatalf("建分类应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	cat := eData(t, w.Body.Bytes())
	cid := int64(cat["id"].(float64))
	if cat["mgmt_fee_pct"] != "10.00" {
		t.Fatalf("费率应 10.00，得 %v", cat["mgmt_fee_pct"])
	}
	if cat["midcheck_from"] != "2026-01-01" {
		t.Fatalf("中检窗口应 2026-01-01，得 %v", cat["midcheck_from"])
	}

	// 列表含该条
	w = eGet(r, "/api/v1/project-categories")
	if !strings.Contains(w.Body.String(), fmt.Sprintf("CAT-%d", ts)) {
		t.Fatalf("列表应含新分类：%s", w.Body.String())
	}

	// 更新（局部）
	w = ePut(r, fmt.Sprintf("/api/v1/project-categories/%d", cid), `{"name":"T21 国家重点(改)"}`)
	if w.Code != 200 {
		t.Fatalf("更新应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := eData(t, w.Body.Bytes())["name"]; got != "T21 国家重点(改)" {
		t.Fatalf("名称应更新，得 %v", got)
	}

	// 挂到测试项目 → 删除应 40902
	pid := createT21Project(t, pool, ts)
	w = ePost(r, fmt.Sprintf("/api/v1/projects/%d/category", pid), fmt.Sprintf(`{"category_id":%d}`, cid))
	if w.Code != 200 {
		t.Fatalf("挂分类应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	w = eDelete(r, fmt.Sprintf("/api/v1/project-categories/%d", cid))
	if w.Code != http.StatusConflict {
		t.Fatalf("被引用删除应 409，得 %d body=%s", w.Code, w.Body.String())
	}
	// 解挂后可删
	if _, err := pool.Exec(testCtx(), `UPDATE e_project SET category_id=NULL WHERE id=$1`, pid); err != nil {
		t.Fatalf("解挂: %v", err)
	}
	w = eDelete(r, fmt.Sprintf("/api/v1/project-categories/%d", cid))
	if w.Code != 200 {
		t.Fatalf("空闲删除应 200，得 %d", w.Code)
	}
	t.Cleanup(func() {
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_project WHERE id=$1`, pid)
	})
}

// TestScanWarnings：中检窗口内项目 → 扫描触发 WARNING 通知（fake Notifier 记录）；幂等去重。
func TestScanWarnings(t *testing.T) {
	pool := poolForE(t)
	ts := time.Now().UnixNano()
	// 窗口覆盖今天：midcheck_from = 今天-1 天，midcheck_to = 今天+30 天（from-15d <= today <= to）
	fn := &fakeNotifier{pool: pool}
	h := NewHandler(pool)
	h.nt = fn
	r := engineWithHandler(t, h)

	pid := createT21Project(t, pool, ts)
	var cid int64
	if err := pool.QueryRow(testCtx(), `
		INSERT INTO e_project_category (tenant_id, code, name, mgmt_fee_pct, midcheck_from, midcheck_to)
		VALUES (1, $1, 'T21 扫描分类', 0, CURRENT_DATE - 1, CURRENT_DATE + 30) RETURNING id`,
		fmt.Sprintf("CAT-S%d", ts)).Scan(&cid); err != nil {
		t.Fatalf("建分类: %v", err)
	}
	if _, err := pool.Exec(testCtx(), `UPDATE e_project SET category_id=$1 WHERE id=$2`, cid, pid); err != nil {
		t.Fatalf("挂分类: %v", err)
	}
	t.Cleanup(func() {
		_, _ = pool.Exec(testCtx(), `DELETE FROM sys_notification WHERE title LIKE 'MIDCHECK_DUE：T21 扫描项目%'`)
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_project WHERE id=$1`, pid)
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_project_category WHERE id=$1`, cid)
	})

	// 首次扫描 → 触达 1 条 MIDCHECK_DUE
	w := ePost(r, "/api/v1/project-categories/scan-warnings", `{}`)
	if w.Code != 200 {
		t.Fatalf("扫描应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	res := eData(t, w.Body.Bytes())
	if res["sent"].(float64) < 1 {
		t.Fatalf("应触达 ≥1 条，得 %v", res)
	}
	if len(fn.pushed) == 0 || !strings.Contains(fn.pushed[0], "MIDCHECK_DUE") {
		t.Fatalf("应产生 MIDCHECK_DUE 触达: %v", fn.pushed)
	}
	// 二次扫描 → 去重（未读通知存在）不再发
	before := len(fn.pushed)
	w = ePost(r, "/api/v1/project-categories/scan-warnings", `{}`)
	if w.Code != 200 {
		t.Fatalf("二次扫描应 200，得 %d", w.Code)
	}
	if len(fn.pushed) != before {
		t.Fatalf("二次扫描应去重不发，before=%d after=%d", before, len(fn.pushed))
	}
}

// createT21Project 建 T21 测试项目。
func createT21Project(t *testing.T, pool *pgxpool.Pool, ts int64) int64 {
	t.Helper()
	var pid int64
	if err := pool.QueryRow(testCtx(), `
		INSERT INTO e_project (tenant_id, status, creator_id, application_id, title, project_type, pi_user_id,
			member_ids, legal_entity_id, start_date, end_date, total_budget, health_score, risk_level, security_level)
		VALUES (1,'EXECUTING',1001,0,$1,'NSFC',1001,'[]'::jsonb,1,
			CURRENT_DATE - INTERVAL '10 day', CURRENT_DATE + INTERVAL '200 day','100000.00',80,'LOW','INTERNAL')
		RETURNING id`, fmt.Sprintf("T21 扫描项目 %d", ts)).Scan(&pid); err != nil {
		t.Fatalf("建项目: %v", err)
	}
	return pid
}

func ePut(r *gin.Engine, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest("PUT", path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	return w
}

func eDelete(r *gin.Engine, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("DELETE", path, nil))
	return w
}

// engineWithHandler 指定 Handler 实例的引擎（注入 fake Notifier 用）。
func engineWithHandler(t *testing.T, h *Handler) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("uid", int64(2001))
		c.Set("tenant_id", int64(1))
		c.Set("roles", []string{"R-MANAGER"})
		c.Next()
	})
	api := r.Group("/api/v1")
	Register(api, h)
	return r
}

func eGet(r *gin.Engine, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
	return w
}
