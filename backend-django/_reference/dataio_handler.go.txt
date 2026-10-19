// T13 Excel 导入导出底座（dataio）：
//   GET  /dataio/template?module=      下载 xlsx 模板（表头+示例行+校验说明 sheet）
//   POST /dataio/import?module=        multipart 上传 xlsx → 逐行导入 → 写 sys_import_log
//   GET  /dataio/imports               导入日志列表
//   POST /dataio/imports/:id/undo      按 snapshot 撤销（业务行未被引用才允许）
//   POST /dataio/export                选择性字段导出 xlsx（spec「选择性导出」）
//
// 模块注册表：新模块实现 moduleSpec 即可挂入（funding.income 首个全链路落地；
// project.e / output.r 待 P5/P9 各自导入逻辑就绪后接入）。
package dataio

import (
	"encoding/json"
	"net/http"
	"strconv"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	nfstore "github.com/eplugger/ark/internal/modules/notify/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	nf *nfstore.Queries
	fs *fstore.Queries
}

func NewHandler(pool *pgxpool.Pool) *Handler {
	return &Handler{nf: nfstore.New(pool), fs: fstore.New(pool)}
}

func Register(r gin.IRoutes, h *Handler) {
	r.GET("/dataio/template", h.Template)
	r.POST("/dataio/import", h.Import)
	r.GET("/dataio/imports", h.ListImports)
	r.POST("/dataio/imports/:id/undo", h.Undo)
	r.POST("/dataio/export", h.Export)
}

func (h *Handler) pageArgs(c *gin.Context) (page, size, limit, offset int) {
	page, _ = strconv.Atoi(c.DefaultQuery("page", "1"))
	size, _ = strconv.Atoi(c.DefaultQuery("size", "20"))
	if page < 1 {
		page = 1
	}
	if size < 1 || size > 200 {
		size = 20
	}
	return page, size, size, (page - 1) * size
}

// ListImports GET /dataio/imports?module=&from=&to=
func (h *Handler) ListImports(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := h.pageArgs(c)
	module := optText(c.Query("module"))
	rows, err := h.nf.ListImportLogs(c, nfstore.ListImportLogsParams{
		TenantID: d.TenantID, Module: module,
		FromAt: tsPtr(c.Query("from")), ToAt: tsPtr(c.Query("to")),
		Limit: int32(limit), Offset: int32(offset),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, err := h.nf.CountImportLogs(c, nfstore.CountImportLogsParams{
		TenantID: d.TenantID, Module: module,
		FromAt: tsPtr(c.Query("from")), ToAt: tsPtr(c.Query("to")),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, l := range rows {
		out = append(out, map[string]any{
			"id": l.ID, "module": l.Module,
			"row_count": l.RowCount, "success_count": l.SuccessCount, "fail_count": l.FailCount,
			"operator_id": l.OperatorID,
			"created_at":  l.CreatedAt.Time.Format("2006-01-02 15:04:05"),
		})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// Undo POST /dataio/imports/:id/undo —— 按 snapshot 撤销。
// 守卫：批次内任何到款行已认领（被业务引用）→ 409 拒绝整体撤销。
func (h *Handler) Undo(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "id 非法")
		return
	}
	log, err := h.nf.GetImportLog(c, nfstore.GetImportLogParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "导入日志不存在")
		return
	}
	if log.Module != ModIncome {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "该模块暂不支持撤销")
		return
	}
	var flowNos []string
	if err := json.Unmarshal(log.Snapshot, &flowNos); err != nil || len(flowNos) == 0 {
		httpx.WriteErr(c, http.StatusConflict, 40901, "无可撤销快照")
		return
	}
	claimed, err := h.fs.CountIncomesClaimedByFlowNos(c, fstore.CountIncomesClaimedByFlowNosParams{
		TenantID: d.TenantID, FlowNos: flowNos,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "撤销检查失败")
		return
	}
	if claimed > 0 {
		httpx.WriteErr(c, http.StatusConflict, 40902, "批次内已有认领入账行，禁止撤销")
		return
	}
	n, err := h.fs.DeleteImportedIncomes(c, fstore.DeleteImportedIncomesParams{
		TenantID: d.TenantID, FlowNos: flowNos,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "撤销失败")
		return
	}
	httpx.WriteOK(c, gin.H{"deleted": n})
}

func optText(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
