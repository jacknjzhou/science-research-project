package funding

import (
	"strings"
	"testing"
)

// TestExecutionDims：dim=subject 聚合（seed 行 8811 approved=150000）；dim=college 非空。
func TestExecutionDims(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newFundingEngine(t, pool, injectDomain([]string{"R-FINANCE"}, 1, 1))

	// subject 维：SUB-EQ 行 approved 应 150000.00
	w := doGet(r, "/api/v1/funding/execution?dim=subject")
	if w.Code != 200 {
		t.Fatalf("subject 维应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	body := w.Body.String()
	if !strings.Contains(body, `"list"`) {
		t.Fatalf("应含 list：%s", body)
	}
	if !strings.Contains(body, "150000.00") {
		t.Fatalf("subject 聚合应含 150000.00（SUB-EQ 行）：%s", body)
	}

	// college 维：seed 项目 department_id 为 NULL → dimId=0，非空即可
	w = doGet(r, "/api/v1/funding/execution?dim=college")
	if w.Code != 200 {
		t.Fatalf("college 维应 200，得 %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "500000.00") {
		t.Fatalf("college 聚合应含 9001 预算 500000.00：%s", w.Body.String())
	}

	// project 维（缺省）：行为不变
	w = doGet(r, "/api/v1/funding/execution?project_id=9001")
	if w.Code != 200 || !strings.Contains(w.Body.String(), "budgetApproved") {
		t.Fatalf("project 维应 200 含 budgetApproved，得 %d body=%s", w.Code, w.Body.String())
	}
}
