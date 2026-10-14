package vstore

import (
	"context"
	"testing"
	"time"
)

// TestStoreShapes 钉住 sqlc 生成物的关键字段类型，防止列/类型漂移破坏 handler 映射。
func TestStoreShapes(t *testing.T) {
	var a Activity
	a.CreatedAt = time.Time{}  // override: time.Time
	a.StartAt = nil            // nullable → *time.Time
	a.BudgetAmount = "1000.00" // NUMERIC ::text → string
	a.Status = "DRAFT"
	var p VActivityParticipant
	p.GuestName = nil // nullable → *string
	var r VActivityReview
	r.ActedAt = time.Time{}
	// 方法存在性（不调用，仅取函数值）
	_ = (&Queries{}).ListActivities
	_ = (&Queries{}).CountActivities
	_ = (&Queries{}).CreateActivity
	_ = (&Queries{}).TransitionStatus
	_ = func(q *Queries) { _, _ = q.SoftDeleteActivity(context.Background(), SoftDeleteActivityParams{}) }
	_ = a
	_ = p
	_ = r
}
