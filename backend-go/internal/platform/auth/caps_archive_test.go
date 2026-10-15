package auth

import "testing"

// TestCapsArchive：O 域权限边界——四性检测 R-MANAGER/R-ADMIN 皆可；入库/借阅审批仅 R-ADMIN，
// R-MANAGER 不得有入库权限。键形如 "<obj> <METHOD>"（与 BuildCaps 一致）。
// 复用同包真实 helper：perfEnf（建 enforcer）、hasCapExact（精确命中）。
func TestCapsArchive(t *testing.T) {
	enf := perfEnf(t)

	mgr := BuildCaps(enf, []string{"R-MANAGER"})
	if !hasCapExact(mgr, "/api/v1/archives/*/check POST") {
		t.Fatalf("R-MANAGER 缺四性检测权限: %v", mgr)
	}
	if !hasCapExact(mgr, "/api/v1/archives/*/submit POST") {
		t.Fatalf("R-MANAGER 缺提交权限: %v", mgr)
	}
	if hasCapExact(mgr, "/api/v1/archives/*/file POST") {
		t.Fatalf("R-MANAGER 不应有入库权限")
	}
	if hasCapExact(mgr, "/api/v1/archives/*/destroy POST") {
		t.Fatalf("R-MANAGER 不应有销毁权限")
	}
	if hasCapExact(mgr, "/api/v1/borrows/*/approve POST") {
		t.Fatalf("R-MANAGER 不应有借阅审批权限")
	}

	adm := BuildCaps(enf, []string{"R-ADMIN"})
	if !hasCapExact(adm, "/api/v1/archives/*/file POST") {
		t.Fatalf("R-ADMIN 缺入库权限: %v", adm)
	}
	if !hasCapExact(adm, "/api/v1/archives/*/destroy POST") {
		t.Fatalf("R-ADMIN 缺销毁权限: %v", adm)
	}
	if !hasCapExact(adm, "/api/v1/borrows/*/approve POST") {
		t.Fatalf("R-ADMIN 缺借阅审批权限: %v", adm)
	}
}
