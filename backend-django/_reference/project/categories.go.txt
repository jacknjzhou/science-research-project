// T21 项目分类管理 + 中检/结项日期范围预警扫描。
package project

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	estore "github.com/eplugger/ark/internal/modules/project/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// Notifier 通知触达接口（notify 模块实现并装配期注入；nil 时扫描静默跳过触达）。
type Notifier interface {
	Push(ctx context.Context, tenantID, userID int64, typ, title, content, bizRef string)
}

// SetNotifier 装配期注入通知器。
func (h *Handler) SetNotifier(n Notifier) { h.nt = n }

func catPathID(c *gin.Context) int64 {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	return id
}

// CreateProjectCategory POST /project-categories {code,name,level,mgmt_fee_pct,窗口...}
func (h *Handler) CreateProjectCategory(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Code         string  `json:"code" binding:"required"`
		Name         string  `json:"name" binding:"required"`
		Level        *string `json:"level"`
		MgmtFeePct   string  `json:"mgmt_fee_pct"`
		MidcheckFrom *string `json:"midcheck_from"`
		MidcheckTo   *string `json:"midcheck_to"`
		ClosingFrom  *string `json:"closing_from"`
		ClosingTo    *string `json:"closing_to"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	r, err := h.q.CreateProjectCategory(c, estore.CreateProjectCategoryParams{
		TenantID: d.TenantID, Code: b.Code, Name: b.Name,
		Level:        nargLevel(b.Level),
		MgmtFeePct:   numFromStr(b.MgmtFeePct),
		MidcheckFrom: datePtr(b.MidcheckFrom), MidcheckTo: datePtr(b.MidcheckTo),
		ClosingFrom: datePtr(b.ClosingFrom), ClosingTo: datePtr(b.ClosingTo),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPICategory(r))
}

// ListProjectCategories GET /project-categories
func (h *Handler) ListProjectCategories(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListProjectCategories(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToAPICategory(r))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": len(out)})
}

// UpdateProjectCategory PUT /project-categories/:id（COALESCE 局部更新）
func (h *Handler) UpdateProjectCategory(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Name         *string `json:"name"`
		Level        *string `json:"level"`
		MgmtFeePct   *string `json:"mgmt_fee_pct"`
		MidcheckFrom *string `json:"midcheck_from"`
		MidcheckTo   *string `json:"midcheck_to"`
		ClosingFrom  *string `json:"closing_from"`
		ClosingTo    *string `json:"closing_to"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	r, err := h.q.UpdateProjectCategory(c, estore.UpdateProjectCategoryParams{
		ID: catPathID(c), TenantID: d.TenantID,
		Name: b.Name, Level: nargLevel(b.Level),
		MgmtFeePct:   numPtrFromStr(b.MgmtFeePct),
		MidcheckFrom: datePtr(b.MidcheckFrom), MidcheckTo: datePtr(b.MidcheckTo),
		ClosingFrom: datePtr(b.ClosingFrom), ClosingTo: datePtr(b.ClosingTo),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "更新失败")
		return
	}
	httpx.WriteOK(c, ToAPICategory(r))
}

// DeleteProjectCategory DELETE /project-categories/:id —— 被项目引用禁删 40902。
func (h *Handler) DeleteProjectCategory(c *gin.Context) {
	d := auth.DomainFrom(c)
	id := catPathID(c)
	n, err := h.q.CountProjectsByCategory(c, &id)
	if err == nil && n > 0 {
		httpx.WriteErr(c, http.StatusConflict, 40902, "分类已被项目引用，禁止删除")
		return
	}
	if _, err := h.q.DeleteProjectCategory(c, estore.DeleteProjectCategoryParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "删除失败")
		return
	}
	httpx.WriteOK(c, gin.H{"deleted": true})
}

