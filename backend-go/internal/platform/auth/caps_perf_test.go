package auth

import (
	"os"
	"strings"
	"testing"

	"github.com/casbin/casbin/v2"
)

// perfEnf 载入 model+policy（与 caps_test.go 同源路径解析）。
func perfEnf(t *testing.T) *casbin.Enforcer {
	t.Helper()
	model := os.Getenv("ARK_AUTH_MODEL_PATH")
	if model == "" {
		model = "./model.conf"
	}
	pol := os.Getenv("ARK_AUTH_POLICY_PATH")
	if pol == "" {
		pol = "./policy.csv"
	}
	enf, err := NewEnforcer(model, pol)
	if err != nil {
		t.Fatal(err)
	}
	return enf
}

func hasCapSuffix(caps []string, suffix string) bool {
	for _, c := range caps {
		if strings.HasSuffix(c, suffix) {
			return true
		}
	}
	return false
}

// R-STAFF：有 confirm/appeal，无 calculate/approve/void/payout 写。
func TestBuildCaps_PerfStaffCaps(t *testing.T) {
	caps := BuildCaps(perfEnf(t), []string{"R-STAFF"})
	if !hasCapSuffix(caps, "/api/v1/perf/records/*/confirm POST") {
		t.Errorf("R-STAFF 应有 confirm 能力: %v", caps)
	}
	if !hasCapSuffix(caps, "/api/v1/perf/records/*/appeal POST") {
		t.Errorf("R-STAFF 应有 appeal 能力: %v", caps)
	}
	for _, bad := range []string{
		"/api/v1/perf/schemes/*/calculate POST",
		"/api/v1/perf/records/*/approve POST",
		"/api/v1/perf/payouts/*/pay POST",
	} {
		if hasCapSuffix(caps, bad) {
			t.Errorf("R-STAFF 不应有 %q 能力", bad)
		}
	}
}

// R-FINANCE：有 payouts 建单/pay/reject，无 records approve、无 schemes POST。
func TestBuildCaps_PerfFinanceCaps(t *testing.T) {
	caps := BuildCaps(perfEnf(t), []string{"R-FINANCE"})
	if !hasCapSuffix(caps, "/api/v1/perf/payouts/*/pay POST") {
		t.Errorf("R-FINANCE 应有 pay 能力: %v", caps)
	}
	if hasCapSuffix(caps, "/api/v1/perf/records/*/approve POST") {
		t.Errorf("R-FINANCE 不应有 record approve 能力")
	}
	if hasCapSuffix(caps, "/api/v1/perf/schemes POST") {
		t.Errorf("R-FINANCE 不应有建方案能力")
	}
}

// R-MANAGER：域内全量（POST/DELETE 通配即覆盖 calculate/approve/payouts pay 等）。
func TestBuildCaps_PerfManagerCaps(t *testing.T) {
	caps := BuildCaps(perfEnf(t), []string{"R-MANAGER"})
	for _, want := range []string{
		"/api/v1/perf/* POST",
		"/api/v1/perf/* DELETE",
	} {
		if !hasCapSuffix(caps, want) {
			t.Errorf("R-MANAGER 应有 %q 能力: %v", want, caps)
		}
	}
}
