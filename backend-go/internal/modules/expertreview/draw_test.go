package expertreview

import (
	"fmt"
	"testing"
)

func TestDrawExcludesAvoidAndDeterministic(t *testing.T) {
	pool := []candidate{
		{1, 201, "A大学", []string{"物理"}, nil, nil},
		{2, 202, "B所", []string{"物理"}, nil, nil},
		{3, 100, "C公司", []string{"物理"}, nil, nil}, // 与项目 PI 同 user_id → 回避
		{4, 204, "承担单位", []string{"物理"}, nil, nil},
	}
	rule := drawRule{FieldTags: []string{"物理"}, ExcludeUserIDs: []int64{100}, ExcludeOrgs: []string{"承担单位"}}
	got := drawExperts(pool, rule, 2, 42) // seed=42
	if len(got) != 2 {
		t.Fatalf("want 2 got %d (%v)", len(got), got)
	}
	for _, id := range got {
		if id == 3 || id == 4 {
			t.Fatalf("回避对象漏入: %d", id)
		}
	}
	// 确定性：同 seed 两次一致
	if a, b := drawExperts(pool, rule, 2, 42), drawExperts(pool, rule, 2, 42); fmt.Sprint(a) != fmt.Sprint(b) {
		t.Fatalf("非确定性: %v vs %v", a, b)
	}
}
