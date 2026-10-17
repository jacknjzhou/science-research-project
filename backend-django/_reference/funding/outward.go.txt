// T14 外拨（F-24）：经费拨付外单位，两级审批 R-MANAGER→R-LEADER 后从预算行实扣。
package funding

import (
	"errors"
	"net/http"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
)

type outwardBody struct {
	ProjectID    int64   `json:"project_id" binding:"required"`
	BudgetID     *int64  `json:"budget_id"`
	BudgetLineID *int64  `json:"budget_line_id"`
	Amount       string  `json:"amount" binding:"required"`
	ToUnit       string  `json:"to_unit" binding:"required"`
	Reason       *string `json:"reason"`
}

// CreateOutward POST /outwards
func (h *Handler) CreateOutward(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b outwardBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	if moneyRat(b.Amount).Sign() <= 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "金额须为正数")
		return
	}
	o, err := h.q.CreateOutward(c, fstore.CreateOutwardParams{
		TenantID: d.TenantID, CreatorID: d.UserID,
		ProjectID: b.ProjectID, BudgetID: b.BudgetID, BudgetLineID: b.BudgetLineID,
		Amount: strToNum(b.Amount), ToUnit: b.ToUnit, Reason: b.Reason,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败："+err.Error())
		return
	}
httpx.WriteOK(c, ToAPIOutward(o))
}

// ListOutwards GET /outwards
func (h *Handler) ListOutwards(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListOutwards(c, fstore.ListOutwardsParams{TenantID: d.TenantID, Limit: limit, Offset: offset})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountOutwards(c, d.TenantID)
	out := make([]map[string]any, 0, len(rows))
	for _, o := range rows {
		out = append(out, ToAPIOutward(o))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// OutwardAction POST /outwards/:id/approval {action: APPROVE|REJECT}
// 两级：R-MANAGER 一级 → R-LEADER 终审；终审后从预算行实扣（余额不足 40902）。
func (h *Handler) OutwardAction(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Action  string `json:"action" binding:"required"`
		Comment *string `json:"comment"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	isLeader := false
	for _, r := range d.Roles {
		if r == "R-LEADER" || r == "R-ADMIN" {
			isLeader = true
		}
	}
	var (
		o   fstore.FOutward
		err error
	)
	switch b.Action {
	case "REJECT":
		// 一级/终审人均可驳回（回到申请人重报）
		o, err = h.q.RejectOutward(c, fstore.RejectOutwardParams{ID: pathID(c), ApprovedBy: &d.UserID})
	case "APPROVE":
		if !isLeader {
			o, err = h.q.ApproveOutwardFirst(c, fstore.ApproveOutwardFirstParams{ID: pathID(c), FirstApprovedBy: &d.UserID})
			if errors.Is(err, pgx.ErrNoRows) {
				httpx.WriteErr(c, http.StatusConflict, 40901, "仅 PENDING 且未一级批复可批")
				return
			}
		} else {
			// R-LEADER/R-ADMIN 终审：若一级未批则先补一级（同人持双角色一次打通），
			// 再终审并入账。ErrNoRows = 一级已批过，直接终审。
			if _, ferr := h.q.ApproveOutwardFirst(c, fstore.ApproveOutwardFirstParams{ID: pathID(c), FirstApprovedBy: &d.UserID}); ferr != nil && !errors.Is(ferr, pgx.ErrNoRows) {
				httpx.WriteErr(c, http.StatusInternalServerError, 50002, "一级批复失败："+ferr.Error())
				return
			}
			o, err = h.q.ApproveOutwardFinal(c, fstore.ApproveOutwardFinalParams{ID: pathID(c), ApprovedBy: &d.UserID})
			if errors.Is(err, pgx.ErrNoRows) {
				httpx.WriteErr(c, http.StatusConflict, 40901, "单据不在待终审状态")
				return
			}
			// 终审通过 → 预算行实扣
			if o.BudgetLineID != nil {
				n, derr := h.q.DeductLineForOutward(c, fstore.DeductLineForOutwardParams{
					ID: *o.BudgetLineID, AmountUsed: o.Amount,
				})
				if derr != nil || n == 0 {
					httpx.WriteErr(c, http.StatusConflict, 40902, "预算行余额不足，外拨无法入账")
					return
				}
			}
			// 通知提交人（best-effort）
			h.notify(o.CreatorID, "MESSAGE", "外拨已批复",
				"外拨单 #"+strconvI(o.ID)+" 已终审通过并从预算扣减", "outward/"+strconvI(o.ID), d.TenantID)
		}
	default:
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "action 仅 APPROVE|REJECT")
		return
	}
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusConflict, 40901, "状态不允许该操作")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "操作失败："+err.Error())
		return
	}
	httpx.WriteOK(c, ToAPIOutward(o))
}

func ToAPIOutward(o fstore.FOutward) map[string]any {
	code := optStr(o.Code)
	unit := o.ToUnit
	lineID := any(nil)
	if o.BudgetLineID != nil {
		lineID = *o.BudgetLineID
	}
	return map[string]any{
		"id": o.ID, "code": code, "status": o.Status,
		"project_id": o.ProjectID, "budget_line_id": lineID,
		"amount": numDec(o.Amount, 2), "to_unit": unit,
		"reason": optStr(o.Reason),
		"first_approved_by": optI64(o.FirstApprovedBy), "approved_by": optI64(o.ApprovedBy),
		"created_at": fmtTz(o.CreatedAt),
	}
}
