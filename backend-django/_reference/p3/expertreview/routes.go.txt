package expertreview

import "github.com/gin-gonic/gin"

// Register 挂 N 竖切到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 静态段 /experts、/reviews 先于参数段注册；gin 树本身优先匹配静态。
// 未列端点由 oapi.Passthrough 兜底（规格 §3.2）。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/experts", h.ListExperts)
	r.POST("/experts", h.CreateExpert)
	r.GET("/experts/:id", h.GetExpert)
	r.PUT("/experts/:id", h.UpdateExpert)
	r.DELETE("/experts/:id", h.DeleteExpert)
	r.POST("/experts/:id/status", h.SetExpertStatus)

	r.GET("/reviews", h.ListReviews)
	r.POST("/reviews", h.CreateReview)
	r.GET("/reviews/:id", h.GetReview)
	r.DELETE("/reviews/:id", h.CancelReview)
	r.GET("/reviews/:id/detail", h.GetReviewDetail)
	r.POST("/reviews/:id/draw", h.DrawExperts)
	r.POST("/reviews/:id/invite", h.InviteExperts)
	r.POST("/reviews/:id/accept", h.AcceptInvitation)
	r.POST("/reviews/:id/decline", h.DeclineInvitation)
	r.POST("/reviews/:id/start", h.StartReview)
	r.POST("/reviews/:id/scores", h.SubmitScore)
	r.POST("/reviews/:id/conclude", h.ConcludeReview)
	r.POST("/reviews/:id/fees", h.GenerateFees)
}
