package sysadmin

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

func injectAdmin(c *gin.Context) {
	c.Set(auth.CtxUserID, int64(1))
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxSecurityLevel, "TOP_SECRET")
	c.Set(auth.CtxRoles, []string{"R-ADMIN"})
	c.Next()
}

// newTestEngine 需 ARK_TEST_DATABASE_URL 且库已应用 000001+000002（CI 服务里跑迁移后再测）。
func newTestEngine(t *testing.T) *gin.Engine {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	enf, err := auth.NewEnforcer("../../platform/auth/model.conf", "../../platform/auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectAdmin)
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool, enf))
	return e
}

func TestListUsers_Endpoint(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/users?page=1&size=20", nil))
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
	if env.Code != 0 || env.Data.Total < 4 || len(env.Data.List) < 4 {
		t.Fatalf("种子用户未返回: %+v", env.Data)
	}
	for _, row := range env.Data.List {
		if _, leak := row["password_hash"]; leak {
			t.Fatal("password_hash 泄漏")
		}
	}
}

func TestGetUser_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/users/999999", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("期望 404，实得 %d", w.Code)
	}
}

func TestGetMe_ReturnsCaps(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/auth/me", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Data struct {
			Roles []string `json:"roles"`
			Caps  []string `json:"caps"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if len(env.Data.Caps) == 0 {
		t.Fatalf("R-ADMIN 应有非空 caps: %v", env.Data)
	}
}
