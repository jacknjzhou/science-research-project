// T23 执行三维监控：dim=project|college|subject。
package funding

import (
	"math/big"
	"net/http"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
)

// FundingExecution GET /funding/execution?projectId=&dim=project|college|subject
// dim 缺省 project（原单项目聚合不变）；college/subject 返回 {list:[...]}。
func (h *Handler) FundingExecution(c *gin.Context) {
	d := auth.DomainFrom(c)
	switch c.DefaultQuery("dim", "project") {
	case "college":
		rows, err := h.q.ExecutionByCollege(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50001, "聚合失败")
			return
		}
		out := make([]map[string]any, 0, len(rows))
		for _, r := range rows {
			out = append(out, dimRow(r.DimID, r.Approved, r.Used, r.Frozen))
		}
		httpx.WriteOK(c, gin.H{"list": out, "total": len(out)})
	case "subject":
		rows, err := h.q.ExecutionBySubject(c, d.TenantID)
		if err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50001, "聚合失败")
			return
		}
		out := make([]map[string]any, 0, len(rows))
		for _, r := range rows {
			out = append(out, dimRow(r.DimID, r.Approved, r.Used, r.Frozen))
		}
		httpx.WriteOK(c, gin.H{"list": out, "total": len(out)})
	default:
		pid := optInt64(c, "project_id")
		if pid == nil {
			httpx.WriteErr(c, http.StatusBadRequest, 40001, "project_id 必填")
			return
		}
		httpx.WriteOK(c, h.executionOf(c, d.TenantID, *pid))
	}
}

// dimRow 聚合行 → 契约 map（金额 string、execRate float64）。
func dimRow(dimID int64, approved, used, frozen pgtype.Numeric) map[string]any {
	a := numToRat(approved)
	u := numToRat(used)
	f := numToRat(frozen)
	remaining := new(big.Rat).Sub(a, new(big.Rat).Add(u, f))
	rate := 0.0
	if a.Sign() > 0 {
		rate, _ = new(big.Rat).Quo(u, a).Float64()
	}
	return map[string]any{
		"dimId": dimID, "approved": a.FloatString(2), "used": u.FloatString(2),
		"frozen": f.FloatString(2), "remaining": remaining.FloatString(2), "execRate": rate,
	}
}

// numToRat pgtype.Numeric → big.Rat（无效值视为 0）。
func numToRat(n pgtype.Numeric) *big.Rat {
	if !n.Valid || n.Int == nil {
		return new(big.Rat)
	}
	r := new(big.Rat).SetInt(n.Int)
	if n.Exp < 0 {
		r.Mul(r, new(big.Rat).SetFrac(big.NewInt(1), new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(-n.Exp)), nil)))
	} else if n.Exp > 0 {
		r.Mul(r, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(n.Exp)), nil)))
	}
	return r
}
