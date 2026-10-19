// T25 申报计划 + 申报单：CRUD / apply-plans、start|stop（时间窗守卫）、
// applications（仅 OPEN 且 now∈[start,end]）、两级审批（T19 服务语义）、to-project 幂等转立项草稿、
// 到期自动停止（可被 cron 重复调用）。
package project

import (
	"encoding/json"
	"errors"
	"math/big"
	"net/http"
	"strconv"
	"strings"
	"time"

	estore "github.com/eplugger/ark/internal/modules/project/store"
	"github.com/eplugger/ark/internal/platform/approval"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

func planPathID(c *gin.Context) int64 {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	return id
}

func dateArg(s *string) pgtype.Date {
	var d pgtype.Date
	if s != nil && *s != "" {
		_ = d.Scan(*s)
	}
	return d
}

func numArg(s string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != "" {
		_ = n.Scan(s)
	}
	return n
}

func numStrPtr(n pgtype.Numeric) any {
	if !n.Valid || n.Int == nil {
		return "0.00"
	}
	r := new(big.Rat).SetInt(n.Int)
	if n.Exp < 0 {
		r.Mul(r, new(big.Rat).SetFrac(big.NewInt(1), new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(-n.Exp)), nil)))
	} else if n.Exp > 0 {
		r.Mul(r, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(n.Exp)), nil)))
	}
	return r.FloatString(2)
}

// CreateApplyPlan POST /apply-plans {name, category_id, source, start_at, end_at, need_review, guide_file_id}
func (h *Handler) CreateApplyPlan(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Name        string  `json:"name" binding:"required"`
		CategoryID  *int64  `json:"category_id"`
		Source      *string `json:"source"`
		StartAt     string  `json:"start_at" binding:"required"`
		EndAt       string  `json:"end_at" binding:"required"`
		NeedReview  *bool   `json:"need_review"`
		GuideFileID *int64  `json:"guide_file_id"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	needReview := true
	if b.NeedReview != nil {
		needReview = *b.NeedReview
	}
	r, err := h.q.CreateApplyPlan(c, estore.CreateApplyPlanParams{
		TenantID: d.TenantID, Name: b.Name, CategoryID: b.CategoryID, Source: b.Source,
		StartAt: dateArg(&b.StartAt), EndAt: dateArg(&b.EndAt),
		NeedReview: needReview, GuideFileID: b.GuideFileID,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": r.ID, "name": r.Name, "status": r.Status,
		"start_at": r.StartAt.Time.Format("2006-01-02"), "end_at": r.EndAt.Time.Format("2006-01-02")})
}

// ListApplyPlans GET /apply-plans
func (h *Handler) ListApplyPlans(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListApplyPlans(c, estore.ListApplyPlansParams{TenantID: d.TenantID, Limit: limit, Offset: offset})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountApplyPlans(c, d.TenantID)
	out := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, gin.H{"id": r.ID, "name": r.Name, "category_id": r.CategoryID,
			"source": r.Source, "start_at": r.StartAt.Time.Format("2006-01-02"),
			"end_at": r.EndAt.Time.Format("2006-01-02"), "need_review": r.NeedReview,
			"status": r.Status})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// StartApplyPlan POST /apply-plans/:id/start（DRAFT→OPEN）/ StopApplyPlan .../stop（OPEN→STOPPED）
func (h *Handler) StartApplyPlan(c *gin.Context) {
	d := auth.DomainFrom(c)
	n, err := h.q.SetApplyPlanStatus(c, estore.SetApplyPlanStatusParams{
		ID: planPathID(c), TenantID: d.TenantID, ToStatus: "OPEN", FromStatus: "DRAFT"})
	if err != nil || n == 0 {
		httpx.WriteErr(c, http.StatusConflict, 40901, "仅 DRAFT 可开启")
		return
	}
	httpx.WriteOK(c, gin.H{"id": planPathID(c), "status": "OPEN"})
}

func (h *Handler) StopApplyPlan(c *gin.Context) {
	d := auth.DomainFrom(c)
	n, err := h.q.SetApplyPlanStatus(c, estore.SetApplyPlanStatusParams{
		ID: planPathID(c), TenantID: d.TenantID, ToStatus: "STOPPED", FromStatus: "OPEN"})
	if err != nil || n == 0 {
		httpx.WriteErr(c, http.StatusConflict, 40901, "仅 OPEN 可停止")
		return
	}
	httpx.WriteOK(c, gin.H{"id": planPathID(c), "status": "STOPPED"})
}

// AutoStopPlans POST /apply-plans/auto-stop —— end_at < today 且 OPEN → STOPPED（cron 幂等）。
func (h *Handler) AutoStopPlans(c *gin.Context) {
	d := auth.DomainFrom(c)
	n, err := h.q.AutoStopExpiredPlans(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "扫描失败")
		return
	}
	httpx.WriteOK(c, gin.H{"stopped": n})
}

// CreateApplication POST /apply-plans/:id/applications {project_name, apply_amount, attachment_ids}
// 守卫：plan OPEN 且 now∈[start,end]，否则 40901。
func (h *Handler) CreateApplication(c *gin.Context) {
	d := auth.DomainFrom(c)
	planID := planPathID(c)
	plan, err := h.q.GetApplyPlan(c, estore.GetApplyPlanParams{ID: planID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "申报计划不存在")
		return
	}
	today := time.Now()
	if plan.Status != "OPEN" || today.Before(plan.StartAt.Time.AddDate(0, 0, 0)) || today.After(plan.EndAt.Time.AddDate(0, 0, 1)) {
		httpx.WriteErr(c, http.StatusConflict, 40901, "计划未开放或不在申报时间窗内")
		return
	}
	var b struct {
		ProjectName   string  `json:"project_name" binding:"required"`
		ApplyAmount   string  `json:"apply_amount"`
		AttachmentIDs []int64 `json:"attachment_ids"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	ids, _ := json.Marshal(b.AttachmentIDs)
	r, err := h.q.CreateApplication(c, estore.CreateApplicationParams{
		TenantID: d.TenantID, PlanID: planID, ProjectName: b.ProjectName,
		ApplyAmount: numArg(b.ApplyAmount), ApplicantID: d.UserID, AttachmentIds: ids,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "提交失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": r.ID, "plan_id": planID, "status": r.Status})
}

