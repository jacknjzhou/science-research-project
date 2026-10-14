package internal

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// buildForTest 装配一个真实引擎：真 Enforcer（任务 9 的 model.conf/policy.csv）、
// 真契约目录、以及一个惰性非 nil Pool。
func buildForTest(t *testing.T) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)

	cfg := config.Load()
	cfg.JWTSecret = "test-secret"
	// go test ./internal/ 的工作目录 = backend-go/internal，
	// Casbin 文件相对该目录为 platform/auth/*，design 相对该目录为 ../../design。
	cfg.AuthModelPath = "platform/auth/model.conf"
	cfg.AuthPolicyPath = "platform/auth/policy.csv"

	enf, err := auth.NewEnforcer(cfg.AuthModelPath, cfg.AuthPolicyPath)
	if err != nil {
		t.Fatalf("NewEnforcer: %v", err)
	}

	spec, err := oapi.LoadDir(designDirForTest())
	if err != nil {
		t.Fatalf("LoadDir: %v", err)
	}

	// 关键：Build 以 `if d.Pool != nil` 守卫 P 竖切注册。测试必须提供非 nil Pool，
	// 否则 GET /api/v1/apply/applications 根本不会注册，请求会落到 passthrough NoRoute
	// 命中契约返回 200 code:0 —— 401 用例就会失败（拿到 200）。
	// pgxpool.New 惰性创建、不会真正连库；Auth 中间件在任何 handler 触达 Pool 之前
	// 就以 401 短路（无 Bearer 头），故本组用例无需真实数据库。
	pool, err := pgxpool.New(context.Background(), "postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable")
	if err != nil {
		t.Fatalf("pgxpool.New: %v", err)
	}
	t.Cleanup(pool.Close)

	// Redis 传 nil 安全：Idempotency 对 GET/HEAD/OPTIONS 直接放行，绝不触碰 Redis。
	return Build(RouterDeps{Cfg: cfg, Pool: pool, Enforcer: enf, Spec: spec})
}

func designDirForTest() string {
	// go test 的工作目录是包目录 backend-go/internal/，向上两级即到仓库根，再入 design。
	return "../../design"
}

func TestBuild_HealthzPublic(t *testing.T) {
	e := buildForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("healthz=%d want 200", rec.Code)
	}
	if !bytes.Contains(rec.Body.Bytes(), []byte(`"ok":true`)) {
		t.Fatalf("healthz body=%s", rec.Body.String())
	}
}

func TestBuild_LoginIssuesToken(t *testing.T) {
	e := buildForTest(t)
	body, _ := json.Marshal(map[string]string{"username": "ark", "password": "ark"})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("login=%d body=%s", rec.Code, rec.Body.String())
	}
	var env struct {
		Code int `json:"code"`
		Data struct {
			AccessToken string `json:"access_token"`
		} `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	if env.Code != 0 || env.Data.AccessToken == "" {
		t.Fatalf("token empty env=%+v", env)
	}
	// 签发的令牌应可被解析回带数据域的 claims（ark → uid=1, tenant=1, roles 含 R-STAFF/R-MANAGER）。
	claims, err := auth.ParseToken("test-secret", env.Data.AccessToken)
	if err != nil {
		t.Fatalf("令牌解析失败: %v", err)
	}
	if claims.UserID != 1 || claims.TenantID != 1 || claims.SecurityLevel != "INTERNAL" {
		t.Fatalf("claims 数据域不符: %+v", claims)
	}
}

func TestBuild_ProtectedNoToken401(t *testing.T) {
	e := buildForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/apply/applications", nil)
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("no-token=%d want 401 body=%s", rec.Code, rec.Body.String())
	}
}
