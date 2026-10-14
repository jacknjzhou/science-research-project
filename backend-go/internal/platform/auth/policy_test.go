package auth

import (
	"os"
	"testing"
)

// 真 model.conf + 真 policy.csv（同服务端运行期），断言鉴权矩阵。
// 无 HTTP、无 DB：直接调 Enforcer.Enforce，本地与 CI 都能跑。
func TestAuthMatrix_TransportLayer(t *testing.T) {
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

	type c struct {
		role, path, method string
		want               bool
	}
	cases := []c{
		// —— U 管理写：仅 R-ADMIN ——
		{"R-ADMIN", "/api/v1/admin/users", "POST", true},
		{"R-ADMIN", "/api/v1/admin/users/1", "PUT", true},
		{"R-ADMIN", "/api/v1/admin/users/1", "DELETE", true},
		{"R-ADMIN", "/api/v1/admin/users/1/roles/2", "DELETE", true},
		{"R-AUDITOR", "/api/v1/admin/users", "POST", false},
		{"R-AUDITOR", "/api/v1/admin/users/1", "PUT", false},
		{"R-AUDITOR", "/api/v1/admin/users/1", "DELETE", false},
		{"R-MANAGER", "/api/v1/admin/users", "GET", false},
		{"R-STAFF", "/api/v1/admin/users", "GET", false},
		// —— R-AUDITOR 只读：admin 读放行、写全拒 ——
		{"R-AUDITOR", "/api/v1/admin/users", "GET", true},
		{"R-AUDITOR", "/api/v1/admin/roles", "GET", true},
		{"R-AUDITOR", "/api/v1/apply/projects", "GET", true},
		// —— /auth/me：每个已认证角色都要能读自己 ——
		{"R-ADMIN", "/api/v1/auth/me", "GET", true},
		{"R-AUDITOR", "/api/v1/auth/me", "GET", true},
		{"R-MANAGER", "/api/v1/auth/me", "GET", true},
		{"R-STAFF", "/api/v1/auth/me", "GET", true},
		{"R-FINANCE", "/api/v1/auth/me", "GET", true},
		{"R-LEADER", "/api/v1/auth/me", "GET", true},
		{"R-EXPERT", "/api/v1/auth/me", "GET", true},
		{"R-ETHICS", "/api/v1/auth/me", "GET", true},
		// —— 业务域按角色 ——
		{"R-MANAGER", "/api/v1/apply/projects", "POST", true},
		{"R-MANAGER", "/api/v1/apply/projects/9", "PUT", true},
		{"R-STAFF", "/api/v1/apply/projects", "GET", true},
		{"R-STAFF", "/api/v1/expense/claims", "POST", false},
		{"R-FINANCE", "/api/v1/expense/claims", "POST", true},
		{"R-EXPERT", "/api/v1/review/tasks/3", "POST", true},
		{"R-EXPERT", "/api/v1/expense/claims", "POST", false},
		{"R-ETHICS", "/api/v1/ethics/reviews", "POST", true},
		// —— 未知角色：一律拒 ——
		{"R-NOPE", "/api/v1/auth/me", "GET", false},
	}
	for _, tc := range cases {
		got, _ := enf.Enforce(tc.role, tc.path, tc.method)
		if got != tc.want {
			t.Errorf("Enforce(%s,%s,%s)=%v，期望 %v", tc.role, tc.path, tc.method, got, tc.want)
		}
	}
}

// BuildCaps 须与鉴权矩阵同源：R-AUDITOR 的能力里不得出现任何写动作。
func TestBuildCaps_NoWritesForAuditor(t *testing.T) {
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
	for _, cap := range BuildCaps(enf, []string{"R-AUDITOR"}) {
		if hasSuffixAny(cap, " POST", " PUT", " DELETE") {
			t.Errorf("R-AUDITOR 不应有写能力: %q", cap)
		}
	}
}

func hasSuffixAny(s string, suffixes ...string) bool {
	for _, suf := range suffixes {
		if len(s) >= len(suf) && s[len(s)-len(suf):] == suf {
			return true
		}
	}
	return false
}