// ListApplications GET /apply-plans/:id/applications —— 形式审查视图（附申请人项目摘要）。
func (h *Handler) ListApplications(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListApplicationsByPlan(c, estore.ListApplicationsByPlanParams{TenantID: d.TenantID, PlanID: planPathID(c)})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, gin.H{"id": r.ID, "project_name": r.ProjectName,
			"apply_amount": numStrPtr(r.ApplyAmount), "applicant_id": r.ApplicantID,
			"status": r.Status, "pi_project_count": r.PiProjectCount,
			"pi_budget_total": numStrPtr(r.PiBudgetTotal), "project_id": r.ProjectID})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": len(out)})
}

// ApproveApplication POST /applications/:id/approve {action: APPROVE|REJECT, comment}
// 两级（T19 服务语义）：R-MANAGER SUBMITTED→COLLEGE_PASSED（学院）；R-LEADER COLLEGE_PASSED→SCHOOL_PASSED（学校）。
// R-ADMIN 直通角色校验但仍按级推进；两级开关 off 时一步到 SCHOOL_PASSED。
func (h *Handler) ApproveApplication(c *gin.Context) {
	d := auth.DomainFrom(c)
	appID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b struct {
		Action  string `json:"action" binding:"required"`
		Comment string `json:"comment"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	if b.Action != "APPROVE" && b.Action != "REJECT" {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "action 仅支持 APPROVE/REJECT")
		return
	}
	app, err := h.q.GetApplication(c, estore.GetApplicationParams{ID: appID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "申报单不存在")
		return
	}
	isAdmin := approval.HasRole(d.Roles, "R-ADMIN")
	twoStep := approval.Enabled()

	// 驳回：按当前级回 REJECTED
	if b.Action == "REJECT" {
		var to, from string
		switch app.Status {
		case "SUBMITTED":
			from, to = "SUBMITTED", "COLLEGE_REJECTED"
		case "COLLEGE_PASSED":
			from, to = "COLLEGE_PASSED", "SCHOOL_REJECTED"
		default:
			httpx.WriteErr(c, http.StatusConflict, 40901, "状态不允许驳回")
			return
		}
		if n, e := h.q.AdvanceApplication(c, estore.AdvanceApplicationParams{ID: appID, TenantID: d.TenantID, ToStatus: to, FromStatus: from}); e != nil || n == 0 {
			httpx.WriteErr(c, http.StatusInternalServerError, 50002, "驳回失败")
			return
		}
		_ = approval.Log(c, h.pool, approval.LogParam{TenantID: d.TenantID, BizType: "APPLICATION",
			BizID: appID, Step: 1, ActorID: d.UserID, ActorRole: firstRoleOf(d.Roles), Action: "REJECT", Comment: b.Comment})
		httpx.WriteOK(c, gin.H{"id": appID, "status": to})
		return
	}

	// 批准推进
	var from, to string
	var step int
	if twoStep {
		switch app.Status {
		case "SUBMITTED":
			if !isAdmin && !approval.HasRole(d.Roles, "R-MANAGER") {
				httpx.WriteErr(c, http.StatusForbidden, 40301, "首审需要 R-MANAGER 角色")
				return
			}
			from, to, step = "SUBMITTED", "COLLEGE_PASSED", 1
		case "COLLEGE_PASSED":
			if !isAdmin && !approval.HasRole(d.Roles, "R-LEADER") {
				httpx.WriteErr(c, http.StatusForbidden, 40301, "终审需要 R-LEADER 角色")
				return
			}
			from, to, step = "COLLEGE_PASSED", "SCHOOL_PASSED", 2
		default:
			httpx.WriteErr(c, http.StatusConflict, 40901, "状态不允许审批")
			return
		}
	} else {
		if app.Status != "SUBMITTED" && app.Status != "COLLEGE_PASSED" {
			httpx.WriteErr(c, http.StatusConflict, 40901, "状态不允许审批")
			return
		}
		from, to, step = app.Status, "SCHOOL_PASSED", 1
	}
	if n, e := h.q.AdvanceApplication(c, estore.AdvanceApplicationParams{ID: appID, TenantID: d.TenantID, ToStatus: to, FromStatus: from}); e != nil || n == 0 {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "审批失败")
		return
	}
	_ = approval.Log(c, h.pool, approval.LogParam{TenantID: d.TenantID, BizType: "APPLICATION",
		BizID: appID, Step: step, ActorID: d.UserID, ActorRole: firstRoleOf(d.Roles), Action: "APPROVE", Comment: b.Comment})
	httpx.WriteOK(c, gin.H{"id": appID, "status": to})
}

// ToProject POST /applications/:id/to-project —— SCHOOL_PASSED → 生成 E_PROJECT 草稿（幂等）。
func (h *Handler) ToProject(c *gin.Context) {
	d := auth.DomainFrom(c)
	appID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	app, err := h.q.GetApplication(c, estore.GetApplicationParams{ID: appID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "申报单不存在")
		return
	}
	if app.Status != "SCHOOL_PASSED" {
		httpx.WriteErr(c, http.StatusConflict, 40901, "仅学校通过的申报单可转立项")
		return
	}
	if app.ProjectID != nil {
		httpx.WriteOK(c, gin.H{"project_id": *app.ProjectID, "duplicated": true})
		return
	}
	plan, err := h.q.GetApplyPlan(c, estore.GetApplyPlanParams{ID: app.PlanID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "申报计划不存在")
		return
	}
	var ptype *string
	if plan.Source != nil && *plan.Source != "" {
		ptype = plan.Source
	}
	p, err := h.q.CreateProjectDraft(c, estore.CreateProjectDraftParams{
		TenantID: d.TenantID, CreatorID: d.UserID, ApplicationID: appID,
		Title: app.ProjectName, ProjectType: ptype, PiUserID: app.ApplicantID,
		TotalBudget: app.ApplyAmount,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "转立项失败")
		return
	}
	_, _ = h.q.BindApplicationProject(c, estore.BindApplicationProjectParams{ID: appID, ProjectID: &p.ID})
	httpx.WriteOK(c, gin.H{"project_id": p.ID, "duplicated": false})
}

var _ = errors.Is
var _ = pgx.ErrNoRows
var _ = strings.TrimSpace
