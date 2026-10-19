// 报销申请：填单（三重指纹查重）/ 列表 / 详情 / 提交（冻结 + 审批链生成，F-07/F-09/F-10）。
package funding

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"strconv"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

type expenseBody struct {
	ProjectID       int64    `json:"project_id" binding:"required"`
	BudgetLineID    *int64   `json:"budget_line_id"`
	LegalEntityID   int64    `json:"legal_entity_id" binding:"required"`
	Amount          string   `json:"amount" binding:"required"`
	ExpenseCategory *string  `json:"expense_category"`
	ExpenseType     string   `json:"expense_type" binding:"required"`
	Description     *string  `json:"description"`
	SubmitMode      string   `json:"submit_mode"`
	InvoiceNo       *string  `json:"invoice_no"`
	InvoiceDate     *string  `json:"invoice_date"`
}

func fingerprintOf(no, amount, date string) string {
	h := sha256.Sum256([]byte(no + "|" + amount + "|" + date))
	return hex.EncodeToString(h[:])
}

// CreateExpense POST /expenses —— 填单（DRAFT）。带发票三要素即建指纹（提交时查重）。
func (h *Handler) CreateExpense(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b expenseBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	switch b.ExpenseType {
	case "EQUIPMENT", "MATERIAL", "TRAVEL", "MEETING", "LABOR", "EXPERT", "OTHER":
	default:
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "expense_type 非法")
		return
	}
	if b.SubmitMode == "" {
		b.SubmitMode = "预算制"
	}
	if b.SubmitMode != "预算制" && b.SubmitMode != "包干制" {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "submit_mode 仅支持 预算制/包干制")
		return
	}
	var fpHash *string
	if b.InvoiceNo != nil && *b.InvoiceNo != "" {
		date := ""
		if b.InvoiceDate != nil {
			date = *b.InvoiceDate
		}
		fp := fingerprintOf(*b.InvoiceNo, b.Amount, date)
		fpHash = &fp
	}
	created, err := h.q.CreateExpense(c, fstore.CreateExpenseParams{
		TenantID: d.TenantID, CreatorID: d.UserID,
		ProjectID: b.ProjectID, BudgetLineID: b.BudgetLineID,
		LegalEntityID: b.LegalEntityID, ApplicantUserID: d.UserID,
		Amount: strToNum(b.Amount),
		ExpenseCategory: b.ExpenseCategory, ExpenseType: b.ExpenseType,
		Description: b.Description, InvoiceIds: []byte("[]"),
		FingerprintInvoiceNo:   b.InvoiceNo,
		FingerprintAmount:      strToNum(b.Amount),
		FingerprintInvoiceDate: parseDatePtr(b.InvoiceDate),
		FingerprintHash:        fpHash,
		SubmitMode:             b.SubmitMode,
	})
	if err != nil {
		// 三重指纹唯一索引（uk_expense_fingerprint）：同发票在途单已存在 → 40903（PRD 11）
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" && pgErr.ConstraintName == "uk_expense_fingerprint" {
			httpx.WriteErr(c, http.StatusConflict, 40903, "同一发票（号码+金额+日期）已存在在途报销单")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败："+err.Error())
		return
	}
	code := codeOf("EXP", created.ID)
	_ = h.q.SetExpenseCode(c, fstore.SetExpenseCodeParams{ID: created.ID, Code: &code})
	httpx.WriteOK(c, ToAPIExpense(created))
}

