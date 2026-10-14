package auth

import (
	"os"
	"testing"
)

func TestBuildCaps_FromPolicy(t *testing.T) {
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
	caps := BuildCaps(enf, []string{"R-ADMIN"})
	if len(caps) == 0 {
		t.Fatal("R-ADMIN 应至少命中若干策略")
	}
	set := map[string]bool{}
	for _, c := range caps {
		set[c] = true
	}
	if !set["/api/v1/* GET"] {
		t.Fatalf("缺 R-ADMIN GET 通配能力: %v", caps)
	}
	// 已排序 & 去重：不应有完全相同项
	for i := 1; i < len(caps); i++ {
		if caps[i] == caps[i-1] {
			t.Fatalf("能力未去重: %v", caps)
		}
	}
	// 未知角色 → 空能力
	if got := BuildCaps(enf, []string{"R-NOPE"}); len(got) != 0 {
		t.Fatalf("未知角色不应有能力: %v", got)
	}
	// nil enforcer → 空（防御）
	if got := BuildCaps(nil, []string{"R-ADMIN"}); len(got) != 0 {
		t.Fatal("nil enforcer 应返回空")
	}
}
