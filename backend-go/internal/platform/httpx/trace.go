package httpx

import (
	"crypto/rand"
	"encoding/hex"

	"github.com/gin-gonic/gin"
)

func NewTraceID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return "go-" + hex.EncodeToString(b)
}

// TraceID 中间件：透传入站 X-Trace-Id，否则新建；写入 context 与响应头。
func TraceID() gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.GetHeader(HeaderTrace)
		if id == "" {
			id = NewTraceID()
		}
		c.Set(CtxTraceID, id)
		c.Header(HeaderTrace, id)
		c.Next()
	}
}
