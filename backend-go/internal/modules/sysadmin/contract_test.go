package sysadmin

import (
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// mustSpec 从仓库根 design/ 加载契约。测试工作目录 = backend-go/internal/modules/sysadmin，
// 上溯 4 级到仓库根，故 ../../../../design；DESIGN_DIR 可覆盖。
func mustSpec(t *testing.T) *oapi.Spec {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../../../design"
	}
	s, err := oapi.LoadDir(d)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestContract_ListUsers_ShapeValidated(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/admin/users")
	if op == nil {
		t.Fatal("未找到 GET /admin/users")
	}
	schema := oapi.ResolveDataSchema(op)
	good := map[string]any{
		"list": []any{
			map[string]any{
				"id": 1, "username": "admin", "real_name": "系统管理员",
				"status": "ACTIVE", "security_level": "TOP_SECRET", "roles": []any{"R-ADMIN"},
			},
		},
		"total": 1, "page": 1, "size": 20,
	}
	if errs := oapi.Validate(good, schema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}
	// 类型漂移：total 应为整型，给字符串必须被拒
	bad := map[string]any{}
	for k, v := range good {
		bad[k] = v
	}
	bad["total"] = "一"
	if errs := oapi.Validate(bad, schema); len(errs) == 0 {
		t.Fatal("类型漂移(total: string)未被捕获")
	}
}

func TestContract_Me_CapsArrayValidated(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/auth/me")
	if op == nil {
		t.Fatal("未找到 GET /auth/me")
	}
	schema := oapi.ResolveDataSchema(op)
	good := map[string]any{
		"user":  map[string]any{"id": 1, "username": "admin", "status": "ACTIVE"},
		"roles": []any{"R-ADMIN"},
		"caps":  []any{"/api/v1/admin/users GET", "/api/v1/admin/users POST"},
	}
	if errs := oapi.Validate(good, schema); len(errs) > 0 {
		t.Fatalf("/auth/me 合规 data 被误判: %v", errs)
	}
}
