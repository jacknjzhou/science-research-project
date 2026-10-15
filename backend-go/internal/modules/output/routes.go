package output

import "github.com/gin-gonic/gin"

// Register 挂 R 竖切到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 静态段（mine/pending-claim/claim/reject/mark-not-mine）先于参数段 :id 注册
// （gin 树本身优先匹配静态，顺序仅为可读性）。
// 未列端点（ai-fill/ai-dedup/patents/metrics/refresh-cited/export）由 oapi.Passthrough
// 兜底，符合规格 §4.2 与计划任务 2.6 注记：本轮 AI/集成类保留 passthrough。
//
// 契约校正：linkProjects 在 design/04 paths 为 PUT /output/{id}/projects（计划示例误写 POST），
// 按契约以 PUT 注册（见铁律：DDL/契约为真源）。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/output", h.ListOutputs)
	r.POST("/output", h.CreateOutput)
	r.GET("/output/mine", h.ListMyOutputs)
	r.GET("/output/pending-claim", h.ListPendingClaim)
	r.POST("/output/claim", h.ClaimOutputs)
	r.POST("/output/reject", h.RejectOutputs)
	r.POST("/output/mark-not-mine", h.MarkNotMine)
	r.PUT("/output/:id/projects", h.LinkProjects)
	r.GET("/output/:id", h.GetOutput)
}
