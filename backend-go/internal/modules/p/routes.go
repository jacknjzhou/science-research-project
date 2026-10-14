package p

import "github.com/gin-gonic/gin"

// Register 把 P 竖切三条路由挂到 /api/v1/apply 分组（对齐 design servers.url=/api/v1 + paths）。
func Register(e *gin.Engine, h *Handler) {
	g := e.Group("/api/v1/apply")
	g.GET("/applications", h.ListApplications)
	g.POST("/applications", h.CreateApplication)
	g.GET("/applications/:id", h.GetApplication)
}
