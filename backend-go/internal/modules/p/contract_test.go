package p

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// mustSpec 从仓库根 design/ 加载契约。测试工作目录 = backend-go/internal/modules/p，
// 上溯 4 级至仓库根（backend-go/internal/modules/p -> ../../../.. = repo root），故用 ../../../../design。
// 可用 DESIGN_DIR 覆盖。
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

// TestValidate_PureContractShape 是无 DB 的纯契约校验：
// 用真实 design 抽出的 GET /apply/applications 的 data schema，
// 喂一份合成的 PageResult 形状，断言 gojsonschema 放行；
// 再把 total 从 integer 改成 string，断言校验器拒绝——真正跑通校验主干。
func TestValidate_PureContractShape(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/apply/applications")
	if op == nil {
		t.Fatal("未找到 GET /apply/applications")
	}
	dataSchema := oapi.ResolveDataSchema(op)

	good := map[string]any{
		"list": []any{
			map[string]any{
				"id":           1,
				"status":       "DRAFT", // enum：M0 经 inlineRefs 放行，只验类型
				"title":        "示例申报",
				"total_budget": "1000.00", // 契约声明为 string
				"member_ids":   []any{int64(7), int64(8)},
			},
		},
		"total": 2,
		"page":  1,
		"size":  20,
	}
	if errs := oapi.Validate(good, dataSchema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}

	// 故意类型漂移：total 应为 integer，给成 string，必须被拒。
	bad := map[string]any{}
	for k, v := range good {
		bad[k] = v
	}
	bad["total"] = "两"
	errs := oapi.Validate(bad, dataSchema)
	if len(errs) == 0 {
		t.Fatal("类型漂移(total: string)未被校验器捕获")
	}
	t.Logf("捕获预期错误: %v", errs)
}

// TestListApplications_ConformsToContract 需要 Postgres：起真实 handler，
// 校验其响应 data 对契约合规。ARK_TEST_DATABASE_URL 未设置时跳过。
func TestListApplications_ConformsToContract(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	e := newTestEngine(t)
	spec := mustSpec(t)
	op := spec.Find("GET", "/apply/applications")
	dataSchema := oapi.ResolveDataSchema(op)

	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/applications", nil))
	var env map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &env)

	errs := oapi.Validate(env["data"], dataSchema)
	if len(errs) > 0 {
		t.Fatalf("响应 data 不合契约: %v", errs)
	}
}
