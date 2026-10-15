// 审批动作（F-09）：末步 APPROVE → 实扣（冻结转已用）；REJECT/RETURN → 解冻。
package funding

import (
	"errors"
	"net/http"
	"strconv"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
)

// ApprovalAction POST /expenses/:id/approval {action: APPROVE|REJECT|RETURN, comment}
// 守卫：存在 PENDING 步骤；审批人须持有当前步角色（R-ADMIN 直通）。
func (h *Handler) ApprovalAction(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Action  string `json:"action" binding:"required"`
		Comment string `json:"comment"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	switch b.Action {
	case "APPROVE", "REJECT", "RETURN":
	default:
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "action 仅支持 APPROVE/REJECT/RETURN")
		return
	}
	expenseID := pathID(c)
	exp, err := h.q.GetExpense(c, expenseID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "报销单不存在")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	if exp.Status != "SUBMITTED" && exp.Status != "AI_REVIEW" && exp.Status != "HUMAN_REVIEW" {
		httpx.WriteErr(c, http.StatusConflict, 40901, "单据不在审批中状态")
		return
	}
	step, err := h.q.GetCurrentApproval(c, expenseID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusConflict, 40901, "无待审步骤")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	// 权限：审批人须持当前步角色；R-ADMIN 直通；重复审批人不可审同一单的连续步（简化：不做）
	if !hasRole(d.Roles, deref(step.Role)) && !hasRole(d.Roles, "R-ADMIN") {
		httpx.WriteErr(c, http.StatusForbidden, 40301, "当前步骤需要 "+deref(step.Role)+" 角色")
		return
	}
	acted, err := h.q.ActApproval(c, fstore.ActApprovalParams{
		ID: step.ID, Action: &b.Action, Comment: &b.Comment, ApproverUserID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "审批写入失败")
		return
	}
	_ = acted
	// 汇总：是否末步
	steps, _ := h.q.ListApprovalsByExpense(c, expenseID)
	done := 0
	for _, s := range steps {
		if s.Status == "DONE" {
			done++
		}
	}
	final := done == len(steps)
	newStatus := "HUMAN_REVIEW"
	switch {
	case b.Action == "APPROVE" && final:
		newStatus = "APPROVED"
	case b.Action == "REJECT":
		newStatus = "REJECTED"
	case b.Action == "RETURN":
		newStatus = "RETURNED"
	}
	// 冻结账户动作（F-10）与状态流转同事务
	terr := pgx.BeginFunc(c, h.db, func(tx pgx.Tx) error {
		q := h.q.WithTx(tx)
		if b.Action == "APPROVE" && final && exp.BudgetLineID != nil && exp.SubmitMode == "预算制" {
			if err := q.CommitSpend(c, fstore.CommitSpendParams{ID: *exp.BudgetLineID, AmountFrozen: exp.Amount}); err != nil {
				return err
			}
		}
		if (b.Action == "REJECT" || b.Action == "RETURN") && exp.BudgetLineID != nil && exp.SubmitMode == "预算制" {
			if err := q.ReleaseLine(c, fstore.ReleaseLineParams{ID: *exp.BudgetLineID, AmountFrozen: exp.Amount}); err != nil {
				return err
			}
		}
		if b.Action == "APPROVE" && !final {
			return q.SetExpenseStatus(c, fstore.SetExpenseStatusParams{ID: expenseID, Status: newStatus})
		}
		return q.SetExpenseStatus(c, fstore.SetExpenseStatusParams{ID: expenseID, Status: newStatus})
	})
	if terr != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "状态/预算更新失败")
		return
	}
	// 触达报销人（best-effort）
	title, content := "报销审批通过", "报销单 "+deref(exp.Code)+" 已全部审批通过并实扣预算"
	if b.Action == "REJECT" {
		title, content = "报销被驳回", "报销单 "+deref(exp.Code)+" 被驳回：预算已解冻，可修改后重新提交"
	} else if b.Action == "RETURN" {
		title, content = "报销被退回", "报销单 "+deref(exp.Code)+" 被退回修改：预算已解冻"
	} else if !final {
		title, content = "报销进入下一审批步", "报销单 "+deref(exp.Code)+" 已通过第 "+itoaStep(step.StepOrder)+" 步"
	}
	h.notify(exp.ApplicantUserID, "EXPENSE_RESULT", title, content, "expense/"+fmtInt(expenseID), d.TenantID)
	fresh, _ := h.q.GetExpense(c, expenseID)
	httpx.WriteOK(c, ToAPIExpense(fresh))
}

func hasRole(roles []string, want string) bool {
	for _, r := range roles {
		if r == want {
			return true
		}
	}
	return false
}

func itoaStep(n int32) string {
	switch n {
	case 1:
		return "一"
	case 2:
		return "二"
	case 3:
		return "三"
	default:
		return "?"
	}
}

func fmtInt(n int64) string { return strconv.FormatInt(n, 10) }
