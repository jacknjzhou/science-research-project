package output

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strconv"
	"strings"
	"time"

	rstore "github.com/eplugger/ark/internal/modules/output/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Handler 承载 R 竖切所有 HTTP 端点。store 层由 sqlc 生成的 rstore.Queries 提供，
// pool 传入即开即用（NoRoute passthrough 负责未实现端点兜底：ai-fill/ai-dedup/
// patents/metrics/refresh/export，见规格 §4.2 与任务 2.6 注记）。
type Handler struct{ q *rstore.Queries }

// NewHandler 用 pgxpool 构造 Handler；pool 由 router.RouterDeps 注入。
func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: rstore.New(pool)} }

// ---------- 请求/分页 helper（逐字拷自 project/handler.go） ----------

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

// optQueryInt64 / optQueryInt32：可空整型查询参数；空或非法 → nil（触发 narg IS NULL 分支跳过过滤）。
func optQueryInt64(c *gin.Context, k string) *int64 {
	if v := c.Query(k); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return &n
		}
	}
	return nil
}

func optQueryInt32(c *gin.Context, k string) *int32 {
	if v := c.Query(k); v != "" {
		if n, err := strconv.ParseInt(v, 10, 32); err == nil {
			i := int32(n)
			return &i
		}
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

// numFromQuery：契约 min_confidence（number）→ pgtype.Numeric；空/非法 → 零值（Valid=false，跳过过滤）。
func numFromQuery(c *gin.Context, k string) pgtype.Numeric {
	var n pgtype.Numeric
	if v := c.Query(k); v != "" {
		_ = n.Scan(v)
	}
	return n
}

// normTitleHash：规范化标题哈希（sha256 hex 64 字符，契合 title_hash VARCHAR(64)），用于去重主键。
func normTitleHash(title string) string {
	sum := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(title))))
	return hex.EncodeToString(sum[:])
}

func newBatchID() string {
	return "B" + strconv.FormatInt(time.Now().UnixNano(), 36)
}

// ---------- 读端点 ----------

