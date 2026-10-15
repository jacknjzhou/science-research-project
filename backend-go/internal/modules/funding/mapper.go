// 契约映射与工具：NUMERIC → 定标字符串（PRD 2.6），时间格式化，可选值解引用。
package funding

import (
	"fmt"
	"strconv"
	"time"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/jackc/pgx/v5/pgtype"
)

func numDec(n pgtype.Numeric, d int) string {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return "0"
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

func numStrOrNil(n pgtype.Numeric, d int) any {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return nil
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

func numFloat(n pgtype.Numeric) float64 {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return 0
	}
	return f.Float64
}

func numPtr(s string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != "" {
		_ = n.Scan(s)
	}
	return n
}

func optStr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func optI64(p *int64) any {
	if p == nil {
		return nil
	}
	return *p
}

func fmtTime(t time.Time) string { return t.Format(time.RFC3339) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.Format(time.RFC3339)
}

func codeOf(prefix string, id int64) string {
	return fmt.Sprintf("%s-%s-%06d", prefix, time.Now().Format("2006"), id)
}

// remainingOf：行可支余额 = 计划 + 调整 - 冻结 - 实扣 - 已释放（表列 remaining 未建生成列，应用层计算）。
func remainingOf(l fstore.FBudgetLine) float64 {
	return numFloat(l.AmountPlanned) + numFloat(l.AmountAdjusted) -
		numFloat(l.AmountFrozen) - numFloat(l.AmountUsed) - numFloat(l.AmountReleased)
}

func ToAPISubject(s fstore.FSubject) map[string]any {
	return map[string]any{
		"id": s.ID, "code": optStr(s.Code), "name": s.Name,
		"parent_id": optI64(s.ParentID), "level": s.Level,
		"category": s.Category, "is_leaf": s.IsLeaf,
		"ratio_limit": numStrOrNil(s.RatioLimit, 4), "sort_no": s.SortNo,
	}
}

func ToAPIBudget(b fstore.FBudget) map[string]any {
	return map[string]any{
		"id": b.ID, "code": optStr(b.Code), "project_id": b.ProjectID,
		"legal_entity_id": b.LegalEntityID, "mode": b.Mode,
		"total_approved": numDec(b.TotalApproved, 2), "total_adjusted": numDec(b.TotalAdjusted, 2),
		"version": b.Version, "status": b.Status,
		"approved_at": fmtTimePtr(b.ApprovedAt), "approved_by": optI64(b.ApprovedBy),
		"created_at": fmtTime(b.CreatedAt), "updated_at": fmtTime(b.UpdatedAt),
	}
}

func ToAPILine(l fstore.FBudgetLine) map[string]any {
	return map[string]any{
		"id": l.ID, "budget_id": l.BudgetID, "subject_id": l.SubjectID,
		"amount_planned": numDec(l.AmountPlanned, 2), "amount_adjusted": numDec(l.AmountAdjusted, 2),
		"amount_frozen": numDec(l.AmountFrozen, 2), "amount_used": numDec(l.AmountUsed, 2),
		"amount_released": numDec(l.AmountReleased, 2),
		"remaining":       strconv.FormatFloat(remainingOf(l), 'f', 2, 64),
		"status":          l.Status,
	}
}

func ToAPIIncome(i fstore.FIncome) map[string]any {
	return map[string]any{
		"id": i.ID, "code": optStr(i.Code), "project_id": optI64(i.ProjectID),
		"legal_entity_id": i.LegalEntityID, "receipt_no": optStr(i.ReceiptNo),
		"receipt_date": fmtTimePtr(i.ReceiptDate), "amount": numDec(i.Amount, 2),
		"payer_name": optStr(i.PayerName), "payer_bank": optStr(i.PayerBank),
		"purpose_text": optStr(i.PurposeText), "bank_flow_no": optStr(i.BankFlowNo),
		"claim_status": i.ClaimStatus, "claimed_by": optI64(i.ClaimedBy),
		"claimed_at": fmtTimePtr(i.ClaimedAt),
		"created_at": fmtTime(i.CreatedAt),
	}
}

func ToAPIExpense(e fstore.FExpense) map[string]any {
	return map[string]any{
		"id": e.ID, "code": optStr(e.Code), "status": e.Status,
		"project_id": e.ProjectID, "budget_line_id": optI64(e.BudgetLineID),
		"applicant_user_id": e.ApplicantUserID, "amount": numDec(e.Amount, 2),
		"expense_category": optStr(e.ExpenseCategory), "expense_type": e.ExpenseType,
		"description":        optStr(e.Description),
		"submit_mode":        e.SubmitMode,
		"ai_verdict":         optStr(e.AiVerdict),
		"invoice_check":      e.InvoiceCheckStatus,
		"submitted_at":       fmtTimePtr(e.SubmittedAt),
		"paid_at":            fmtTimePtr(e.PaidAt),
		"frozen_at":          fmtTimePtr(e.FrozenAt),
		"created_at":         fmtTime(e.CreatedAt),
	}
}

func ToAPIApproval(a fstore.FExpenseApproval) map[string]any {
	return map[string]any{
		"id": a.ID, "expense_id": a.ExpenseID, "step_order": a.StepOrder,
		"approver_user_id": optI64(a.ApproverUserID), "role": optStr(a.Role),
		"action": optStr(a.Action), "comment": optStr(a.Comment),
		"status": a.Status, "acted_at": fmtTimePtr(a.ActedAt),
	}
}
