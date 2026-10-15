// 预算编制 / 批复 / 调整（F-02/03/04）与科目字典（F-01）。
// 金额一律 NUMERIC 字符串承载（PRD 2.6）；行余额在应用层计算（表 remaining 未建生成列）。
package funding

import (
	"errors"
	"math/big"
	"net/http"
	"time"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// —— 金额工具（big.Rat 精确加减，2 位小数输出）——
func moneyRat(s string) *big.Rat {
	r, ok := new(big.Rat).SetString(s)
	if !ok {
		return new(big.Rat)
	}
	return r
}

func moneyStr(r *big.Rat) string {
	f, _ := r.Float64()
	return strconvFormat(f)
}

func strconvFormat(f float64) string {
	return trimMoney(big.NewRat(int64(f*100), 100))
}

func trimMoney(r *big.Rat) string {
	f, _ := r.Float64()
	s := big.NewRat(0, 1)
	s.SetFloat64(f)
	return s.FloatString(2)
}

func addMoney(a, b string) string { return moneyStr(new(big.Rat).Add(moneyRat(a), moneyRat(b))) }

func numRat(n pgtype.Numeric) *big.Rat {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return new(big.Rat)
	}
	r := new(big.Rat)
	r.SetFloat64(f.Float64)
	return r
}

func strToNum(s string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != "" {
		_ = n.Scan(s)
	}
	return n
}

