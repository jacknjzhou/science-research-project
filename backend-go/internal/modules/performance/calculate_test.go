package performance

import (
	"encoding/json"
	"testing"

	"github.com/jackc/pgx/v5/pgtype"
)

func pgnum(t *testing.T, s string) pgtype.Numeric {
	t.Helper()
	var n pgtype.Numeric
	if s != "" {
		if err := n.Scan(s); err != nil {
			t.Fatalf("pgnum scan %q: %v", s, err)
		}
	}
	return n
}

func mkFactor(t *testing.T, ds, weight, maxScore, rule string) factorInput {
	t.Helper()
	f := factorInput{DataSource: ds, Weight: pgnum(t, weight), FactorCode: "X"}
	if maxScore != "" {
		f.MaxScore = pgnum(t, maxScore)
	}
	if rule != "" {
		f.ScoringRule = json.RawMessage(rule)
	}
	return f
}

func TestPeriodRange_Year(t *testing.T) {
	from, to := periodRange("YEAR", "2026")
	if from.Time.Year() != 2026 || from.Time.Month() != 1 || from.Time.Day() != 1 {
		t.Fatalf("2026 起错: %v", from.Time)
	}
	if to.Time.Year() != 2026 || to.Time.Month() != 12 || to.Time.Day() != 31 {
		t.Fatalf("2026 止错: %v", to.Time)
	}
	if !from.Valid || !to.Valid {
		t.Fatal("年周期应有效")
	}
}

func TestPeriodRange_Quarter(t *testing.T) {
	from, to := periodRange("QUARTER", "2026Q3")
	if from.Time.Month() != 7 || from.Time.Day() != 1 {
		t.Fatalf("Q3 起错: %v", from.Time)
	}
	if to.Time.Month() != 9 || to.Time.Day() != 30 {
		t.Fatalf("Q3 止错(应 9/30): %v", to.Time)
	}
}

func TestPeriodRange_Month(t *testing.T) {
	from, to := periodRange("MONTH", "2026-02")
	if from.Time.Month() != 2 || from.Time.Day() != 1 {
		t.Fatalf("2 月起错: %v", from.Time)
	}
	if to.Time.Month() != 2 || to.Time.Day() != 28 {
		t.Fatalf("2026 非闰年 2 月止应为 28: %v", to.Time)
	}
}

func TestPeriodRange_Bad(t *testing.T) {
	from, _ := periodRange("YEAR", "not-a-date")
	if from.Valid {
		t.Fatal("非法周期串应返回 Valid=false")
	}
}

func TestScoreFactor_Count(t *testing.T) {
	f := mkFactor(t, "R_OUTPUT", "40.00", "", `{"method":"COUNT","unit":2}`)
	agg := aggResult{byType: map[string]int32{"PAPER": 3}, total: 3}
	metric, raw, weighted, _ := scoreFactor(f, agg)
	if metric != 3 || raw != 6 || weighted != 2.4 {
		t.Fatalf("COUNT: metric=%v raw=%v wgt=%v 期望 3/6/2.4", metric, raw, weighted)
	}
}

func TestScoreFactor_ByLevel(t *testing.T) {
	f := mkFactor(t, "R_OUTPUT", "50.00", "", `{"method":"BY_LEVEL","levelMap":{"PAPER":10,"PATENT":20}}`)
	agg := aggResult{byType: map[string]int32{"PAPER": 2, "PATENT": 1, "UNKNOWN": 5}, total: 8}
	_, raw, weighted, _ := scoreFactor(f, agg)
	// 2*10 + 1*20 + 5*0 = 40
	if raw != 40 || weighted != 20 {
		t.Fatalf("BY_LEVEL: raw=%v wgt=%v 期望 40/20", raw, weighted)
	}
}

func TestScoreFactor_ByAmount(t *testing.T) {
	f := mkFactor(t, "F_INCOME", "60.00", "30.00", `{"method":"BY_AMOUNT","unit":0.001}`)
	agg := aggResult{amount: 100000} // 100000*0.001=100，但 max_score=30 封顶
	_, raw, weighted, _ := scoreFactor(f, agg)
	if raw != 30 {
		t.Fatalf("BY_AMOUNT 应封顶 30，得 raw=%v", raw)
	}
	if weighted != 18 {
		t.Fatalf("30*60/100=18，得 wgt=%v", weighted)
	}
}

func TestScoreFactor_Ladder(t *testing.T) {
	f := mkFactor(t, "T_DEAL", "100.00", "", `{"method":"LADDER","ladder":[{"min":0,"max":100000,"score":10},{"min":100000,"max":1000000,"score":20}]}`)
	agg := aggResult{amount: 500000}
	_, raw, _, _ := scoreFactor(f, agg)
	if raw != 20 {
		t.Fatalf("LADDER 500000 应落第二档=20，得 %v", raw)
	}
}

func TestScoreFactor_Manual(t *testing.T) {
	f := mkFactor(t, "MANUAL", "10.00", "", `{}`)
	_, raw, _, _ := scoreFactor(f, aggResult{})
	if raw != 0 {
		t.Fatalf("MANUAL 应 0 分，得 %v", raw)
	}
}

func TestScoreFactor_BadRule(t *testing.T) {
	f := mkFactor(t, "R_OUTPUT", "10.00", "", `{ this is not json }`)
	_, raw, _, _ := scoreFactor(f, aggResult{total: 5})
	if raw != 0 {
		t.Fatalf("坏规则应记 0，得 %v", raw)
	}
}
