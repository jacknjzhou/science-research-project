package auth

import "testing"

// N 域 caps 派生 + Enforce 测试。复用 caps_project_test.go/caps_perf_test.go 已定义的
// perfEnf/hasCapExact（同包，勿重复定义）。覆盖 R-MANAGER 读写、R-LEADER 审批、
// R-EXPERT 应允/打分（含负例：无抽取/结论/建库），并直接 Enforce 校验 keyMatch2 多段命中。

func TestBuildCaps_ExpertReviewManagerCaps(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-MANAGER"})
	for _, want := range []string{
		"/api/v1/experts GET",
		"/api/v1/experts POST",
		"/api/v1/experts/*/status POST",
		"/api/v1/reviews/*/draw POST",
		"/api/v1/reviews/*/conclude POST",
		"/api/v1/reviews/*/fees POST",
	} {
		if !hasCapExact(caps, want) {
			t.Errorf("R-MANAGER 应有 %q 能力: %v", want, caps)
		}
	}
	// 直接 Enforce：keyMatch2 `*` 须命中多段真实路径。
	type c struct {
		role, path, method string
		want               bool
	}
	for _, tc := range []c{
		{"R-MANAGER", "/api/v1/experts/5/status", "POST", true},
		{"R-MANAGER", "/api/v1/experts/5", "PUT", true},
		{"R-MANAGER", "/api/v1/reviews/9/draw", "POST", true},
		{"R-MANAGER", "/api/v1/reviews/9/detail", "GET", true},
	} {
		if got, _ := enf.Enforce(tc.role, tc.path, tc.method); got != tc.want {
			t.Errorf("Enforce(%s,%s,%s)=%v，期望 %v", tc.role, tc.path, tc.method, got, tc.want)
		}
	}
}

func TestBuildCaps_ExpertReviewExpertCaps(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-EXPERT"})
	for _, want := range []string{
		"/api/v1/reviews/*/scores POST",
		"/api/v1/reviews/*/accept POST",
		"/api/v1/reviews/*/decline POST",
		"/api/v1/reviews GET",
	} {
		if !hasCapExact(caps, want) {
			t.Errorf("R-EXPERT 应有 %q 能力: %v", want, caps)
		}
	}
	// 负例：专家无抽取/结论/建库权限。
	for _, bad := range []string{
		"/api/v1/reviews/*/draw POST",
		"/api/v1/reviews/*/conclude POST",
		"/api/v1/experts POST",
	} {
		if hasCapExact(caps, bad) {
			t.Errorf("R-EXPERT 不应有 %q 能力", bad)
		}
	}
	if got, _ := enf.Enforce("R-EXPERT", "/api/v1/reviews/3/scores", "POST"); !got {
		t.Errorf("R-EXPERT 应对评审 3 打分放行")
	}
	if got, _ := enf.Enforce("R-EXPERT", "/api/v1/reviews/3/draw", "POST"); got {
		t.Errorf("R-EXPERT 不应有抽取权限")
	}
}

func TestBuildCaps_ExpertReviewLeaderApproves(t *testing.T) {
	enf := perfEnf(t)
	caps := BuildCaps(enf, []string{"R-LEADER"})
	if !hasCapExact(caps, "/api/v1/reviews/*/conclude POST") {
		t.Errorf("R-LEADER 应有结论审批能力: %v", caps)
	}
	if hasCapExact(caps, "/api/v1/experts POST") {
		t.Errorf("R-LEADER 不应建专家库")
	}
}