// ListExpenses GET /expenses?project_id=&status=&applicant_user_id=。
func (h *Handler) ListExpenses(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListExpenses(c, fstore.ListExpensesParams{
		TenantID:        d.TenantID,
		ProjectID:       optInt64(c, "project_id"),
		Status:          optQuery(c, "status"),
		ApplicantUserID: optInt64(c, "applicant_user_id"),
		Limit:           limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, err := h.q.CountExpenses(c, fstore.CountExpensesParams{
		TenantID:        d.TenantID,
		ProjectID:       optInt64(c, "project_id"),
		Status:          optQuery(c, "status"),
		ApplicantUserID: optInt64(c, "applicant_user_id"),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, e := range rows {
		out = append(out, ToAPIExpense(e))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// GetExpense GET /expenses/:id —— 含审批步骤。
func (h *Handler) GetExpense(c *gin.Context) {
	e, err := h.q.GetExpense(c, pathID(c))
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "报销单不存在")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	steps, err := h.q.ListApprovalsByExpense(c, e.ID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	ss := make([]map[string]any, 0, len(steps))
	for _, s := range steps {
		ss = append(ss, ToAPIApproval(s))
	}
	m := ToAPIExpense(e)
	m["approvals"] = ss
	httpx.WriteOK(c, m)
}

type approverRef struct{ role string }

// SubmitExpense POST /expenses/:id/submit —— 事务：
// DRAFT→SUBMITTED；三重指纹查重（40903）；预算制冻结（余额不足 40902）；
// 生成审批链（<10 万 1 步 R-MANAGER，≥10 万 2 步 R-MANAGER→R-LEADER）。
func (h *Handler) SubmitExpense(c *gin.Context) {
	d := auth.DomainFrom(c)
	submitted, err := h.q.SubmitExpense(c, pathID(c))
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusConflict, 40901, "仅 DRAFT 状态可提交")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "提交失败")
		return
	}
	// 三重指纹查重（提交时点，同指纹存在未终止单 → 拒绝并回退状态）
	if submitted.FingerprintHash != nil {
		taken, err := h.q.FingerprintTaken(c, fstore.FingerprintTakenParams{
			TenantID: d.TenantID, FingerprintHash: submitted.FingerprintHash,
		})
		if err == nil && taken != submitted.ID {
			_ = h.q.SetExpenseStatus(c, fstore.SetExpenseStatusParams{ID: submitted.ID, Status: "DRAFT"})
			httpx.WriteErr(c, http.StatusConflict, 40903, "同一发票（号码+金额+日期）已存在在途报销单")
			return
		}
	}
	// 预算冻结（F-10）：行级 FOR UPDATE 校验余额后冻结
	if submitted.SubmitMode == "预算制" && submitted.BudgetLineID != nil {
		err = pgx.BeginFunc(c, h.db, func(tx pgx.Tx) error {
			q := h.q.WithTx(tx)
			line, err := q.GetLineForUpdate(c, *submitted.BudgetLineID)
			if err != nil {
				return err
			}
			if remainingOf(line) < numFloat(submitted.Amount) {
				return errInsufficient
			}
			return q.FreezeLine(c, fstore.FreezeLineParams{
				ID: line.ID, AmountFrozen: submitted.Amount,
			})
		})
		if err != nil {
			_ = h.q.SetExpenseStatus(c, fstore.SetExpenseStatusParams{ID: submitted.ID, Status: "DRAFT"})
			if errors.Is(err, errInsufficient) {
				httpx.WriteErr(c, http.StatusConflict, 40902, "预算行可支余额不足，冻结失败")
				return
			}
			httpx.WriteErr(c, http.StatusInternalServerError, 50002, "预算冻结失败")
			return
		}
	}
	// 审批链（F-09 简化规则路由）
	amount := numFloat(submitted.Amount)
	steps := []string{"R-MANAGER"}
	if amount >= 100000 {
		steps = append(steps, "R-LEADER")
	}
	for i, role := range steps {
		r := role
		if err := h.q.CreateApproval(c, fstore.CreateApprovalParams{
			TenantID: d.TenantID, CreatorID: d.UserID,
			ExpenseID: submitted.ID, StepOrder: int32(i + 1), Role: &r,
		}); err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50002, "审批链生成失败")
			return
		}
	}
	// 触达第一步审批角色（best-effort）
	h.notifyRole(steps[0], "EXPENSE_APPROVAL", "待审批：报销单 "+deref(submitted.Code),
		"金额 "+numDec(submitted.Amount, 2)+" 元，请及时审批",
		"expense/"+strconv.FormatInt(submitted.ID, 10), d.TenantID)
	fresh, _ := h.q.GetExpense(c, submitted.ID)
	httpx.WriteOK(c, ToAPIExpense(fresh))
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
