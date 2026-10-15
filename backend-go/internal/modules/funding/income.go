// 到款登记 / 列表 / 认领 / 银行流水批量导入（F-05/F-06）。
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

type incomeBody struct {
	LegalEntityID int64   `json:"legal_entity_id" binding:"required"`
	ReceiptNo     *string `json:"receipt_no"`
	ReceiptDate   *string `json:"receipt_date"`
	Amount        string  `json:"amount" binding:"required"`
	PayerName     *string `json:"payer_name"`
	PayerBank     *string `json:"payer_bank"`
	PurposeText   *string `json:"purpose_text"`
	BankFlowNo    *string `json:"bank_flow_no"`
}

// CreateIncome POST /incomes —— 单笔登记（UNCLAIMED）。
func (h *Handler) CreateIncome(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b incomeBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	created, err := h.q.CreateIncome(c, fstore.CreateIncomeParams{
		TenantID: d.TenantID, CreatorID: d.UserID,
		LegalEntityID: b.LegalEntityID,
		ReceiptNo:     b.ReceiptNo, ReceiptDate: parseDatePtr(b.ReceiptDate),
		Amount: strToNum(b.Amount),
		PayerName: b.PayerName, PayerBank: b.PayerBank,
		PurposeText: b.PurposeText, BankFlowNo: b.BankFlowNo,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "登记失败："+err.Error())
		return
	}
	code := codeOf("INC", created.ID)
	_ = h.q.SetIncomeCode(c, fstore.SetIncomeCodeParams{ID: created.ID, Code: &code})
	httpx.WriteOK(c, ToAPIIncome(created))
}

// GetIncome GET /incomes/:id 由 List 承担；详情：
func (h *Handler) ListIncomes(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListIncomes(c, fstore.ListIncomesParams{
		TenantID:    d.TenantID,
		ClaimStatus: optQuery(c, "claim_status"),
		ProjectID:   optInt64(c, "project_id"),
		Kw:          optQuery(c, "kw"),
		Limit:       limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, err := h.q.CountIncomes(c, fstore.CountIncomesParams{
		TenantID:    d.TenantID,
		ClaimStatus: optQuery(c, "claim_status"),
		ProjectID:   optInt64(c, "project_id"),
		Kw:          optQuery(c, "kw"),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, i := range rows {
		out = append(out, ToAPIIncome(i))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// ClaimIncome POST /incomes/:id/claim —— 负责人认领（UNCLAIMED→CLAIMED，回填 project_id）。
func (h *Handler) ClaimIncome(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		ProjectID int64 `json:"project_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	claimed, err := h.q.ClaimIncome(c, fstore.ClaimIncomeParams{
		ID: pathID(c), ProjectID: &b.ProjectID, ClaimedBy: &d.UserID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusConflict, 40901, "仅 UNCLAIMED 状态可认领")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "认领失败")
		return
	}
	httpx.WriteOK(c, ToAPIIncome(claimed))
}

type bankFlowIn struct {
	BankFlowNo  string  `json:"bank_flow_no" binding:"required"`
	Amount      string  `json:"amount" binding:"required"`
	PayerName   *string `json:"payer_name"`
	PurposeText *string `json:"purpose_text"`
	ReceiptNo   *string `json:"receipt_no"`
	ReceiptDate *string `json:"receipt_date"`
}

// ImportBankFlow POST /incomes/import-bank-flow —— 批量导入（F-06）。
// bank_flow_no 为幂等键：同租户已存在 → 跳过；返回 {imported, skipped}。
func (h *Handler) ImportBankFlow(c *gin.Context) {
	d := auth.DomainFrom(c)
	var rows []bankFlowIn
	if err := c.ShouldBindJSON(&rows); err != nil || len(rows) == 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误：非空数组必填")
		return
	}
	var imported, skipped int64
	for _, r := range rows {
		exists, err := h.q.IncomeFlowNoExists(c, fstore.IncomeFlowNoExistsParams{
			TenantID: d.TenantID, BankFlowNo: &r.BankFlowNo,
		})
		if err == nil && exists {
			skipped++
			continue
		}
		_, err = h.q.CreateIncome(c, fstore.CreateIncomeParams{
			TenantID: d.TenantID, CreatorID: d.UserID,
			LegalEntityID: 1, // 批量导入缺省法人=1（主法人），业务上可后续认领时纠正
			ReceiptNo:     r.ReceiptNo, ReceiptDate: parseDatePtr(r.ReceiptDate),
			Amount: strToNum(r.Amount),
			PayerName: r.PayerName, PurposeText: r.PurposeText,
			BankFlowNo: &r.BankFlowNo,
		})
		if err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50002, "导入失败："+err.Error())
			return
		}
		imported++
	}
	httpx.WriteOK(c, gin.H{"imported": imported, "skipped": skipped})
}
