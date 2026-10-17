package activity

import "github.com/gin-gonic/gin"

// Register 把 V 竖切挂到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 静态段 calendar/stats 先于 /:id 注册无冲突（gin 路由树区分静态与参数段，且方法一致）。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/activities", h.ListActivities)
	r.POST("/activities", h.CreateActivity)
	r.GET("/activities/calendar", h.ActivityCalendar)
	r.GET("/activities/stats", h.ActivityStats)
	r.GET("/activities/:id", h.GetActivity)
	r.PUT("/activities/:id", h.UpdateActivity)
	r.DELETE("/activities/:id", h.DeleteActivity)
	r.POST("/activities/:id/submit", h.SubmitActivity)
	r.POST("/activities/:id/approve", h.ApproveActivity)
	r.POST("/activities/:id/hold", h.HoldActivity)
	r.POST("/activities/:id/archive", h.ArchiveActivity)
	r.POST("/activities/:id/cancel", h.CancelActivity)
	r.GET("/activities/:id/participants", h.ListParticipants)
	r.POST("/activities/:id/participants", h.AddParticipant)
	r.DELETE("/activities/:id/participants/:pid", h.RemoveParticipant)
}
