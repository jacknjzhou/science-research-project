package project

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/eplugger/ark/internal/platform/approval"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func testCtx() context.Context { return context.Background() }

// poolForE ARK_TEST_DATABASE_URL 缺省 SKIP。
func poolForE(t *testing.T) *pgxpool.Pool {
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

// newRolesEngine 带 roles 注入的测试引擎（T19 两级审核需要区分首审/终审角色）。
func newRolesEngine(t *testing.T, pool *pgxpool.Pool, roles []string) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("uid", int64(2001))
		c.Set("tenant_id", int64(1))
		c.Set("roles", roles)
		c.Next()
	})
	api := r.Group("/api/v1")
	Register(api, NewHandler(pool))
	return r
}

func ePost(r *gin.Engine, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	return w
}

// eData 解析信封 data。
func eData(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var env struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("data 解析失败: %v body=%s", err, string(body))
	}
	return env.Data
}

// changeStatus 直查变更单状态（无 HTTP 读端点）。
func changeStatus(t *testing.T, pool *pgxpool.Pool, id int64) string {
	t.Helper()
	var st string
	if err := pool.QueryRow(testCtx(), `SELECT status FROM e_change_request WHERE id=$1`, id).Scan(&st); err != nil {
		t.Fatalf("查变更单: %v", err)
	}
	return st
}

// seedTwoStepFixture 清理旧数据 + 建 1 个测试项目 + 3 张 SUBMITTED 变更单，返回 (projectID, changeIDs)。
func seedTwoStepFixture(t *testing.T, pool *pgxpool.Pool) (int64, []int64) {
	t.Helper()
	ts := time.Now().UnixNano()
	title := fmt.Sprintf("T19 两级审核项目 %d", ts)
	_, _ = pool.Exec(testCtx(), `DELETE FROM sys_approval_log WHERE biz_type='CHANGE_REQUEST' AND biz_id IN
		(SELECT id FROM e_change_request WHERE code LIKE 'T19-CR-%')`)
	_, _ = pool.Exec(testCtx(), `DELETE FROM e_change_request WHERE code LIKE 'T19-CR-%'`)
	_, _ = pool.Exec(testCtx(), `DELETE FROM e_project WHERE title LIKE 'T19 两级审核项目 %'`)

	var pid int64
	if err := pool.QueryRow(testCtx(), `
		INSERT INTO e_project (tenant_id, status, creator_id, application_id, title, project_type, pi_user_id,
			member_ids, legal_entity_id, start_date, end_date, total_budget, health_score, risk_level, security_level)
		VALUES (1,'EXECUTING',1001,0,$1,'NSFC',1001,'[]'::jsonb,1,
			CURRENT_DATE - INTERVAL '10 day', CURRENT_DATE + INTERVAL '200 day','100000.00',80,'LOW','INTERNAL')
		RETURNING id`, title).Scan(&pid); err != nil {
		t.Fatalf("建项目: %v", err)
	}
	ids := make([]int64, 0, 3)
	for i := 1; i <= 3; i++ {
		var cid int64
		if err := pool.QueryRow(testCtx(), `
			INSERT INTO e_change_request (code, tenant_id, status, creator_id, project_id, change_type, reason)
			VALUES ($1, 1, 'SUBMITTED', 1001, $2, 'BUDGET', 'T19 测试变更')
			RETURNING id`,
			fmt.Sprintf("T19-CR-%d-%d", ts, i), pid).Scan(&cid); err != nil {
			t.Fatalf("建变更单: %v", err)
		}
		ids = append(ids, cid)
	}
	t.Cleanup(func() {
		_, _ = pool.Exec(testCtx(), `DELETE FROM sys_approval_log WHERE biz_type='CHANGE_REQUEST' AND biz_id = ANY($1)`, ids)
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_change_request WHERE id = ANY($1)`, ids)
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_project WHERE id=$1`, pid)
	})
	return pid, ids
}

