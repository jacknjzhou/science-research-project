package project

import (
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// mustSpec 从仓库根 design/ 载入契约。cwd=backend-go/internal/modules/project → 上溯 4 级。
// 复用与 activity/contract_test.go 同路径解析；DESIGN_DIR 可覆盖。
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

// TestValidate_ProjectContractShape：GET /project/mine 的 data 应是 PageResult；
// total 漂成 string 必须被拒。与 V 域同款守 shape 漂移。
func TestValidate_ProjectContractShape(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/project/mine")
	if op == nil {
		t.Fatal("未找到 GET /project/mine")
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

// TestMapper_ProjectKeys：ToAPIProject 输出应含契约 snake_case 关键字段。
// 无库，只校 mapper 结构对齐——DB-gated 端到端在 handler_test 里。
func TestMapper_ProjectKeys(t *testing.T) {
	m := ToAPIProject(newSampleProject())
	for _, k := range []string{
		"id", "code", "tenant_id", "status", "title", "project_type", "pi_user_id",
		"security_level", "created_at", "updated_at", "total_budget", "health_score",
	} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIProject 缺 key %q", k)
		}
	}
	if _, ok := m["total_budget"].(string); !ok {
		t.Errorf("total_budget 应为 string（NUMERIC 契约）")
	}
}

// TestMapper_MidCheckKeys：中检 mapper 输出应含 expert_ids/score_detail/conclusion 等。
func TestMapper_MidCheckKeys(t *testing.T) {
	m := ToAPIMidCheck(newSampleMidCheck())
	for _, k := range []string{
		"id", "code", "project_id", "status", "check_round", "check_date",
		"expert_ids", "conclusion", "score_detail",
	} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIMidCheck 缺 key %q", k)
		}
	}
	// expert_ids 应解成 []any（jsonb）
	if _, ok := m["expert_ids"].([]any); !ok {
		t.Errorf("expert_ids 应为 jsonb 数组，实得 %T", m["expert_ids"])
	}
}
