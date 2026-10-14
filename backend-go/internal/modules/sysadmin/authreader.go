package sysadmin

import (
	"context"
	"errors"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// AuthReader 实现 auth.UserReader，经 sqlc 生成的 sysstore 查询取回登录身份。
type AuthReader struct{ q *store.Queries }

// NewAuthReader 以 pgx 连接池构造 AuthReader。
func NewAuthReader(pool *pgxpool.Pool) *AuthReader {
	return &AuthReader{q: store.New(pool)}
}

// FindForLogin 按 username+tenantID 取回用户，组装 auth.LoginUser。
// 用户名不存在返回 (nil,nil)（登录侧统一按 401 处理，避免枚举）。
func (a *AuthReader) FindForLogin(ctx context.Context, username string, tenantID int64) (*auth.LoginUser, error) {
	u, err := a.q.GetUserByUsername(ctx, store.GetUserByUsernameParams{Username: username, TenantID: tenantID})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	codes, err := a.q.ListRoleCodesByUser(ctx, u.ID)
	if err != nil {
		return nil, err
	}
	ph := ""
	if u.PasswordHash != nil {
		ph = *u.PasswordHash
	}
	le := int64(0)
	if u.LegalEntityID != nil {
		le = *u.LegalEntityID
	}
	return &auth.LoginUser{
		UserID:        u.ID,
		TenantID:      u.TenantID,
		LegalEntityID: le,
		SecurityLevel: u.SecurityLevel,
		PasswordHash:  ph,
		Roles:         codes,
		Active:        u.Status == "ACTIVE",
	}, nil
}
