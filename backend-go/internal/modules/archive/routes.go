package archive

import "github.com/gin-gonic/gin"

// Register 挂 O 竖切到受保护分组（/api/v1 前缀由 router.Build 提供）。
// 铁律：静态段须先于参数段注册——故 /documents/search 早于 /documents/:id，
// 否则会被 :id 吞并。items/:itemId 依赖 :id 前缀，顺序无冲突。
// FillItem 契约动词为 PUT（见 16-科研档案管理-O.openapi.yaml），非 POST。
func Register(r gin.IRoutes, h *Handler) {
	// 文档
	r.POST("/documents", h.UploadDocument)
	r.GET("/documents/search", h.SearchDocuments) // 静态段，先于 :id
	r.GET("/documents/:id", h.GetDocument)
	r.DELETE("/documents/:id", h.DeleteDocument)
	r.GET("/documents/:id/download", h.DownloadDocument)

	// 案卷 CRUD
	r.GET("/archives", h.ListArchives)
	r.POST("/archives", h.CreateArchive)
	r.GET("/archives/:id", h.GetArchive)
	r.PUT("/archives/:id", h.UpdateArchive)
	r.DELETE("/archives/:id", h.DeleteArchive)

	// 门类清单
	r.GET("/archives/:id/items", h.ListItems)
	r.POST("/archives/:id/items", h.AddItem)
	r.PUT("/archives/:id/items/:itemId", h.FillItem) // 契约 PUT
	r.DELETE("/archives/:id/items/:itemId", h.DeleteItem)

	// 来源摄取 + 状态机 + 四性检测
	r.POST("/archives/:id/ingest", h.IngestSource)
	r.POST("/archives/:id/submit", h.SubmitArchive)
	r.POST("/archives/:id/check", h.CheckArchive)
	r.POST("/archives/:id/file", h.FileArchive)
	r.POST("/archives/:id/destroy", h.DestroyArchive)

	// 借阅
	r.GET("/borrows", h.ListBorrows)
	r.POST("/borrows", h.CreateBorrow)
	r.POST("/borrows/:id/approve", h.ApproveBorrow)
	r.POST("/borrows/:id/reject", h.RejectBorrow)
	r.POST("/borrows/:id/return", h.ReturnBorrow)
}
