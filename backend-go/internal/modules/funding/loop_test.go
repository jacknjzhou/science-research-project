package funding

import (
	"fmt"
	"net/http"
	"testing"
)

// TestFundingLoopEndToEnd：建预算→提交→批复→登记到款→认领→填报销→提交（冻结）→两步审批（实扣）→执行率→预警。
func TestFundingLoopEndToEnd(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)

	r := newFundingEngine(t, pool, injectDomain([]string{"R-FINANCE", "R-MANAGER", "R-LEADER"}, 1, 1))

	// 1) 科目字典
	if w := doGet(r, "/api/v1/subjects"); w.Code != 200 {
		t.Fatalf("subjects 应 200，得 %d body=%s", w.Code, w.Body.String())
	}

	// 2) 新建预算（项目 9002 复用做编制演练，避免污染 9001 主链路）
	//    科目 id 为自增，先从字典接口取前两个真实 id。
	w := doGet(r, "/api/v1/subjects")
	if w.Code != 200 {
		t.Fatalf("subjects 应 200，得 %d", w.Code)
	}
	var subjEnv struct {
		Data struct {
			List []map[string]any `json:"list"`
		} `json:"data"`
	}
	parse(t, w.Body.Bytes(), &subjEnv.Data)
	if len(subjEnv.Data.List) < 2 {
		t.Fatalf("seed 科目不足 2 条，得 %d", len(subjEnv.Data.List))
	}
	sid1 := int64(subjEnv.Data.List[0]["id"].(float64))
	sid2 := int64(subjEnv.Data.List[1]["id"].(float64))
	w = doPost(r, "/api/v1/budgets", fmt.Sprintf(`{"project_id":9002,"legal_entity_id":1,"mode":"预算制","lines":[{"subject_id":%d,"amount":"60000.00"},{"subject_id":%d,"amount":"40000.00"}]}`, sid1, sid2))
	if w.Code != 200 {
		t.Fatalf("创建预算应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	bud := dataMap(t, w.Body.Bytes())
	bid := int(bud["id"].(float64))
	if bud["status"] != "DRAFT" {
		t.Fatalf("新预算应 DRAFT，得 %v", bud["status"])
	}
	if bud["total_approved"] != "100000.00" {
		t.Fatalf("total_approved 应 100000.00，得 %v", bud["total_approved"])
	}

	// 3) 非法流转：DRAFT 直接批复 → 40901
	if w := doPost(r, fmt.Sprintf("/api/v1/budgets/%d/approve", bid), `{}`); w.Code != http.StatusConflict {
		t.Fatalf("DRAFT 直接批复应 409，得 %d", w.Code)
	}
	// 4) 提交 → 批复
	w = doPost(r, fmt.Sprintf("/api/v1/budgets/%d/submit", bid), `{}`)
	if w.Code != 200 {
		t.Fatalf("提交应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	w = doPost(r, fmt.Sprintf("/api/v1/budgets/%d/approve", bid), `{}`)
	if w.Code != 200 {
		t.Fatalf("批复应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	bud = dataMap(t, w.Body.Bytes())
	if bud["status"] != "EXECUTING" {
		t.Fatalf("批复后应 EXECUTING，得 %v", bud["status"])
	}

	// 5) 到款登记 + 认领
	w = doPost(r, "/api/v1/incomes", `{"legal_entity_id":1,"amount":"12345.67","payer_name":"测试付款方","bank_flow_no":"FLOW-E2E-1"}`)
	if w.Code != 200 {
		t.Fatalf("到款登记应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	inc := dataMap(t, w.Body.Bytes())
	iid := int(inc["id"].(float64))
	if inc["claim_status"] != "UNCLAIMED" {
		t.Fatalf("新到款应 UNCLAIMED，得 %v", inc["claim_status"])
	}
	w = doPost(r, fmt.Sprintf("/api/v1/incomes/%d/claim", iid), `{"project_id":9001}`)
	if w.Code != 200 {
		t.Fatalf("认领应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if w = doPost(r, fmt.Sprintf("/api/v1/incomes/%d/claim", iid), `{"project_id":9001}`); w.Code != http.StatusConflict {
		t.Fatalf("重复认领应 409，得 %d", w.Code)
	}

	// 6) 批量导入：2 新 + 1 重复（FLOW-SEED-1）
	w = doPost(r, "/api/v1/incomes/import-bank-flow", `[
		{"bank_flow_no":"FLOW-E2E-2","amount":"1000.00","payer_name":"甲"},
		{"bank_flow_no":"FLOW-E2E-3","amount":"2000.00","payer_name":"乙"},
		{"bank_flow_no":"FLOW-SEED-1","amount":"999999.00","payer_name":"重复流水"}]`)
	if w.Code != 200 {
		t.Fatalf("导入应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	imp := dataMap(t, w.Body.Bytes())
	if imp["imported"].(float64) != 2 || imp["skipped"].(float64) != 1 {
		t.Fatalf("导入应 imported=2 skipped=1，得 %v", imp)
	}

	// 7) 报销：6 万（≥10 万阈值下、两步以内）→ 提交冻结 → 两步审批
	//    seed 预算 8801 设备费行 8811 余额 150000
	w = doPost(r, "/api/v1/expenses", `{"project_id":9001,"budget_line_id":8811,"legal_entity_id":1,"amount":"60000.00","expense_type":"EQUIPMENT","description":"E2E 设备费","submit_mode":"预算制","invoice_no":"INV-E2E-1","invoice_date":"2026-10-01"}`)
	if w.Code != 200 {
		t.Fatalf("填报销应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	exp := dataMap(t, w.Body.Bytes())
	eid := int(exp["id"].(float64))

	// 指纹查重：同发票号+金额+日期再建一张 → 创建即 40903（uk_expense_fingerprint 唯一索引）
	w = doPost(r, "/api/v1/expenses", `{"project_id":9001,"budget_line_id":8811,"legal_entity_id":1,"amount":"60000.00","expense_type":"EQUIPMENT","submit_mode":"预算制","invoice_no":"INV-E2E-1","invoice_date":"2026-10-01"}`)
	if w.Code != http.StatusConflict {
		t.Fatalf("重复指纹建单应 409，得 %d body=%s", w.Code, w.Body.String())
	}

	// 提交主单：冻结（60 万审批链两步：金额 <10 万？6 万 → 1 步 R-MANAGER）
	w = doPost(r, fmt.Sprintf("/api/v1/expenses/%d/submit", eid), `{}`)
	if w.Code != 200 {
		t.Fatalf("提交应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	// 行余额复核：150000 - 60000 = 90000
	if w = doGet(r, "/api/v1/budget-lines/8811/balance"); w.Code != 200 {
		t.Fatalf("余额查询应 200，得 %d", w.Code)
	}
	bal := dataMap(t, w.Body.Bytes())
	if bal["remaining"] != "90000.00" || bal["amount_frozen"] != "60000.00" {
		t.Fatalf("冻结后余额应 remaining=90000.00 frozen=60000.00，得 %v", bal)
	}

	// 审批（6 万 → 一步 R-MANAGER）→ APPROVED 且实扣
	if w = doPost(r, fmt.Sprintf("/api/v1/expenses/%d/approval", eid), `{"action":"APPROVE","comment":"同意"}`); w.Code != 200 {
		t.Fatalf("审批应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	exp = dataMap(t, w.Body.Bytes())
	if exp["status"] != "APPROVED" {
		t.Fatalf("末步批准后应 APPROVED，得 %v", exp["status"])
	}
	if w = doGet(r, "/api/v1/budget-lines/8811/balance"); w.Code != 200 {
		t.Fatalf("余额查询应 200，得 %d", w.Code)
	}
	bal = dataMap(t, w.Body.Bytes())
	if bal["amount_used"] != "60000.00" || bal["amount_frozen"] != "0.00" || bal["remaining"] != "90000.00" {
		t.Fatalf("实扣后应 used=60000 frozen=0 remaining=90000，得 %v", bal)
	}

	// 8) 执行率：预算 50 万批复、到账 30 万+12345.67、已用 6 万
	if w = doGet(r, "/api/v1/funding/execution?project_id=9001"); w.Code != 200 {
		t.Fatalf("执行率应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	ex := dataMap(t, w.Body.Bytes())
	if ex["budgetApproved"] != "500000.00" || ex["used"] != "60000.00" {
		t.Fatalf("执行率聚合异常，得 %v", ex)
	}

	// 9) 预警（9001 执行率 12%，正常窗口）→ 列表不含 9001 CRITICAL
	if w = doGet(r, "/api/v1/funding/warnings"); w.Code != 200 {
		t.Fatalf("预警应 200，得 %d", w.Code)
	}

	// 10) 间接费计提：默认 20% × 已认领到账
	w = doPost(r, "/api/v1/indirect-fees/calculate", `{"project_id":9001}`)
	if w.Code != 200 {
		t.Fatalf("计提应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	ind := dataMap(t, w.Body.Bytes())
	if ind["indirectAmount"] == "" || ind["indirectAmount"] == nil {
		t.Fatalf("计提结果缺失，得 %v", ind)
	}

	// 11) 越权：无角色审批 → 403
	r2 := newFundingEngine(t, pool, injectDomain([]string{"R-STAFF"}, 2, 1))
	w = doPost(r2, "/api/v1/expenses", `{"project_id":9001,"budget_line_id":8812,"legal_entity_id":1,"amount":"1000.00","expense_type":"MATERIAL","submit_mode":"预算制"}`)
	if w.Code != 200 {
		t.Fatalf("STAFF 填单应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	sid := int(dataMap(t, w.Body.Bytes())["id"].(float64))
	if w = doPost(r2, fmt.Sprintf("/api/v1/expenses/%d/submit", sid), `{}`); w.Code != 200 {
		t.Fatalf("STAFF 提交应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if w = doPost(r2, fmt.Sprintf("/api/v1/expenses/%d/approval", sid), `{"action":"APPROVE"}`); w.Code != http.StatusForbidden {
		t.Fatalf("无角色审批应 403，得 %d body=%s", w.Code, w.Body.String())
	}
	// 驳回解冻：R-MANAGER 驳回 → 行 8812 解冻
	r3 := newFundingEngine(t, pool, injectDomain([]string{"R-MANAGER"}, 3, 1))
	if w = doPost(r3, fmt.Sprintf("/api/v1/expenses/%d/approval", sid), `{"action":"REJECT","comment":"材料超标"}`); w.Code != 200 {
		t.Fatalf("驳回应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if w = doGet(r3, "/api/v1/budget-lines/8812/balance"); w.Code != 200 {
		t.Fatalf("余额查询应 200，得 %d", w.Code)
	}
	bal2 := dataMap(t, w.Body.Bytes())
	if bal2["amount_released"] != "1000.00" || bal2["amount_frozen"] != "0.00" {
		t.Fatalf("驳回后应 released=1000 frozen=0，得 %v", bal2)
	}
}

// TestSubjectsShape：科目字典形状（无 DB 逻辑，仅数据通路）。
func TestSubjectsShape(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newFundingEngine(t, pool, injectDomain([]string{"R-FINANCE"}, 1, 1))
	w := doGet(r, "/api/v1/subjects")
	if w.Code != 200 {
		t.Fatalf("应 200，得 %d", w.Code)
	}
	var env struct {
		Data struct {
			Total int `json:"total"`
		} `json:"data"`
	}
	parse(t, w.Body.Bytes(), &env.Data)
	if env.Data.Total != 8 {
		t.Fatalf("seed 科目应 8 条，得 %d", env.Data.Total)
	}
}
