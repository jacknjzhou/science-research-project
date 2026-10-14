package mstore

import (
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

func TestStoreShapes(t *testing.T) {
	var s Scheme
	s.CreatedAt = time.Time{}          // override: time.Time
	s.Active = true
	var f SchemeFactor
	f.Weight = pgtype.Numeric{}        // SELECT * → NUMERIC 不 override，恒 pgtype.Numeric
	f.MaxScore = pgtype.Numeric{}      // NUMERIC 可空也是 pgtype.Numeric（靠 .Valid 判空）
	var r Record
	r.TotalScore = pgtype.Numeric{}    // pgtype.Numeric
	r.Rank = nil                       // INT nullable → *int32
	r.CalcAt = nil                     // *time.Time
	var it RecordItem
	it.MetricValue = pgtype.Numeric{} // pgtype.Numeric
	it.Evidence = []byte("[]")        // JSONB → []byte
	var p Payout
	p.Amount = pgtype.Numeric{}        // pgtype.Numeric
	p.ApproverIds = []byte("[]")       // 生成物为 ApproverIds（sqlc 对 _ids 的驼峰处理）
	// 非实体查询的 Row 结构存在性
	var rr RankedRecordsRow
	rr.Rn = 1                          // window row_number → int64（列名 rn）
	_ = rr
	// 方法存在性（取函数值，不调用）
	_ = (&Queries{}).ListSchemes
	_ = (&Queries{}).UpsertRecord
	_ = (&Queries{}).MetricsOutputsByStaff
	_ = (&Queries{}).MetricsIncomeByStaff
	_ = (&Queries{}).ListCalcStaff
	_ = (&Queries{}).RankedRecords
	_ = (&Queries{}).PayPayout
	_ = s; _ = f; _ = r; _ = it; _ = p
}
