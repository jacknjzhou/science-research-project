package performance

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
)

// scoringRule 是 m_scheme_factor.scoring_rule 的解析结构。
type scoringRule struct {
	Method   string              `json:"method"`   // COUNT | BY_LEVEL | BY_AMOUNT | LADDER
	Unit     *float64            `json:"unit"`     // 每单位分值（COUNT/BY_AMOUNT），缺省 1
	LevelMap map[string]float64  `json:"levelMap"` // BY_LEVEL：key(output_type/project_type)→分
	Ladder   []ladderTier        `json:"ladder"`   // LADDER：区间→分
}

type ladderTier struct {
	Min   float64 `json:"min"`
	Max   float64 `json:"max"` // 上界含（闭区间 [min,max]）；末档可用极大值
	Score float64 `json:"score"`
}

// aggResult 是某数据源对某 staff 聚合后的规范化信号。
type aggResult struct {
	byType   map[string]int32 // R_OUTPUT→output_type 计数；E_PROJECT→project_type 计数
	total    int32            // 单据总数（Σ byType 或单值型不适用则 0）
	amount   float64          // 金额（F_INCOME/T_DEAL 的 metric；E_PROJECT 的 Σ 预算）
	evidence []any            // 证据对象数组（直接落 m_record_item.evidence）
}

var reYear = regexp.MustCompile(`^(\d{4})$`)
var reQuarter = regexp.MustCompile(`^(\d{4})\s*[Qq]([1-4])$`)
var reMonth = regexp.MustCompile(`^(\d{4})-(\d{2})$`)

// periodRange：把 (periodType, period) 归一为 [from,to] 闭区间日期（pgtype.Date）。
// 支持 YEAR="2026" / QUARTER="2026Q3" / MONTH="2026-03"。无法解析→返回空(from/to Valid=false)，
// 由 metrics 的 `::date IS NULL` 分支兜底为“全时段”（M0 宽松，不报 400 之外错误）。
func periodRange(periodType, period string) (from, to pgtype.Date) {
	p := strings.TrimSpace(period)
	var start, next time.Time
	if m := reQuarter.FindStringSubmatch(p); m != nil {
		y, _ := strconv.Atoi(m[1])
		q, _ := strconv.Atoi(m[2])
		start = time.Date(y, time.Month((q-1)*3+1), 1, 0, 0, 0, 0, time.UTC)
		next = start.AddDate(0, 3, 0)
	} else if m := reMonth.FindStringSubmatch(p); m != nil {
		y, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		start = time.Date(y, time.Month(mo), 1, 0, 0, 0, 0, time.UTC)
		next = start.AddDate(0, 1, 0)
	} else if m := reYear.FindStringSubmatch(p); m != nil {
		y, _ := strconv.Atoi(m[1])
		start = time.Date(y, 1, 1, 0, 0, 0, 0, time.UTC)
		next = start.AddDate(1, 0, 0)
	} else {
		return pgtype.Date{Valid: false}, pgtype.Date{Valid: false}
	}
	_ = periodType // 冗余：以 period 串自证粒度；保留形参便于契约可读与将来校验
	toDay := next.AddDate(0, 0, -1)
	return pgtype.Date{Time: start, Valid: true}, pgtype.Date{Time: toDay, Valid: true}
}

// factorInput：scoreFactor 的窄入参，只取用得到的因子字段——把纯计分逻辑与 sqlc 生成物字段名解耦。
// Weight/MaxScore 直接接 mstore.SchemeFactor 的同名字段（SELECT * → pgtype.Numeric）。
type factorInput struct {
	FactorCode  string
	Weight      pgtype.Numeric
	MaxScore    pgtype.Numeric
	ScoringRule json.RawMessage
	DataSource  string
}

