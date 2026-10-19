package performance

import (
	"encoding/json"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
)

func jsonToAny(b []byte, fallback any) any {
	if len(b) == 0 {
		return fallback
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return fallback
	}
	return v
}

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

func optStr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func optInt64Ptr(v *int64) any {
	if v == nil {
		return nil
	}
	return *v
}

// numDec：pgtype.Numeric → 定标字符串（d 位小数）。无效/!Valid 兜底 "0"（用于 NOT NULL 读出字段）。
func numDec(n pgtype.Numeric, d int) string {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return "0"
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

// numStrOrNil：pgtype.Numeric → 定标字符串；无效/!Valid → nil（用于契约 nullable 字段，如 max_score）。
func numStrOrNil(n pgtype.Numeric, d int) any {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return nil
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

func ToAPIScheme(r mstore.Scheme) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"name":             r.Name,
		"period_type":      r.PeriodType,
		"scope_dept_id":    optInt64Ptr(r.ScopeDeptID),
		"scope_staff_type": optStr(r.ScopeStaffType),
		"effective_period": r.EffectivePeriod,
		"version":          r.Version,
		"active":           r.Active,
		"status":           r.Status,
		"created_at":       fmtTime(r.CreatedAt),
		"updated_at":       fmtTime(r.UpdatedAt),
	}
}

func ToAPIFactor(r mstore.SchemeFactor) map[string]any {
	return map[string]any{
		"id":           r.ID,
		"scheme_id":    r.SchemeID,
		"factor_code":  r.FactorCode,
		"factor_name":  optStr(r.FactorName),
		"weight":       numDec(r.Weight, 2),        // pgtype.Numeric → "30.00"
		"scoring_rule": jsonToAny(r.ScoringRule, map[string]any{}),
		"max_score":    numStrOrNil(r.MaxScore, 2), // 可空
		"data_source":  r.DataSource,
		"clause_ref":   optStr(r.ClauseRef),
		"sort_no":      r.SortNo,
	}
}

// ToAPIRecord：list/get 通用形状（Record 契约字段）。items 不在此，detail 端点另拼。
func ToAPIRecord(r mstore.Record) map[string]any {
	return map[string]any{
		"id":            r.ID,
		"scheme_id":     r.SchemeID,
		"scheme_name":   nil,
		"staff_user_id": r.StaffUserID,
		"staff_name":    nil,
		"period":        r.Period,
		"dept_id":       optInt64Ptr(r.DeptID),
		"total_score":   numDec(r.TotalScore, 2), // "88.50"
		"rank":          r.Rank,                  // *int32 → JSON number/null
		"status":        r.Status,
		"calc_batch":    optStr(r.CalcBatch),
		"calc_at":       fmtTimePtr(r.CalcAt),
		"confirmed_at":  fmtTimePtr(r.ConfirmedAt),
		"approve_at":    fmtTimePtr(r.ApproveAt),
	}
}

func ToAPIRecordItem(r mstore.RecordItem) map[string]any {
	return map[string]any{
		"id":             r.ID,
		"record_id":      r.RecordID,
		"factor_code":    r.FactorCode,
		"factor_name":    nil,
		"metric_value":   numDec(r.MetricValue, 4),   // "3.0000"
		"raw_score":      numDec(r.RawScore, 2),
		"weighted_score": numDec(r.WeightedScore, 2),
		"evidence":       jsonToAny(r.Evidence, []any{}),
	}
}

// ToAPIRecordDetail：record + items 拼装（/perf/records/{id}/detail、/perf/me）。
func ToAPIRecordDetail(r mstore.Record, items []mstore.RecordItem) map[string]any {
	out := ToAPIRecord(r)
	list := make([]map[string]any, 0, len(items))
	for _, it := range items {
		list = append(list, ToAPIRecordItem(it))
	}
	out["items"] = list
	return out
}

func ToAPIPayout(r mstore.Payout) map[string]any {
	return map[string]any{
		"id":            r.ID,
		"code":          optStr(r.Code),
		"record_id":     r.RecordID,
		"payee_user_id": r.PayeeUserID,
		"payee_name":    nil,
		"amount":        numDec(r.Amount, 2), // "12000.00"
		"period":        optStr(r.Period),
		"pay_channel":   optStr(r.PayChannel),
		"status":        r.Status,
		"approved_at":   fmtTimePtr(r.ApprovedAt),
		"paid_at":       fmtTimePtr(r.PaidAt),
		"voucher_code":  optStr(r.VoucherCode),
	}
}

// ToAPIRank：RankedRecords 行 → RankItem（含生成列 rn 作 rank）。RankedRecordsRow = model 全列 + Rn int64。
func ToAPIRank(r mstore.RankedRecordsRow) map[string]any {
	return map[string]any{
		"rank":          r.Rn,
		"staff_user_id": r.StaffUserID,
		"staff_name":    nil,
		"dept_id":       optInt64Ptr(r.DeptID),
		"total_score":   numDec(r.TotalScore, 2),
	}
}
