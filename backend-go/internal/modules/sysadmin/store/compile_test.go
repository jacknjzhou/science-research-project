package sysstore

import (
	"context"
	"testing"
)

// TestGeneratedShape_Compiles 钉住关键模型/参数结构的存在与字段类型，
// 若 sqlc 生成形状漂移（改名/改类型）此断言先于业务层失败，报错更定位。
func TestGeneratedShape_Compiles(t *testing.T) {
	var u SysUser
	var ph *string = u.PasswordHash
	_ = ph
	var _ int64 = u.ID
	var _ *int64 = u.LegalEntityID

	var lp ListUsersParams
	var _ *string = lp.Status
	var _ *string = lp.Keyword
	var _ int32 = lp.Limit
	var _ int64 = lp.TenantID

	// Queries 构造（nil pool 不连库，仅证明类型存在且方法签名就位）
	var q *Queries
	_ = q
	_ = context.Background
	_ = func() { _, _ = (&Queries{}).GetUserByUsername(context.Background(), GetUserByUsernameParams{}) }
}
