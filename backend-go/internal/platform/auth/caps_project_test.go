package auth

import (
	"strings"
	"testing"
)

// hasCapExact：全字符串命中（不依赖 HasSuffix）。与 caps_perf_test.go 的
// hasCapSuffix 独立命名，避免同包冲突（记忆教训：helper 重名会编译失败）。
func hasCapExact(caps []string, want string) bool {
	for _, c := range caps {
		if c == want {
			return true
		}
	}
	return false
}

// TestBuildCaps_ProjectStaffCaps：R-STAFF 拥有 project/mine GET、tasks PUT、四个建单 POST；
// 无 change-request approve（属主管/领导）。
func TestBuildCaps_ProjectStaffCaps(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-STAFF"})
	for _, want := range []string{
		"/api/v1/project/mine GET",
		"/api/v1/project/*/tasks/* PUT",
		"/api/v1/project/*/progress-report POST",
		"/api/v1/project/*/mid-check POST",
		"/api/v1/project/*/change-request POST",
		"/api/v1/project/*/final-accept POST",
	} {
		if !hasCapExact(caps, want) {
			t.Errorf("R-STAFF 应有 %q 能力: %v", want, caps)
		}
	}
	if hasCapExact(caps, "/api/v1/project/*/change-request/*/approve POST") {
		t.Errorf("R-STAFF 不应有变更审批能力")
	}
}

// TestBuildCaps_ProjectManagerCaps：R-MANAGER 拥有变更审批 + 中检建单 + 全域读。
func TestBuildCaps_ProjectManagerCaps(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-MANAGER"})
	for _, want := range []string{
		"/api/v1/project/* GET",
		"/api/v1/project/*/change-request/*/approve POST",
		"/api/v1/project/*/mid-check POST",
	} {
		if !hasCapExact(caps, want) {
			t.Errorf("R-MANAGER 应有 %q 能力: %v", want, caps)
		}
	}
}

// TestBuildCaps_ProjectFinanceReadOnly：R-FINANCE 只读项目，不允许任何写动作。
func TestBuildCaps_ProjectFinanceReadOnly(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-FINANCE"})
	if !hasCapExact(caps, "/api/v1/project/* GET") {
		t.Errorf("R-FINANCE 应有项目读能力: %v", caps)
	}
	for _, c := range caps {
		if strings.HasPrefix(c, "/api/v1/project/") && strings.HasSuffix(c, " POST") {
			t.Errorf("R-FINANCE 不应有项目写动作: %s", c)
		}
	}
}
