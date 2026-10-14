package p

import (
	"encoding/json"
	"strconv"

	"github.com/eplugger/ark/internal/modules/p/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	q *store.Queries
}

func NewHandler(pool *pgxpool.Pool) *Handler {
	return &Handler{q: store.New(pool)}
}

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

func (h *Handler) ListApplications(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	status := optQuery(c, "status")
	ptype := optQuery(c, "project_type")
	rows, err := h.q.ListApplications(c, store.ListApplicationsParams{
		TenantID: d.TenantID, Status: status, ProjectType: ptype, Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountApplications(c, store.CountApplicationsParams{
		TenantID: d.TenantID, Status: status, ProjectType: ptype,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIApplication(store.Application(r)))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

func (h *Handler) GetApplication(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	r, err := h.q.GetApplication(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "记录不存在")
		return
	}
	httpx.WriteOK(c, ToAPIApplication(store.Application(r)))
}

func (h *Handler) CreateApplication(c *gin.Context) {
	d := auth.DomainFrom(c)
	var body struct {
		Title        string          `json:"title" binding:"required"`
		ProjectType  string          `json:"project_type" binding:"required"`
		PiUserID     int64           `json:"pi_user_id" binding:"required"`
		MemberIDs    json.RawMessage `json:"member_ids"`
		DepartmentID *int64          `json:"department_id"`
		Abstract     *string         `json:"abstract"`
		TotalBudget  *string         `json:"total_budget"`
		IsHorizontal bool            `json:"is_horizontal"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	memberIDs := body.MemberIDs
	if len(memberIDs) == 0 {
		memberIDs = json.RawMessage("[]")
	}
	var budget pgtype.Numeric
	if body.TotalBudget != nil && *body.TotalBudget != "" {
		if err := budget.Scan(*body.TotalBudget); err != nil {
			httpx.WriteErr(c, 400, 40002, "预算格式错误")
			return
		}
	}
	r, err := h.q.CreateApplication(c, store.CreateApplicationParams{
		TenantID: d.TenantID, Status: "DRAFT", CreatorID: d.UserID,
		Title: body.Title, ProjectType: body.ProjectType, PiUserID: body.PiUserID,
		MemberIds: memberIDs, DepartmentID: body.DepartmentID,
		Abstract: body.Abstract, Column10: budget, IsHorizontal: body.IsHorizontal,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIApplication(store.Application(r)))
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}