// ListSubjects GET /subjects —— 启用科目（扁平，前端组树）。
func (h *Handler) ListSubjects(c *gin.Context) {
	rows, err := h.q.ListSubjects(c)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, s := range rows {
		out = append(out, ToAPISubject(s))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": len(out)})
}

type budgetBody struct {
	ProjectID     int64    `json:"project_id" binding:"required"`
	LegalEntityID int64    `json:"legal_entity_id" binding:"required"`
	Mode          string   `json:"mode" binding:"required"`
	Lines         []lineIn `json:"lines" binding:"required,min=1"`
}

type lineIn struct {
	SubjectID int64  `json:"subject_id" binding:"required"`
	Amount    string `json:"amount" binding:"required"`
}

// CreateBudget POST /budgets —— 预算编制（DRAFT）：头 + 多科目行，同事务。
func (h *Handler) CreateBudget(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b budgetBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	if b.Mode != "预算制" && b.Mode != "包干制" {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "mode 仅支持 预算制/包干制")
		return
	}
	var out any
	err := pgx.BeginFunc(c, h.db, func(tx pgx.Tx) error {
		q := h.q.WithTx(tx)
		total := "0"
		for _, l := range b.Lines {
			total = addMoney(total, l.Amount)
		}
		created, err := q.CreateBudget(c, fstore.CreateBudgetParams{
			TenantID: d.TenantID, CreatorID: d.UserID,
			ProjectID: b.ProjectID, LegalEntityID: b.LegalEntityID,
			Mode: b.Mode, TotalApproved: strToNum(total),
		})
		if err != nil {
			return err
		}
		for _, l := range b.Lines {
			if _, err := q.CreateBudgetLine(c, fstore.CreateBudgetLineParams{
				TenantID: d.TenantID, CreatorID: d.UserID,
				BudgetID: created.ID, SubjectID: l.SubjectID,
				AmountPlanned: strToNum(l.Amount),
			}); err != nil {
				return err
			}
		}
		code := codeOf("BUD", created.ID)
		if err := q.SetBudgetCode(c, fstore.SetBudgetCodeParams{ID: created.ID, Code: &code}); err != nil {
			return err
		}
		out = ToAPIBudget(created)
		return nil
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败："+err.Error())
		return
	}
	httpx.WriteOK(c, out)
}

// GetBudget GET /budgets/:id。
func (h *Handler) GetBudget(c *gin.Context) {
	b, err := h.q.GetBudget(c, pathID(c))
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "预算不存在")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	lines, err := h.q.ListLinesByBudget(c, b.ID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	ls := make([]map[string]any, 0, len(lines))
	for _, l := range lines {
		ls = append(ls, ToAPILine(l))
	}
	m := ToAPIBudget(b)
	m["lines"] = ls
	httpx.WriteOK(c, m)
}

// ListBudgets GET /budgets?project_id=&status=&page=&size=。
func (h *Handler) ListBudgets(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListBudgets(c, fstore.ListBudgetsParams{
		TenantID:  d.TenantID,
		ProjectID: optInt64(c, "project_id"),
		Status:    optQuery(c, "status"),
		Limit:     limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, err := h.q.CountBudgets(c, fstore.CountBudgetsParams{
		TenantID:  d.TenantID,
		ProjectID: optInt64(c, "project_id"),
		Status:    optQuery(c, "status"),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, b := range rows {
		out = append(out, ToAPIBudget(b))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// ListBudgetLines GET /budgets/:id/lines。
func (h *Handler) ListBudgetLines(c *gin.Context) {
	lines, err := h.q.ListLinesByBudget(c, pathID(c))
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(lines))
	for _, l := range lines {
		out = append(out, ToAPILine(l))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": len(out)})
}

// SubmitBudget POST /budgets/:id/submit —— DRAFT→SUBMITTED（守卫：仅 DRAFT 可提）。
func (h *Handler) SubmitBudget(c *gin.Context) {
	b, err := h.q.SubmitBudget(c, pathID(c))
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusConflict, 40901, "仅 DRAFT 状态可提交")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "提交失败")
		return
	}
	httpx.WriteOK(c, ToAPIBudget(b))
}

// ApproveBudget POST /budgets/:id/approve —— SUBMITTED→EXECUTING（批复即生效，回填 approved_at/by）。
func (h *Handler) ApproveBudget(c *gin.Context) {
	d := auth.DomainFrom(c)
	b, err := h.q.ApproveBudget(c, fstore.ApproveBudgetParams{ID: pathID(c), ApprovedBy: &d.UserID})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusConflict, 40901, "仅 SUBMITTED 状态可批复")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "批复失败")
		return
	}
	httpx.WriteOK(c, ToAPIBudget(b))
}

type adjustBody struct {
	Lines  []adjustLineIn `json:"lines" binding:"required,min=1"`
	Remark string         `json:"remark"`
}

type adjustLineIn struct {
	LineID int64  `json:"line_id" binding:"required"`
	Delta  string `json:"delta" binding:"required"`
}

// AdjustBudget POST /budgets/:id/adjust —— EXECUTING 下调整：行 amount_adjusted 累加，
// 头 total_adjusted/version 同步递增（可正可负；调整后行余额仍受报销冻结校验兜底）。
func (h *Handler) AdjustBudget(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b adjustBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	var out any
	err := pgx.BeginFunc(c, h.db, func(tx pgx.Tx) error {
		q := h.q.WithTx(tx)
		sum := new(big.Rat)
		for _, l := range b.Lines {
			sum.Add(sum, moneyRat(l.Delta))
		}
		bud, err := q.AdjustBudget(c, fstore.AdjustBudgetParams{
			ID: pathID(c), TotalAdjusted: strToNum(sum.FloatString(2)),
		})
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return errStateConflict("仅 EXECUTING 状态可调整")
			}
			return err
		}
		for _, l := range b.Lines {
			if err := q.AdjustLine(c, fstore.AdjustLineParams{ID: l.LineID, AmountAdjusted: strToNum(l.Delta)}); err != nil {
				return err
			}
		}
		_, _ = d, time.Now()
		out = ToAPIBudget(bud)
		return nil
	})
	if err != nil {
		var sc *stateConflict
		if errors.As(err, &sc) {
			httpx.WriteErr(c, http.StatusConflict, 40901, sc.msg)
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "调整失败")
		return
	}
	httpx.WriteOK(c, out)
}

// LineBalance GET /budget-lines/:lineId/balance —— 行余额快照。
func (h *Handler) LineBalance(c *gin.Context) {
	l, err := h.q.GetLine(c, pathID(c))
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			httpx.WriteErr(c, http.StatusNotFound, 40401, "预算行不存在")
			return
		}
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	httpx.WriteOK(c, ToAPILine(l))
}
