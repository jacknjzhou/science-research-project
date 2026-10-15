package approval

import (
	"context"
	"testing"
	"time"
)

// TestEditableMatrix 锁规则矩阵：学校通过→全员锁；学院通过→仅管理员；审批中→全员锁。
func TestEditableMatrix(t *testing.T) {
	cases := []struct {
		status string
		want   map[string]bool
	}{
		{"DRAFT", map[string]bool{"R-STAFF": true, "R-MANAGER": true, "R-LEADER": true, "R-ADMIN": true}},
		{"RETURNED", map[string]bool{"R-STAFF": true, "R-MANAGER": true, "R-LEADER": true, "R-ADMIN": true}},
		{"SUBMITTED", map[string]bool{"R-STAFF": false, "R-MANAGER": false, "R-LEADER": false, "R-ADMIN": false}},
		{"APPROVING", map[string]bool{"R-STAFF": false, "R-MANAGER": false, "R-LEADER": false, "R-ADMIN": false}},
		{"COLLEGE_PASSED", map[string]bool{"R-STAFF": false, "R-MANAGER": false, "R-LEADER": false, "R-ADMIN": true}},
		{"SCHOOL_PASSED", map[string]bool{"R-STAFF": false, "R-MANAGER": false, "R-LEADER": false, "R-ADMIN": false}},
		{"APPROVED", map[string]bool{"R-STAFF": false, "R-MANAGER": false, "R-LEADER": false, "R-ADMIN": false}},
		{"EFFECTIVE", map[string]bool{"R-STAFF": false, "R-MANAGER": false, "R-LEADER": false, "R-ADMIN": false}},
	}
	for _, c := range cases {
		for role, want := range c.want {
			if got := Editable(c.status, role); got != want {
				t.Errorf("Editable(%q, %q) = %v, want %v", c.status, role, got, want)
			}
		}
	}
}

// TestEnabled：env 开关语义（ARK_APPROVAL_TWOSTEP=on 开，默认关）。
func TestEnabled(t *testing.T) {
	t.Setenv("ARK_APPROVAL_TWOSTEP", "")
	if Enabled() {
		t.Fatal("默认应关闭")
	}
	t.Setenv("ARK_APPROVAL_TWOSTEP", "off")
	if Enabled() {
		t.Fatal("off 应关闭")
	}
	t.Setenv("ARK_APPROVAL_TWOSTEP", "on")
	if !Enabled() {
		t.Fatal("on 应开启")
	}
}

// TestNextStep 两级推进序号。
func TestNextStep(t *testing.T) {
	ts := TwoStep{FirstRole: "R-MANAGER", SecondRole: "R-LEADER"}
	if got := ts.NextStep(false, 0); got != 1 {
		t.Fatalf("单级模式恒 1，得 %d", got)
	}
	if got := ts.NextStep(true, 0); got != 1 {
		t.Fatalf("两级首步应 1，得 %d", got)
	}
	if got := ts.NextStep(true, 1); got != 2 {
		t.Fatalf("两级次步应 2，得 %d", got)
	}
}

// TestHasRole 角色包含判断。
func TestHasRole(t *testing.T) {
	roles := []string{"R-MANAGER", "R-FINANCE"}
	if !HasRole(roles, "R-MANAGER") || HasRole(roles, "R-LEADER") {
		t.Fatal("HasRole 判断错误")
	}
}

// TestLogRoundtrip DB-gated：写流水 → 按业务反查（顺序 + 字段）。
func TestLogRoundtrip(t *testing.T) {
	pool := poolForTest(t)
	s := New(pool)
	ctx := context.Background()
	// 唯一 biz_id 保证重复运行稳定（不清理历史流水）
	bizID := time.Now().UnixNano() % 1_000_000_000
	p1 := LogParam{TenantID: 1, BizType: "TEST_BIZ", BizID: bizID, Step: 0, ActorID: 9, ActorRole: "R-STAFF", Action: "SUBMIT"}
	p2 := LogParam{TenantID: 1, BizType: "TEST_BIZ", BizID: bizID, Step: 1, ActorID: 10, ActorRole: "R-MANAGER", Action: "APPROVE", Comment: "同意"}
	if err := s.Log(ctx, p1); err != nil {
		t.Fatalf("写流水: %v", err)
	}
	if err := s.Log(ctx, p2); err != nil {
		t.Fatalf("写流水2: %v", err)
	}
	logs, err := s.ListLogs(ctx, 1, "TEST_BIZ", bizID)
	if err != nil {
		t.Fatalf("查流水: %v", err)
	}
	if len(logs) != 2 {
		t.Fatalf("应 2 条流水，得 %d", len(logs))
	}
	if logs[0].Action != "SUBMIT" || logs[1].Action != "APPROVE" || logs[1].Comment != "同意" {
		t.Fatalf("流水内容不符: %+v", logs)
	}
	if !logs[0].ActedAt.Before(logs[1].ActedAt) && !logs[0].ActedAt.Equal(logs[1].ActedAt) {
		t.Fatalf("流水时间应升序")
	}
}
