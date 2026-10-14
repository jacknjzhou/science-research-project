package p

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

// 手工把数据域塞进 context（M0 阶段鉴权中间件尚未接入，见任务9）
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Next()
}

func newTestEngine(t *testing.T) *gin.Engine {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomain)
	// Task 12 起 Register 不再自带 /api/v1 前缀，改由调用方分组提供，整路径仍为 /api/v1/apply/...
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool))
	return e
}

func TestListApplications_Endpoint(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/applications?page=1&size=20", nil))
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
	if env.Code != 0 || env.Data.Total != 2 || len(env.Data.List) != 2 {
		t.Fatalf("列表结果不符: %+v", env)
	}
	// 字段形状对齐契约：total_budget 为 string，member_ids 为数组
	row := env.Data.List[0]
	if _, ok := row["total_budget"].(string); !ok {
		t.Fatalf("total_budget 非字符串: %#v", row["total_budget"])
	}
	if _, ok := row["member_ids"].([]any); !ok {
		t.Fatalf("member_ids 非数组: %#v", row["member_ids"])
	}
}

func TestGetApplication_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	r := httptest.NewRequest("GET", "/api/v1/apply/applications/999999", nil)
	e.ServeHTTP(w, r)
	if w.Code != http.StatusNotFound {
		t.Fatalf("期望 404，实得 %d", w.Code)
	}
}
