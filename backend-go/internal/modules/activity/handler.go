package activity

import (
	"encoding/json"
	"fmt"
	"strconv"
	"time"

	vstore "github.com/eplugger/ark/internal/modules/activity/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct{ q *vstore.Queries }

func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: vstore.New(pool)} }

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

func optInt64(c *gin.Context, k string) *int64 {
	if v := c.Query(k); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return &n
		}
	}
	return nil
}

// bindActivity 解析 ActivityRequest（create/update 共用）。
type activityBody struct {
	ActivityType      string          `json:"activity_type" binding:"required"`
	Title             string          `json:"title" binding:"required"`
	Level             *string         `json:"level"`
	HostMode          *string         `json:"host_mode"`
	Theme             *string         `json:"theme"`
	StartAt           *string         `json:"start_at"`
	EndAt             *string         `json:"end_at"`
	Venue             *string         `json:"venue"`
	OnlineURL         *string         `json:"online_url"`
	HostUnit          *string         `json:"host_unit"`
	OrganizerDeptID   *int64          `json:"organizer_dept_id"`
	InvitedExperts    json.RawMessage `json:"invited_experts"`
	EstAttendees      *int32          `json:"est_attendees"`
	ProjectID         *int64          `json:"project_id"`
	BudgetSubjectCode *string         `json:"budget_subject_code"`
	BudgetAmount      *string         `json:"budget_amount"`
	Agenda            json.RawMessage `json:"agenda"`
	AttachmentIDs     json.RawMessage `json:"attachment_ids"`
	SecurityLevel     *string         `json:"security_level"`
	Remark            *string         `json:"remark"`
}

func parseTS(s *string) *time.Time {
	if s == nil || *s == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, *s)
	if err != nil {
		return nil
	}
	return &t
}

func jsonOrEmpty(b json.RawMessage) []byte {
	if len(b) == 0 {
		return []byte("[]")
	}
	return b
}

func numeric(s *string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != nil && *s != "" {
		_ = n.Scan(*s)
	}
	return n
}

// tsOf 把 *time.Time 转成生成物用的 pgtype.Timestamptz；nil → NULL(Valid=false)，使时间过滤被忽略。
func tsOf(t *time.Time) pgtype.Timestamptz {
	if t == nil {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: *t, Valid: true}
}

// toActivity 把 sqlc 生成的 GetActivityRow 逐字段转成 vstore.Activity 供 mapper 使用。
// 各 XxxRow（List/Create/Update/Transition/MarkHold/MarkArchive/MarkCancel/Calendar）字段
// 集合与顺序完全一致，均与 GetActivityRow 结构相同，故调用点先转 GetActivityRow 再走此函数。
func toActivity(r vstore.GetActivityRow) vstore.Activity {
	return vstore.Activity{
		ID: r.ID, Code: r.Code, TenantID: r.TenantID, Status: r.Status, Deleted: r.Deleted,
		CreatorID: r.CreatorID, ModifierID: r.ModifierID, CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt,
		Remark: r.Remark, SecurityLevel: r.SecurityLevel, ActivityType: r.ActivityType, Level: r.Level,
		HostMode: r.HostMode, Title: r.Title, Theme: r.Theme, StartAt: r.StartAt, EndAt: r.EndAt,
		Venue: r.Venue, OnlineUrl: r.OnlineUrl, HostUnit: r.HostUnit, OrganizerDeptID: r.OrganizerDeptID,
		InvitedExperts: r.InvitedExperts, EstAttendees: r.EstAttendees, ProjectID: r.ProjectID,
		BudgetSubjectCode: r.BudgetSubjectCode, BudgetAmount: r.BudgetAmount, Agenda: r.Agenda,
		AttachmentIds: r.AttachmentIds, MinutesRich: r.MinutesRich, SignInCount: r.SignInCount,
		HoldProofIds: r.HoldProofIds, SubmitAt: r.SubmitAt, ApproveAt: r.ApproveAt, ArchiveAt: r.ArchiveAt,
		CancelAt: r.CancelAt, CancelReason: r.CancelReason,
	}
}

