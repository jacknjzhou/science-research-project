package project

import "github.com/gin-gonic/gin"

// Register 挂 E 竖切到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 静态段 /project/mine 先于参数段 /project/:id 注册（gin 树本身会优先匹配静态，
// 顺序保证可读）。未列端点（health-score/risk-warnings/trace/archive-checklist）
// 由 oapi.Passthrough 兜底，符合规格 §3.2。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/project/mine", h.ListMyProjects)
	r.GET("/project/:id", h.GetProject)
	r.GET("/project/:id/tasks", h.ListTasks)
	r.GET("/project/:id/milestones", h.ListMilestones)
	r.PUT("/project/:id/tasks/:taskId", h.UpdateTask)
	r.POST("/project/:id/progress-report", h.CreateProgressReport)
	r.POST("/project/:id/mid-check", h.CreateMidCheck)
	r.POST("/project/:id/change-request", h.CreateChangeRequest)
	r.POST("/project/:id/change-request/:changeId/approve", h.ApproveChangeRequest)
	// T19 两级审核 + 批量
	r.POST("/projects/approve-batch", h.ApproveChangeBatch)
	// T21 项目分类 + 日期范围预警
	r.GET("/project-categories", h.ListProjectCategories)
	r.POST("/project-categories", h.CreateProjectCategory)
	r.PUT("/project-categories/:id", h.UpdateProjectCategory)
	r.DELETE("/project-categories/:id", h.DeleteProjectCategory)
	r.POST("/project-categories/scan-warnings", h.ScanWarnings)
	r.POST("/projects/:id/category", h.AttachProjectCategory)
	// T22 任务书 PDF 解析（回填表单用，不落库）
	r.POST("/projects/extract-taskbook", h.ExtractTaskbook)
	r.POST("/project/:id/final-accept", h.CreateFinalAccept)
}
