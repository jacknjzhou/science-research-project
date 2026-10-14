package auth

import (
	"testing"

	"github.com/casbin/casbin/v2"
)

// 该测试在 package dir (internal/platform/auth) 下运行，
// 故使用相对当前目录的 "model.conf" / "policy.csv"。
func newTestEnforcer(t *testing.T) *casbin.Enforcer {
	t.Helper()
	e, err := NewEnforcer("model.conf", "policy.csv")
	if err != nil {
		t.Fatalf("加载 model.conf/policy.csv 失败: %v", err)
	}
	return e
}

func TestEnforcer_RBACAllowDeny(t *testing.T) {
	e := newTestEnforcer(t)

	cases := []struct {
		role   string
		path   string
		method string
		want   bool
	}{
		{"R-ADMIN", "/api/v1/apply/applications", "GET", true},
		{"R-ADMIN", "/api/v1/apply/applications", "POST", true},
		{"R-STAFF", "/api/v1/apply/applications", "GET", true},
		{"R-STAFF", "/api/v1/admin/users", "GET", false},        // 超出 apply/* 作用域
		{"R-STAFF", "/api/v1/apply/applications", "PUT", false}, // 无 PUT 授权
		{"R-STAFF-NOACCESS", "/api/v1/apply/applications", "GET", false},
	}
	for _, tc := range cases {
		got, err := e.Enforce(tc.role, tc.path, tc.method)
		if err != nil {
			t.Fatalf("Enforce(%s,%s,%s) 报错: %v", tc.role, tc.path, tc.method, err)
		}
		if got != tc.want {
			t.Fatalf("Enforce(%s,%s,%s)=%v 期望 %v", tc.role, tc.path, tc.method, got, tc.want)
		}
	}
}
