// T24 PI 画像真数据：项目数/经费（真聚合）/成果数/考核分。
package performance

import (
	"math/big"
	"net/http"
	"strconv"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
)

// Portrait GET /portrait/:userId —— 全部真 SQL（无 mock 回退）。
func (h *Handler) Portrait(c *gin.Context) {
	d := auth.DomainFrom(c)
	uid, err := strconv.ParseInt(c.Param("userId"), 10, 64)
	if err != nil || uid <= 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "userId 非法")
		return
	}
	ps, err := h.q.PortraitProjectStats(c, mstore.PortraitProjectStatsParams{TenantID: d.TenantID, Uid: uid})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "项目聚合失败")
		return
	}
	oc, _ := h.q.PortraitOutputCount(c, mstore.PortraitOutputCountParams{TenantID: d.TenantID, Uid: uid})
	var score string
	if s, err := h.q.PortraitLatestScore(c, mstore.PortraitLatestScoreParams{TenantID: d.TenantID, Uid: uid}); err == nil {
		score = numToDec(s)
	}
	budget := numToDec(ps.BudgetTotal)
	// 执行率：该用户名下项目（主持+参与）used 聚合 / budget_total
	usedRat, uerr := h.q.PortraitUsedTotal(c, mstore.PortraitUsedTotalParams{TenantID: d.TenantID, Uid: uid})
	used := "0.00"
	if uerr == nil {
		used = numToDec(usedRat)
	}
	rate := 0.0
	b, _ := new(big.Rat).SetString(budget)
	u, _ := new(big.Rat).SetString(used)
	if b != nil && b.Sign() > 0 && u != nil {
		rate, _ = new(big.Rat).Quo(u, b).Float64()
	}
	httpx.WriteOK(c, gin.H{
		"userId": uid,
		"projects": gin.H{
			"count": ps.ProjectCount, "budgetTotal": budget, "usedTotal": used, "execRate": rate,
		},
		"outputs": gin.H{"count": oc},
		"assessment": gin.H{"latestScore": score},
	})
}

// numToDec pgtype.Numeric → "1234.56"（无效值 "0.00"）。
func numToDec(n pgtype.Numeric) string {
	if !n.Valid || n.Int == nil {
		return "0.00"
	}
	r := new(big.Rat).SetInt(n.Int)
	if n.Exp < 0 {
		r.Mul(r, new(big.Rat).SetFrac(big.NewInt(1), new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(-n.Exp)), nil)))
	} else if n.Exp > 0 {
		r.Mul(r, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(n.Exp)), nil)))
	}
	return r.FloatString(2)
}
