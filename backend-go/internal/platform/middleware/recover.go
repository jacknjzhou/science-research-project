package middleware

import (
	"net/http"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// Recover 捕获 panic，返回 500 统一包络，并落结构化日志。
func Recover(l *zap.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				l.Error("panic recovered", zap.Any("err", r), zap.String("traceId", c.GetString(httpx.CtxTraceID)))
				httpx.WriteErr(c, http.StatusInternalServerError, 50000, "服务器内部错误")
				c.Abort()
			}
		}()
		c.Next()
	}
}
