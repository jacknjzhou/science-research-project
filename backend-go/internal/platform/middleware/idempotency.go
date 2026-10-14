package middleware

import (
	"bytes"
	"io"
	"net/http"
	"time"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

// captureWriter 在把响应写给真实客户端的同时，把响应体复制进 buf 供 Redis 缓存回放。
// 必须同时写 underlying 与 buf——否则首次请求客户端拿不到 body（计划原稿只写 buf 是缺陷）。
type captureWriter struct {
	gin.ResponseWriter
	buf *bytes.Buffer
}

func (w *captureWriter) Write(b []byte) (int, error) {
	w.buf.Write(b)
	return w.ResponseWriter.Write(b)
}

func (w *captureWriter) WriteString(s string) (int, error) {
	w.buf.WriteString(s)
	return w.ResponseWriter.WriteString(s)
}

var _ io.Writer = (*captureWriter)(nil)

// Idempotency：对带 Idempotency-Key 的非安全方法做 Redis 去重与回放。
//
// 关键前置守卫（Task 12 依赖）：安全方法（GET/HEAD/OPTIONS）与缺失 Idempotency-Key
// 的写请求一律直接 c.Next() 放行，绝不触碰 Redis——这样即使 rdb 为 nil 也不会 panic。
func Idempotency(rdb *redis.Client, ttl time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		switch c.Request.Method {
		case http.MethodGet, http.MethodHead, http.MethodOptions:
			c.Next()
			return
		}
		key := c.GetHeader("Idempotency-Key")
		if key == "" {
			c.Next()
			return
		}
		cacheKey := "idem:" + c.Request.Method + ":" + c.Request.URL.Path + ":" + key
		ctx := c.Request.Context()

		// 已有缓存 → 回放
		if body, err := rdb.Get(ctx, cacheKey).Bytes(); err == nil {
			c.Data(http.StatusOK, "application/json; charset=utf-8", body)
			c.Abort()
			return
		}
		// 抢占：SETNX 处理中标记，避免并发重复执行
		ok, _ := rdb.SetNX(ctx, cacheKey+":lock", "1", ttl).Result()
		if !ok {
			httpx.WriteErr(c, http.StatusConflict, 40909, "相同幂等键正在处理中")
			c.Abort()
			return
		}
		cw := &captureWriter{ResponseWriter: c.Writer, buf: &bytes.Buffer{}}
		c.Writer = cw
		c.Next()
		// 完成后写入结果并清锁
		rdb.Set(ctx, cacheKey, cw.buf.Bytes(), ttl)
		rdb.Del(ctx, cacheKey+":lock")
	}
}
