package middleware

import (
	"net/http"
	"strings"

	"github.com/casbin/casbin/v2"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// Auth 校验 Bearer JWT → 注入数据域 → Casbin 判权（任一带权限的 role 命中即放行）。
func Auth(secret string, enf *casbin.Enforcer) gin.HandlerFunc {
	return func(c *gin.Context) {
		h := c.GetHeader("Authorization")
		if !strings.HasPrefix(h, "Bearer ") {
			httpx.WriteErr(c, http.StatusUnauthorized, 40101, "未认证")
			c.Abort()
			return
		}
		claims, err := auth.ParseToken(secret, strings.TrimPrefix(h, "Bearer "))
		if err != nil {
			httpx.WriteErr(c, http.StatusUnauthorized, 40102, "令牌无效或过期")
			c.Abort()
			return
		}
		// 数据域注入
		c.Set(auth.CtxUserID, claims.UserID)
		c.Set(auth.CtxTenantID, claims.TenantID)
		c.Set(auth.CtxLegalEntityID, claims.LegalEntityID)
		if claims.SecurityLevel != "" {
			c.Set(auth.CtxSecurityLevel, claims.SecurityLevel)
		}
		c.Set(auth.CtxRoles, claims.Roles)

		// 授权：逐角色判定，命中即放行
		path := c.Request.URL.Path
		method := c.Request.Method
		ok := false
		for _, role := range claims.Roles {
			if allowed, _ := enf.Enforce(role, path, method); allowed {
				ok = true
				break
			}
		}
		if !ok {
			httpx.WriteErr(c, http.StatusForbidden, 40301, "无权限")
			c.Abort()
			return
		}
		c.Next()
	}
}
