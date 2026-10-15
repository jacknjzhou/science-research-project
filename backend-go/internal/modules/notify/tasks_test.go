package notify

import (
	"context"
	"fmt"
	"testing"
	"time"
)

// TestTasksAggregation：未读 TODO 通知 + 我名下 PENDING 审批单都进 /tasks；summary 计数。
func TestTasksAggregation(t *testing.T) {
	pool := poolForTest(t)
	h := NewHandler(pool)
	ctx := context.Background()
	const uid = int64(9011)

	if _, err := pool.Exec(ctx, `DELETE FROM sys_notification WHERE user_id = $1`, uid); err != nil {
		t.Fatalf("清理通知: %v", err)
	}

	// 造一条未读 TODO（通知侧待办）+ 一条 MESSAGE（消息 tab）
	h.Push(ctx, 1, uid, "TODO", "T20 待办通知", "内容", "expense/1")
	h.Push(ctx, 1, uid, "MESSAGE", "T20 消息", "内容", "message/from/9001")

	// 造一张 PENDING 审批单（跨域：直接插 F_EXPENSE + 当前步 R-MANAGER PENDING）
	ts := time.Now().UnixNano()
	var eid int64
	if err := pool.QueryRow(ctx, `
		INSERT INTO f_expense (tenant_id, status, creator_id, code, project_id, budget_line_id, legal_entity_id,
			applicant_user_id, amount, expense_type, description, invoice_ids, attachment_ids, submit_mode,
			invoice_check_status)
		VALUES (1, 'SUBMITTED', 100, $1, 9001, 8812, 1, 100, 500, 'MATERIAL', 'T20 待办聚合测试', '[]', '[]', '预算制', 'PENDING')
		RETURNING id`, fmt.Sprintf("EXP-T20-%d", ts)).Scan(&eid); err != nil {
		t.Fatalf("建报销单: %v", err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO f_expense_approval (tenant_id, status, creator_id, expense_id, step_order, role)
		VALUES (1, 'PENDING', 100, $1, 1, 'R-MANAGER')`, eid); err != nil {
		t.Fatalf("建审批步骤: %v", err)
	}
	t.Cleanup(func() {
		_, _ = pool.Exec(ctx, `DELETE FROM f_expense_approval WHERE expense_id=$1`, eid)
		_, _ = pool.Exec(ctx, `DELETE FROM f_expense WHERE id=$1`, eid)
		_, _ = pool.Exec(ctx, `DELETE FROM sys_notification WHERE user_id=$1 AND title LIKE 'T20 %'`, uid)
	})

	r := engine(t, h, uid, 1)

	// /tasks：应含 1 条 NOTIFICATION + 1 条 APPROVAL
	w := doGet(r, "/api/v1/tasks")
	if w.Code != 200 {
		t.Fatalf("/tasks 应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	env := bodyJSON(t, w.Body.Bytes())
	if env["total"].(float64) != 2 {
		t.Fatalf("待办应 2 条，得 %v", env)
	}
	foundApproval := false
	for _, it := range env["list"].([]any) {
		if it.(map[string]any)["kind"] == "APPROVAL" {
			foundApproval = true
			if it.(map[string]any)["amount"] != "500.00" {
				t.Fatalf("待办金额应 500.00，得 %v", it.(map[string]any)["amount"])
			}
		}
	}
	if !foundApproval {
		t.Fatalf("待办应含 APPROVAL 项: %v", env["list"])
	}

	// /tasks/summary：todo=2（1 通知 + 1 审批）、message=1、warning=0
	w = doGet(r, "/api/v1/tasks/summary")
	if w.Code != 200 {
		t.Fatalf("summary 应 200，得 %d", w.Code)
	}
	sum := bodyJSON(t, w.Body.Bytes())
	if sum["todo"].(float64) != 2 || sum["message"].(float64) != 1 || sum["warning"].(float64) != 0 {
		t.Fatalf("summary 应 todo=2 message=1 warning=0，得 %v", sum)
	}

	// 审批完（步骤置 DONE + 单据 APPROVED）→ 待办消失
	if _, err := pool.Exec(ctx, `UPDATE f_expense_approval SET status='DONE', acted_at=now() WHERE expense_id=$1`, eid); err != nil {
		t.Fatalf("置步骤 DONE: %v", err)
	}
	if _, err := pool.Exec(ctx, `UPDATE f_expense SET status='APPROVED' WHERE id=$1`, eid); err != nil {
		t.Fatalf("置单据 APPROVED: %v", err)
	}
	w = doGet(r, "/api/v1/tasks")
	env = bodyJSON(t, w.Body.Bytes())
	if env["total"].(float64) != 1 {
		t.Fatalf("审批后待办应剩 1 条（仅通知），得 %v", env)
	}
}

// TestMessageLoop：点对点消息 → 收件箱（type=MESSAGE）→ summary message 计数。
func TestMessageLoop(t *testing.T) {
	pool := poolForTest(t)
	h := NewHandler(pool)
	ctx := context.Background()
	const sender, receiver = int64(9021), int64(9022)
	if _, err := pool.Exec(ctx, `DELETE FROM sys_notification WHERE user_id IN ($1,$2) AND title LIKE 'T20%'`, sender, receiver); err != nil {
		t.Fatalf("清理: %v", err)
	}
	t.Cleanup(func() {
		_, _ = pool.Exec(ctx, `DELETE FROM sys_notification WHERE user_id IN ($1,$2) AND title LIKE 'T20%'`, sender, receiver)
	})

	// A 发消息给 B
	sr := engine(t, h, sender, 1)
	w := doPost(sr, "/api/v1/messages", `{"to_user_ids":[9022],"title":"T20 业务咨询","body":"预算调整怎么走流程？"}`)
	if w.Code != 200 {
		t.Fatalf("发消息应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := bodyJSON(t, w.Body.Bytes()); got["sent"].(float64) != 1 {
		t.Fatalf("sent 应 1，得 %v", got)
	}

	// B 收件箱
	rr := engine(t, h, receiver, 1)
	w = doGet(rr, "/api/v1/messages")
	if w.Code != 200 {
		t.Fatalf("收件箱应 200，得 %d", w.Code)
	}
	env := bodyJSON(t, w.Body.Bytes())
	if env["total"].(float64) < 1 {
		t.Fatalf("收件箱应 ≥1 条，得 %v", env["total"])
	}
	ok := false
	for _, it := range env["list"].([]any) {
		if it.(map[string]any)["title"] == "T20 业务咨询" {
			ok = true
		}
	}
	if !ok {
		t.Fatalf("收件箱应含该消息: %v", env["list"])
	}

	// B summary：message ≥1
	w = doGet(rr, "/api/v1/tasks/summary")
	sum := bodyJSON(t, w.Body.Bytes())
	if sum["message"].(float64) < 1 {
		t.Fatalf("summary message 应 ≥1，得 %v", sum)
	}
}
