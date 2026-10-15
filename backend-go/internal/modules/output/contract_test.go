package output

import (
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// mustSpec 从仓库根 design/ 载入契约。cwd=backend-go/internal/modules/output → 上溯 4 级。
// 复用与 project/contract_test.go 同路径解析；DESIGN_DIR 可覆盖。
func mustSpec(t *testing.T) *oapi.Spec {
	t.Helper()
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

// TestValidate_OutputContractShape：GET /output 的 data 应是 PageResult；total 漂成 string 必须被拒。
// 与 E/V 域同款守 shape 漂移（不依赖数据库）。
func TestValidate_OutputContractShape(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/output")
	if op == nil {
		t.Fatal("未找到 GET /output")
	}
	dataSchema := oapi.ResolveDataSchema(op)

	good := map[string]any{
		"list":  []any{},
		"total": 3,
		"page":  1,
		"size":  20,
	}
	if errs := oapi.Validate(good, dataSchema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}

	bad := map[string]any{"list": []any{}, "total": "三", "page": 1, "size": 20}
	if errs := oapi.Validate(bad, dataSchema); len(errs) == 0 {
		t.Fatal("类型漂移(total: string)未被校验器捕获")
	}
}

// TestMapper_OutputKeys：ToAPIOutput 输出应含契约 snake_case 关键字段；authors 应解成 []any（jsonb 数组）。
func TestMapper_OutputKeys(t *testing.T) {
	m := ToAPIOutput(newSampleOutput())
	for _, k := range []string{
		"id", "code", "tenant_id", "status", "output_type", "title",
		"authors", "affiliations", "project_ids", "claim_status",
		"security_level", "legal_entity_id", "created_at", "updated_at",
	} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIOutput 缺 key %q", k)
		}
	}
	if _, ok := m["authors"].([]any); !ok {
		t.Errorf("authors 应为 jsonb 数组，实得 %T", m["authors"])
	}
	// match_confidence 契约声明为 number；样例无值 → 键应存在（可为 nil）
	if _, ok := m["match_confidence"]; !ok {
		t.Errorf("ToAPIOutput 缺 key match_confidence")
	}
}

// TestMapper_ClaimRecordKeys：认领流水 mapper 输出应含 output_id/user_id/action/reason/batch_id。
func TestMapper_ClaimRecordKeys(t *testing.T) {
	m := ToAPIClaimRecord(newSampleClaimRecord())
	for _, k := range []string{"id", "output_id", "user_id", "action", "reason", "batch_id", "action_at"} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIClaimRecord 缺 key %q", k)
		}
	}
}
