package sysadmin

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
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

func TestHashPassword_Verifiable(t *testing.T) {
	h, err := hashPassword("Admin@123456")
	if err != nil {
		t.Fatal(err)
	}
	if h == "Admin@123456" || len(h) < 50 {
		t.Fatalf("哈希异常: %q", h)
	}
	if bcrypt.CompareHashAndPassword([]byte(h), []byte("Admin@123456")) != nil {
		t.Fatal("bcrypt 往返校验失败")
	}
	if bcrypt.CompareHashAndPassword([]byte(h), []byte("wrong")) == nil {
		t.Fatal("错误口令竟通过")
	}
}

func nopCloserString(s string) io.ReadCloser { return io.NopCloser(strings.NewReader(s)) }

func TestCreateUser_DuplicateUsername409(t *testing.T) {
	e := newTestEngine(t)
	body := `{"username":"tester1","real_name":"测试员","password":"Test@123456","security_level":"INTERNAL","roles":["R-STAFF"]}`
	for i := 0; i < 2; i++ {
		w := httptest.NewRecorder()
		r := httptest.NewRequest("POST", "/api/v1/admin/users", nil)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Idempotency-Key", "itest-create-1")
		r.Body = nopCloserString(body)
		e.ServeHTTP(w, r)
		if i == 0 && w.Code != 200 {
			t.Fatalf("首次创建应 200，实得 %d body=%s", w.Code, w.Body.String())
		}
		if i == 1 && w.Code != http.StatusConflict {
			t.Fatalf("重复用户名应 409，实得 %d", w.Code)
		}
	}
}

func TestListRoles_ReturnsSeededEight(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/roles", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Data struct {
			List []map[string]any `json:"list"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if len(env.Data.List) < 8 {
		t.Fatalf("8 基础角色未返回: %d", len(env.Data.List))
	}
}

func TestAssignRevokeRole(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/api/v1/admin/users/1/roles", nil)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Idempotency-Key", "itest-assign-1")
	r.Body = nopCloserString(`{"role_id":8}`)
	e.ServeHTTP(w, r)
	if w.Code != 200 {
		t.Fatalf("幂等再授权应 200，实得 %d body=%s", w.Code, w.Body.String())
	}
}
