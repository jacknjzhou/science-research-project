package auth

import (
	"context"
	"net/http"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
)

// LoginUser 是登录所需的身份快照，由 auth.UserReader 从数据源取回。
type LoginUser struct {
	UserID        int64
	TenantID      int64
	LegalEntityID int64
	SecurityLevel string
	PasswordHash  string // 空串=无口令账号，一律拒登
	Roles         []string
	Active        bool // status==ACTIVE
}

// UserReader 抽象"取回登录身份"的数据访问，便于 handler 脱库单测与 sysadmin.AuthReader 实现。
type UserReader interface {
	FindForLogin(ctx context.Context, username string, tenantID int64) (*LoginUser, error)
}

// NewLoginHandler 签发带数据域的 JWT。
//   - reader==nil：走内置 ark/ark dev 回退，保证未接库时（router 单测/compose 冒烟）零回归。
//   - reader!=nil：按 username+tenant_id 取回身份，bcrypt 校验 password_hash，命中即签发真实数据域 claims。
// 登录路由始终公开，不进鉴权中间件。
func NewLoginHandler(secret string, ttl int64, reader UserReader) gin.HandlerFunc {
	return func(c *gin.Context) {
		var body struct {
			Username string `json:"username" binding:"required"`
			Password string `json:"password" binding:"required"`
			TenantID *int64 `json:"tenant_id"`
		}
		if err := c.ShouldBindJSON(&body); err != nil {
			httpx.WriteErr(c, http.StatusBadRequest, 40001, "用户名/密码必填")
			return
		}

		// dev 回退：仅 ark/ark 通过，签发固定数据域，便于冒烟与前端直连。
		if reader == nil {
			if body.Username != "ark" || body.Password != "ark" {
				httpx.WriteErr(c, http.StatusUnauthorized, 40102, "账号或密码错误")
				return
			}
			issue(c, secret, ttl, Claims{
				UserID: 1, TenantID: 1, LegalEntityID: 0,
				SecurityLevel: "INTERNAL", Roles: []string{"R-STAFF", "R-MANAGER"},
			})
			return
		}

		tid := int64(1)
		if body.TenantID != nil {
			tid = *body.TenantID
		}
		u, err := reader.FindForLogin(c.Request.Context(), body.Username, tid)
		// 统一失败码，避免用户名枚举（取回失败/不存在/无口令/bcrypt 不符一律 401）。
		if err != nil || u == nil || u.PasswordHash == "" ||
			bcrypt.CompareHashAndPassword([]byte(u.PasswordHash), []byte(body.Password)) != nil {
			httpx.WriteErr(c, http.StatusUnauthorized, 40102, "账号或密码错误")
			return
		}
		if !u.Active {
			httpx.WriteErr(c, http.StatusForbidden, 40302, "账号已停用或锁定")
			return
		}
		issue(c, secret, ttl, Claims{
			UserID: u.UserID, TenantID: u.TenantID, LegalEntityID: u.LegalEntityID,
			SecurityLevel: u.SecurityLevel, Roles: u.Roles,
		})
	}
}

// issue 统一签发：GenToken + WriteOK，输出 {token_type, access_token, expires_in}。
func issue(c *gin.Context, secret string, ttl int64, claims Claims) {
	tok, err := GenToken(secret, ttl, claims)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "签发令牌失败")
		return
	}
	httpx.WriteOK(c, gin.H{"token_type": "Bearer", "access_token": tok, "expires_in": ttl})
}
