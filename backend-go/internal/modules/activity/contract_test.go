package activity

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// mustSpec 从仓库根 design/ 载入契约。测试工作目录 = backend-go/internal/modules/activity，
// 上溯 4 级至仓库根，故 ../../../../design。可用 DESIGN_DIR 覆盖。
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

// 纯形状校验：GET /activities 的 data 应为 PageResult；total 由 integer 漂成 string 必须被拒。
func TestValidate_ActivityContractShape(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/activities")
	if op == nil {
		t.Fatal("未找到 GET /activities")
	}
	dataSchema := oapi.ResolveDataSchema(op)

	good := map[string]any{
		"list":  []any{},
		"total": 5,
		"page":  1,
		"size":  20,
	}
	if errs := oapi.Validate(good, dataSchema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}

	bad := map[string]any{"list": []any{}, "total": "五", "page": 1, "size": 20}
	if errs := oapi.Validate(bad, dataSchema); len(errs) == 0 {
		t.Fatal("类型漂移(total: string)未被校验器捕获")
	}
}

// DB 门控：真实 handler 的响应 data 须对契约合规。
func TestListActivities_ConformsToContract(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	e := newTestEngine(t)
	spec := mustSpec(t)
	op := spec.Find("GET", "/activities")
	dataSchema := oapi.ResolveDataSchema(op)

	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/activities", nil))
	var env map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &env)

	if errs := oapi.Validate(env["data"], dataSchema); len(errs) > 0 {
		t.Fatalf("响应 data 不合契约: %v", errs)
	}
}
