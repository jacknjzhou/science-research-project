package sysadmin

import (
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// TestContract_Dict_ShapeValidated 字典端点契约校验（12-U openapi）。
func TestContract_Dict_ShapeValidated(t *testing.T) {
	spec := mustSpec(t)

	// GET /dicts/{code}：data = Dict + items[]
	op := spec.Find("GET", "/dicts/{code}")
	if op == nil {
		t.Fatal("未找到 GET /dicts/{code}")
	}
	schema := oapi.ResolveDataSchema(op)
	good := map[string]any{
		"id": 1, "code": "project_type", "name": "项目类型", "tenant_id": 1,
		"items": []any{
			map[string]any{
				"id": 10, "dict_id": 1, "item_code": "NSFC", "item_label": "国家自然科学基金",
				"sort_no": 1, "active": true, "tenant_id": 1,
				"ext": map[string]any{"icon": "NS", "color": "#2C6E49"},
			},
		},
	}
	if errs := oapi.Validate(good, schema); len(errs) > 0 {
		t.Fatalf("GET /dicts/{code} 合规 data 被误判: %v", errs)
	}
	// 漂移：items 必须是数组
	bad := map[string]any{}
	for k, v := range good {
		bad[k] = v
	}
	bad["items"] = "oops"
	if errs := oapi.Validate(bad, schema); len(errs) == 0 {
		t.Fatal("类型漂移(items: string)未被捕获")
	}

	// POST /admin/dicts：data = Dict
	if op = spec.Find("POST", "/admin/dicts"); op == nil {
		t.Fatal("未找到 POST /admin/dicts")
	}
	schema = oapi.ResolveDataSchema(op)
	if errs := oapi.Validate(map[string]any{
		"id": 2, "code": "output_source", "name": "成果来源", "tenant_id": 1,
	}, schema); len(errs) > 0 {
		t.Fatalf("POST /admin/dicts 合规 data 被误判: %v", errs)
	}
}
