// T15 支出科目树形管理（F-01 扩展）+ 经费预警配置 CRUD。
package funding

import (
	"encoding/json"
	"errors"
	"net/http"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// SubjectsTree GET /subjects/tree —— 多级科目树（含未启用过滤交给前端）。
func (h *Handler) SubjectsTree(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListSubjectsAll(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	type node struct {
		fstore.FSubject
		Children []*node `json:"children"`
	}
	byID := map[int64]*node{}
	roots := []*node{}
	for i := range rows {
		byID[rows[i].ID] = &node{FSubject: rows[i], Children: []*node{}}
	}
	for i := range rows {
		n := byID[rows[i].ID]
		if rows[i].ParentID != nil {
			if p, ok := byID[*rows[i].ParentID]; ok {
				p.Children = append(p.Children, n)
				continue
			}
		}
		roots = append(roots, n)
	}
	httpx.WriteOK(c, roots)
}

type subjectBody struct {
	Code       *string      `json:"code"`
	Name       string       `json:"name" binding:"required"`
	ParentID   *int64       `json:"parent_id"`
	Category   string       `json:"category" binding:"required"`
	IsLeaf     *bool        `json:"is_leaf"`
	RatioLimit *string      `json:"ratio_limit"`
	AppliesTo  *[]string    `json:"applies_to"`
	SortNo     *int32       `json:"sort_no"`
	Remark     *string      `json:"remark"`
}

// CreateSubject POST /subjects —— 多级：parent 存在则 level=parent.level+1。
func (h *Handler) CreateSubject(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b subjectBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	var level int16 = 1
	if b.ParentID != nil {
		p, err := h.q.GetSubject(c, *b.ParentID)
		if err != nil {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "上级科目不存在")
			return
		}
		level = p.Level + 1
	}
	isLeaf := true
	if b.IsLeaf != nil {
		isLeaf = *b.IsLeaf
	}
	var appliesTo []byte
	if b.AppliesTo != nil {
		appliesTo, _ = json.Marshal(*b.AppliesTo)
	}
	var ratio pgtype.Numeric
	if b.RatioLimit != nil {
		ratio = strToNum(*b.RatioLimit)
	}
	sortNo := int32(0)
	if b.SortNo != nil {
		sortNo = *b.SortNo
	}
	s, err := h.q.CreateSubject(c, fstore.CreateSubjectParams{
		Code: b.Code, TenantID: d.TenantID, CreatorID: d.UserID,
		Name: b.Name, ParentID: b.ParentID, Level: level, Category: b.Category,
		IsLeaf: isLeaf, RatioLimit: ratio, AppliesTo: appliesTo,
		SortNo: sortNo,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败："+err.Error())
		return
	}
	httpx.WriteOK(c, ToAPISubject(s))
}

// UpdateSubject PUT /subjects/:id
func (h *Handler) UpdateSubject(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Name       *string `json:"name"`
		RatioLimit *string `json:"ratio_limit"`
		SortNo     *int32  `json:"sort_no"`
		Remark     *string `json:"remark"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	var ratio pgtype.Numeric
	if b.RatioLimit != nil {
		ratio = strToNum(*b.RatioLimit)
	}
	s, err := h.q.UpdateSubject(c, fstore.UpdateSubjectParams{
		ID: pathID(c),
		Name: b.Name, RatioLimit: ratio, SortNo: b.SortNo, Remark: b.Remark, ModifierID: &d.UserID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "科目不存在")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "更新失败："+err.Error())
		return
	}
	httpx.WriteOK(c, ToAPISubject(s))
}

// DeleteSubject DELETE /subjects/:id —— 守卫：有子级或被预算行引用禁删。
func (h *Handler) DeleteSubject(c *gin.Context) {
	id := pathID(c)
	kids, err := h.q.CountSubjectChildren(c, &id)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "校验失败")
		return
	}
	if kids > 0 {
		httpx.WriteErr(c, http.StatusConflict, 40901, "存在下级科目，禁止删除")
		return
	}
	refs, err := h.q.CountSubjectBudgetRefs(c, id)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "校验失败")
		return
	}
	if refs > 0 {
		httpx.WriteErr(c, http.StatusConflict, 40902, "科目已被预算引用，禁止删除")
		return
	}
	if _, err := h.q.DeleteSubject(c, id); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "删除失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id})
}

// —— 预警配置 ——

// ListWarnConfigs GET /funding/warn-configs?warn_kind=&enabled=
func (h *Handler) ListWarnConfigs(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	var enabled *bool
	switch c.Query("enabled") {
	case "true":
		v := true
		enabled = &v
	case "false":
		v := false
		enabled = &v
	}
	rows, err := h.q.ListWarnConfigs(c, fstore.ListWarnConfigsParams{
		TenantID: d.TenantID, WarnKind: optQuery(c, "warn_kind"), Enabled: enabled,
		Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountWarnConfigs(c, fstore.CountWarnConfigsParams{
		TenantID: d.TenantID, WarnKind: optQuery(c, "warn_kind"), Enabled: enabled,
	})
	out := make([]map[string]any, 0, len(rows))
	for _, w := range rows {
		out = append(out, ToAPIWarnConfig(w))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

type warnBody struct {
	ProjectCategoryID *int64  `json:"project_category_id"`
	WarnKind          string  `json:"warn_kind" binding:"required"`
	ThresholdPct      *string `json:"threshold_pct"`
	AheadDays         *int32  `json:"ahead_days"`
	Level             string  `json:"level"`
	Channel           string  `json:"channel"`
	CronExpr          *string `json:"cron_expr"`
	Template          *string `json:"template"`
	Enabled           *bool   `json:"enabled"`
	Remark            *string `json:"remark"`
}

var WARN_KINDS = map[string]bool{
	"EXEC_RATE": true, "DEADLINE": true, "ANNUAL_FEE": true, "MIDCHECK": true, "CLOSING": true,
}

// CreateWarnConfig POST /funding/warn-configs
func (h *Handler) CreateWarnConfig(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b warnBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	if !WARN_KINDS[b.WarnKind] {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "warn_kind 非法（EXEC_RATE|DEADLINE|ANNUAL_FEE|MIDCHECK|CLOSING）")
		return
	}
	level := b.Level
	if level == "" {
		level = "P2"
	}
	channel := b.Channel
	if channel == "" {
		channel = "INBOX"
	}
	enabled := true
	if b.Enabled != nil {
		enabled = *b.Enabled
	}
	var ratio pgtype.Numeric
	if b.ThresholdPct != nil {
		ratio = strToNum(*b.ThresholdPct)
	}
	w, err := h.q.CreateWarnConfig(c, fstore.CreateWarnConfigParams{
		TenantID: d.TenantID, CreatorID: d.UserID,
		ProjectCategoryID: b.ProjectCategoryID, WarnKind: b.WarnKind,
		ThresholdPct: ratio, AheadDays: b.AheadDays,
		Level: level, Channel: channel, CronExpr: b.CronExpr,
		Template: b.Template, Enabled: enabled, Remark: b.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败："+err.Error())
		return
	}
	httpx.WriteOK(c, ToAPIWarnConfig(w))
}

// UpdateWarnConfig PUT /funding/warn-configs/:id —— 局部更新（未传字段不覆盖）。
func (h *Handler) UpdateWarnConfig(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		ProjectCategoryID *int64  `json:"project_category_id"`
		ThresholdPct      *string `json:"threshold_pct"`
		AheadDays         *int32  `json:"ahead_days"`
		Level             string  `json:"level"`
		Channel           string  `json:"channel"`
		CronExpr          *string `json:"cron_expr"`
		Template          *string `json:"template"`
		Enabled           *bool   `json:"enabled"`
		Remark            *string `json:"remark"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	var ratio pgtype.Numeric
	if b.ThresholdPct != nil {
		ratio = strToNum(*b.ThresholdPct)
	}
	w, err := h.q.UpdateWarnConfig(c, fstore.UpdateWarnConfigParams{
		ID: pathID(c), TenantID: d.TenantID,
		ThresholdPct: ratio, AheadDays: b.AheadDays,
		Level: optStrPtr(b.Level), Channel: optStrPtr(b.Channel), CronExpr: b.CronExpr,
		Template: b.Template, Enabled: b.Enabled, Remark: b.Remark,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "配置不存在")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "更新失败："+err.Error())
		return
	}
	httpx.WriteOK(c, ToAPIWarnConfig(w))
}

// DeleteWarnConfig DELETE /funding/warn-configs/:id
func (h *Handler) DeleteWarnConfig(c *gin.Context) {
	d := auth.DomainFrom(c)
	if _, err := h.q.DeleteWarnConfig(c, fstore.DeleteWarnConfigParams{ID: pathID(c), TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "删除失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": pathID(c)})
}

func ToAPIWarnConfig(w fstore.FWarnConfig) map[string]any {
	return map[string]any{
		"id": w.ID, "warn_kind": w.WarnKind,
		"project_category_id": optI64(w.ProjectCategoryID),
		"threshold_pct":       numStrOrNil(w.ThresholdPct, 4), "ahead_days": optI64I32(w.AheadDays),
		"level": w.Level, "channel": w.Channel, "cron_expr": optStr(w.CronExpr),
		"template": optStr(w.Template), "enabled": w.Enabled,
		"remark": optStr(w.Remark), "created_at": fmtTz(w.CreatedAt),
	}
}

// optStrPtr 空串 → nil（PUT 局部更新语义：未传字段不覆盖）。
func optStrPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
