package auth

import (
	"net/http"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// HandleLogin 开发/演示登录：校验内置账号，签发带数据域的 JWT。
// M0 内置 ark/ark 便于 compose 冒烟与前端直连；生产接统一身份在 M1 替换本实现。
func HandleLogin(secret string, ttl int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		var body struct {
			Username string `json:"username" binding:"required"`
			Password string `json:"password" binding:"required"`
		}
		if err := c.ShouldBindJSON(&body); err != nil {
			httpx.WriteErr(c, http.StatusBadRequest, 40001, "用户名/密码必填")
			return
		}
		if body.Username != "ark" || body.Password != "ark" {
			httpx.WriteErr(c, http.StatusUnauthorized, 40102, "账号或密码错误")
			return
		}
		claims := Claims{
			UserID:        1,
			TenantID:      1,
			LegalEntityID: 0,
			SecurityLevel: "INTERNAL",
			Roles:         []string{"R-STAFF", "R-MANAGER"},
		}
		tok, err := GenToken(secret, ttl, claims)
		if err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50001, "签发令牌失败")
			return
		}
		httpx.WriteOK(c, gin.H{
			"token_type":   "Bearer",
			"access_token": tok,
			"expires_in":   ttl,
		})
	}
}