func (h *Handler) ListActivities(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	var from, to *time.Time
	if f := optQuery(c, "from"); f != nil {
		if t, err := time.Parse("2006-01-02", *f); err == nil {
			from = &t
		}
	}
	if t := optQuery(c, "to"); t != nil {
		if tt, err := time.Parse("2006-01-02", *t); err == nil {
			to = &tt
		}
	}
	var kw *string
	if v := optQuery(c, "keyword"); v != nil {
		w := "%" + *v + "%"
		kw = &w
	}
	var kwStr string
	if kw != nil {
		kwStr = *kw
	}
	var dept int64
	if p := optInt64(c, "organizer_dept_id"); p != nil {
		dept = *p
	}
	rows, err := h.q.ListActivities(c, vstore.ListActivitiesParams{
		TenantID: d.TenantID, Column2: c.Query("status"), Column3: c.Query("activity_type"),
		Column4: c.Query("level"), Column5: c.Query("host_mode"), Column6: dept,
		Column7: tsOf(from), Column8: tsOf(to), Column9: kwStr, Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountActivities(c, vstore.CountActivitiesParams{
		TenantID: d.TenantID, Column2: c.Query("status"), Column3: c.Query("activity_type"),
		Column4: c.Query("level"), Column5: c.Query("host_mode"), Column6: dept,
		Column7: tsOf(from), Column8: tsOf(to), Column9: kwStr,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

func (h *Handler) GetActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	parts, _ := h.q.ListParticipants(c, vstore.ListParticipantsParams{ActivityID: id, TenantID: d.TenantID})
	revs, _ := h.q.ListReviews(c, vstore.ListReviewsParams{ActivityID: id, TenantID: d.TenantID})
	plist := make([]map[string]any, 0, len(parts))
	for _, p := range parts {
		plist = append(plist, ToAPIParticipant(p))
	}
	rlis := make([]map[string]any, 0, len(revs))
	for _, rv := range revs {
		rlis = append(rlis, ToAPIReview(rv))
	}
	out := ToAPIActivity(toActivity(vstore.GetActivityRow(r)))
	out["participants"] = plist
	out["reviews"] = rlis
	httpx.WriteOK(c, out)
}

func (h *Handler) CreateActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	var body activityBody
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	sl := "INTERNAL"
	if body.SecurityLevel != nil && *body.SecurityLevel != "" {
		sl = *body.SecurityLevel
	}
	r, err := h.q.CreateActivity(c, vstore.CreateActivityParams{
		TenantID: d.TenantID, Status: "DRAFT", SecurityLevel: sl, CreatorID: d.UserID,
		Code: nil, ActivityType: body.ActivityType, Level: body.Level, HostMode: body.HostMode,
		Title: body.Title, Theme: body.Theme, StartAt: parseTS(body.StartAt), EndAt: parseTS(body.EndAt),
		Venue: body.Venue, OnlineUrl: body.OnlineURL, HostUnit: body.HostUnit, OrganizerDeptID: body.OrganizerDeptID,
		Column17: jsonOrEmpty(body.InvitedExperts), EstAttendees: body.EstAttendees, ProjectID: body.ProjectID,
		BudgetSubjectCode: body.BudgetSubjectCode, Column21: numeric(body.BudgetAmount),
		Column22: jsonOrEmpty(body.Agenda), Column23: jsonOrEmpty(body.AttachmentIDs), Remark: body.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	// M0 code 分配：ACT-<年>-<id 6 位补零>，回写（不引编号中心，见 §6 注）
	code := fmt.Sprintf("ACT-%d-%06d", time.Now().Year(), r.ID)
	_ = code // 见步骤 2：若已加 AssignCode 查询则回写；否则 ToAPI 里 code=null 由 passthrough 演示
	httpx.WriteOK(c, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
}

func (h *Handler) UpdateActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body activityBody
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	sl := "INTERNAL"
	if body.SecurityLevel != nil && *body.SecurityLevel != "" {
		sl = *body.SecurityLevel
	}
	r, err := h.q.UpdateActivity(c, vstore.UpdateActivityParams{
		ID: id, TenantID: d.TenantID, ActivityType: body.ActivityType, Level: body.Level,
		HostMode: body.HostMode, Title: body.Title, Theme: body.Theme, StartAt: parseTS(body.StartAt),
		EndAt: parseTS(body.EndAt), Venue: body.Venue, OnlineUrl: body.OnlineURL, HostUnit: body.HostUnit,
		OrganizerDeptID: body.OrganizerDeptID, Column14: jsonOrEmpty(body.InvitedExperts),
		EstAttendees: body.EstAttendees, ProjectID: body.ProjectID, BudgetSubjectCode: body.BudgetSubjectCode,
		Column18: numeric(body.BudgetAmount), Column19: jsonOrEmpty(body.Agenda),
		Column20: jsonOrEmpty(body.AttachmentIDs), SecurityLevel: sl, Remark: body.Remark, ModifierID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "活动不存在或状态不可编辑（仅 DRAFT/RETURNED）")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
}

func (h *Handler) DeleteActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	n, err := h.q.SoftDeleteActivity(c, vstore.SoftDeleteActivityParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}

// 合法迁移表（硬编码状态机，端点驱动）。键 = from，值 = 允许 to 集合。
var allowedTransitions = map[string]map[string]bool{
	"DRAFT":       {"SUBMITTED": true, "CANCELLED": true},
	"RETURNED":    {"SUBMITTED": true, "CANCELLED": true},
	"SUBMITTED":   {"DEPT_REVIEW": true, "APPROVED": true, "REJECTED": true, "RETURNED": true, "CANCELLED": true},
	"DEPT_REVIEW": {"APPROVED": true, "REJECTED": true, "RETURNED": true, "CANCELLED": true},
	"APPROVED":    {"HELD": true, "CANCELLED": true},
	"HELD":        {"ARCHIVED": true},
}

// 单级审批：APPROVE→APPROVED 或进入下一级；REJECT→REJECTED；RETURN→RETURNED。
func nextOnApprove(from string, level int16, action string) (to string, ok bool) {
	switch action {
	case "REJECT":
		if from == "SUBMITTED" || from == "DEPT_REVIEW" {
			return "REJECTED", true
		}
	case "RETURN":
		if from == "SUBMITTED" || from == "DEPT_REVIEW" {
			return "RETURNED", true
		}
	case "APPROVE":
		if from == "SUBMITTED" {
			if level <= 1 {
				return "DEPT_REVIEW", true // 部门一级通过后进入院所级
			}
			return "APPROVED", true
		}
		if from == "DEPT_REVIEW" {
			return "APPROVED", true
		}
	}
	return "", false
}

func (h *Handler) SubmitActivity(c *gin.Context) { h.transition(c, "SUBMITTED") }

func (h *Handler) transition(c *gin.Context, to string) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	cur, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	if !allowedTransitions[cur.Status][to] {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移："+cur.Status+"→"+to)
		return
	}
	r, err := h.q.TransitionStatus(c, vstore.TransitionStatusParams{
		ID: id, TenantID: d.TenantID, Status: cur.Status, Status_2: to, ModifierID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "状态迁移失败")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
}

func (h *Handler) ApproveActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		ReviewLevel *int16  `json:"review_level"`
		Action      string  `json:"action" binding:"required"`
		Opinion     *string `json:"opinion"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	level := int16(1)
	if body.ReviewLevel != nil {
		level = *body.ReviewLevel
	}
	cur, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	to, ok := nextOnApprove(cur.Status, level, body.Action)
	if !ok {
		httpx.WriteErr(c, 409, 40901, "非法审批：当前态 "+cur.Status+" 不支持该动作/层级")
		return
	}
	// 写留痕
	_, _ = h.q.InsertReview(c, vstore.InsertReviewParams{
		ActivityID: id, ReviewLevel: level, ReviewerID: d.UserID, Action: body.Action, Opinion: body.Opinion, TenantID: d.TenantID,
	})
	r, err := h.q.TransitionStatus(c, vstore.TransitionStatusParams{
		ID: id, TenantID: d.TenantID, Status: cur.Status, Status_2: to, ModifierID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "状态迁移失败")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
}

func (h *Handler) HoldActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		SignInCount  *int32   `json:"sign_in_count"`
		HoldProofIDs []string `json:"hold_proof_ids"`
	}
	_ = c.ShouldBindJSON(&body)
	var proofs []byte
	if len(body.HoldProofIDs) > 0 {
		proofs, _ = json.Marshal(body.HoldProofIDs)
	}
	r, err := h.q.MarkHold(c, vstore.MarkHoldParams{
		ID: id, TenantID: d.TenantID, SignInCount: body.SignInCount, Column4: proofs, ModifierID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "仅 APPROVED 可标记举办")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
}

func (h *Handler) ArchiveActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		MinutesRich *string `json:"minutes_rich"`
	}
	_ = c.ShouldBindJSON(&body)
	if body.MinutesRich == nil || *body.MinutesRich == "" {
		httpx.WriteErr(c, 400, 40002, "归档需填纪要")
		return
	}
	r, err := h.q.MarkArchive(c, vstore.MarkArchiveParams{
		ID: id, TenantID: d.TenantID, MinutesRich: body.MinutesRich, ModifierID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "仅 HELD 可归档")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
}

func (h *Handler) CancelActivity(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		CancelReason *string `json:"cancel_reason"`
	}
	_ = c.ShouldBindJSON(&body)
	r, err := h.q.MarkCancel(c, vstore.MarkCancelParams{
		ID: id, TenantID: d.TenantID, CancelReason: body.CancelReason, ModifierID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "终态不可取消")
		return
	}
	httpx.WriteOK(c, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
}

func (h *Handler) ActivityCalendar(c *gin.Context) {
	d := auth.DomainFrom(c)
	month := c.DefaultQuery("month", time.Now().Format("2006-01"))
	start, err := time.Parse("2006-01", month)
	if err != nil {
		httpx.WriteErr(c, 400, 40003, "month 需 YYYY-MM")
		return
	}
	end := start.AddDate(0, 1, 0)
	rows, _ := h.q.ListCalendar(c, vstore.ListCalendarParams{TenantID: d.TenantID, StartAt: &start, StartAt_2: &end})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIActivity(toActivity(vstore.GetActivityRow(r))))
	}
	httpx.WriteOK(c, gin.H{"month": month, "list": list})
}

func (h *Handler) ActivityStats(c *gin.Context) {
	d := auth.DomainFrom(c)
	groupBy := c.DefaultQuery("group_by", "activity_type")
	type bucket struct {
		Key   string `json:"key"`
		Count int32  `json:"count"`
	}
	buckets := make([]bucket, 0)
	switch groupBy {
	case "level":
		rows, err := h.q.StatsByLevel(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, 500, 50004, "统计失败")
			return
		}
		for _, r := range rows {
			// StatsByLevelRow.Key 源自可空 level 列 → 生成物为 *string；其余分支为 string。
			key := ""
			if r.Key != nil {
				key = *r.Key
			}
			buckets = append(buckets, bucket{Key: key, Count: r.Count})
		}
	case "organizer_dept_id":
		rows, err := h.q.StatsByDept(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, 500, 50004, "统计失败")
			return
		}
		for _, r := range rows {
			buckets = append(buckets, bucket{Key: r.Key, Count: r.Count})
		}
	case "month":
		rows, err := h.q.StatsByMonth(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, 500, 50004, "统计失败")
			return
		}
		for _, r := range rows {
			buckets = append(buckets, bucket{Key: r.Key, Count: r.Count})
		}
	default:
		rows, err := h.q.StatsByType(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, 500, 50004, "统计失败")
			return
		}
		for _, r := range rows {
			buckets = append(buckets, bucket{Key: r.Key, Count: r.Count})
		}
	}
	httpx.WriteOK(c, gin.H{"buckets": buckets})
}

func (h *Handler) ListParticipants(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, _ := h.q.ListParticipants(c, vstore.ListParticipantsParams{ActivityID: id, TenantID: d.TenantID})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIParticipant(r))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

func (h *Handler) AddParticipant(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		UserID      *int64  `json:"user_id"`
		GuestName   *string `json:"guest_name"`
		Role        string  `json:"role" binding:"required"`
		ReportTitle *string `json:"report_title"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if body.UserID == nil && (body.GuestName == nil || *body.GuestName == "") {
		httpx.WriteErr(c, 400, 40004, "user_id 与 guest_name 至少给一个")
		return
	}
	// 归属校验：活动须存在且属本租户
	if _, err := h.q.GetActivity(c, vstore.GetActivityParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "活动不存在")
		return
	}
	r, err := h.q.AddParticipant(c, vstore.AddParticipantParams{
		ActivityID: id, UserID: body.UserID, GuestName: body.GuestName, Role: body.Role, ReportTitle: body.ReportTitle, TenantID: d.TenantID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "参与人重复或写入冲突")
		return
	}
	httpx.WriteOK(c, ToAPIParticipant(r))
}

func (h *Handler) RemoveParticipant(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	pid, _ := strconv.ParseInt(c.Param("pid"), 10, 64)
	n, err := h.q.DeleteParticipant(c, vstore.DeleteParticipantParams{ID: pid, ActivityID: id, TenantID: d.TenantID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "参与人不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": pid, "deleted": true})
}
