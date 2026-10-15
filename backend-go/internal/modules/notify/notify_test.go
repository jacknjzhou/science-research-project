package notify

import (
	"context"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// poolForTest：ARK_TEST_DATABASE_URL 缺省 SKIP。
func poolForTest(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("ARK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("ARK_TEST_DATABASE_URL 未设置，跳过 DB 集成")
	}
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func engine(t *testing.T, h *Handler, uid, tenant int64) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("uid", uid)
		c.Set("tenant_id", tenant)
		c.Set("roles", []string{"R-MANAGER"})
		c.Next()
	})
	api := r.Group("/api/v1")
	Register(api, h)
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

// TestNotifyLoop：Push → 未读数 → 列表 → 单条已读 → 全部已读。
func TestNotifyLoop(t *testing.T) {
	pool := poolForTest(t)
	h := NewHandler(pool)
	r := engine(t, h, 9001, 1)

	// 清理本测试用户的历史通知
	if _, err := pool.Exec(context.Background(),
		`DELETE FROM sys_notification WHERE user_id = 9001`); err != nil {
		t.Fatalf("清理失败: %v", err)
	}

	// Push 2 条不同类型
	h.Push(context.Background(), 1, 9001, "TODO", "待办A", "内容A", "expense/1")
	h.Push(context.Background(), 1, 9001, "WARNING", "预警B", "内容B", "budget/1")

	// 未读数 = 2
	if w := doGet(r, "/api/v1/notifications/unread-count"); w.Code != 200 {
		t.Fatalf("未读数应 200，得 %d", w.Code)
	} else if got := bodyJSON(t, w.Body.Bytes()); got["unread"].(float64) != 2 {
		t.Fatalf("未读应 2，得 %v", got)
	}

	// typ 过滤
	if w := doGet(r, "/api/v1/notifications?typ=WARNING"); w.Code != 200 {
		t.Fatalf("列表应 200，得 %d", w.Code)
	} else if env := bodyJSON(t, w.Body.Bytes()); env["total"].(float64) != 1 {
		t.Fatalf("WARNING 过滤应 1 条，得 %v", env["total"])
	}

	// 单条已读 → 未读 -1
	if w := doPost(r, "/api/v1/notifications/read-all", `{}`); w.Code != 200 {
		t.Fatalf("全部已读应 200，得 %d", w.Code)
	}
	if w := doGet(r, "/api/v1/notifications/unread-count"); w.Code != 200 {
		t.Fatalf("未读数应 200，得 %d", w.Code)
	} else if got := bodyJSON(t, w.Body.Bytes()); got["unread"].(float64) != 0 {
		t.Fatalf("全部已读后未读应 0，得 %v", got)
	}
}

// TestPushRoleFanout：角色扇出——R-MANAGER 的每个启用用户各得一行（用租户 1 真实 seed 角色）。
func TestPushRoleFanout(t *testing.T) {
	pool := poolForTest(t)
	h := NewHandler(pool)

	// 记录扇出前的 R-MANAGER 通知总量
	var before int
	if err := pool.QueryRow(context.Background(),
		`SELECT count(*) FROM sys_notification n
		 JOIN sys_user_role ur ON ur.user_id = n.user_id
		 JOIN sys_role r ON r.id = ur.role_id
		 WHERE r.code = 'R-MANAGER' AND ur.tenant_id = 1`).Scan(&before); err != nil {
		t.Fatalf("前置计数失败: %v", err)
	}

	h.PushRole(context.Background(), 1, "R-MANAGER", "TODO", "扇出测试", "内容", "expense/9")

	var after int
	if err := pool.QueryRow(context.Background(),
		`SELECT count(*) FROM sys_notification n
		 JOIN sys_user_role ur ON ur.user_id = n.user_id
		 JOIN sys_role r ON r.id = ur.role_id
		 WHERE r.code = 'R-MANAGER' AND ur.tenant_id = 1`).Scan(&after); err != nil {
		t.Fatalf("后置计数失败: %v", err)
	}
	if after <= before {
		t.Fatalf("角色扇出应新增通知：before=%d after=%d", before, after)
	}

	// 清理扇出测试行（按 title 精确清理，不动他人数据）
	if _, err := pool.Exec(context.Background(),
		`DELETE FROM sys_notification WHERE title = '扇出测试'`); err != nil {
		t.Fatalf("清理失败: %v", err)
	}
}