// scoreFactor：对一个因子 + 其数据源聚合结果，算出 (metric, raw, weighted, evidence)。纯函数。
func scoreFactor(f factorInput, agg aggResult) (metric, raw, weighted float64, evidence []any) {
	var rule scoringRule
	_ = json.Unmarshal(f.ScoringRule, &rule) // 解析失败→零值 rule，method=""→走 default 记 0
	weight := numN(f.Weight)
	maxScore := numN(f.MaxScore) // !Valid → 0（即不限顶）
	unit := 1.0
	if rule.Unit != nil && *rule.Unit != 0 {
		unit = *rule.Unit
	}
	evidence = agg.evidence
	if evidence == nil {
		evidence = []any{}
	}
	switch strings.ToUpper(strings.TrimSpace(rule.Method)) {
	case "COUNT":
		metric = float64(agg.total)
		raw = metric * unit
	case "BY_LEVEL":
		metric = float64(agg.total)
		for k, cnt := range agg.byType {
			raw += float64(cnt) * rule.LevelMap[k] // levelMap 无此 key → 0
		}
	case "BY_AMOUNT":
		metric = agg.amount
		raw = metric * unit
	case "LADDER":
		metric = agg.amount
		if metric == 0 {
			metric = float64(agg.total)
		}
		for _, t := range rule.Ladder {
			if metric >= t.Min && metric <= t.Max {
				raw = t.Score
				break
			}
		}
	default: // MANUAL / 未知 → 不自动计分
		metric = 0
		raw = 0
	}
	if maxScore > 0 && raw > maxScore {
		raw = maxScore
	}
	weighted = raw * weight / 100.0
	return metric, raw, weighted, evidence
}

// numOr：把 metrics.sql 里 NUMERIC::text 投影出的字符串转 float；失败或空返回 def（仅用于跨表聚合行）。
func numOr(s string, def float64) float64 {
	if s == "" {
		return def
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return def
	}
	return v
}

// numN：把 pgtype.Numeric（因子 Weight/MaxScore）转 float；!Valid 或出错返回 0。
func numN(n pgtype.Numeric) float64 {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return 0
	}
	return f.Float64
}

// ComputeResult：一次 calculate 的汇总（对齐契约 CalculateResult）。
type ComputeResult struct {
	CalcBatch string `json:"calc_batch"`
	Period    string `json:"period"`
	Computed  int    `json:"computed"`
	Inserted  int    `json:"inserted"`
	Updated   int    `json:"updated"`
}

type calculateBody struct {
	Period   string  `json:"period" binding:"required"`
	DeptIDs  []int64 `json:"dept_ids"`
	StaffIDs []int64 `json:"staff_ids"`
}

// CalculatePerformance：处理 POST /perf/schemes/{id}/calculate。
func (h *Handler) CalculatePerformance(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	scheme, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	var b calculateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	factors, err := h.q.ListFactorsBySchemeForCalc(c, mstore.ListFactorsBySchemeForCalcParams{SchemeID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "读取因子失败")
		return
	}
	if len(factors) == 0 {
		httpx.WriteErr(c, 400, 40001, "方案未配置因子，无法计算")
		return
	}
	from, to := periodRange(scheme.PeriodType, b.Period)

	// 解析待算人员集合：staff_ids 优先；否则按 dept_ids 取在研项目 PI（distinct）。
	staff := b.StaffIDs
	staffDept := map[int64]*int64{}
	if len(staff) == 0 {
		rows, err := h.q.ListCalcStaff(c, mstore.ListCalcStaffParams{TenantID: d.TenantID, DeptIds: b.DeptIDs})
		if err != nil {
			httpx.WriteErr(c, 500, 50002, "取计算人员失败")
			return
		}
		for _, r := range rows {
			staff = append(staff, r.StaffUserID)
			if r.DeptID != nil {
				staffDept[r.StaffUserID] = r.DeptID
			}
		}
	}

	batch := c.GetHeader("Idempotency-Key")
	if batch == "" {
		batch = fmt.Sprintf("BATCH-%s-%d", b.Period, time.Now().UTC().Unix())
	}

	res := ComputeResult{CalcBatch: batch, Period: b.Period}
	for _, sid := range staff {
		inserted, err := h.computeStaff(c, d, id, factors, sid, staffDept[sid], b.Period, from, to, batch)
		if err != nil {
			httpx.WriteErr(c, 500, 50002, "计算失败："+err.Error())
			return
		}
		res.Computed++
		if inserted {
			res.Inserted++
		} else {
			res.Updated++
		}
	}
	httpx.WriteOK(c, res)
}

