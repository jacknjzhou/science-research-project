package dataops

import (
	"context"
	"encoding/json"
	"io"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func strReader(s string) io.Reader { return strings.NewReader(s) }

func poolForTest(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("ARK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("ARK_TEST_DATABASE_URL 未设置，跳过 DB 集成")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatalf("parse dsn: %v", err)
	}
	// 全量并行跑测试时 PG 连接数紧张：测试池收紧到 2。
	cfg.MaxConns = 2
	pool, err := pgxpool.NewWithConfig(context.Background(), cfg)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func runSeed(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "testdata", "seed_dash.sql"))
	if err != nil {
		t.Fatalf("seed 文件读取失败: %v", err)
	}
	if _, err := pool.Exec(context.Background(), string(b)); err != nil {
		t.Fatalf("seed 执行失败: %v", err)
	}
}

func dashboardJSON(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var env struct {
		Code int             `json:"code"`
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("响应非 JSON: %v body=%s", err, string(body))
	}
	if env.Code != 0 {
		t.Fatalf("业务码应 0，得 %d body=%s", env.Code, string(body))
	}
	var m map[string]any
	if err := json.Unmarshal(env.Data, &m); err != nil {
		t.Fatalf("data 解析失败: %v", err)
	}
	return m
}

// TestFundingDashboard：seed_dash（租户 7）场景聚合数值断言。
// seed：预算 10 万（EXECUTING）；已认领到账 4 万（claimed_at=now 本年）；无报销 → used=0。
func TestFundingDashboard(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("uid", int64(1))
		c.Set("tenant_id", int64(7))
		c.Set("roles", []string{"R-MANAGER"})
		c.Next()
	})
	Register(r.Group("/api/v1"), NewHandler(pool))

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/dashboard/funding", nil))
	if w.Code != 200 {
		t.Fatalf("应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	m := dashboardJSON(t, w.Body.Bytes())

	if m["totalBudget"] != "100000.00" {
		t.Fatalf("totalBudget 应 100000.00，得 %v", m["totalBudget"])
	}
	if m["yearUsed"] != "0.00" {
		t.Fatalf("yearUsed 应 0.00（无报销），得 %v", m["yearUsed"])
	}
	if m["executionRate"].(float64) != 0 {
		t.Fatalf("执行率应 0，得 %v", m["executionRate"])
	}
	if m["yearIncome"] != "40000.00" {
		t.Fatalf("yearIncome 应 40000.00，得 %v", m["yearIncome"])
	}
	// 热力图：法人 1 一行
	heat, ok := m["deptHeatmap"].([]any)
	if !ok || len(heat) != 1 {
		t.Fatalf("deptHeatmap 应 1 行，得 %v", m["deptHeatmap"])
	}
	// 三预警桶存在
	alerts, ok := m["alerts"].(map[string]any)
	if !ok || alerts["pre"] == nil || alerts["during"] == nil || alerts["post"] == nil {
		t.Fatalf("alerts 应含 pre/during/post，得 %v", alerts)
	}
}
