package p

import "github.com/gin-gonic/gin"

// Register 把 P 竖切挂到调用方给定的路由结合（受保护分组 /api/v1）之上。
// 相对路径只写 /apply 前缀；/api/v1 前缀由 router.Build 的 api := e.Group("/api/v1") 提供。
//
// 注：计划原稿函数体写作 r.Group("/apply")，但 gin v1.10.0 的 gin.IRoutes 接口并不含
// Group() 方法（仅 *RouterGroup / *Engine 有）。为保持铁律要求的签名 p.Register(gin.IRoutes, *Handler)，
// 这里直接在 r 上以 /apply 相对路径注册三条路由——当 r 为 *RouterGroup(基础路径 /api/v1) 时，
// 实际整路径同样是 /api/v1/apply/...，且继承该分组的鉴权/幂等中间件，行为与 Group("/apply") 完全一致。
func Register(r gin.IRoutes, h *Handler) {
	// 申报指南（P-02）
	r.GET("/apply/guidelines", h.ListGuidelines)
	r.POST("/apply/guidelines", h.UpsertGuideline)
	r.GET("/apply/guidelines/:id", h.GetGuideline)
	// 申报书（P-05）
	r.GET("/apply/applications", h.ListApplications)
	r.POST("/apply/applications", h.CreateApplication)
	r.GET("/apply/applications/:id", h.GetApplication)
}
