package notify

import (
	"github.com/gin-gonic/gin"
)

// Register 通知中心路由（挂受保护分组 /api/v1）。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/notifications", h.List)
	r.GET("/notifications/unread-count", h.UnreadCount)
	r.POST("/notifications/read-all", h.MarkAllRead)
	r.POST("/notifications/:id/read", h.MarkRead)
	// T20 任务中心 + 站内消息
	r.GET("/tasks", h.Tasks)
	r.GET("/tasks/summary", h.TasksSummary)
	r.POST("/messages", h.SendMessage)
	r.GET("/messages", h.ListMessages)
}

// pageArgs 分页参数（与 funding 同约定：page 从 1，size 默认 20 上限 200）。
func pageArgs(c *gin.Context) (page, size, limit, offset int) {
	page = atoiDefault(c.Query("page"), 1)
	size = atoiDefault(c.Query("size"), 20)
	if size < 1 {
		size = 20
	}
	if size > 200 {
		size = 200
	}
	if page < 1 {
		page = 1
	}
	return page, size, size, (page - 1) * size
}

func atoiDefault(s string, def int) int {
	if s == "" {
		return def
	}
	n := 0
	for _, ch := range s {
		if ch < '0' || ch > '9' {
			return def
		}
		n = n*10 + int(ch-'0')
	}
	return n
}

// optQuery 非空查询参数指针。
func optQuery(c *gin.Context, key string) *string {
	v := c.Query(key)
	if v == "" {
		return nil
	}
	return &v
}
