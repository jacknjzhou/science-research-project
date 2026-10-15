package expertreview

import (
	"os"
	"testing"
	"time"

	nstore "github.com/eplugger/ark/internal/modules/expertreview/store"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/jackc/pgx/v5/pgtype"
)

// mustSpec 从仓库根 design/ 载入契约。cwd=backend-go/internal/modules/expertreview → 上溯 4 级。
// 与 project/output/contract_test.go 同路径解析；DESIGN_DIR 可覆盖。
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

// ---------- 样例（无库即可跑，供 mapper 键校验复用） ----------

func newSampleExpert() nstore.Expert {
	title := "教授"
	org := "A大学"
	uid := int64(100)
	return nstore.Expert{
		ID: 1, TenantID: 1, Status: "ACTIVE", Name: "张三",
		Title: &title, OrgName: &org, UserID: &uid,
		Source: "EXTERNAL", ExpertiseLevel: "EXPERT", SecurityLevel: "INTERNAL",
		FieldTags:      []byte(`["物理","化学"]`),
		AvoidOrgs:      []byte(`["B所"]`),
		AvoidPersonIds: []byte(`[200,201]`),
		ReviewCount:    0,
		CreatedAt:      time.Now().UTC(), UpdatedAt: time.Now().UTC(),
	}
}

func newSampleReviewTask() nstore.ReviewTask {
	tt := "PROJECT"
	tid := int64(5)
	pid := int64(9)
	return nstore.ReviewTask{
		ID: 1, TenantID: 1, Status: "DRAFT",
		BizType: "MID_CHECK", TargetType: &tt, TargetID: &tid, ProjectID: &pid,
		Title: "中期检查评审", ReviewMethod: "RANDOM", PlanCount: 3,
		DrawRule: []byte(`{"field_tags":["物理"]}`), SecurityLevel: "INTERNAL",
		CreatedAt: time.Now().UTC(), UpdatedAt: time.Now().UTC(),
	}
}

func newSampleScore() nstore.Score {
	var tot pgtype.Numeric
	_ = tot.Scan("88.50")
	return nstore.Score{
		ID: 1, TenantID: 1, TaskID: 1, ExpertID: 2,
		DimensionScores: []byte(`[{"d":"创新","s":90}]`),
		TotalScore:      tot, Status: "SUBMITTED",
	}
}

func newSampleInvitation() nstore.ListInvitationsRow {
	return nstore.ListInvitationsRow{
		ID: 1, TenantID: 1, TaskID: 1, ExpertID: 2,
		SeatNo: 1, AvoidHit: false, Response: "PENDING", ExpertName: "李四",
	}
}

// ---------- 契约形状（不依赖数据库） ----------

func TestValidate_ExpertContractShape(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/experts")
	if op == nil {
		t.Fatal("未找到 GET /experts")
	}
	dataSchema := oapi.ResolveDataSchema(op)
	good := map[string]any{"list": []any{}, "total": 3, "page": 1, "size": 20}
	if errs := oapi.Validate(good, dataSchema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}
	bad := map[string]any{"list": []any{}, "total": "三", "page": 1, "size": 20}
	if errs := oapi.Validate(bad, dataSchema); len(errs) == 0 {
		t.Fatal("类型漂移(total: string)未被校验器捕获")
	}
}

func TestValidate_ReviewContractShape(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/reviews")
	if op == nil {
		t.Fatal("未找到 GET /reviews")
	}
	dataSchema := oapi.ResolveDataSchema(op)
	good := map[string]any{"list": []any{}, "total": 1, "page": 1, "size": 20}
	if errs := oapi.Validate(good, dataSchema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}
}

// ---------- mapper 键校验 ----------

func TestMapper_ExpertKeys(t *testing.T) {
	m := ToAPIExpert(newSampleExpert())
	for _, k := range []string{
		"id", "code", "tenant_id", "status", "name", "source", "expertise_level",
		"field_tags", "avoid_orgs", "avoid_person_ids", "security_level", "created_at", "updated_at",
	} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIExpert 缺 key %q", k)
		}
	}
	for _, arr := range []string{"field_tags", "avoid_orgs", "avoid_person_ids"} {
		if _, ok := m[arr].([]any); !ok {
			t.Errorf("ToAPIExpert %q 应为 jsonb 数组，实得 %T", arr, m[arr])
		}
	}
}

func TestMapper_ReviewTaskKeys(t *testing.T) {
	m := ToAPIReviewTask(newSampleReviewTask())
	for _, k := range []string{
		"id", "biz_type", "target_type", "target_id", "project_id", "title",
		"review_method", "plan_count", "draw_rule", "status", "security_level",
		"created_at", "updated_at",
	} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIReviewTask 缺 key %q", k)
		}
	}
	if _, ok := m["draw_rule"].(map[string]any); !ok {
		t.Errorf("ToAPIReviewTask draw_rule 应为对象，实得 %T", m["draw_rule"])
	}
}

func TestMapper_ScoreKeys(t *testing.T) {
	m := ToAPIScore(newSampleScore())
	for _, k := range []string{"id", "task_id", "expert_id", "dimension_scores", "total_score", "status"} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIScore 缺 key %q", k)
		}
	}
	// total_score 契约是 NUMERIC(10,2) 定标字符串。
	if ts, ok := m["total_score"].(string); !ok || ts != "88.50" {
		t.Errorf("total_score 应为定标字符串 88.50，实得 %#v", m["total_score"])
	}
	if _, ok := m["dimension_scores"].([]any); !ok {
		t.Errorf("dimension_scores 应为 jsonb 数组，实得 %T", m["dimension_scores"])
	}
}

func TestMapper_InvitationKeys(t *testing.T) {
	m := ToAPIInvitation(newSampleInvitation())
	for _, k := range []string{"id", "task_id", "expert_id", "expert_name", "seat_no", "avoid_hit", "response"} {
		if _, ok := m[k]; !ok {
			t.Errorf("ToAPIInvitation 缺 key %q", k)
		}
	}
}
