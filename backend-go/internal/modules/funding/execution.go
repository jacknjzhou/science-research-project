// 执行率聚合（/funding/execution）、执行预警（/funding/warnings）、间接费用计提（F-12）。
package funding

import (
	"errors"
	"math/big"
	"net/http"
	"strconv"
	"time"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
)

// executionOf：聚合某项目执行度量（金额 string，比率 float64）。
func (h *Handler) executionOf(c *gin.Context, tenantID, projectID int64) map[string]any {
	p := &projectID
	budget, _ := h.q.SumBudgetApproved(c, fstore.SumBudgetApprovedParams{TenantID: tenantID, ProjectID: projectID})
	income, _ := h.q.SumClaimedIncome(c, fstore.SumClaimedIncomeParams{TenantID: tenantID, ProjectID: p})
	used, _ := h.q.SumExpenseUsed(c, fstore.SumExpenseUsedParams{TenantID: tenantID, ProjectID: projectID})
	frozen, _ := h.q.SumExpenseFrozen(c, fstore.SumExpenseFrozenParams{TenantID: tenantID, ProjectID: projectID})

	budgetR := moneyRat(budget)
	incomeR := moneyRat(income)
	usedR := moneyRat(used)
	frozenR := moneyRat(frozen)
	remaining := new(big.Rat).Sub(new(big.Rat).Add(budgetR, new(big.Rat)), new(big.Rat).Add(usedR, frozenR))

	rate := func(used, base *big.Rat) float64 {
		if base.Sign() <= 0 {
			return 0
		}
		f, _ := new(big.Rat).Quo(used, base).Float64()
		return f
	}
	return map[string]any{
		"projectId":         projectID,
		"budgetApproved":    budgetR.FloatString(2),
		"incomeTotal":       incomeR.FloatString(2),
		"used":              usedR.FloatString(2),
		"frozen":            frozenR.FloatString(2),
		"remaining":         remaining.FloatString(2),
		"execRateByBudget":  rate(usedR, budgetR),
		"execRateByIncome":  rate(usedR, incomeR),
	}
}

// FundingWarnings GET /funding/warnings?projectId=
// 惰性计算不落库：WARN 执行率≥80%；CRITICAL ≥100%；DEADLINE_RISK 结题窗口 30 天内且 <100%。
func (h *Handler) FundingWarnings(c *gin.Context) {
	d := auth.DomainFrom(c)
	pid := optInt64(c, "project_id")

	var projects []fstore.ListExecutingProjectsRow
	if pid != nil {
		brief, err := h.q.GetProjectBrief(c, *pid)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				httpx.WriteOK(c, gin.H{"list": []any{}})
				return
			}
			httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
			return
		}
		projects = append(projects, fstore.ListExecutingProjectsRow{
			ID: brief.ID, Code: brief.Code, Title: brief.Title,
			EndDate: brief.EndDate, ActualEndDate: brief.ActualEndDate,
		})
	} else {
		rows, err := h.q.ListExecutingProjects(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
			return
		}
		projects = rows
	}

	out := make([]map[string]any, 0, len(projects))
	for _, p := range projects {
		m := h.executionOf(c, d.TenantID, p.ID)
		rate, _ := m["execRateByBudget"].(float64)
		var level, message string
		deadline := p.ActualEndDate
		if deadline == nil {
			deadline = p.EndDate
		}
		switch {
		case rate >= 1.0:
			level, message = "CRITICAL", "经费执行率已达 100%，请关注后续支出合规性"
		case rate >= 0.8:
			level, message = "WARN", "经费执行率已超过 80%，请评估剩余预算安排"
		}
		if level != "CRITICAL" && deadline != nil {
			days := int(time.Until(*deadline).Hours() / 24)
			if days >= 0 && days <= 30 && rate < 1.0 {
				level, message = "DEADLINE_RISK", "距结题窗口 "+strconv.Itoa(days)+" 天，执行率 "+
					strconv.FormatFloat(rate*100, 'f', 1, 64)+"%，存在突击支出风险"
			}
		}
		if level == "" {
			continue
		}
		out = append(out, map[string]any{
			"projectId":   p.ID,
			"projectCode": optStr(p.Code),
			"projectName": p.Title,
			"level":       level,
			"execRate":    rate,
			"deadline":    fmtTimePtr(deadline),
			"message":     message,
		})
		// CRITICAL 触达 PI（best-effort，去重交给通知侧 biz_ref 未读判断）
		if level == "CRITICAL" {
			if brief, err := h.q.GetProjectBrief(c, p.ID); err == nil {
				h.notify(brief.PiUserID, "FUNDING_WARNING", "经费预警：项目 "+p.Title,
					message, "project/"+fmtInt(p.ID), d.TenantID)
			}
		}
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": len(out)})
}