// computeStaff：对单个 staff 聚合→算分→upsert record→重建 items。返回是否“新增”（false=覆盖）。
func (h *Handler) computeStaff(ctx context.Context, d auth.Domain, schemeID int64,
	factors []mstore.SchemeFactor, staffID int64, deptID *int64, period string,
	from, to pgtype.Date, batch string) (bool, error) {

	// 存在性预判（区分 inserted/updated）：同方案同周期该人是否已有记录。
	prescheme := schemeID
	cnt, err := h.q.CountRecords(ctx, mstore.CountRecordsParams{
		TenantID: d.TenantID, SchemeID: &prescheme, Period: &period,
		DeptID: nil, StaffUserID: &staffID, Status: nil, Code: nil,
	})
	if err != nil {
		return false, err
	}
	existed := cnt > 0

	// 只为“出现过的数据源”发查询，避免无谓扫描。
	need := map[string]bool{}
	for _, f := range factors {
		need[f.DataSource] = true
	}
	var (
		aggOut, aggProj aggResult
		aggInc, aggDeal aggResult
	)
	if need["R_OUTPUT"] {
		rows, err := h.q.MetricsOutputsByStaff(ctx, mstore.MetricsOutputsByStaffParams{
			TenantID: d.TenantID, FromDate: from, ToDate: to, Column2: staffID,
		})
		if err != nil {
			return existed, err
		}
		aggOut = aggFromTypeRows(rows)
	}
	if need["E_PROJECT"] {
		rows, err := h.q.MetricsProjectsByStaff(ctx, mstore.MetricsProjectsByStaffParams{
			TenantID: d.TenantID, Column2: staffID, FromDate: from, ToDate: to,
		})
		if err != nil {
			return existed, err
		}
		aggProj = aggFromProjRows(rows)
	}
	if need["F_INCOME"] {
		row, err := h.q.MetricsIncomeByStaff(ctx, mstore.MetricsIncomeByStaffParams{
			TenantID: d.TenantID, Column2: staffID, FromDate: from, ToDate: to,
		})
		if err != nil {
			return existed, err
		}
		aggInc = aggFromAmountRow(row.Metric, jsonbBytes(row.Evidence))
	}
	if need["T_DEAL"] {
		row, err := h.q.MetricsTransferByStaff(ctx, mstore.MetricsTransferByStaffParams{
			TenantID: d.TenantID, Column2: staffID, FromDate: from, ToDate: to,
		})
		if err != nil {
			return existed, err
		}
		aggDeal = aggFromAmountRow(row.Metric, jsonbBytes(row.Evidence))
	}

	// 逐因子算分，累加 total，收集明细。
	total := 0.0
	type itemRow struct {
		code             string
		metric, raw, wgt float64
		ev               []any
	}
	items := make([]itemRow, 0, len(factors))
	for _, f := range factors {
		var agg aggResult
		switch f.DataSource {
		case "R_OUTPUT":
			agg = aggOut
		case "E_PROJECT":
			agg = aggProj
		case "F_INCOME":
			agg = aggInc
		case "T_DEAL":
			agg = aggDeal
		default: // MANUAL
			agg = aggResult{}
		}
		fi := factorInput{
			FactorCode: f.FactorCode, Weight: f.Weight, MaxScore: f.MaxScore,
			ScoringRule: json.RawMessage(f.ScoringRule), DataSource: f.DataSource,
		}
		metric, raw, weighted, ev := scoreFactor(fi, agg)
		total += weighted
		items = append(items, itemRow{code: f.FactorCode, metric: metric, raw: raw, wgt: weighted, ev: ev})
	}

	// 组装 calc_detail（复核用的算分快照）。
	detail := map[string]any{
		"period": period, "calc_batch": batch, "scheme_id": schemeID,
		"total": round2(total),
		"factors": func() []map[string]any {
			out := make([]map[string]any, 0, len(items))
			for _, it := range items {
				out = append(out, map[string]any{
					"factor_code": it.code, "metric": it.metric,
					"raw_score": round2(it.raw), "weighted_score": round2(it.wgt),
				})
			}
			return out
		}(),
	}
	detailJSON, _ := json.Marshal(detail)

	rec, err := h.q.UpsertRecord(ctx, mstore.UpsertRecordParams{
		TenantID: d.TenantID, CreatorID: d.UserID, SchemeID: schemeID, StaffUserID: staffID,
		Period: period, DeptID: deptID, Column7: numericPtr(fmt.Sprintf("%.2f", round2(total))),
		Column8: detailJSON, CalcBatch: &batch, Column10: "INTERNAL",
	})
	if err != nil {
		return existed, err
	}
	// 重建明细。
	if err := h.q.DeleteItemsByRecord(ctx, rec.ID); err != nil {
		return existed, err
	}
	for _, it := range items {
		evb, _ := json.Marshal(it.ev)
		if _, err := h.q.InsertItem(ctx, mstore.InsertItemParams{
			RecordID: rec.ID, TenantID: d.TenantID, FactorCode: it.code,
			Column4: numericPtr(fmt.Sprintf("%.4f", it.metric)),
			Column5: numericPtr(fmt.Sprintf("%.2f", round2(it.raw))),
			Column6: numericPtr(fmt.Sprintf("%.2f", round2(it.wgt))),
			Column7: evb,
		}); err != nil {
			return existed, err
		}
	}
	return !existed, nil
}

