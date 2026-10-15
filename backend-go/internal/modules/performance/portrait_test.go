package performance

import (
	"net/http/httptest"
	"strings"
	"testing"
)

// TestPortraitRealData：uid=100（seed_m：e_project pi=100 预算 50 万、r_output authors 命中）→
// 全真数据断言：projects.count=1、budgetTotal=500000.00、outputs.count=1。
func TestPortraitRealData(t *testing.T) {
	ctx, pool := poolForTest(t)
	runSeed(t, ctx, pool)
	r := newPerfEngine(t, pool, injectPerfDomain([]string{"R-MANAGER"}, 100, 1))

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/portrait/100", nil))
	if w.Code != 200 {
		t.Fatalf("画像应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	body := w.Body.String()
	if !strings.Contains(body, `"userId":100`) {
		t.Fatalf("应含 userId:100：%s", body)
	}
	if !strings.Contains(body, `"budgetTotal":"500000.00"`) {
		t.Fatalf("budgetTotal 应 500000.00（seed_m e_project）：%s", body)
	}
	if !strings.Contains(body, `"count":1`) {
		t.Fatalf("项目/成果 count 应 1：%s", body)
	}
}
