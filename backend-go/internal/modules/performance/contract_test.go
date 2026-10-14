package performance

import (
	"testing"
	"time"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/jackc/pgx/v5/pgtype"
)

func numLit(s string) pgtype.Numeric {
	var n pgtype.Numeric
	_ = n.Scan(s)
	return n
}

func TestToAPIFactorShape(t *testing.T) {
	f := mstore.SchemeFactor{
		ID: 1, SchemeID: 10, FactorCode: "PAPER_COUNT", FactorName: strPtr("论文数"),
		Weight: numLit("40.00"), MaxScore: numLit("100.00"), DataSource: "R_OUTPUT",
		ScoringRule: []byte(`{"method":"COUNT","unit":2}`), ClauseRef: nil, SortNo: 1,
	}
	out := ToAPIFactor(f)
	if out["weight"] != "40.00" {
		t.Fatalf("weight 应格式化 40.00，得 %v", out["weight"])
	}
	if out["max_score"] != "100.00" {
		t.Fatalf("max_score 应 100.00，得 %v", out["max_score"])
	}
	rule, ok := out["scoring_rule"].(map[string]any)
	if !ok || rule["method"] != "COUNT" {
		t.Fatalf("scoring_rule 应解为对象且 method=COUNT，得 %#v", out["scoring_rule"])
	}
	if out["factor_name"] != "论文数" {
		t.Fatalf("factor_name 应解引用，得 %v", out["factor_name"])
	}
}

func TestToAPIFactorMaxScoreNull(t *testing.T) {
	f := mstore.SchemeFactor{ID: 2, FactorCode: "X", Weight: numLit("10.00"), MaxScore: pgtype.Numeric{Valid: false}}
	out := ToAPIFactor(f)
	if v, ok := out["max_score"]; !ok || v != nil {
		t.Fatalf("无效 MaxScore → nil，得 %#v", out["max_score"])
	}
}

func TestToAPIRecordShape(t *testing.T) {
	rec := mstore.Record{
		ID: 5, SchemeID: 10, StaffUserID: 100, Period: "2026",
		TotalScore: numLit("88.50"), Status: "CALCULATED",
		CalcAt: &time.Time{}, Rank: nil,
	}
	out := ToAPIRecord(rec)
	if out["total_score"] != "88.50" {
		t.Fatalf("total_score 应 88.50，得 %v", out["total_score"])
	}
	if out["staff_name"] != nil || out["scheme_name"] != nil {
		t.Fatalf("无 join 字段应为 nil")
	}
	if out["status"] != "CALCULATED" {
		t.Fatalf("status 透传错，得 %v", out["status"])
	}
}

func TestToAPIPayoutShape(t *testing.T) {
	p := mstore.Payout{ID: 1, RecordID: 5, PayeeUserID: 100, Amount: numLit("12000.00"), Status: "DRAFT"}
	out := ToAPIPayout(p)
	if out["amount"] != "12000.00" {
		t.Fatalf("amount 应 12000.00，得 %v", out["amount"])
	}
}

func TestToAPIRankShape(t *testing.T) {
	r := mstore.RankedRecordsRow{ID: 5, StaffUserID: 100, TotalScore: numLit("90.00"), Rn: 1}
	out := ToAPIRank(r)
	if out["rank"] != int64(1) {
		t.Fatalf("rank=rn=1，得 %v", out["rank"])
	}
	if out["total_score"] != "90.00" {
		t.Fatalf("total_score 应 90.00，得 %v", out["total_score"])
	}
}
