package auth

import "testing"

// R 域 caps 派生测试。复用 caps_project_test.go 已定义的 perfEnf/hasCapExact（同包，勿重复定义）。
// 至少覆盖 R-STAFF / R-MANAGER / R-EXPERT 三组（+ 只读负例）。

// TestBuildCaps_OutputStaffCaps：R-STAFF 拥有成果台账读/新建、我的、待认领、认领/拒绝/非我 + 全域读；
// 但无关联项目 PUT（属主管）。
func TestBuildCaps_OutputStaffCaps(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-STAFF"})
	for _, want := range []string{
		"/api/v1/output GET",
		"/api/v1/output POST",
		"/api/v1/output/mine GET",
		"/api/v1/output/pending-claim GET",
		"/api/v1/output/claim POST",
		"/api/v1/output/reject POST",
		"/api/v1/output/mark-not-mine POST",
		"/api/v1/output/* GET",
	} {
		if !hasCapExact(caps, want) {
			t.Errorf("R-STAFF 应有 %q 能力: %v", want, caps)
		}
	}
	if hasCapExact(caps, "/api/v1/output/*/projects PUT") {
		t.Errorf("R-STAFF 不应有关联项目 PUT 能力")
	}
}

// TestBuildCaps_OutputManagerCaps：R-MANAGER 全域读 + 关联项目 PUT。
func TestBuildCaps_OutputManagerCaps(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-MANAGER"})
	for _, want := range []string{
		"/api/v1/output GET",
		"/api/v1/output/* GET",
		"/api/v1/output/*/projects PUT",
	} {
		if !hasCapExact(caps, want) {
			t.Errorf("R-MANAGER 应有 %q 能力: %v", want, caps)
		}
	}
}

// TestBuildCaps_OutputExpertRead：R-EXPERT 读成果（评审依赖），无任何写动作。
func TestBuildCaps_OutputExpertRead(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-EXPERT"})
	for _, want := range []string{
		"/api/v1/output GET",
		"/api/v1/output/* GET",
	} {
		if !hasCapExact(caps, want) {
			t.Errorf("R-EXPERT 应有 %q 能力: %v", want, caps)
		}
	}
	for _, bad := range []string{
		"/api/v1/output POST",
		"/api/v1/output/claim POST",
		"/api/v1/output/*/projects PUT",
	} {
		if hasCapExact(caps, bad) {
			t.Errorf("R-EXPERT 不应有 %q 能力", bad)
		}
	}
}