// —— 把 sqlc 行规整为 aggResult ——

func aggFromTypeRows(rows []mstore.MetricsOutputsByStaffRow) aggResult {
	a := aggResult{byType: map[string]int32{}, evidence: []any{}}
	for _, r := range rows {
		a.byType[r.OutputType] = r.Cnt
		a.total += r.Cnt
		a.evidence = appendEvidence(a.evidence, jsonbBytes(r.Evidence))
	}
	return a
}

func aggFromProjRows(rows []mstore.MetricsProjectsByStaffRow) aggResult {
	a := aggResult{byType: map[string]int32{}, evidence: []any{}}
	for _, r := range rows {
		a.byType[coalesceStr(r.ProjectType, "")] = r.Cnt
		a.total += r.Cnt
		a.amount += numOr(r.Amount, 0)
		a.evidence = appendEvidence(a.evidence, jsonbBytes(r.Evidence))
	}
	return a
}

func aggFromAmountRow(metric string, ev []byte) aggResult {
	return aggResult{
		byType:   map[string]int32{},
		amount:   numOr(metric, 0),
		evidence: appendEvidence([]any{}, ev),
	}
}

// appendEvidence：把一行 JSONB 证据（形如 [{...},{...}]）解包追加到大数组；解析失败静默跳过。
func appendEvidence(dst []any, raw []byte) []any {
	if len(raw) == 0 {
		return dst
	}
	var part []any
	if err := json.Unmarshal(raw, &part); err != nil {
		return dst
	}
	return append(dst, part...)
}

// jsonbBytes：把 sqlc 生成的 `Evidence interface{}`（COALESCE(jsonb_agg(...)) 列，pgx 常解为 []byte）
// 归一为 []byte 供 appendEvidence 使用；nil→nil、[]byte/string 直接取，其余走 JSON 编码兜底。
func jsonbBytes(v any) []byte {
	switch t := v.(type) {
	case nil:
		return nil
	case []byte:
		return t
	case string:
		return []byte(t)
	default:
		b, err := json.Marshal(v)
		if err != nil {
			return nil
		}
		return b
	}
}

// numericPtr：字符串→pgtype.Numeric（供 numeric 参数位；空/非法→无效）。
func numericPtr(s string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != "" {
		_ = n.Scan(s)
	}
	return n
}

func round2(f float64) float64 {
	return float64(int64(f*100+0.5)) / 100
}
