package funding

import (
	"fmt"
	"testing"
	"time"
)

// TestClaimMgmtFee：项目挂分类（pct=10）→ 认领 1000 → mgmt_fee=100.00。
func TestClaimMgmtFee(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newFundingEngine(t, pool, injectDomain([]string{"R-FINANCE", "R-MANAGER", "R-LEADER"}, 1, 1))

	// 建分类 pct=10
	var cid int64
	ts := time.Now().UnixNano()
	if err := pool.QueryRow(testCtx(), `
		INSERT INTO e_project_category (tenant_id, code, name, mgmt_fee_pct)
		VALUES (1, $1, 'T21 管理费分类', 10) RETURNING id`,
		fmt.Sprintf("CAT-M%d", ts)).Scan(&cid); err != nil {
		t.Fatalf("建分类: %v", err)
	}
	// 项目 9001 挂分类
	if _, err := pool.Exec(testCtx(), `UPDATE e_project SET category_id=$1 WHERE id=9001`, cid); err != nil {
		t.Fatalf("挂分类: %v", err)
	}
	t.Cleanup(func() {
		_, _ = pool.Exec(testCtx(), `UPDATE e_project SET category_id=NULL WHERE id=9001`)
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_project_category WHERE id=$1`, cid)
	})

	// 到款 1000 + 认领
	w := doPost(r, "/api/v1/incomes", fmt.Sprintf(`{"legal_entity_id":1,"amount":"1000.00","payer_name":"T21 付款方","bank_flow_no":"FLOW-MGMT-%d"}`, ts))
	if w.Code != 200 {
		t.Fatalf("到款登记应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	iid := int64(dataMap(t, w.Body.Bytes())["id"].(float64))
	w = doPost(r, fmt.Sprintf("/api/v1/incomes/%d/claim", iid), `{"project_id":9001}`)
	if w.Code != 200 {
		t.Fatalf("认领应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	inc := dataMap(t, w.Body.Bytes())
	if inc["mgmt_fee"] != "100.00" {
		t.Fatalf("管理费应 100.00（1000×10%%），得 %v", inc["mgmt_fee"])
	}

	// 无分类项目 → 管理费 0
	w = doPost(r, "/api/v1/incomes", fmt.Sprintf(`{"legal_entity_id":1,"amount":"500.00","payer_name":"T21 无分类","bank_flow_no":"FLOW-NOCAT-%d"}`, ts))
	iid2 := int64(dataMap(t, w.Body.Bytes())["id"].(float64))
	// 临时解挂分类后认领
	if _, err := pool.Exec(testCtx(), `UPDATE e_project SET category_id=NULL WHERE id=9001`); err != nil {
		t.Fatalf("解挂: %v", err)
	}
	w = doPost(r, fmt.Sprintf("/api/v1/incomes/%d/claim", iid2), `{"project_id":9001}`)
	if w.Code != 200 {
		t.Fatalf("认领应 200，得 %d", w.Code)
	}
	if got := dataMap(t, w.Body.Bytes())["mgmt_fee"]; got != "0.00" {
		t.Fatalf("无分类管理费应 0.00，得 %v", got)
	}
}
