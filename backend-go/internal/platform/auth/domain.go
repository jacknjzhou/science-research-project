package auth

import "github.com/gin-gonic/gin"

const (
	CtxUserID        = "uid"
	CtxTenantID      = "tenant_id"
	CtxLegalEntityID = "legal_entity_id"
	CtxSecurityLevel = "security_level"
	CtxRoles         = "roles"
)

type Domain struct {
	UserID        int64
	TenantID      int64
	LegalEntityID int64 // 0 表示未细分
	SecurityLevel string
	Roles         []string
}

func DomainFrom(c *gin.Context) Domain {
	d := Domain{SecurityLevel: "INTERNAL"}
	if v, ok := c.Get(CtxUserID); ok {
		d.UserID, _ = v.(int64)
	}
	if v, ok := c.Get(CtxTenantID); ok {
		d.TenantID, _ = v.(int64)
	}
	if v, ok := c.Get(CtxLegalEntityID); ok {
		d.LegalEntityID, _ = v.(int64)
	}
	if v, ok := c.Get(CtxSecurityLevel); ok {
		if s, ok2 := v.(string); ok2 && s != "" {
			d.SecurityLevel = s
		}
	}
	if v, ok := c.Get(CtxRoles); ok {
		d.Roles, _ = v.([]string)
	}
	return d
}
