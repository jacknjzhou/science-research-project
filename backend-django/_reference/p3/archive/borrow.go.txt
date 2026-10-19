package archive

import (
	"strconv"
	"time"

	ostore "github.com/eplugger/ark/internal/modules/archive/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// ---------- 请求体 ----------

type borrowCreateBody struct {
	ArchiveID  int64   `json:"archive_id" binding:"required"`
	Purpose    *string `json:"purpose"`
	BorrowType *string `json:"borrow_type"` // READ/COPY；缺省由 SQL COALESCE→READ
	DueAt      *string `json:"due_at"`      // RFC3339 / 2006-01-02
}

// parseBorrowID 逐字镜像 parseArchiveID，仅换参数名与提示，保持错误码一致。
func parseBorrowID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "id 非法")
		return 0, false
	}
	return id, true
}

// ---------- 借阅申请/审批/归还 ----------

// CreateBorrow 契约 POST /borrows：archive 须 ARCHIVED（否则 40901），Code 留空（同 CreateArchive，
// 编号中心本轮不接入）。borrower/creator 均为当前用户。
func (h *Handler) CreateBorrow(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b borrowCreateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	cur, err := h.q.GetArchive(c, b.ArchiveID)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "案卷不存在")
		return
	}
	if cur.Status != "ARCHIVED" {
		httpx.WriteErr(c, 409, 40901, "仅 ARCHIVED 案卷可借阅")
		return
	}
	r, err := h.q.CreateBorrow(c, ostore.CreateBorrowParams{
		Code: nil, TenantID: d.TenantID, CreatorID: d.UserID,
		ArchiveID: b.ArchiveID, BorrowerUserID: d.UserID,
		Purpose: b.Purpose, BorrowType: b.BorrowType, DueAt: tsOf(parseTS(b.DueAt)),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建借阅失败")
		return
	}
	httpx.WriteOK(c, ToAPIBorrow(r))
}

// ListBorrows 契约 GET /borrows：路由可达性由 Casbin 控制（R-ADMIN 全域、普通角色读自身），
// 此处仅按需透传可选筛选（borrower / archive_id / status）+ 分页，不重复做角色判断。
func (h *Handler) ListBorrows(c *gin.Context) {
	page, size, limit, offset := pageArgs(c)
	borrower := optInt64(c, "borrower")
	archiveID := optInt64(c, "archive_id")
	status := optQuery(c, "status")
	rows, err := h.q.ListBorrows(c, ostore.ListBorrowsParams{
		BorrowerUserID: borrower, ArchiveID: archiveID, Status: status,
		Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountBorrows(c, ostore.CountBorrowsParams{
		BorrowerUserID: borrower, Status: status,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIBorrow(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// setBorrowStatus 借阅态迁移共用：GetBorrow→校验前态→SetBorrowStatus(乐观并发)→回读。
// extra 回调按迁移类型补填 approved_by/approved_at/returned_at 等留痕字段。
func (h *Handler) setBorrowStatus(c *gin.Context, to, allowedFrom string, extra func(p *ostore.SetBorrowStatusParams, d auth.Domain, now time.Time)) {
	d := auth.DomainFrom(c)
	id, ok := parseBorrowID(c)
	if !ok {
		return
	}
	cur, err := h.q.GetBorrow(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "借阅不存在")
		return
	}
	if cur.Status != allowedFrom {
		httpx.WriteErr(c, 409, 40901, "当前状态不允许该操作")
		return
	}
	now := time.Now()
	p := ostore.SetBorrowStatusParams{
		Status: to, ModifierID: d.UserID, ID: id, FromStatus: strOf(cur.Status),
	}
	if extra != nil {
		extra(&p, d, now)
	}
	rows, err := h.q.SetBorrowStatus(c, p)
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "流转失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 409, 40901, "状态已变更，请刷新重试")
		return
	}
	r, _ := h.q.GetBorrow(c, id)
	httpx.WriteOK(c, ToAPIBorrow(r))
}

// ApproveBorrow 契约 POST /borrows/{id}/approve：SUBMITTED → APPROVED（Casbin 限 R-ADMIN）。
func (h *Handler) ApproveBorrow(c *gin.Context) {
	h.setBorrowStatus(c, "APPROVED", "SUBMITTED", func(p *ostore.SetBorrowStatusParams, d auth.Domain, now time.Time) {
		userID := d.UserID
		p.ApprovedBy = &userID
		p.ApprovedAt = tsOf(&now)
	})
}

// RejectBorrow 契约 POST /borrows/{id}/reject：SUBMITTED → REJECTED（Casbin 限 R-ADMIN）。
func (h *Handler) RejectBorrow(c *gin.Context) {
	h.setBorrowStatus(c, "REJECTED", "SUBMITTED", nil)
}

// ReturnBorrow 契约 POST /borrows/{id}/return：APPROVED → RETURNED，填 returned_at。
func (h *Handler) ReturnBorrow(c *gin.Context) {
	h.setBorrowStatus(c, "RETURNED", "APPROVED", func(p *ostore.SetBorrowStatusParams, _ auth.Domain, now time.Time) {
		p.ReturnedAt = tsOf(&now)
	})
}
