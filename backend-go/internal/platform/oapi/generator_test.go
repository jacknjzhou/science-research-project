package oapi

import (
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

func TestPassthrough_GeneratesEnvelope(t *testing.T) {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../../../design"
	}
	spec, err := LoadDir(d)
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID())
	e.NoRoute(Passthrough(spec))

	// 选一条契约里存在、但未手工实现的动作路由（示例：提交申报）
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/apply/applications/1/submit", nil))
	if w.Code != 200 {
		t.Fatalf("passthrough 期望 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if !containsStr(w.Body.String(), "\"code\":0") || !containsStr(w.Body.String(), "\"traceId\":") {
		t.Fatalf("passthrough 包络不合规: %s", w.Body.String())
	}
}

func TestPassthrough_ListPageParams(t *testing.T) {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../../../design"
	}
	spec, err := LoadDir(d)
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID())
	e.NoRoute(Passthrough(spec))

	// GET 列表路由：应生成 PageResult（含 list），并按查询串落地 page/size
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/applications?page=2&size=5", nil))
	if w.Code != 200 {
		t.Fatalf("passthrough 期望 200，得 %d body=%s", w.Code, w.Body.String())
	}
	body := w.Body.String()
	if !containsStr(body, "\"code\":0") || !containsStr(body, "\"list\"") {
		t.Fatalf("passthrough 列表包络不合规: %s", body)
	}
	if !containsStr(body, "\"page\":2") || !containsStr(body, "\"size\":5") {
		t.Fatalf("page/size 应按查询串落地: %s", body)
	}
}

func TestPassthrough_UnknownRoute(t *testing.T) {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../../../design"
	}
	spec, err := LoadDir(d)
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID())
	e.NoRoute(Passthrough(spec))

	// 契约里没有的路由应 404 + code:40401
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/nope/nothing", nil))
	if !containsStr(w.Body.String(), "\"code\":40401") {
		t.Fatalf("未定义路由期望 code:40401，得 body=%s", w.Body.String())
	}
}

func containsStr(s, sub string) bool { return len(s) >= len(sub) && indexOfStr(s, sub) >= 0 }
func indexOfStr(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
