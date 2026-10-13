package httpx

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// Envelope 是全站统一响应包裹，字段名与 design/README.md §三 完全一致。
type Envelope struct {
	Code      int    `json:"code"`
	Message   string `json:"message"`
	Data      any    `json:"data"`
	TraceID   string `json:"traceId"`
	Timestamp int64  `json:"timestamp"`
}

const (
	CtxTraceID  = "traceId"
	HeaderTrace = "X-Trace-Id"
)

func traceOf(c *gin.Context) string {
	if v := c.GetString(CtxTraceID); v != "" {
		return v
	}
	return NewTraceID()
}

// WriteOK 写成功包络（code=0）。
func WriteOK(c *gin.Context, data any) {
	c.JSON(http.StatusOK, Envelope{
		Code: 0, Message: "ok", Data: data,
		TraceID: traceOf(c), Timestamp: time.Now().UnixMilli(),
	})
}

// WriteErr 写业务错误包络；HTTP 状态表达传输层，code 表达业务错误（PRD 2.5）。
func WriteErr(c *gin.Context, status, code int, msg string) {
	c.JSON(status, Envelope{
		Code: code, Message: msg, Data: nil,
		TraceID: traceOf(c), Timestamp: time.Now().UnixMilli(),
	})
}
