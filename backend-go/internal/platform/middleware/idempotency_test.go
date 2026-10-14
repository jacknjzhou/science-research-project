package middleware

import (
	"io"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

// newIdemEngine 返回挂了 Idempotency 中间件的引擎与处理调用计数器（指针，供断言）。
// rdb 可为 nil：安全方法/缺幂等键请求应在触达 Redis 之前短路。
func newIdemEngine(rdb *redis.Client) (*gin.Engine, *int) {
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), Idempotency(rdb, time.Minute))
	n := 0
	counter := &n
	e.POST("/api/v1/apply/applications", func(c *gin.Context) {
		n++
		httpx.WriteOK(c, gin.H{"created": n})
	})
	e.GET("/api/v1/apply/applications", func(c *gin.Context) {
		n++
		httpx.WriteOK(c, gin.H{"created": n})
	})
	return e, counter
}

func postWithKey(e *gin.Engine, idemKey string) string {
	req := httptest.NewRequest("POST", "/api/v1/apply/applications", strings.NewReader(`{}`))
	if idemKey != "" {
		req.Header.Set("Idempotency-Key", idemKey)
	}
	w := httptest.NewRecorder()
	e.ServeHTTP(w, req)
	b, _ := io.ReadAll(w.Body)
	return string(b)
}

// 步骤1 用例（计划原样）：同 key 二次请求回放首次响应体。
func TestIdempotency_ReplaysSameBody(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	e, _ := newIdemEngine(rdb)

	first := postWithKey(e, "K-1")
	second := postWithKey(e, "K-1")
	if first != second {
		t.Fatalf("幂等失败: first=%s second=%s", first, second)
	}
	if !strings.Contains(first, "\"created\":1") || !strings.Contains(second, "\"created\":1") {
		t.Fatalf("应回放首次结果: %s / %s", first, second)
	}
}

// 用例2（Task12 关键）：首次执行并缓存；同 key 回放时处理函数不再被执行（call-count==1）。
func TestIdempotency_HandlerNotReexecuted(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	e, calls := newIdemEngine(rdb)

	_ = postWithKey(e, "K-count")
	if *calls != 1 {
		t.Fatalf("首次应执行 1 次，实际 %d", *calls)
	}
	// 二次同 key → 回放缓存，处理函数不得再执行
	second := postWithKey(e, "K-count")
	if *calls != 1 {
		t.Fatalf("回放不得重新执行处理函数，实际调用次数=%d", *calls)
	}
	if !strings.Contains(second, "\"created\":1") {
		t.Fatalf("回放体应仍是首次结果 created:1，得 %s", second)
	}
	// Redis 里应存有缓存键
	if !mr.Exists("idem:POST:/api/v1/apply/applications:K-count") {
		t.Fatal("首次结果未缓存到 Redis")
	}
}

// 用例3：GET 直接放行，绝不触碰 Redis（用 nil 客户端证明守卫在 Redis 之前短路）。
func TestIdempotency_GetPassthrough(t *testing.T) {
	e, calls := newIdemEngine(nil) // nil redis：若误触达会 panic
	req := httptest.NewRequest("GET", "/api/v1/apply/applications", nil)
	req.Header.Set("Idempotency-Key", "K-GET") // 即便带 key，GET 也应放行
	w := httptest.NewRecorder()
	e.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("GET 期望 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if *calls != 1 {
		t.Fatalf("GET 应直达处理函数一次，实际 %d", *calls)
	}
	if !strings.Contains(w.Body.String(), "\"created\":1") {
		t.Fatalf("GET 未经幂等处理: %s", w.Body.String())
	}
}

// 用例4：缺失 Idempotency-Key 的写请求直接放行、不去重（每次执行；用 nil 客户端证明不触达 Redis）。
func TestIdempotency_MissingKeyPassthrough(t *testing.T) {
	e, calls := newIdemEngine(nil) // nil redis：缺 key 不应触达
	_ = postWithKey(e, "")
	_ = postWithKey(e, "")
	if *calls != 2 {
		t.Fatalf("无幂等键应每次都执行处理函数，实际 %d", *calls)
	}
}
