package project

import (
	"encoding/json"
	"strconv"
	"time"

	estore "github.com/eplugger/ark/internal/modules/project/store"
	"github.com/eplugger/ark/internal/platform/approval"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Handler 承载 E 竖切所有 HTTP 端点。store 层由 sqlc 生成的 estore.Queries 提供，
// pool 传入即开即用（NoRoute passthrough 负责未实现端点兜底，见 router.go）。
type Handler struct {
	q    *estore.Queries
	pool *pgxpool.Pool
	nt   Notifier // T21 预警扫描触达（notify 模块实现，装配期注入）
	tbLLM TaskbookLLM // T22 任务书 PDF 解析 LLM（llm.Client 实现，装配期注入）
}

// NewHandler 用 pgxpool 构造 Handler；pool 由 router.RouterDeps 注入。
func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: estore.New(pool), pool: pool} }

// ---------- 请求/分页 helper（逐字拷自 activity/handler.go） ----------

func pageArgs(c *gin.Context) (page, size, limit, offset int32) {
	p, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	s, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if p < 1 {
		p = 1
	}
	if s < 1 {
		s = 20
	}
	if s > 200 {
		s = 200
	}
	return int32(p), int32(s), int32(s), int32((p - 1) * s)
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

// parseDatePtr 支持 "2006-01-02" 与 RFC3339；解析失败或空 → pgtype.Date{}（!Valid）。
func parseDatePtr(s *string) pgtype.Date {
	if s == nil || *s == "" {
		return pgtype.Date{}
	}
	for _, layout := range []string{"2006-01-02", time.RFC3339, "2006-01-02T15:04:05"} {
		if t, err := time.Parse(layout, *s); err == nil {
			return pgtype.Date{Time: t, Valid: true}
		}
	}
	return pgtype.Date{}
}

// jsonOrNil：[]byte 空则传 nil（让 sqlc 里的 COALESCE 兜底）。
func jsonOrNil(b []byte) []byte {
	if len(b) == 0 {
		return nil
	}
	return b
}

// ---------- 读端点 ----------

// ListMyProjects 契约 GET /project/mine：PI 视角的项目分页。
func (h *Handler) ListMyProjects(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	status := optQuery(c, "status")
	ptype := optQuery(c, "project_type")
	kw := optQuery(c, "kw")
	rows, err := h.q.ListMyProjects(c, estore.ListMyProjectsParams{
		PiUserID: d.UserID, Status: status, ProjectType: ptype, Kw: kw,
		Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountMyProjects(c, estore.CountMyProjectsParams{
		PiUserID: d.UserID, Status: status, ProjectType: ptype, Kw: kw,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIProject(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetProject 契约 GET /project/{id}：单个项目详情。
func (h *Handler) GetProject(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetProject(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "项目不存在")
		return
	}
	httpx.WriteOK(c, ToAPIProject(r))
}

// ListTasks 契约 GET /project/{id}/tasks：项目下 WBS 任务列表。
func (h *Handler) ListTasks(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, err := h.q.ListTasks(c, estore.ListTasksParams{ProjectID: id, Status: optQuery(c, "status")})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToAPITask(r))
	}
	httpx.WriteOK(c, gin.H{"list": out})
}

// ListMilestones 契约 GET /project/{id}/milestones：里程碑列表（供甘特视图）。
func (h *Handler) ListMilestones(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, err := h.q.ListMilestones(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToAPIMilestone(r))
	}
	httpx.WriteOK(c, gin.H{"list": out})
}

// ---------- 动作端点 ----------

type taskUpdateBody struct {
	Status          string `json:"status" binding:"required"`
	OwnerUserID     *int64 `json:"owner_user_id"`
	ProgressPercent int32  `json:"progress_percent"`
}

// UpdateTask 契约 PUT /project/{id}/tasks/{taskId}：更新任务状态/负责人/进度。
func (h *Handler) UpdateTask(c *gin.Context) {
	projectID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	taskID, _ := strconv.ParseInt(c.Param("taskId"), 10, 64)
	var b taskUpdateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	rows, err := h.q.UpdateTask(c, estore.UpdateTaskParams{
		ID: taskID, ProjectID: projectID,
		Status: b.Status, OwnerUserID: b.OwnerUserID, ProgressPercent: b.ProgressPercent,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "更新失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 404, 40401, "任务不存在")
		return
	}
	r, err := h.q.GetTask(c, estore.GetTaskParams{ID: taskID, ProjectID: projectID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "任务不存在")
		return
	}
	httpx.WriteOK(c, ToAPITask(r))
}

type progressReportBody struct {
	Period          string  `json:"period" binding:"required"`
	ReportType      string  `json:"report_type" binding:"required"`
	ContentRich     *string `json:"content_rich"`
	ProgressPercent int32   `json:"progress_percent"`
	IssuesText      *string `json:"issues_text"`
	NextPlan        *string `json:"next_plan"`
	AttachmentIDs   []int64 `json:"attachment_ids"`
}

// CreateProgressReport 契约 POST /project/{id}/progress-report。
func (h *Handler) CreateProgressReport(c *gin.Context) {
	d := auth.DomainFrom(c)
	projectID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b progressReportBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if _, err := h.q.GetProject(c, projectID); err != nil {
		httpx.WriteErr(c, 404, 40401, "项目不存在")
		return
	}
	att, _ := json.Marshal(b.AttachmentIDs)
	r, err := h.q.CreateProgressReport(c, estore.CreateProgressReportParams{
		Code: "", TenantID: d.TenantID, CreatorID: d.UserID, ProjectID: projectID,
		Period: b.Period, ReportType: b.ReportType, ContentRich: b.ContentRich,
		ProgressPercent: b.ProgressPercent, IssuesText: b.IssuesText, NextPlan: b.NextPlan,
		AttachmentIds: jsonOrNil(att),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIProgressReport(r))
}

type midCheckBody struct {
	CheckRound int     `json:"check_round" binding:"required"`
	CheckDate  *string `json:"check_date"`
	PlanID     *int64  `json:"plan_id"`
	TemplateID *int64  `json:"template_id"`
}

// CreateMidCheck 契约 POST /project/{id}/mid-check。
func (h *Handler) CreateMidCheck(c *gin.Context) {
	d := auth.DomainFrom(c)
	projectID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b midCheckBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if _, err := h.q.GetProject(c, projectID); err != nil {
		httpx.WriteErr(c, 404, 40401, "项目不存在")
		return
	}
	r, err := h.q.CreateMidCheck(c, estore.CreateMidCheckParams{
		Code: "", TenantID: d.TenantID, CreatorID: d.UserID, ProjectID: projectID,
		CheckRound: int32(b.CheckRound), CheckDate: parseDatePtr(b.CheckDate),
		PlanID: b.PlanID, TemplateID: b.TemplateID, ExpertIds: nil,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIMidCheck(r))
}

type changeRequestBody struct {
	ChangeType string          `json:"change_type" binding:"required"`
	OldValue   json.RawMessage `json:"old_value"`
	NewValue   json.RawMessage `json:"new_value"`
	Reason     *string         `json:"reason"`
}

// CreateChangeRequest 契约 POST /project/{id}/change-request。
func (h *Handler) CreateChangeRequest(c *gin.Context) {
	d := auth.DomainFrom(c)
	projectID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b changeRequestBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if _, err := h.q.GetProject(c, projectID); err != nil {
		httpx.WriteErr(c, 404, 40401, "项目不存在")
		return
	}
	r, err := h.q.CreateChangeRequest(c, estore.CreateChangeRequestParams{
		Code: "", TenantID: d.TenantID, CreatorID: d.UserID, ProjectID: projectID,
		ChangeType: b.ChangeType, OldValue: jsonOrNil(b.OldValue), NewValue: jsonOrNil(b.NewValue),
		Reason: b.Reason,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIChangeRequest(r))
}

// ApproveChangeRequest 契约 POST /project/{id}/change-request/{changeId}/approve。
// 状态机：SUBMITTED/APPROVING → APPROVED。非法迁移/未命中 → 40901。
func (h *Handler) ApproveChangeRequest(c *gin.Context) {
	projectID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	changeID, _ := strconv.ParseInt(c.Param("changeId"), 10, 64)
	d := auth.DomainFrom(c)
	var b struct {
		Comment string `json:"comment"`
	}
	_ = c.ShouldBindJSON(&b)
	code, msg := h.approveChangeOne(c, d, projectID, changeID, b.Comment)
	if code != 0 {
		httpx.WriteErr(c, code, errCodeOf(code), msg)
		return
	}
	r, err := h.q.GetChangeRequest(c, changeID)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "变更单不存在")
		return
	}
	httpx.WriteOK(c, ToAPIChangeRequest(r))
}

// approveChangeOne 单条变更审批核心（T19 两级可配）：
//   - 两级开关 off（默认）：SUBMITTED/APPROVING → EFFECTIVE（单步，行为不变）
//   - on：首审 R-MANAGER SUBMITTED→APPROVING；终审 R-LEADER APPROVING→EFFECTIVE（R-ADMIN 直通）
//
// 全部动作写 sys_approval_log（biz_type=CHANGE_REQUEST）。
// 返回 (httpCode, errInfo)；成功 httpCode=0。
func (h *Handler) approveChangeOne(c *gin.Context, d auth.Domain, projectID, changeID int64, comment string) (int, string) {
	row, err := h.q.GetChangeRequest(c, changeID)
	if err != nil {
		return 404, "变更单不存在"
	}
	if row.ProjectID != projectID {
		return 404, "变更单不存在"
	}
	twoStep := approval.Enabled()
	isAdmin := approval.HasRole(d.Roles, "R-ADMIN")
	// 角色/状态校验
	if twoStep {
		switch row.Status {
		case "SUBMITTED":
			if !isAdmin && !approval.HasRole(d.Roles, approval.TwoStep{FirstRole: "R-MANAGER", SecondRole: "R-LEADER"}.FirstRole) {
				return 403, "首审需要 R-MANAGER 角色"
			}
		case "APPROVING":
			if !isAdmin && !approval.HasRole(d.Roles, approval.TwoStep{FirstRole: "R-MANAGER", SecondRole: "R-LEADER"}.SecondRole) {
				return 403, "终审需要 R-LEADER 角色"
			}
		default:
			return 409, "状态不允许审批"
		}
	} else if row.Status != "SUBMITTED" && row.Status != "APPROVING" {
		return 409, "状态不允许或变更单不存在"
	}
	// 推进
	var toStatus string
	var step int
	if twoStep && row.Status == "SUBMITTED" {
		toStatus, step = "APPROVING", 1
	} else {
		toStatus, step = "EFFECTIVE", 2
		if !twoStep {
			step = 1
		}
	}
	n, err := h.q.AdvanceChangeRequest(c, estore.AdvanceChangeRequestParams{
		ID: changeID, ProjectID: projectID, ToStatus: toStatus, FromStatus: row.Status,
	})
	if err != nil {
		return 500, "审批失败"
	}
	if n == 0 {
		return 409, "状态不允许或变更单不存在"
	}
	// 审核流水（best-effort）
	_ = approval.Log(c, h.pool, approval.LogParam{
		TenantID: d.TenantID, BizType: "CHANGE_REQUEST", BizID: changeID,
		Step: step, ActorID: d.UserID, ActorRole: firstRoleOf(d.Roles), Action: "APPROVE", Comment: comment,
	})
	return 0, ""
}

// ApproveChangeBatch POST /projects/approve-batch {ids:[], action, comment}
// 批量变更单审批（ids 为变更单 id）：逐条事务、逐条结果 {id, ok, err}。
func (h *Handler) ApproveChangeBatch(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		IDs     []int64 `json:"ids" binding:"required,min=1"`
		Action  string  `json:"action" binding:"required"`
		Comment string  `json:"comment"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "参数错误："+err.Error())
		return
	}
	if b.Action != "APPROVE" && b.Action != "REJECT" {
		httpx.WriteErr(c, 400, 40001, "action 仅支持 APPROVE/REJECT")
		return
	}
	results := make([]gin.H, 0, len(b.IDs))
	okN := 0
	for _, id := range b.IDs {
		// 变更单归属项目未知 → 先查再以 projectID 审批
		row, err := h.q.GetChangeRequest(c, id)
		if err != nil {
			results = append(results, gin.H{"id": id, "ok": false, "err": "变更单不存在"})
			continue
		}
		var code int
		var msg string
		if b.Action == "REJECT" {
			code, msg = h.rejectChangeOne(c, d, row.ProjectID, id, b.Comment)
		} else {
			code, msg = h.approveChangeOne(c, d, row.ProjectID, id, b.Comment)
		}
		if code == 0 {
			okN++
			results = append(results, gin.H{"id": id, "ok": true})
		} else {
			results = append(results, gin.H{"id": id, "ok": false, "err": msg})
		}
	}
	httpx.WriteOK(c, gin.H{"total": len(b.IDs), "ok": okN, "results": results})
}

// rejectChangeOne 变更单驳回：SUBMITTED/APPROVING → REJECTED + 流水。
func (h *Handler) rejectChangeOne(c *gin.Context, d auth.Domain, projectID, changeID int64, comment string) (int, string) {
	row, err := h.q.GetChangeRequest(c, changeID)
	if err != nil {
		return 404, "变更单不存在"
	}
	if row.ProjectID != projectID || (row.Status != "SUBMITTED" && row.Status != "APPROVING") {
		return 409, "状态不允许驳回"
	}
	n, err := h.q.AdvanceChangeRequest(c, estore.AdvanceChangeRequestParams{
		ID: changeID, ProjectID: projectID, ToStatus: "REJECTED", FromStatus: row.Status,
	})
	if err != nil || n == 0 {
		return 500, "驳回失败"
	}
	_ = approval.Log(c, h.pool, approval.LogParam{
		TenantID: d.TenantID, BizType: "CHANGE_REQUEST", BizID: changeID,
		Step: 1, ActorID: d.UserID, ActorRole: firstRoleOf(d.Roles), Action: "REJECT", Comment: comment,
	})
	return 0, ""
}

// firstRoleOf 取第一个角色（流水展示用；无角色返回空）。
func firstRoleOf(roles []string) string {
	if len(roles) > 0 {
		return roles[0]
	}
	return ""
}

// errCodeOf http 状态码 → 业务错误码。
func errCodeOf(httpCode int) int {
	switch httpCode {
	case 404:
		return 40401
	case 403:
		return 40301
	case 409:
		return 40901
	default:
		return 50001
	}
}

type finalAcceptBody struct {
	FinanceReportID *int64 `json:"finance_report_id"`
}

// CreateFinalAccept 契约 POST /project/{id}/final-accept。
func (h *Handler) CreateFinalAccept(c *gin.Context) {
	d := auth.DomainFrom(c)
	projectID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b finalAcceptBody
	// 允许空 body（finance_report_id 可空）；绑定失败不阻断，只吞掉错误按空 body 处理。
	_ = c.ShouldBindJSON(&b)
	if _, err := h.q.GetProject(c, projectID); err != nil {
		httpx.WriteErr(c, 404, 40401, "项目不存在")
		return
	}
	r, err := h.q.CreateFinalAccept(c, estore.CreateFinalAcceptParams{
		Code: "", TenantID: d.TenantID, CreatorID: d.UserID, ProjectID: projectID,
		FinanceReportID: b.FinanceReportID,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIFinalAccept(r))
}
