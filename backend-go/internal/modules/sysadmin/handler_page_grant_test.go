package sysadmin

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestPageGrantLifecycle 覆盖：种子读取、全量替换幂等、'*' 行语义、
// 未知角色码 400、staff 写 403、staff 可读。
func TestPageGrantLifecycle(t *testing.T) {
	admin := newDictEngine(t, []string{"R-ADMIN"})
	staff := newDictEngine(t, []string{"R-STAFF"})
	suffix := fmt.Sprintf("%d", time.Now().UnixNano()%100000)

	// 1) staff 可读种子（migration 000014 灌入 59 行）
	w := httptest.NewRecorder()
	staff.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/page-grants", nil))
	d := dictEnv(t, w)
	seeds, _ := d["grants"].([]any)
	if len(seeds) == 0 {
		t.Fatalf("种子授权行应非空，得 %v", d)
	}

	// 2) admin 全量替换：保留 dash:* + 新增自定义页 → 自定义角色可见
	body := `{"grants":[
		{"page_name":"dash","role_code":"*"},
		{"page_name":"pg-test-` + suffix + `","role_code":"*"}
	]}`
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("PUT", "/api/v1/admin/page-grants", strings.NewReader(body)))
	d = dictEnv(t, w)
	grants := d["grants"].([]any)
	if len(grants) != 2 {
		t.Fatalf("替换后应 2 行，得 %d", len(grants))
	}

	// 3) 幂等：再 PUT 同 body → 仍 2 行
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("PUT", "/api/v1/admin/page-grants", strings.NewReader(body)))
	d = dictEnv(t, w)
	if n := len(d["grants"].([]any)); n != 2 {
		t.Fatalf("幂等替换后应仍 2 行，得 %d", n)
	}

	// 4) 未知角色码 → 400
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("PUT", "/api/v1/admin/page-grants",
		strings.NewReader(`{"grants":[{"page_name":"dash","role_code":"R-NOPE"}]}`)))
	if w.Code != http.StatusBadRequest {
		t.Fatalf("未知角色码应 400，得 %d body=%s", w.Code, w.Body.String())
	}

	// 5) staff 写 → 403（policy 仅 R-ADMIN 通配 PUT）
	w = httptest.NewRecorder()
	staff.ServeHTTP(w, httptest.NewRequest("PUT", "/api/v1/admin/page-grants", strings.NewReader(body)))
	if w.Code != http.StatusForbidden {
		t.Fatalf("staff 写应 403，得 %d", w.Code)
	}

	// 6) 还原种子矩阵（避免污染其它用例的 dash 可见性）
	if err := restoreSeedGrants(t, admin); err != nil {
		t.Fatal(err)
	}

	// 7) '*' 行语义验证：dash 授权 role_code='*'，staff 登录后读回应含 dash
	w = httptest.NewRecorder()
	staff.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/page-grants", nil))
	d = dictEnv(t, w)
	var hasDashStar bool
	for _, g := range d["grants"].([]any) {
		row := g.(map[string]any)
		if row["page_name"] == "dash" && row["role_code"] == "*" {
			hasDashStar = true
		}
	}
	if !hasDashStar {
		t.Fatalf("还原后 dash:* 行应存在")
	}
}

// restoreSeedGrants 把测试期替换的矩阵还原为 migration 000014 的种子并集。
func restoreSeedGrants(t *testing.T, admin http.Handler) error {
	t.Helper()
	type row struct {
		PageName string `json:"page_name"`
		RoleCode string `json:"role_code"`
	}
	rows := []row{
		{"dash", "*"}, {"guide", "*"}, {"project", "*"},
		{"bigscreen", "R-LEADER"}, {"bigscreen", "R-FINANCE"}, {"bigscreen", "R-AUDITOR"}, {"bigscreen", "R-ADMIN"},
		{"editor", "R-STAFF"}, {"editor", "R-MANAGER"}, {"editor", "R-LEADER"},
		{"review", "R-MANAGER"}, {"review", "R-EXPERT"}, {"review", "R-ETHICS"}, {"review", "R-LEADER"}, {"review", "R-ADMIN"},
		{"projects", "R-STAFF"}, {"projects", "R-MANAGER"}, {"projects", "R-LEADER"},
		{"expense", "R-STAFF"}, {"expense", "R-MANAGER"}, {"expense", "R-FINANCE"},
		{"claim", "R-STAFF"}, {"claim", "R-MANAGER"}, {"claim", "R-LEADER"},
		{"output", "R-STAFF"}, {"output", "R-MANAGER"}, {"output", "R-LEADER"},
		{"transfer", "R-MANAGER"}, {"transfer", "R-LEADER"}, {"transfer", "R-ADMIN"},
		{"procurement", "R-MANAGER"}, {"procurement", "R-FINANCE"}, {"procurement", "R-ADMIN"},
		{"asset", "R-MANAGER"}, {"asset", "R-FINANCE"}, {"asset", "R-ADMIN"},
		{"portrait", "R-LEADER"}, {"portrait", "R-MANAGER"}, {"portrait", "R-ADMIN"},
		{"activity", "R-STAFF"}, {"activity", "R-MANAGER"}, {"activity", "R-LEADER"}, {"activity", "R-AUDITOR"},
		{"performance", "R-STAFF"}, {"performance", "R-MANAGER"}, {"performance", "R-LEADER"}, {"performance", "R-FINANCE"}, {"performance", "R-AUDITOR"},
		{"expert-review", "R-EXPERT"}, {"expert-review", "R-MANAGER"}, {"expert-review", "R-LEADER"}, {"expert-review", "R-AUDITOR"},
		{"archive", "R-ADMIN"}, {"archive", "R-MANAGER"}, {"archive", "R-AUDITOR"},
		{"admin-users", "R-ADMIN"}, {"admin-roles", "R-ADMIN"}, {"admin-roles", "R-AUDITOR"},
		{"admin-dicts", "R-ADMIN"},
	}
	grants := make([]map[string]string, 0, len(rows))
	for _, r := range rows {
		grants = append(grants, map[string]string{"page_name": r.PageName, "role_code": r.RoleCode})
	}
	b, _ := json.Marshal(map[string]any{"grants": grants})
	w := httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("PUT", "/api/v1/admin/page-grants", strings.NewReader(string(b))))
	if w.Code != http.StatusOK {
		return fmt.Errorf("还原种子矩阵失败 HTTP %d body=%s", w.Code, w.Body.String())
	}
	return nil
}
