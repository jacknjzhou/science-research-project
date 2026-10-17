package expertreview

import (
	"encoding/json"
	"strconv"
	"time"

	nstore "github.com/eplugger/ark/internal/modules/expertreview/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
)

// strNumeric：契约 string(NUMERIC 精度) → pgtype.Numeric；空 → !Valid。
func strNumeric(s string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != "" {
		_ = n.Scan(s)
	}
	return n
}

// ---------- 评审任务 CRUD ----------

// ListReviews 契约 GET /reviews：biz_type/status 筛选的分页评审列表。
func (h *Handler) ListReviews(c *gin.Context) {
	page, size, limit, offset := pageArgs(c)
	p := nstore.ListReviewsParams{
		BizType: optQuery(c, "biz_type"),
		Status:  optQuery(c, "status"),
		Limit:   limit, Offset: offset,
	}
	rows, err := h.q.ListReviews(c, p)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountReviews(c, nstore.CountReviewsParams{BizType: p.BizType, Status: p.Status})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIReviewTask(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetReview 契约 GET /reviews/{id}：评审任务（不含名单）。
func (h *Handler) GetReview(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	httpx.WriteOK(c, ToAPIReviewTask(r))
}

type reviewCreateBody struct {
	BizType       string          `json:"biz_type" binding:"required"`
	TargetType    *string         `json:"target_type"`
	TargetID      *int64          `json:"target_id"`
	ProjectID     *int64          `json:"project_id"`
	Title         string          `json:"title" binding:"required"`
	ReviewMethod  *string         `json:"review_method"`
	PlanCount     int32           `json:"plan_count"`
	DrawRule      json.RawMessage `json:"draw_rule"`
	SecurityLevel *string         `json:"security_level"`
}

// CreateReview 契约 POST /reviews：新建评审任务（落 DRAFT）。
// code 号段（RVW-年-序）待编号中心接线前留空，与 R 同款（M0 简化）。plan_count<=0 兜底 3。
func (h *Handler) CreateReview(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b reviewCreateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if b.PlanCount <= 0 {
		b.PlanCount = 3
	}
	r, err := h.q.CreateReviewTask(c, nstore.CreateReviewTaskParams{
		Code:          "",
		TenantID:      d.TenantID,
		CreatorID:     d.UserID,
		SecurityLevel: b.SecurityLevel,
		BizType:       b.BizType,
		TargetType:    b.TargetType,
		TargetID:      b.TargetID,
		ProjectID:     b.ProjectID,
		Title:         b.Title,
		ReviewMethod:  b.ReviewMethod,
		PlanCount:     b.PlanCount,
		DrawRule:      jsonOrNil(b.DrawRule),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIReviewTask(r))
}

// CancelReview 契约 DELETE /reviews/{id}：取消评审（→CANCELLED）。
func (h *Handler) CancelReview(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, err := h.q.UpdateReviewStatus(c, nstore.UpdateReviewStatusParams{Status: "CANCELLED", ID: id})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "取消失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	httpx.WriteOK(c, nil)
}

// ---------- 抽取 / 邀请 / 应允 / 开始 ----------

// buildCandidates 从 n_expert 活动专家构造抽取候选（解析 field_tags/回避列 jsonb）。
func buildCandidates(experts []nstore.Expert) []candidate {
	out := make([]candidate, 0, len(experts))
	for _, e := range experts {
		var fields, avoidOrg []string
		var avoidUsr []int64
		_ = json.Unmarshal(e.FieldTags, &fields)
		_ = json.Unmarshal(e.AvoidOrgs, &avoidOrg)
		_ = json.Unmarshal(e.AvoidPersonIds, &avoidUsr)
		var uid int64
		if e.UserID != nil {
			uid = *e.UserID
		}
		var org string
		if e.OrgName != nil {
			org = *e.OrgName
		}
		out = append(out, candidate{ExpertID: e.ID, UserID: uid, OrgName: org, Fields: fields, AvoidOrg: avoidOrg, AvoidUsr: avoidUsr})
	}
	return out
}

type drawBody struct {
	Method    string `json:"method"`
	PlanCount int32  `json:"plan_count"`
	Seed      *int64 `json:"seed"`
}

// DrawExperts 契约 POST /reviews/{id}/draw：回避过滤 + 确定性随机 → DRAFT→DRAWN。
// 回避快照取自 task.draw_rule 的 exclude_user_ids/exclude_orgs（建单时由发起人/PI 录入，
// 使 N 自包含、不跨模块读 E）；seed 缺省用时钟，测试/复现可传固定值（铁律 11）。
func (h *Handler) DrawExperts(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b drawBody
	_ = c.ShouldBindJSON(&b) // 允许空 body
	task, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	var rule drawRule
	_ = json.Unmarshal(task.DrawRule, &rule)
	experts, err := h.q.ActiveExpertsForDraw(c)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	pool := buildCandidates(experts)
	n := task.PlanCount
	if b.PlanCount > 0 {
		n = b.PlanCount
	}
	seed := time.Now().UnixNano()
	if b.Seed != nil {
		seed = *b.Seed
	}
	drawn := drawExperts(pool, rule, int(n), seed)
	seat := int32(0)
	for _, eid := range drawn {
		seat++
		if _, err := h.q.InsertInvitation(c, nstore.InsertInvitationParams{
			TenantID: task.TenantID, TaskID: task.ID, ExpertID: eid,
			SeatNo: seat, AvoidHit: false, Response: "PENDING",
		}); err != nil {
			httpx.WriteErr(c, 500, 50002, "落库失败")
			return
		}
	}
	if _, err := h.q.MarkReviewDrawn(c, id); err != nil {
		httpx.WriteErr(c, 500, 50002, "状态更新失败")
		return
	}
	httpx.WriteOK(c, gin.H{"drawn": drawn, "count": len(drawn)})
}

// InviteExperts 契约 POST /reviews/{id}/invite：DRAWN→INVITING；
// 若 biz_type=MID_CHECK，把拟邀专家 user_id 经 E 单一写者回填 E_MID_CHECK.expert_ids。
func (h *Handler) InviteExperts(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	task, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	if _, err := h.q.UpdateReviewStatus(c, nstore.UpdateReviewStatusParams{Status: "INVITING", ID: id}); err != nil {
		httpx.WriteErr(c, 500, 50002, "状态更新失败")
		return
	}
	if task.BizType == "MID_CHECK" && task.TargetID != nil {
		invites, _ := h.q.ListInvitations(c, id)
		userIDs := make([]int64, 0, len(invites))
		for _, iv := range invites {
			if ex, err := h.q.GetExpert(c, iv.ExpertID); err == nil && ex.UserID != nil {
				userIDs = append(userIDs, *ex.UserID)
			}
		}
		if len(userIDs) > 0 {
			if err := h.e.SetMidCheckExperts(c, *task.TargetID, userIDs); err != nil {
				httpx.WriteErr(c, 500, 50003, "回写评审专家失败")
				return
			}
		}
	}
	httpx.WriteOK(c, nil)
}

type respondBody struct {
	ExpertID int64 `json:"expert_id"`
}

// AcceptInvitation 契约 POST /reviews/{id}/accept：接受邀请；达法定人数(plan_count)→QUORUM。
func (h *Handler) AcceptInvitation(c *gin.Context) {
	h.respond(c, "ACCEPT")
}

// DeclineInvitation 契约 POST /reviews/{id}/decline：拒绝邀请。
func (h *Handler) DeclineInvitation(c *gin.Context) {
	h.respond(c, "DECLINE")
}

func (h *Handler) respond(c *gin.Context, resp string) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	task, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	var b respondBody
	_ = c.ShouldBindJSON(&b)
	if b.ExpertID == 0 {
		httpx.WriteErr(c, 400, 40001, "缺少 expert_id")
		return
	}
	rows, err := h.q.RespondInvitation(c, nstore.RespondInvitationParams{Response: resp, TaskID: id, ExpertID: b.ExpertID})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "操作失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 404, 40402, "邀请不存在")
		return
	}
	if resp == "ACCEPT" {
		accepted, _ := h.q.CountAccepted(c, id)
		if accepted >= int64(task.PlanCount) {
			_, _ = h.q.UpdateReviewStatus(c, nstore.UpdateReviewStatusParams{Status: "QUORUM", ID: id})
		}
	}
	httpx.WriteOK(c, nil)
}

// StartReview 契约 POST /reviews/{id}/start：QUORUM→IN_REVIEW。
func (h *Handler) StartReview(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, err := h.q.MarkReviewStarted(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "状态更新失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	httpx.WriteOK(c, nil)
}

// ---------- 打分 / 结论 / 评审费 / 详情 ----------

type scoreSubmitBody struct {
	ExpertID        int64           `json:"expert_id" binding:"required"`
	TargetType      *string         `json:"target_type"`
	TargetID        *int64          `json:"target_id"`
	DimensionScores json.RawMessage `json:"dimension_scores"`
	TotalScore      string          `json:"total_score" binding:"required"`
	Comment         *string         `json:"comment"`
	Status          string          `json:"status"`
}

// SubmitScore 契约 POST /reviews/{id}/scores：专家提交打分（UpsertScore）；
// 已提交数达已接受数→COLLECTING。
func (h *Handler) SubmitScore(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	task, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	var b scoreSubmitBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	sc, err := h.q.UpsertScore(c, nstore.UpsertScoreParams{
		TenantID: task.TenantID, TaskID: id, ExpertID: b.ExpertID,
		TargetType: b.TargetType, TargetID: b.TargetID,
		DimensionScores: jsonOrNil(b.DimensionScores),
		TotalScore:      strNumeric(b.TotalScore),
		Comment:         b.Comment,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "提交失败")
		return
	}
	submitted, _ := h.q.CountScores(c, id)
	accepted, _ := h.q.CountAccepted(c, id)
	if accepted > 0 && submitted >= accepted {
		_, _ = h.q.UpdateReviewStatus(c, nstore.UpdateReviewStatusParams{Status: "COLLECTING", ID: id})
	}
	httpx.WriteOK(c, ToAPIScore(sc))
}

type concludeBody struct {
	Conclusion string `json:"conclusion" binding:"required"`
}

// buildScoreSummary 汇总打分：count/avg/per_expert，供 score_summary 落库与回写。
func (h *Handler) buildScoreSummary(c *gin.Context, taskID int64) (map[string]any, error) {
	scores, err := h.q.ListScores(c, taskID)
	if err != nil {
		return nil, err
	}
	per := make([]map[string]any, 0, len(scores))
	var sum float64
	var cnt int
	for _, s := range scores {
		f, ferr := s.TotalScore.Float64Value()
		var val float64
		if ferr == nil && f.Valid {
			val = f.Float64
			sum += val
			cnt++
		}
		per = append(per, map[string]any{
			"expert_id":   s.ExpertID,
			"total_score": numStrOrNil(s.TotalScore, 2),
			"status":      s.Status,
		})
	}
	avg := "0"
	if cnt > 0 {
		avg = strconv.FormatFloat(sum/float64(cnt), 'f', 2, 64)
	}
	return map[string]any{"count": cnt, "avg": avg, "per_expert": per}, nil
}

// ConcludeReview 契约 POST /reviews/{id}/conclude：汇总→CONCLUDED，按 biz_type 经单一写者回写 E/R。
func (h *Handler) ConcludeReview(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	task, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	var b concludeBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	summary, err := h.buildScoreSummary(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "汇总失败")
		return
	}
	sumJSON := marshalJSON(summary)
	if _, err := h.q.ConcludeReviewTask(c, nstore.ConcludeReviewTaskParams{
		Conclusion: b.Conclusion, ScoreSummary: sumJSON, ID: id,
	}); err != nil {
		httpx.WriteErr(c, 500, 50002, "结论落库失败")
		return
	}
	var projectID int64
	if task.ProjectID != nil {
		projectID = *task.ProjectID
	}
	var targetID int64
	if task.TargetID != nil {
		targetID = *task.TargetID
	}
	if err := h.concludeWriteback(c, task.BizType, targetID, projectID, b.Conclusion, summary); err != nil {
		httpx.WriteErr(c, 500, 50003, "回写被评审对象失败")
		return
	}
	out, _ := h.q.GetReviewTask(c, id)
	httpx.WriteOK(c, ToAPIReviewTask(out))
}

type feeBody struct {
	Amount     string  `json:"amount"`
	PayChannel *string `json:"pay_channel"`
}

// GenerateFees 契约 POST /reviews/{id}/fees：按已接受专家逐人生成评审费（联动 F）。
// code 号段待编号中心接线前留空（可空列）；amount 缺省 0。
func (h *Handler) GenerateFees(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	d := auth.DomainFrom(c)
	task, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	var b feeBody
	_ = c.ShouldBindJSON(&b)
	accepted, err := h.q.ListAcceptedExperts(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	n := 0
	for _, a := range accepted {
		if _, err := h.q.InsertFee(c, nstore.InsertFeeParams{
			Code: "", TenantID: task.TenantID, CreatorID: d.UserID,
			TaskID: id, ExpertID: a.ExpertID, Amount: strNumeric(b.Amount), PayChannel: b.PayChannel,
		}); err != nil {
			httpx.WriteErr(c, 500, 50002, "生成失败")
			return
		}
		n++
	}
	httpx.WriteOK(c, gin.H{"generated": n})
}

// GetReviewDetail 契约 GET /reviews/{id}/detail：task + invitations + scores。
func (h *Handler) GetReviewDetail(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	task, err := h.q.GetReviewTask(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "评审任务不存在")
		return
	}
	invites, err := h.q.ListInvitations(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	scores, err := h.q.ListScores(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	inv := make([]map[string]any, 0, len(invites))
	for _, iv := range invites {
		inv = append(inv, ToAPIInvitation(iv))
	}
	scs := make([]map[string]any, 0, len(scores))
	for _, s := range scores {
		scs = append(scs, ToAPIScore(s))
	}
	httpx.WriteOK(c, gin.H{"task": ToAPIReviewTask(task), "invitations": inv, "scores": scs})
}