// ListOutputs 契约 GET /output：成果台账分页（多条件 narg 过滤）。
func (h *Handler) ListOutputs(c *gin.Context) {
	page, size, limit, offset := pageArgs(c)
	kw := optQuery(c, "keyword")
	if kw == nil {
		kw = optQuery(c, "kw")
	}
	params := rstore.ListOutputsParams{
		OutputType:   optQuery(c, "output_type"),
		Status:       optQuery(c, "status"),
		ClaimStatus:  optQuery(c, "claim_status"),
		Source:       optQuery(c, "source"),
		Kw:           kw,
		Year:         optQueryInt32(c, "year"),
		DepartmentID: optQueryInt64(c, "department_id"),
		ProjectID:    optQueryInt64(c, "project_id"),
		Limit:        limit,
		Offset:       offset,
	}
	rows, err := h.q.ListOutputs(c, params)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountOutputs(c, rstore.CountOutputsParams{
		OutputType:   params.OutputType,
		Status:       params.Status,
		ClaimStatus:  params.ClaimStatus,
		Source:       params.Source,
		Kw:           params.Kw,
		Year:         params.Year,
		DepartmentID: params.DepartmentID,
		ProjectID:    params.ProjectID,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIOutput(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// ListMyOutputs 契约 GET /output/mine：命中本人 authors.user_id 的成果分页。
func (h *Handler) ListMyOutputs(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	ot := optQuery(c, "output_type")
	yr := optQueryInt32(c, "year")
	rows, err := h.q.ListMyOutputs(c, rstore.ListMyOutputsParams{
		UserID: d.UserID, OutputType: ot, Year: yr, Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountMyOutputs(c, rstore.CountMyOutputsParams{UserID: d.UserID, OutputType: ot, Year: yr})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIOutput(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// ListPendingClaim 契约 GET /output/pending-claim：推送给本人的高置信/可疑待认领卡片。
func (h *Handler) ListPendingClaim(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	minC := numFromQuery(c, "min_confidence")
	rows, err := h.q.ListPendingClaim(c, rstore.ListPendingClaimParams{
		UserID: d.UserID, MinConfidence: minC, Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountPendingClaim(c, rstore.CountPendingClaimParams{UserID: d.UserID, MinConfidence: minC})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIOutput(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetOutput 契约 GET /output/:id：单个成果详情。
func (h *Handler) GetOutput(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetOutput(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "成果不存在")
		return
	}
	httpx.WriteOK(c, ToAPIOutput(r))
}

// ---------- 写端点 ----------

type outputCreateBody struct {
	OutputType    string          `json:"output_type" binding:"required"`
	Title         string          `json:"title" binding:"required"`
	Source        string          `json:"source"`
	TitleEn       *string         `json:"title_en"`
	Abstract      *string         `json:"abstract"`
	PublishDate   *string         `json:"publish_date"`
	Language      *string         `json:"language"`
	Authors       json.RawMessage `json:"authors"`
	Affiliations  json.RawMessage `json:"affiliations"`
	SecurityLevel *string         `json:"security_level"`
	Remark        *string         `json:"remark"`
}

// CreateOutput 契约 POST /output：手动录入成果（R-02），落 MANUAL_DRAFT/CLAIMED 并算 title_hash 去重键。
func (h *Handler) CreateOutput(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b outputCreateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	src := b.Source
	if src == "" {
		src = "MANUAL"
	}
	th := normTitleHash(b.Title)
	r, err := h.q.CreateOutput(c, rstore.CreateOutputParams{
		Code:                "", // code 前缀待 seq_prefix_registry 登记，先留空（可空列）
		TenantID:            d.TenantID,
		CreatorID:           d.UserID,
		OutputType:          b.OutputType,
		Title:               b.Title,
		TitleEn:             b.TitleEn,
		Abstract:            b.Abstract,
		PublishDate:         parseDatePtr(b.PublishDate),
		Authors:             jsonOrNil(b.Authors),
		ExternalAuthorNames: nil,
		Affiliations:        jsonOrNil(b.Affiliations),
		Language:            b.Language,
		Source:              src,
		TitleHash:           &th,
		DepartmentID:        nil,
		LegalEntityID:       d.LegalEntityID,
		SecurityLevel:       b.SecurityLevel,
		Remark:              b.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIOutput(r))
}

type claimItem struct {
	OutputID     int64           `json:"output_id" binding:"required"`
	EditedFields json.RawMessage `json:"edited_fields"`
}

type claimBody struct {
	Action string      `json:"action"` // 契约含 action，但动作以端点为权威（忽略 body 值）
	Reason *string     `json:"reason"`
	Items  []claimItem `json:"items" binding:"required"`
}

// claimTokens 依动作映射 DDL 合法枚举 (claim_status, status, is_claimed)。
func claimTokens(action string) (string, string, bool) {
	switch action {
	case "CLAIM":
		return "CLAIMED", "CLAIMED", true
	case "REJECT":
		return "REJECTED", "REJECTED", false
	case "MARK_NOT_MINE":
		return "NOT_MINE", "PENDING_CLAIM", false
	default:
		return "PENDING", "PENDING_CLAIM", false
	}
}

// processClaim 是 claim/reject/mark-not-mine 的共同实现（批量上限 100，逐条 SetClaimStatus + InsertClaimRecord）。
// 动作 token 以命中的 HTTP 端点为权威，不信任 body 里的 action。
func (h *Handler) processClaim(c *gin.Context, action string) {
	d := auth.DomainFrom(c)
	var b claimBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if len(b.Items) == 0 || len(b.Items) > 100 {
		httpx.WriteErr(c, 400, 40001, "批量项数非法（1-100）")
		return
	}
	batchID := newBatchID()
	claimStatus, status, isClaimed := claimTokens(action)
	results := make([]map[string]any, 0, len(b.Items))
	for _, it := range b.Items {
		rows, err := h.q.SetClaimStatus(c, rstore.SetClaimStatusParams{
			ClaimStatus: claimStatus, Status: status, IsClaimed: isClaimed, ID: it.OutputID,
		})
		if err != nil {
			results = append(results, gin.H{"output_id": it.OutputID, "success": false, "message": "更新失败"})
			continue
		}
		if rows == 0 {
			results = append(results, gin.H{"output_id": it.OutputID, "success": false, "message": "成果不存在或状态冲突"})
			continue
		}
		_, _ = h.q.InsertClaimRecord(c, rstore.InsertClaimRecordParams{
			TenantID: d.TenantID, CreatorID: d.UserID, OutputID: it.OutputID,
			UserID: d.UserID, Action: action, Reason: b.Reason, BatchID: &batchID,
		})
		results = append(results, gin.H{"output_id": it.OutputID, "success": true, "new_status": status, "message": "ok"})
	}
	httpx.WriteOK(c, gin.H{"batch_id": batchID, "results": results})
}

// ClaimOutputs 契约 POST /output/claim。
func (h *Handler) ClaimOutputs(c *gin.Context) { h.processClaim(c, "CLAIM") }

// RejectOutputs 契约 POST /output/reject。
func (h *Handler) RejectOutputs(c *gin.Context) { h.processClaim(c, "REJECT") }

// MarkNotMine 契约 POST /output/mark-not-mine。
func (h *Handler) MarkNotMine(c *gin.Context) { h.processClaim(c, "MARK_NOT_MINE") }

type projectLinkBody struct {
	ProjectIDs      []int64   `json:"project_ids" binding:"required"`
	RelationType    *string   `json:"relation_type"`
	ContributionPct *float64  `json:"contribution_pct"`
}

// LinkProjects 契约 PUT /output/:id/projects：全量设置关联项目集合 + CLAIMED→ASSIGNED_TO_PROJECT。
func (h *Handler) LinkProjects(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b projectLinkBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if _, err := h.q.GetOutput(c, id); err != nil {
		httpx.WriteErr(c, 404, 40401, "成果不存在")
		return
	}
	var cp pgtype.Numeric
	if b.ContributionPct != nil {
		_ = cp.Scan(strconv.FormatFloat(*b.ContributionPct, 'f', -1, 64))
	}
	for _, pid := range b.ProjectIDs {
		if err := h.q.LinkProject(c, rstore.LinkProjectParams{
			TenantID: d.TenantID, CreatorID: d.UserID, OutputID: id, ProjectID: pid,
			RelationType: b.RelationType, ContributionPct: cp,
		}); err != nil {
			httpx.WriteErr(c, 500, 50002, "关联失败")
			return
		}
	}
	_, _ = h.q.SetOutputStatus(c, rstore.SetOutputStatusParams{Status: "ASSIGNED_TO_PROJECT", ID: id})
	httpx.WriteOK(c, gin.H{"linked": len(b.ProjectIDs)})
}
