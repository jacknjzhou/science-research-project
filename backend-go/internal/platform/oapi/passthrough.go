package oapi

import (
	"net/http"
	"strconv"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// Passthrough 作为 gin NoRoute 兜底：命中契约但未手工实现的路由，依 design 生成合规示例响应。
// 真实已实现路由因 gin 已注册而不进 NoRoute，故只有 passthrough 目标会到这里。
func Passthrough(s *Spec) gin.HandlerFunc {
	return func(c *gin.Context) {
		op := s.Match(c.Request.Method, c.Request.URL.Path)
		if op == nil {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "契约未定义该路由")
			return
		}
		data := op.Generate()
		// GET 列表路由落地真实分页参数（page/size 取查询串，缺省回退生成值）
		if m, ok := data.(map[string]any); ok {
			if list, hasList := m["list"].([]any); hasList && c.Request.Method == "GET" {
				m["page"] = atoiDefault(c.Query("page"), 1)
				m["size"] = atoiDefault(c.Query("size"), len(list))
			}
		}
		httpx.WriteOK(c, data)
	}
}

func atoiDefault(s string, def int) int {
	if s == "" {
		return def
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return n
}
