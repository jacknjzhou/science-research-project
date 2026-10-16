package project

import (
	"fmt"
	"net/http"
	"testing"
)

// TestChangeRequestAutoCode 回归：code 有 (tenant_id, code) WHERE deleted=0 唯一索引，
// 调用方未指定 code 时 handler 必须自动生成唯一单号——否则第二条即撞 uk_e_change_code（50002）。
func TestChangeRequestAutoCode(t *testing.T) {
	pool := poolForE(t)
	t.Setenv("ARK_APPROVAL_TWOSTEP", "off")
	staff := newRolesEngine(t, pool, []string{"R-STAFF"})

	// 任取一个可访问项目；空库则跳过
	var pid int64
	if err := pool.QueryRow(testCtx(), `SELECT id FROM e_project WHERE deleted=0 AND tenant_id=1 ORDER BY id LIMIT 1`).Scan(&pid); err != nil {
		t.Skip("无可用项目，跳过")
	}

	ids := map[string]bool{}
	for i := 0; i < 2; i++ {
		w := ePost(staff, fmt.Sprintf("/api/v1/project/%d/change-request", pid),
			`{"change_type":"DELAY","old_value":{"end_date":"2026-03-30"},"new_value":{"end_date":"2026-09-30"},"reason":"回归：自动单号"}`)
		if w.Code != http.StatusOK {
			t.Fatalf("第 %d 条无 code 变更单应 200，得 %d body=%s", i+1, w.Code, w.Body.String())
		}
		d := eData(t, w.Body.Bytes())
		code, _ := d["code"].(string)
		if code == "" {
			t.Fatalf("返回单号不应为空: %s", w.Body.String())
		}
		if ids[code] {
			t.Fatalf("单号重复: %s", code)
		}
		ids[code] = true
	}
}
