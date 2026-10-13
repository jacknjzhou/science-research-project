package httpx

import (
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestWriteOK_EnvelopeShape(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(TraceID())
	r.GET("/x", func(c *gin.Context) { WriteOK(c, gin.H{"hello": "world"}) })

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", "/x", nil))

	if w.Header().Get("X-Trace-Id") == "" {
		t.Fatal("缺少 X-Trace-Id 响应头")
	}
	var env struct {
		Code      int            `json:"code"`
		Message   string         `json:"message"`
		Data      map[string]any `json:"data"`
		TraceID   string         `json:"traceId"`
		Timestamp int64          `json:"timestamp"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
		t.Fatalf("响应非 JSON: %v", err)
	}
	if env.Code != 0 || env.Message != "ok" || env.Data["hello"] != "world" {
		t.Fatalf("包络形状错误: %+v", env)
	}
	if env.TraceID == "" || env.Timestamp <= 0 {
		t.Fatalf("traceId/timestamp 缺失: %+v", env)
	}
}
