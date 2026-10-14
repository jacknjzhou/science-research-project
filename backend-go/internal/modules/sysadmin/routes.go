package sysadmin

import "github.com/gin-gonic/gin"

// Register 把 sysadmin 路由挂到给定分组（gin v1.10 IRoutes 无 Group()，直接 .GET/.POST）。
// 任务 12 会补全写侧/角色路由并登记 revoke（参数改名 :userId→:id）；此处先登记已落地的读侧与 /auth/me。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/admin/users", h.ListUsers)
	r.GET("/admin/users/:id", h.GetUser)
	r.GET("/auth/me", h.GetMe)
}