// AttachProjectCategory POST /projects/:id/category {category_id} —— 立项/变更时挂分类。
func (h *Handler) AttachProjectCategory(c *gin.Context) {
	pid, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b struct {
		CategoryID int64 `json:"category_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	if _, err := h.q.GetProjectCategory(c, estore.GetProjectCategoryParams{ID: b.CategoryID, TenantID: 1}); err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "分类不存在")
		return
	}
	if _, err := h.q.AttachProjectCategory(c, estore.AttachProjectCategoryParams{ID: pid, CategoryID: &b.CategoryID}); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "挂接失败")
		return
	}
	httpx.WriteOK(c, gin.H{"project_id": pid, "category_id": b.CategoryID})
}

// ScanWarnings POST /project-categories/scan-warnings
// 中检/结项日期范围预警：EXECUTING 项目 × 分类窗口（进入窗口或窗口前 15 天）→ 通知负责人。
// 去重：同用户同标题未读通知已存在则不重发（幂等，可被 cron 重复调用）。
func (h *Handler) ScanWarnings(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListMidcheckDueProjects(c)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "扫描失败")
		return
	}
	sent := 0
	for _, p := range rows {
		var kind, title, due string
		if p.MidcheckFrom.Valid && p.MidcheckTo.Valid && inWindow(p.MidcheckFrom, p.MidcheckTo, 15) {
			kind = "MIDCHECK_DUE"
			title = "中检窗口提醒"
			due = p.MidcheckTo.Time.Format("2006-01-02")
		} else if p.ClosingFrom.Valid && p.ClosingTo.Valid && inWindow(p.ClosingFrom, p.ClosingTo, 15) {
			kind = "CLOSING_DUE"
			title = "结项窗口提醒"
			due = p.ClosingTo.Time.Format("2006-01-02")
		} else {
			continue
		}
		// 去重：同用户同标题未读通知已存在则跳过
		var n int
		if err := h.pool.QueryRow(c, `SELECT count(*) FROM sys_notification WHERE user_id=$1 AND title=$2 AND read_at IS NULL`,
			p.PiUserID, kind+"："+p.Title).Scan(&n); err == nil && n > 0 {
			continue
		}
		if h.nt != nil {
			// T24：F_WARN_CONFIG 模板渲染（channel=cron 的 MIDCHECK/CLOSING 配置；{project}/{date} 占位）
			content := "项目《" + p.Title + "》" + title + "，截止 " + due + "，请及时安排中检/结项材料"
			if tpl := h.warnTemplate(c, d.TenantID, strings.TrimSuffix(kind, "_DUE")); tpl != "" {
				content = strings.NewReplacer("{project}", p.Title, "{date}", due).Replace(tpl)
			}
			h.nt.Push(c, d.TenantID, p.PiUserID, "WARNING", kind+"："+p.Title, content,
				"project/"+strconv.FormatInt(p.ID, 10))
			sent++
		}
	}
	httpx.WriteOK(c, gin.H{"scanned": len(rows), "sent": sent})
}

// warnTemplate 取启用的预警模板（F_WARN_CONFIG；无配置返回空走默认文案）。
func (h *Handler) warnTemplate(c *gin.Context, tenantID int64, kind string) string {
	var tpl *string
	if err := h.pool.QueryRow(c,
		`SELECT template FROM f_warn_config WHERE tenant_id=$1 AND warn_kind=$2 AND deleted=0
		 AND status='ACTIVE' AND enabled LIMIT 1`, tenantID, kind).Scan(&tpl); err != nil || tpl == nil {
		return ""
	}
	return *tpl
}

// inWindow 当前日期 ∈ [from-15d, to]。
func inWindow(from, to pgtype.Date, aheadDays int) bool {
	now := time.Now()
	lower := from.Time.AddDate(0, 0, -aheadDays)
	return !now.Before(lower) && !now.After(to.Time)
}

// nargLevel level 指针 → sqlc narg。
func nargLevel(l *string) *string {
	if l == nil || *l == "" {
		return nil
	}
	return l
}

// datePtr "2006-01-02" → pgtype.Date（nil → 无效值即 NULL）。
func datePtr(s *string) (d pgtype.Date) {
	if s == nil || *s == "" {
		return
	}
	_ = d.Scan(*s)
	return
}

// numFromStr "10.00" → pgtype.Numeric。
func numFromStr(s string) (n pgtype.Numeric) {
	if s == "" {
		return
	}
	_ = n.Scan(s)
	return
}

func numPtrFromStr(s *string) (n pgtype.Numeric) {
	if s == nil || *s == "" {
		return
	}
	_ = n.Scan(*s)
	return
}

var _ = errors.Is
var _ = pgx.ErrNoRows
