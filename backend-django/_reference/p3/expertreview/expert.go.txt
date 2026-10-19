package expertreview

import (
	"encoding/json"
	"strconv"

	nstore "github.com/eplugger/ark/internal/modules/expertreview/store"
	"github.com/eplugger/ark/internal/modules/output"
	"github.com/eplugger/ark/internal/modules/project"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Handler 承载 N 竖切所有 HTTP 端点。store 由 sqlc 生成的 nstore.Queries 提供；
// e/r 是 E、R 域的 Handler，供评审结论按 biz_type 经「单一写者」导出方法回写（见 writeback.go）。
type Handler struct {
	q *nstore.Queries
	e *project.Handler
	r *output.Handler
}

// NewHandler 用 pgxpool + E/R Handler 构造 N Handler。
func NewHandler(pool *pgxpool.Pool, e *project.Handler, r *output.Handler) *Handler {
	return &Handler{q: nstore.New(pool), e: e, r: r}
}

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

// jsonOrNil：[]byte 空则传 nil（让 SQL 里的 COALESCE 兜底）。
func jsonOrNil(b []byte) []byte {
	if len(b) == 0 {
		return nil
	}
	return b
}

// marshalJSON：把任意值序列化成 jsonb 载荷；marshal 失败返回 nil。
func marshalJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	return b
}

// ---------- 专家库 CRUD ----------

// validExpertStatus 限定 n_expert.status CHECK 枚举（CANDIDATE/ACTIVE/SUSPENDED/BLACKLIST）。
func validExpertStatus(s string) bool {
	switch s {
	case "CANDIDATE", "ACTIVE", "SUSPENDED", "BLACKLIST":
		return true
	}
	return false
}

// ListExperts 契约 GET /experts：状态/来源/关键词筛选的分页专家列表。
func (h *Handler) ListExperts(c *gin.Context) {
	page, size, limit, offset := pageArgs(c)
	p := nstore.ListExpertsParams{
		Status: optQuery(c, "status"),
		Source: optQuery(c, "source"),
		Kw:     optQuery(c, "kw"),
		Limit:  limit, Offset: offset,
	}
	rows, err := h.q.ListExperts(c, p)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountExperts(c, nstore.CountExpertsParams{Status: p.Status, Source: p.Source, Kw: p.Kw})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIExpert(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetExpert 契约 GET /experts/{id}：单个专家详情。
func (h *Handler) GetExpert(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetExpert(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "专家不存在")
		return
	}
	httpx.WriteOK(c, ToAPIExpert(r))
}

type expertCreateBody struct {
	Name           string   `json:"name" binding:"required"`
	Gender         *string  `json:"gender"`
	Title          *string  `json:"title"`
	OrgName        *string  `json:"org_name"`
	UserID         *int64   `json:"user_id"`
	Source         *string  `json:"source"`
	FieldTags      []string `json:"field_tags"`
	ExpertiseLevel *string  `json:"expertise_level"`
	AvoidOrgs      []string `json:"avoid_orgs"`
	AvoidPersonIDs []int64  `json:"avoid_person_ids"`
	SecurityLevel  *string  `json:"security_level"`
}

// CreateExpert 契约 POST /experts：新建专家（落 CANDIDATE）。
// code 号段（EXR-年-序）待编号中心接线前留空，与 R 域同款（M0 简化，可空列）。
func (h *Handler) CreateExpert(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b expertCreateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	r, err := h.q.CreateExpert(c, nstore.CreateExpertParams{
		Code:           "",
		TenantID:       d.TenantID,
		Status:         "CANDIDATE",
		CreatorID:      d.UserID,
		SecurityLevel:  b.SecurityLevel,
		Name:           b.Name,
		Gender:         b.Gender,
		Title:          b.Title,
		OrgName:        b.OrgName,
		UserID:         b.UserID,
		Source:         b.Source,
		FieldTags:      jsonOrNil(marshalJSON(b.FieldTags)),
		ExpertiseLevel: b.ExpertiseLevel,
		AvoidOrgs:      jsonOrNil(marshalJSON(b.AvoidOrgs)),
		AvoidPersonIds: jsonOrNil(marshalJSON(b.AvoidPersonIDs)),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIExpert(r))
}

type expertUpdateBody struct {
	Name           *string  `json:"name"`
	Title          *string  `json:"title"`
	OrgName        *string  `json:"org_name"`
	FieldTags      []string `json:"field_tags"`
	AvoidOrgs      []string `json:"avoid_orgs"`
	AvoidPersonIDs []int64  `json:"avoid_person_ids"`
}

// UpdateExpert 契约 PUT /experts/{id}：更新专家（字段子集）。
// SQL 用 name=COALESCE 非空覆盖，故缺省 name 时以现存 name 兜底，避免误清空。
func (h *Handler) UpdateExpert(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b expertUpdateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	cur, err := h.q.GetExpert(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "专家不存在")
		return
	}
	name := cur.Name
	if b.Name != nil && *b.Name != "" {
		name = *b.Name
	}
	rows, err := h.q.UpdateExpert(c, nstore.UpdateExpertParams{
		Name:           name,
		Title:          b.Title,
		OrgName:        b.OrgName,
		FieldTags:      marshalJSON(b.FieldTags),
		AvoidOrgs:      marshalJSON(b.AvoidOrgs),
		AvoidPersonIds: marshalJSON(b.AvoidPersonIDs),
		ModifierID:     d.UserID,
		ID:             id,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "更新失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 404, 40401, "专家不存在")
		return
	}
	out, err := h.q.GetExpert(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "专家不存在")
		return
	}
	httpx.WriteOK(c, ToAPIExpert(out))
}

type expertStatusBody struct {
	Status string `json:"status" binding:"required"`
}

// SetExpertStatus 契约 POST /experts/{id}/status：启停/黑名单（校验目标 status ∈ 枚举）。
func (h *Handler) SetExpertStatus(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var b expertStatusBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if !validExpertStatus(b.Status) {
		httpx.WriteErr(c, 400, 40002, "状态取值非法")
		return
	}
	rows, err := h.q.SetExpertStatus(c, nstore.SetExpertStatusParams{Status: b.Status, ID: id})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "更新失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 404, 40401, "专家不存在")
		return
	}
	out, err := h.q.GetExpert(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "专家不存在")
		return
	}
	httpx.WriteOK(c, ToAPIExpert(out))
}

// DeleteExpert 契约 DELETE /experts/{id}：软删除。
func (h *Handler) DeleteExpert(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	rows, err := h.q.SoftDeleteExpert(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "删除失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 404, 40401, "专家不存在")
		return
	}
	httpx.WriteOK(c, nil)
}