type indirectCalcBody struct {
	ProjectID int64    `json:"project_id" binding:"required"`
	Rate      *float64 `json:"rate"`
}

// CalculateIndirectFee POST /indirect-fees/calculate —— 按认领到账额 × 间接费率计提（F-12 简化）。
// 费率缺省 0.20；上限 0.30（超限 40904）；同项目幂等更新。
func (h *Handler) CalculateIndirectFee(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b indirectCalcBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	rate := 0.20
	if b.Rate != nil {
		rate = *b.Rate
	}
	if rate < 0 || rate > 0.30 {
		httpx.WriteErr(c, http.StatusUnprocessableEntity, 40904, "间接费率须在 0~0.30 内")
		return
	}
	if _, err := h.q.GetProjectBrief(c, b.ProjectID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "项目不存在")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	income, _ := h.q.SumClaimedIncome(c, fstore.SumClaimedIncomeParams{TenantID: d.TenantID, ProjectID: &b.ProjectID})
	used, _ := h.q.SumExpenseUsed(c, fstore.SumExpenseUsedParams{TenantID: d.TenantID, ProjectID: b.ProjectID})
	budget, _ := h.q.SumBudgetApproved(c, fstore.SumBudgetApprovedParams{TenantID: d.TenantID, ProjectID: b.ProjectID})

	incomeR := moneyRat(income)
	indirect := new(big.Rat).Mul(incomeR, new(big.Rat).SetFloat64(rate))
	detail, _ := jsonMarshal(map[string]any{
		"rate": rate, "base": "claimed_income", "income": income, "formula": "income * rate",
	})
	period := time.Now().Format("200601")

	existing, err := h.q.GetIndirectFeeByProject(c, fstore.GetIndirectFeeByProjectParams{
		ProjectID: b.ProjectID, TenantID: d.TenantID,
	})
	var saved fstore.FIndirectFee
	if err == nil {
		saved, err = h.q.UpdateIndirectFee(c, fstore.UpdateIndirectFeeParams{
			ID: existing.ID, TenantID: d.TenantID, Period: period,
			TotalBudget: strToNum(budget), ActualIncome: strToNum(income), ActualExpense: strToNum(used),
			IndirectRate: strToNum(ratStr(rate)), IndirectAmount: ratToNum(indirect),
			PerformanceRate: strToNum("0"), PerformanceAmount: strToNum("0"),
			CalcDetail: detail,
		})
	} else {
		saved, err = h.q.CreateIndirectFee(c, fstore.CreateIndirectFeeParams{
			TenantID: d.TenantID, CreatorID: d.UserID,
			ProjectID: b.ProjectID, LegalEntityID: defaultEntity, // E_PROJECT 无法人快照读出时缺省主法人
			Period: period, TotalBudget: strToNum(budget),
			ActualIncome: strToNum(income), ActualExpense: strToNum(used),
			IndirectRate: strToNum(ratStr(rate)), IndirectAmount: ratToNum(indirect),
			PerformanceRate: strToNum("0"), PerformanceAmount: strToNum("0"),
			CalcDetail: detail,
		})
	}
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "计提失败："+err.Error())
		return
	}
	httpx.WriteOK(c, map[string]any{
		"id": saved.ID, "projectId": saved.ProjectID, "period": saved.Period,
		"actualIncome": numDec(saved.ActualIncome, 2), "indirectRate": numDec(saved.IndirectRate, 4),
		"indirectAmount": numDec(saved.IndirectAmount, 2),
	})
}

// ListIndirectFees GET /indirect-fees?project_id=（当前仅支持单项目查询，缺省空）。
func (h *Handler) ListIndirectFees(c *gin.Context) {
	d := auth.DomainFrom(c)
	pid := optInt64(c, "project_id")
	if pid == nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "project_id 必填")
		return
	}
	fee, err := h.q.GetIndirectFeeByProject(c, fstore.GetIndirectFeeByProjectParams{
		ProjectID: *pid, TenantID: d.TenantID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteOK(c, gin.H{"list": []any{}})
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	httpx.WriteOK(c, gin.H{"list": []any{fee}, "total": 1})
}
