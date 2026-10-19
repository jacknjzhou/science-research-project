// 审批动作（F-09）：末步 APPROVE → 实扣（冻结转已用）；REJECT/RETURN → 解冻。
// T19：审批动作写 sys_approval_log 流水；新增批量审批端点（逐条事务、逐条结果）。
package funding

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/eplugger/ark/internal/platform/approval"
	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
)

// approveOne 单条报销审批核心：校验状态/步骤/角色 → 写步骤 → 状态流转 + 预算动作 + 流水（同事务）。
// 返回 (httpCode, errInfo)；成功 httpCode=0。
func (h *Handler) approveOne(c *gin.Context, d auth.Domain, expenseID int64, action, comment string) (int, string) {
	exp, err := h.q.GetExpense(c, expenseID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return http.StatusNotFound, "报销单不存在"
		}
		return http.StatusInternalServerError, "查询失败"
	}
	if exp.Status != "SUBMITTED" && exp.Status != "AI_REVIEW" && exp.Status != "HUMAN_REVIEW" {
		return http.StatusConflict, "单据不在审批中状态"
	}
	step, err := h.q.GetCurrentApproval(c, expenseID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return http.StatusConflict, "无待审步骤"
		}
		return http.StatusInternalServerError, "查询失败"
	}
	// 权限：审批人须持当前步角色；R-ADMIN 直通
	if !approval.HasRole(d.Roles, deref(step.Role)) && !approval.HasRole(d.Roles, "R-ADMIN") {
		return http.StatusForbidden, "当前步骤需要 " + deref(step.Role) + " 角色"
	}
	acted, err := h.q.ActApproval(c, fstore.ActApprovalParams{
		ID: step.ID, Action: &action, Comment: &comment, ApproverUserID: &d.UserID,
	})
	if err != nil {
		return http.StatusInternalServerError, "审批写入失败"
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
	case action == "APPROVE" && final:
		newStatus = "APPROVED"
	case action == "REJECT":
		newStatus = "REJECTED"
	case action == "RETURN":
		newStatus = "RETURNED"
	}
	// 冻结账户动作（F-10）与状态流转、审核流水同事务
	terr := pgx.BeginFunc(c, h.db, func(tx pgx.Tx) error {
		q := h.q.WithTx(tx)
		if action == "APPROVE" && final && exp.BudgetLineID != nil && exp.SubmitMode == "预算制" {
			if err := q.CommitSpend(c, fstore.CommitSpendParams{ID: *exp.BudgetLineID, AmountFrozen: exp.Amount}); err != nil {
				return err
			}
		}
		if (action == "REJECT" || action == "RETURN") && exp.BudgetLineID != nil && exp.SubmitMode == "预算制" {
			if err := q.ReleaseLine(c, fstore.ReleaseLineParams{ID: *exp.BudgetLineID, AmountFrozen: exp.Amount}); err != nil {
				return err
			}
		}
		// T19：审核动作流水（biz_type=EXPENSE；step 取审批步骤序号）
		if err := approval.LogTx(c, tx, approval.LogParam{
			TenantID: d.TenantID, BizType: "EXPENSE", BizID: expenseID,
			Step: int(step.StepOrder), ActorID: d.UserID, ActorRole: deref(step.Role),
			Action: action, Comment: comment,
		}); err != nil {
			return err
		}
		return q.SetExpenseStatus(c, fstore.SetExpenseStatusParams{ID: expenseID, Status: newStatus})
	})
	if terr != nil {
		return http.StatusInternalServerError, "状态/预算更新失败"
	}
	// 触达报销人（best-effort）
	title, content := "报销审批通过", "报销单 "+deref(exp.Code)+" 已全部审批通过并实扣预算"
	if action == "REJECT" {
		title, content = "报销被驳回", "报销单 "+deref(exp.Code)+" 被驳回：预算已解冻，可修改后重新提交"
	} else if action == "RETURN" {
		title, content = "报销被退回", "报销单 "+deref(exp.Code)+" 被退回修改：预算已解冻"
	} else if !final {
		title, content = "报销进入下一审批步", "报销单 "+deref(exp.Code)+" 已通过第 "+itoaStep(step.StepOrder)+" 步"
	}
	h.notify(exp.ApplicantUserID, "EXPENSE_RESULT", title, content, "expense/"+fmtInt(expenseID), d.TenantID)
	return 0, ""
}

// ApprovalAction POST /expenses/:id/approval {action: APPROVE|REJECT|RETURN, comment}
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
	code, msg := h.approveOne(c, d, pathID(c), b.Action, b.Comment)
	if code != 0 {
		httpx.WriteErr(c, code, errCodeOf(code), msg)
		return
	}
	fresh, err := h.q.GetExpense(c, pathID(c))
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	httpx.WriteOK(c, ToAPIExpense(fresh))
}

// ApprovalBatch POST /expenses/approval-batch {ids:[], action, comment}
// 逐条独立事务、逐条结果：部分失败不影响其余（spec A 组批量审核）。
func (h *Handler) ApprovalBatch(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		IDs     []int64 `json:"ids" binding:"required,min=1"`
		Action  string  `json:"action" binding:"required"`
		Comment string  `json:"comment"`
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
	results := make([]gin.H, 0, len(b.IDs))
	okN := 0
	for _, id := range b.IDs {
		code, msg := h.approveOne(c, d, id, b.Action, b.Comment)
		if code == 0 {
			okN++
			results = append(results, gin.H{"id": id, "ok": true})
		} else {
			results = append(results, gin.H{"id": id, "ok": false, "err": msg})
		}
	}
	httpx.WriteOK(c, gin.H{"total": len(b.IDs), "ok": okN, "results": results})
}

// errCodeOf http 状态码 → 业务错误码（审批复用既有码位）。
func errCodeOf(httpCode int) int {
	switch httpCode {
	case http.StatusNotFound:
		return 40401
	case http.StatusForbidden:
		return 40301
	case http.StatusConflict:
		return 40901
	default:
		return 50001
	}
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
