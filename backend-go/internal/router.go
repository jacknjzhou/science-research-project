package internal

import (
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/middleware"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// NewRouter 构建 Gin 引擎并挂载横切中间件与 /healthz。
func NewRouter(l *zap.Logger) *gin.Engine {
	e := gin.New()
	e.Use(httpx.TraceID(), middleware.Recover(l))
	e.GET("/healthz", func(c *gin.Context) { httpx.WriteOK(c, gin.H{"ok": true}) })
	return e
}
