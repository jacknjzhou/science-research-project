package activity

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// M0 无鉴权中间件，手工塞数据域（V handler 需 tenant_id + user_id）。
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxUserID, int64(1001))
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
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool))
	return e
}

// 依赖 testdata/seed_v.sql：tenant=1 未删 2 行，A 为 DRAFT 可流转。
func TestListActivities_Endpoint(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/activities?page=1&size=20", nil))
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
		t.Fatalf("列表结果不符（期望 tenant=1 未删 2 行）: %+v", env)
	}
	row := env.Data.List[0]
	if _, ok := row["budget_amount"].(string); !ok {
		t.Fatalf("budget_amount 应为字符串: %#v", row["budget_amount"])
	}
}

func TestGetActivity_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/activities/999999", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("期望 404，实得 %d", w.Code)
	}
}

// DRAFT → SUBMITTED 合法流转；重复 submit 应命中状态机拒绝（40901）。
func TestSubmitActivity_Transition(t *testing.T) {
	e := newTestEngine(t)
	// 先建一条 DRAFT
	body := bytes.NewBufferString(`{"title":"T1 学术报告","activity_type":"LECTURE"}`)
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/activities", body)
	req.Header.Set("Content-Type", "application/json")
	e.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("创建失败 HTTP %d body=%s", w.Code, w.Body.String())
	}
	var created struct {
		Data struct {
			ID     int64  `json:"id"`
			Status string `json:"status"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &created)
	if created.Data.Status != "DRAFT" {
		t.Fatalf("新建应为 DRAFT，实得 %q", created.Data.Status)
	}

	subURL := "/api/v1/activities/" + strconv.FormatInt(created.Data.ID, 10) + "/submit"
	w2 := httptest.NewRecorder()
	e.ServeHTTP(w2, httptest.NewRequest("POST", subURL, nil))
	if w2.Code != 200 {
		t.Fatalf("submit HTTP %d body=%s", w2.Code, w2.Body.String())
	}

	// 再次 submit：已 SUBMITTED，状态机应拒
	w3 := httptest.NewRecorder()
	e.ServeHTTP(w3, httptest.NewRequest("POST", subURL, nil))
	var denied map[string]any
	_ = json.Unmarshal(w3.Body.Bytes(), &denied)
	if denied["code"] == float64(0) {
		t.Fatalf("重复 submit 不应成功: %s", w3.Body.String())
	}
}
