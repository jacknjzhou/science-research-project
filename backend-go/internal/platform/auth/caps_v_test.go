package auth

import (
	"os"
	"strings"
	"testing"
)

// R-STAFF 的 BuildCaps 应包含 submit 动作的能力模板，但不包含 approve/hold 审批动作。
// 与鉴权矩阵同源：前端 auth.can 据此门控按钮可见性。
func TestBuildCaps_ActivityStaffCaps(t *testing.T) {
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
	caps := BuildCaps(enf, []string{"R-STAFF"})
	var hasSubmit, hasApprove, hasHold bool
	for _, c := range caps {
		switch {
		case strings.HasSuffix(c, "/api/v1/activities/*/submit POST"):
			hasSubmit = true
		case strings.HasSuffix(c, "/api/v1/activities/*/approve POST"):
			hasApprove = true
		case strings.HasSuffix(c, "/api/v1/activities/*/hold POST"):
			hasHold = true
		}
	}
	if !hasSubmit {
		t.Errorf("R-STAFF 应有 submit 能力: %v", caps)
	}
	if hasApprove || hasHold {
		t.Errorf("R-STAFF 不应有审批(approve/hold)能力: approve=%v hold=%v", hasApprove, hasHold)
	}
}