// TestChangeTwoStep：两级链路（env on）——R-STAFF 403 → R-MANAGER 首审 APPROVING →
// R-MANAGER 终审 403 → R-LEADER 终审 EFFECTIVE；流水 step=1/2。
func TestChangeTwoStep(t *testing.T) {
	pool := poolForE(t)
	t.Setenv("ARK_APPROVAL_TWOSTEP", "on")
	pid, ids := seedTwoStepFixture(t, pool)
	cid := ids[0]

	mgr := newRolesEngine(t, pool, []string{"R-MANAGER"})
	ldr := newRolesEngine(t, pool, []string{"R-LEADER"})
	staff := newRolesEngine(t, pool, []string{"R-STAFF"})

	path := fmt.Sprintf("/api/v1/project/%d/change-request/%d/approve", pid, cid)
	// 无角色 → 403
	if w := ePost(staff, path, `{}`); w.Code != http.StatusForbidden {
		t.Fatalf("R-STAFF 首审应 403，得 %d body=%s", w.Code, w.Body.String())
	}
	// 首审 → APPROVING
	if w := ePost(mgr, path, `{"comment":"学院同意"}`); w.Code != 200 {
		t.Fatalf("首审应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := changeStatus(t, pool, cid); got != "APPROVING" {
		t.Fatalf("首审后应 APPROVING，得 %s", got)
	}
	// R-MANAGER 再审（终审角色不符）→ 403
	if w := ePost(mgr, path, `{}`); w.Code != http.StatusForbidden {
		t.Fatalf("R-MANAGER 终审应 403，得 %d body=%s", w.Code, w.Body.String())
	}
	// 终审 → EFFECTIVE
	if w := ePost(ldr, path, `{"comment":"学校同意"}`); w.Code != 200 {
		t.Fatalf("终审应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := changeStatus(t, pool, cid); got != "EFFECTIVE" {
		t.Fatalf("终审后应 EFFECTIVE，得 %s", got)
	}
	// 已生效再审 → 409
	if w := ePost(ldr, path, `{}`); w.Code != http.StatusConflict {
		t.Fatalf("已生效再审应 409，得 %d", w.Code)
	}
	// 流水：step=1(APPROVE) + step=2(APPROVE)
	logs, err := approval.New(pool).ListLogs(testCtx(), 1, "CHANGE_REQUEST", cid)
	if err != nil {
		t.Fatalf("查流水: %v", err)
	}
	if len(logs) != 2 {
		t.Fatalf("应 2 条流水，得 %d", len(logs))
	}
	if logs[0].Step != 1 || logs[1].Step != 2 || logs[1].Comment != "学校同意" {
		t.Fatalf("流水不符: %+v", logs)
	}
}

// TestChangeSingleStep：默认开关 off——一步 EFFECTIVE（行为不变），流水 step=1。
func TestChangeSingleStep(t *testing.T) {
	pool := poolForE(t)
	t.Setenv("ARK_APPROVAL_TWOSTEP", "off")
	pid, ids := seedTwoStepFixture(t, pool)
	cid := ids[1]
	staff := newRolesEngine(t, pool, []string{"R-STAFF"})
	path := fmt.Sprintf("/api/v1/project/%d/change-request/%d/approve", pid, cid)
	if w := ePost(staff, path, `{}`); w.Code != 200 {
		t.Fatalf("单级模式 R-STAFF 应可直批，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := changeStatus(t, pool, cid); got != "EFFECTIVE" {
		t.Fatalf("单级直批后应 EFFECTIVE，得 %s", got)
	}
	logs, err := approval.New(pool).ListLogs(testCtx(), 1, "CHANGE_REQUEST", cid)
	if err != nil || len(logs) != 1 || logs[0].Step != 1 {
		t.Fatalf("单级流水应 1 条 step=1，得 %+v err=%v", logs, err)
	}
}

// TestChangeBatch：批量审批——R-ADMIN 直通 3 张（2 有效 + 1 不存在）→ ok=2。
func TestChangeBatch(t *testing.T) {
	pool := poolForE(t)
	t.Setenv("ARK_APPROVAL_TWOSTEP", "on")
	_, ids := seedTwoStepFixture(t, pool)
	admin := newRolesEngine(t, pool, []string{"R-ADMIN"})
	w := ePost(admin, "/api/v1/projects/approve-batch",
		fmt.Sprintf(`{"ids":[%d,%d,999999],"action":"APPROVE","comment":"批量"}`, ids[1], ids[2]))
	if w.Code != 200 {
		t.Fatalf("批量应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	res := eData(t, w.Body.Bytes())
	if res["total"].(float64) != 3 || res["ok"].(float64) != 2 {
		t.Fatalf("应 total=3 ok=2，得 %v", res)
	}
	results := res["results"].([]any)
	if results[2].(map[string]any)["ok"].(bool) {
		t.Fatalf("不存在变更单应失败，得 %v", results[2])
	}
	// R-ADMIN 直通豁免角色校验，但两级状态机仍逐步推进：首次批量 → APPROVING
	if got := changeStatus(t, pool, ids[1]); got != "APPROVING" {
		t.Fatalf("首次批量后应 APPROVING，得 %s", got)
	}
	// 第二次批量 → EFFECTIVE
	w = ePost(admin, "/api/v1/projects/approve-batch",
		fmt.Sprintf(`{"ids":[%d],"action":"APPROVE"}`, ids[1]))
	if w.Code != 200 {
		t.Fatalf("二次批量应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := changeStatus(t, pool, ids[1]); got != "EFFECTIVE" {
		t.Fatalf("二次批量后应 EFFECTIVE，得 %s", got)
	}
	// 空 ids → 400
	if w := ePost(admin, "/api/v1/projects/approve-batch", `{"ids":[],"action":"APPROVE"}`); w.Code != 400 {
		t.Fatalf("空 ids 应 400，得 %d", w.Code)
	}
}
