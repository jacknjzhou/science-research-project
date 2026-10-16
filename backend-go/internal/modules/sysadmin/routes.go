package sysadmin

import "github.com/gin-gonic/gin"

// Register 把 U 路由挂到受保护分组（相对 /admin、/auth 前缀；/api/v1 由 router.Build 分组提供）。
// gin v1.10 的 gin.IRoutes 无 Group()，直接 r.GET/.POST 相对路径注册（与 P 模块同款）。
// 参数名统一 :id（用户）/:roleId，避免同方法树 wildcard 名冲突导致 gin panic。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/auth/me", h.GetMe)
	r.GET("/admin/users", h.ListUsers)
	r.POST("/admin/users", h.CreateUser)
	r.GET("/admin/users/:id", h.GetUser)
	r.PUT("/admin/users/:id", h.UpdateUser)
	r.DELETE("/admin/users/:id", h.DeleteUser)
	r.GET("/admin/roles", h.ListRoles)
	r.POST("/admin/roles", h.CreateRole)
	r.PUT("/admin/roles/:roleId", h.UpdateRole)
	r.DELETE("/admin/roles/:roleId", h.DeleteRole)
	r.POST("/admin/users/:id/roles", h.AssignRole)
	r.DELETE("/admin/users/:id/roles/:roleId", h.RevokeRole)

	// 数据字典（PRD 2.8）：管理端 CRUD 仅 R-ADMIN（policy 通配），/dicts/:code 全员只读。
	// :dictId 命名避免与 /admin/users/:id 同树 wildcard 冲突。
	r.GET("/admin/dicts", h.ListDicts)
	r.POST("/admin/dicts", h.UpsertDict)
	r.GET("/admin/dicts/:dictId", h.GetDict)
	r.DELETE("/admin/dicts/:dictId", h.DeleteDict)
	r.POST("/admin/dicts/:dictId/items", h.UpsertDictItem)
	r.PUT("/admin/dicts/:dictId/items/:itemId", h.UpdateDictItem)
	r.DELETE("/admin/dicts/:dictId/items/:itemId", h.DeleteDictItem)
	r.GET("/dicts/:code", h.GetDictByCode)
}
