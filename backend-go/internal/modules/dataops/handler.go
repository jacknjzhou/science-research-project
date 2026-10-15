// 数据决策域（D）：经费监督大屏真聚合（F-18 一图一舱三预警）。
// 只读投影，复用 fstore 查询；legalEntityId 可空看合并视图。
package dataops

import (
	"math/big"
	"net/http"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	q *fstore.Queries
}

func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: fstore.New(pool)} }

func Register(r gin.IRoutes, h *Handler) {
	r.GET("/dashboard/funding", h.FundingDashboard)
}

// FundingDashboard GET /dashboard/funding?legalEntityId=&fiscalYear=
// （fiscalYear 暂以当前自然年承载，年内口径见各查询；契约字段全量输出）。
func (h *Handler) FundingDashboard(c *gin.Context) {
	d := auth.DomainFrom(c)
	entity := optInt64(c, "legalEntityId")

	budget, err := h.q.DashTotalBudget(c, fstore.DashTotalBudgetParams{TenantID: d.TenantID, LegalEntityID: entity})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "预算聚合失败")
		return
	}
	income, err := h.q.DashYearIncome(c, fstore.DashYearIncomeParams{TenantID: d.TenantID, LegalEntityID: entity})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "到账聚合失败")
		return
	}
	used, err := h.q.DashYearUsed(c, fstore.DashYearUsedParams{TenantID: d.TenantID, LegalEntityID: entity})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "支出聚合失败")
		return
	}
	violation, err := h.q.DashViolationCount(c, fstore.DashViolationCountParams{TenantID: d.TenantID, LegalEntityID: entity})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "违规统计失败")
		return
	}
	heat, err := h.q.DashDeptHeatmap(c, fstore.DashDeptHeatmapParams{TenantID: d.TenantID, LegalEntityID: entity})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "部门热力聚合失败")
		return
	}
	trend, err := h.q.DashTrend12(c, fstore.DashTrend12Params{TenantID: d.TenantID, LegalEntityID: entity})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "趋势聚合失败")
		return
	}
	buckets, err := h.q.DashCountsByState(c, fstore.DashCountsByStateParams{TenantID: d.TenantID, LegalEntityID: entity})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "三预警统计失败")
		return
	}

	heatOut := make([]map[string]any, 0, len(heat))
	for _, r := range heat {
		heatOut = append(heatOut, map[string]any{
			"departmentId":  r.DepartmentID,
			"amount":        r.Used,
			"budget":        r.Budget,
			"executionRate": rateOf(r.Used, r.Budget),
		})
	}
	trendOut := make([]map[string]any, 0, len(trend))
	for _, r := range trend {
		trendOut = append(trendOut, map[string]any{
			"month":         r.Month,
			"amount":        r.Total,
			"executionRate": rateOf(r.Total, budget),
		})
	}
	alerts := map[string]any{"pre": []any{}, "during": []any{}, "post": []any{}}
	for _, b := range buckets {
		alerts[b.Bucket] = map[string]any{"count": b.Cnt}
	}

	// T23 三维监控：大屏补充 byCollege / bySubject 分组聚合（失败静默，不阻断主聚合）
	byCollege := make([]map[string]any, 0)
	bySubject := make([]map[string]any, 0)
	if rows, err := h.q.ExecutionByCollege(c, d.TenantID); err == nil {
		for _, r := range rows {
			byCollege = append(byCollege, map[string]any{
				"dimId": r.DimID, "approved": numToDec(r.Approved), "used": numToDec(r.Used),
				"frozen": numToDec(r.Frozen), "executionRate": rateOf(numToDec(r.Used), numToDec(r.Approved)),
			})
		}
	}
	if rows, err := h.q.ExecutionBySubject(c, d.TenantID); err == nil {
		for _, r := range rows {
			bySubject = append(bySubject, map[string]any{
				"dimId": r.DimID, "approved": numToDec(r.Approved), "used": numToDec(r.Used),
				"frozen": numToDec(r.Frozen), "executionRate": rateOf(numToDec(r.Used), numToDec(r.Approved)),
			})
		}
	}

	httpx.WriteOK(c, map[string]any{
		"totalBudget":   budget,
		"yearIncome":    income,
		"yearUsed":      used,
		"executionRate": rateOf(used, budget),
		"violationCount": violation,
		"deptHeatmap":   heatOut,
		"trend12Months": trendOut,
		"alerts":        alerts,
		"byCollege":     byCollege,
		"bySubject":     bySubject,
	})
}

// rateOf used/budget（两位小数；budget=0 时 0）。
func rateOf(used, budget string) float64 {
	b, ok := new(big.Rat).SetString(budget)
	if !ok || b.Sign() == 0 {
		return 0
	}
	u, ok := new(big.Rat).SetString(used)
	if !ok {
		return 0
	}
	f, _ := new(big.Rat).Quo(u, b).Float64()
	// 保留两位
	return float64(int(f*100+0.5)) / 100
}

// optInt64 非空查询参数转 int64 指针。
func optInt64(c *gin.Context, key string) *int64 {
	v := c.Query(key)
	if v == "" {
		return nil
	}
	n := int64(0)
	for _, ch := range v {
		if ch < '0' || ch > '9' {
			return nil
		}
		n = n*10 + int64(ch-'0')
	}
	return &n
}


// numToDec T23：pgtype.Numeric → "1234.56"（无效值 "0.00"）。
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
