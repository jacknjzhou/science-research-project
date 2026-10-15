// T14 结转（F-25）：结题项目余额结转下年度，批复后生成 F_INCOME 结转行。
package funding

import (
	"errors"
	"net/http"
	"time"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
)

type carryoverBody struct {
	ProjectID  int64   `json:"project_id" binding:"required"`
	FiscalYear int     `json:"fiscal_year" binding:"required"`
	TargetYear int     `json:"target_year" binding:"required"`
	Amount     string  `json:"amount" binding:"required"`
	Remark     *string `json:"remark"`
}

// CreateCarryover POST /carryovers —— 守卫：E_PROJECT.status=CLOSED（结题）。
func (h *Handler) CreateCarryover(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b carryoverBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	if moneyRat(b.Amount).Sign() <= 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "金额须为正数")
		return
	}
	if b.TargetYear <= b.FiscalYear {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "目标年度须晚于来源年度")
		return
	}
	proj, err := h.q.GetProjectStatusForGuard(c, b.ProjectID)
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "项目不存在")
		return
	}
	if proj.Status != "CLOSED" {
		httpx.WriteErr(c, http.StatusConflict, 40901, "仅结题（CLOSED）项目可发起结转")
		return
	}
	co, err := h.q.CreateCarryover(c, fstore.CreateCarryoverParams{
		TenantID: d.TenantID, CreatorID: d.UserID,
		ProjectID: b.ProjectID, FiscalYear: int32(b.FiscalYear), TargetYear: int32(b.TargetYear),
		Amount: strToNum(b.Amount), Remark: b.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败："+err.Error())
		return
	}
httpx.WriteOK(c, ToAPICarryover(co))
}

// ListCarryovers GET /carryovers
func (h *Handler) ListCarryovers(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListCarryovers(c, fstore.ListCarryoversParams{TenantID: d.TenantID, Limit: limit, Offset: offset})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountCarryovers(c, d.TenantID)
	out := make([]map[string]any, 0, len(rows))
	for _, co := range rows {
		out = append(out, ToAPICarryover(co))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// CarryoverAction POST /carryovers/:id/approval {action: APPROVE|REJECT}
// 批复（R-MANAGER/R-LEADER/R-ADMIN）→ 生成下年度 F_INCOME 结转到账行。
func (h *Handler) CarryoverAction(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Action string `json:"action" binding:"required"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	co, err := h.q.GetCarryover(c, pathID(c))
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "结转单不存在")
		return
	}
	switch b.Action {
	case "REJECT":
		co, err = h.q.RejectCarryover(c, co.ID)
	case "APPROVE":
		co, err = h.q.ApproveCarryover(c, fstore.ApproveCarryoverParams{ID: co.ID, Note: "approved"})
		if err == nil && co.IncomeID == nil {
			// 生成下年度结转到账行（CARRYOVER 语义存 remark；流水号幂等键 = CRO-<id>）
			flow := "CRO-" + strconvI(co.ID)
			inc, ierr := h.q.CreateIncome(c, fstore.CreateIncomeParams{
				TenantID: d.TenantID, CreatorID: d.UserID, LegalEntityID: 1,
				ReceiptDate: nowDatePtr(),
				Amount:      co.Amount,
				PurposeText: strPtr("项目 #" + strconvI(co.ProjectID) + " 结转 " + strconvI(int64(co.FiscalYear)) + "→" + strconvI(int64(co.TargetYear))),
				BankFlowNo:  &flow,
			})
			if ierr == nil {
					_ = h.q.SetCarryoverIncome(c, fstore.SetCarryoverIncomeParams{ID: co.ID, IncomeID: &inc.ID})
				co.IncomeID = &inc.ID
			}
		}
	default:
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "action 仅 APPROVE|REJECT")
		return
	}
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusConflict, 40901, "仅 PENDING 可操作")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "操作失败："+err.Error())
		return
	}
	httpx.WriteOK(c, ToAPICarryover(co))
}

func ToAPICarryover(co fstore.FCarryover) map[string]any {
	code := optStr(co.Code)
	incomeID := optI64(co.IncomeID)
	return map[string]any{
		"id": co.ID, "code": code, "status": co.Status,
		"project_id": co.ProjectID, "fiscal_year": co.FiscalYear, "target_year": co.TargetYear,
		"amount": numDec(co.Amount, 2), "income_id": incomeID,
		"remark": optStr(co.Remark), "created_at": fmtTz(co.CreatedAt),
	}
}

func strPtr(s string) *string { return &s }

// nowDatePtr 当前日期（结转 F_INCOME 收款日）。
func nowDatePtr() *time.Time { t := time.Now(); return &t }
