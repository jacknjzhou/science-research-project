package sysadmin

import (
	"time"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
)

// ToAPIUser 把 sqlc SysUser 行映射为契约 User 形状（snake_case，附 roles[]）。
// 铁律：password_hash 永不进入返回值。
func ToAPIUser(u store.SysUser, roles []string) map[string]any {
	if roles == nil {
		roles = []string{}
	}
	out := map[string]any{
		"id":                u.ID,
		"username":          u.Username,
		"real_name":         u.RealName,
		"employment_status": u.EmploymentStatus,
		"security_level":    u.SecurityLevel,
		"status":            u.Status,
		"tenant_id":         u.TenantID,
		"deleted":           u.Deleted,
		"creator_id":        u.CreatorID,
		"roles":             roles,
		"created_at":        u.CreatedAt.UTC().Format(time.RFC3339Nano),
		"updated_at":        u.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}
	putStr := func(k string, v *string) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putStr("email", u.Email)
	putStr("phone", u.Phone)
	putStr("staff_no", u.StaffNo)
	putStr("remark", u.Remark)
	if u.LegalEntityID != nil {
		out["legal_entity_id"] = *u.LegalEntityID
	} else {
		out["legal_entity_id"] = nil
	}
	return out
}

// ToAPIRole 映射 sys_role → 契约 Role（任务 11 使用）。
func ToAPIRole(r store.SysRole) map[string]any {
	return map[string]any{
		"id":         r.ID,
		"code":       r.Code,
		"name":       r.Name,
		"is_builtin": r.IsBuiltin,
		"tenant_id":  r.TenantID,
		"created_at": r.CreatedAt.UTC().Format(time.RFC3339Nano),
		"updated_at": r.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}
}
