package sysadmin

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// dbPool：仅当 ARK_TEST_DATABASE_URL 就绪时建池，否则 t.Skip（本地无库零回归）。
func dbPool(t *testing.T) *pgxpool.Pool {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设 ARK_TEST_DATABASE_URL，跳过真响应集成用例")
	}
	pool, err := pgxpool.New(context.Background(), u)
	if err != nil {
		t.Fatalf("建池失败: %v", err)
	}
	if err := pool.Ping(context.Background()); err != nil {
		pool.Close()
		t.Skipf("数据库不可达，跳过: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// 真 GET /admin/users 响应体必须符合契约 data schema，且不得外泄 password_hash。
func TestIntegration_ListUsers_RealResponseConforms(t *testing.T) {
	pool := dbPool(t)
	e, err := auth.NewEnforcer(
		envOr("ARK_AUTH_MODEL_PATH", "../../platform/auth/model.conf"),
		envOr("ARK_AUTH_POLICY_PATH", "../../platform/auth/policy.csv"),
	)
	if err != nil {
		t.Fatal(err)
	}
	h := NewHandler(pool, e)

	gin.SetMode(gin.TestMode)
	r := gin.New()
	// 中间件注入数据域，复现 middleware.Auth 放行 R-ADMIN 后的上下文（与 handler_test.go injectAdmin 同构）
	r.Use(func(c *gin.Context) {
		c.Set(auth.CtxUserID, int64(1))
		c.Set(auth.CtxTenantID, int64(1))
		c.Next()
	})
	r.GET("/admin/users", h.ListUsers)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/admin/users?page=1&size=10", nil)
	r.ServeHTTP(rec, req)

	if rec.Code != 200 {
		t.Fatalf("期望 200，实得 %d body=%s", rec.Code, rec.Body.String())
	}
	var envelope struct {
		Code int             `json:"code"`
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.Code != 0 {
		t.Fatalf("包络 code 应为 0: %d", envelope.Code)
	}

	spec := mustSpec(t)
	op := spec.Find("GET", "/admin/users")
	if op == nil {
		t.Fatal("契约缺 GET /admin/users")
	}
	schema := oapi.ResolveDataSchema(op)
	var data any
	if err := json.Unmarshal(envelope.Data, &data); err != nil {
		t.Fatal(err)
	}
	if errs := oapi.Validate(data, schema); len(errs) > 0 {
		t.Fatalf("真响应违反契约: %v", errs)
	}
	body := rec.Body.String()
	if strings.Contains(body, "password_hash") || strings.Contains(body, "PasswordHash") {
		t.Fatalf("响应泄漏口令散列: %s", body)
	}
}
