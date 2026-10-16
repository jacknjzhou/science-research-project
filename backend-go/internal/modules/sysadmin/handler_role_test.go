package sysadmin

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

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// newRoleEngine 与 newDictEngine 同款（角色注入 + Casbin 判权模拟）。
func newRoleEngine(t *testing.T, roles []string) *gin.Engine {
	t.Helper()
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { pool.Close() })
	enf, err := auth.NewEnforcer("../../platform/auth/model.conf", "../../platform/auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), func(c *gin.Context) {
		c.Set(auth.CtxUserID, int64(1))
		c.Set(auth.CtxTenantID, int64(1))
		c.Set(auth.CtxSecurityLevel, "TOP_SECRET")
		c.Set(auth.CtxRoles, roles)
		allowed := false
		for _, role := range roles {
			if ok, _ := enf.Enforce(role, c.Request.URL.Path, c.Request.Method); ok {
				allowed = true
				break
			}
		}
		if !allowed {
			httpx.WriteErr(c, http.StatusForbidden, 40301, "无权限")
			c.Abort()
			return
		}
		c.Next()
	})
	Register(e.Group("/api/v1"), NewHandler(pool, enf))
	return e
}

func roleEnv(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var env struct {
		Code int            `json:"code"`
		Data map[string]any `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	return env.Data
}

// TestRoleCRUD_Lifecycle 覆盖：新建/改名/删除自定义角色 + 内置删 409 + 重码 409。
func TestRoleCRUD_Lifecycle(t *testing.T) {
	admin := newRoleEngine(t, []string{"R-ADMIN"})
	code := fmt.Sprintf("R-TST-%d", time.Now().UnixNano()%100000000)

	// 1) 新建
	w := httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/admin/roles",
		strings.NewReader(`{"code":"`+code+`","name":"测试角色"}`)))
	if w.Code != http.StatusOK {
		t.Fatalf("新建角色应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	d := roleEnv(t, w)
	id := int64(d["id"].(float64))
	if d["is_builtin"] != false {
		t.Fatalf("自定义角色 is_builtin 应 false: %v", d)
	}

	// 2) 重码 409
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/admin/roles",
		strings.NewReader(`{"code":"`+code+`","name":"重复角色"}`)))
	if w.Code != http.StatusConflict {
		t.Fatalf("重码应 409，得 %d", w.Code)
	}

	// 3) 改名
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("PUT", fmt.Sprintf("/api/v1/admin/roles/%d", id),
		strings.NewReader(`{"name":"测试角色·改"}`)))
	if got := roleEnv(t, w)["name"]; got != "测试角色·改" {
		t.Fatalf("改名失败: %v", w.Body.String())
	}

	// 4) 删除（解绑状态）→ 200
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("DELETE", fmt.Sprintf("/api/v1/admin/roles/%d", id), nil))
	if w.Code != http.StatusOK {
		t.Fatalf("删除自定义角色应 200，得 %d body=%s", w.Code, w.Body.String())
	}

	// 5) 内置角色删 409（R-STAFF id 取目录）
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/roles", nil))
	list := roleEnv(t, w)["list"].([]any)
	var staffID float64
	for _, it := range list {
		row := it.(map[string]any)
		if row["code"] == "R-STAFF" {
			staffID = row["id"].(float64)
		}
	}
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("DELETE", fmt.Sprintf("/api/v1/admin/roles/%d", int64(staffID)), nil))
	if w.Code != http.StatusConflict {
		t.Fatalf("删除内置角色应 409，得 %d", w.Code)
	}
}
