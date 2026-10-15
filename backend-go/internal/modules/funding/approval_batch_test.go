package funding

import (
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/eplugger/ark/internal/platform/approval"
)

// TestApprovalBatch：批量审批——2 成功 + 1 不存在失败；每条成功动作落 sys_approval_log。
func TestApprovalBatch(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newFundingEngine(t, pool, injectDomain([]string{"R-MANAGER"}, 1, 1))

	// 建两张报销单（行 8812，小额走一步 R-MANAGER）并提交
	mk := func(inv string) int64 {
		w := doPost(r, "/api/v1/expenses", fmt.Sprintf(`{"project_id":9001,"budget_line_id":8812,"legal_entity_id":1,"amount":"300.00","expense_type":"MATERIAL","submit_mode":"预算制","invoice_no":"%s","invoice_date":"2026-10-01"}`, inv))
		if w.Code != 200 {
			t.Fatalf("建单应 200，得 %d body=%s", w.Code, w.Body.String())
		}
		id := int64(dataMap(t, w.Body.Bytes())["id"].(float64))
		if w = doPost(r, fmt.Sprintf("/api/v1/expenses/%d/submit", id), `{}`); w.Code != 200 {
			t.Fatalf("提交应 200，得 %d", w.Code)
		}
		return id
	}
	ts := time.Now().UnixNano()
	e1 := mk(fmt.Sprintf("INV-BATCH-%d-1", ts))
	e2 := mk(fmt.Sprintf("INV-BATCH-%d-2", ts))

	// 批量：e1/e2 成功，999999 不存在失败
	w := doPost(r, "/api/v1/expenses/approval-batch", fmt.Sprintf(`{"ids":[%d,%d,999999],"action":"APPROVE","comment":"批量同意"}`, e1, e2))
	if w.Code != 200 {
		t.Fatalf("批量审批应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	res := dataMap(t, w.Body.Bytes())
	if res["total"].(float64) != 3 || res["ok"].(float64) != 2 {
		t.Fatalf("应 total=3 ok=2，得 %v", res)
	}
	results := res["results"].([]any)
	last := results[2].(map[string]any)
	if last["ok"].(bool) {
		t.Fatalf("不存在单应失败，得 %v", last)
	}
	if results[0].(map[string]any)["ok"] != true || results[1].(map[string]any)["ok"] != true {
		t.Fatalf("前两条应成功，得 %v", results)
	}

	// 流水断言：sys_approval_log 应有 EXPENSE/e1、e2 的 APPROVE 记录
	svc := approval.New(pool)
	logs, err := svc.ListLogs(testCtx(), 1, "EXPENSE", e1)
	if err != nil {
		t.Fatalf("查流水: %v", err)
	}
	if len(logs) == 0 || logs[len(logs)-1].Action != "APPROVE" {
		t.Fatalf("e1 应有 APPROVE 流水，得 %+v", logs)
	}
	if logs[len(logs)-1].Step != 1 {
		t.Fatalf("一步审批流水 step 应 1，得 %d", logs[len(logs)-1].Step)
	}

	// 非法 action → 400
	if w = doPost(r, "/api/v1/expenses/approval-batch", `{"ids":[1],"action":"NOPE"}`); w.Code != http.StatusBadRequest {
		t.Fatalf("非法 action 应 400，得 %d", w.Code)
	}
}
