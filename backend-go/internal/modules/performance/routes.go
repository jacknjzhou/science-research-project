package performance

import "github.com/gin-gonic/gin"

// Register 把 M 竖切挂到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 分层：/perf/schemes[/:id][/activate|/calculate|/factors[/:factorId]]
//
//	/perf/records[/:id][/detail|/confirm|/appeal|/approve|/void]
//	/perf/payouts[/:id][/approve|/pay|/reject]
//	/perf/me  /perf/ranking
func Register(r gin.IRoutes, h *Handler) {
	// T24 PI 画像（真数据聚合）
	r.GET("/portrait/:userId", h.Portrait)
	// 方案
	r.GET("/perf/schemes", h.ListSchemes)
	r.POST("/perf/schemes", h.CreateScheme)
	r.GET("/perf/schemes/:id", h.GetScheme)
	r.PUT("/perf/schemes/:id", h.UpdateScheme)
	r.DELETE("/perf/schemes/:id", h.DeleteScheme)
	r.POST("/perf/schemes/:id/activate", h.ActivateScheme)
	r.POST("/perf/schemes/:id/calculate", h.CalculatePerformance)
	// 因子（嵌在方案下）
	r.GET("/perf/schemes/:id/factors", h.ListFactors)
	r.POST("/perf/schemes/:id/factors", h.UpsertFactor)
	r.PUT("/perf/schemes/:id/factors/:factorId", h.UpdateFactor)
	r.DELETE("/perf/schemes/:id/factors/:factorId", h.DeleteFactor)
	// 记录
	r.GET("/perf/records", h.ListRecords)
	r.GET("/perf/records/:id", h.GetRecord)
	r.GET("/perf/records/:id/detail", h.GetRecordDetail)
	r.POST("/perf/records/:id/confirm", h.ConfirmRecord)
	r.POST("/perf/records/:id/appeal", h.AppealRecord)
	r.POST("/perf/records/:id/approve", h.ApproveRecord)
	r.POST("/perf/records/:id/void", h.VoidRecord)
	// 发放
	r.GET("/perf/payouts", h.ListPayouts)
	r.POST("/perf/payouts", h.CreatePayout)
	r.GET("/perf/payouts/:id", h.GetPayout)
	r.POST("/perf/payouts/:id/approve", h.ApprovePayout)
	r.POST("/perf/payouts/:id/pay", h.PayPayout)
	r.POST("/perf/payouts/:id/reject", h.RejectPayout)
	// 个人视图 / 排行
	r.GET("/perf/me", h.MyPerformance)
	r.GET("/perf/ranking", h.PerfRanking)
}
