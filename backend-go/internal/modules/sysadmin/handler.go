package sysadmin

import (
	"strconv"

	"github.com/casbin/casbin/v2"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
)

type Handler struct {
	q   *store.Queries
	enf *casbin.Enforcer
}

func NewHandler(pool *pgxpool.Pool, enf *casbin.Enforcer) *Handler {
	return &Handler{q: store.New(pool), enf: enf}
}

// pageArgs 与 P 模块同款分页解析（size 上限 200）。
func pageArgs(c *gin.Context) (page, size, limit, offset int32) {
	p, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	s, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if p < 1 {
		p = 1
	}
	if s < 1 {
		s = 20
	}
	if s > 200 {
		s = 200
	}
	return int32(p), int32(s), int32(s), int32((p - 1) * s)
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

// ListUsers 租户硬隔离 + 状态/关键词筛选。
func (h *Handler) ListUsers(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	status := optQuery(c, "status")
	var kw *string
	if v := optQuery(c, "keyword"); v != nil {
		w := "%" + *v + "%"
		kw = &w
	}
	rows, err := h.q.ListUsers(c, store.ListUsersParams{
		TenantID: d.TenantID, Status: status, Keyword: kw, Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountUsers(c, store.CountUsersParams{TenantID: d.TenantID, Status: status, Keyword: kw})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		codes, _ := h.q.ListRoleCodesByUser(c, r.ID)
		list = append(list, ToAPIUser(r, codes))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetUser 仅取本租户、未软删的用户，否则 404。
func (h *Handler) GetUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	u, err := h.q.GetUser(c, store.GetUserParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	codes, _ := h.q.ListRoleCodesByUser(c, u.ID)
	httpx.WriteOK(c, ToAPIUser(u, codes))
}

// GetMe 回显当前登录者：完整 User（DB 取回，租户一致）+ 角色 + 能力集合（Caps 源自 Casbin）。
func (h *Handler) GetMe(c *gin.Context) {
	d := auth.DomainFrom(c)
	roles := d.Roles
	if codes, err := h.q.ListRoleCodesByUser(c, d.UserID); err == nil && len(codes) > 0 {
		roles = codes
	}
	caps := auth.BuildCaps(h.enf, roles)
	var user map[string]any
	if u, err := h.q.GetUser(c, store.GetUserParams{ID: d.UserID, TenantID: d.TenantID}); err == nil {
		user = ToAPIUser(u, roles)
	} else {
		// 资料缺失（如已软删）仍回可辨识骨架，避免 me 端点整体失败
		user = map[string]any{"id": d.UserID, "security_level": d.SecurityLevel, "roles": roles}
	}
	httpx.WriteOK(c, gin.H{"user": user, "roles": roles, "caps": caps})
}

// hashPassword 生成 bcrypt(cost 默认) 哈希，供新用户/改密落库。
func hashPassword(plain string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(plain), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func strPtr(s *string) *string { return s }

// CreateUser 建用户：username 租户内唯一（409），口令 bcrypt 入库，roles 逐条绑定。
func (h *Handler) CreateUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	var body struct {
		Username         string   `json:"username" binding:"required"`
		RealName         string   `json:"real_name" binding:"required"`
		Password         string   `json:"password" binding:"required"`
		Email            *string  `json:"email"`
		Phone            *string  `json:"phone"`
		StaffNo          *string  `json:"staff_no"`
		SecurityLevel    string   `json:"security_level"`
		EmploymentStatus string   `json:"employment_status"`
		Roles            []string `json:"roles"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	ph, err := hashPassword(body.Password)
	if err != nil {
		httpx.WriteErr(c, 500, 50003, "口令加密失败")
		return
	}
	sl := body.SecurityLevel
	if sl == "" {
		sl = "INTERNAL"
	}
	es := body.EmploymentStatus
	if es == "" {
		es = "ONBOARD"
	}
	u, err := h.q.CreateUser(c, store.CreateUserParams{
		Username: body.Username, RealName: body.RealName, PasswordHash: &ph,
		Email: strPtr(body.Email), Phone: strPtr(body.Phone), StaffNo: strPtr(body.StaffNo),
		EmploymentStatus: es, SecurityLevel: sl, Status: "ACTIVE",
		TenantID: d.TenantID, LegalEntityID: nil, CreatorID: d.UserID,
	})
	if err != nil {
		// 23505 = unique_violation（uk_user_username）
		httpx.WriteErr(c, 409, 40901, "用户名已存在或写入冲突")
		return
	}
	for _, code := range body.Roles {
		role, err := h.q.GetRoleByCode(c, store.GetRoleByCodeParams{TenantID: d.TenantID, Code: code})
		if err != nil {
			continue // 未知角色码忽略
		}
		_ = h.q.AssignRole(c, store.AssignRoleParams{UserID: u.ID, RoleID: role.ID, TenantID: d.TenantID})
	}
	codes, _ := h.q.ListRoleCodesByUser(c, u.ID)
	httpx.WriteOK(c, ToAPIUser(u, codes))
}

// UpdateUser 读旧行→合并可变列→落库；password 给出则重设。
func (h *Handler) UpdateUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	cur, err := h.q.GetUser(c, store.GetUserParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	var body struct {
		RealName      *string `json:"real_name"`
		Email         *string `json:"email"`
		Phone         *string `json:"phone"`
		SecurityLevel *string `json:"security_level"`
		Status        *string `json:"status"`
		Password      *string `json:"password"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	realName := cur.RealName
	if body.RealName != nil {
		realName = *body.RealName
	}
	sl := cur.SecurityLevel
	if body.SecurityLevel != nil {
		sl = *body.SecurityLevel
	}
	st := cur.Status
	if body.Status != nil {
		st = *body.Status
	}
	updated, err := h.q.UpdateUser(c, store.UpdateUserParams{
		ID: id, TenantID: d.TenantID, RealName: realName,
		Email: body.Email, Phone: body.Phone, SecurityLevel: sl, Status: st,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50004, "更新失败")
		return
	}
	if body.Password != nil && *body.Password != "" {
		ph, err := hashPassword(*body.Password)
		if err == nil {
			_ = h.q.UpdateUserPassword(c, store.UpdateUserPasswordParams{ID: id, TenantID: d.TenantID, PasswordHash: &ph})
			updated.PasswordHash = &ph
		}
	}
	codes, _ := h.q.ListRoleCodesByUser(c, id)
	httpx.WriteOK(c, ToAPIUser(updated, codes))
}

// DeleteUser 软删（deleted=1 + status=DISABLED）。
func (h *Handler) DeleteUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	if _, err := h.q.GetUser(c, store.GetUserParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	if err := h.q.SoftDeleteUser(c, store.SoftDeleteUserParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 500, 50005, "停用失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}

// ListRoles 本租户角色目录。
func (h *Handler) ListRoles(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListRoles(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, 500, 50006, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIRole(r))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

// AssignRole 授予角色：校验角色与用户均属本租户，幂等绑定后回显用户。
func (h *Handler) AssignRole(c *gin.Context) {
	d := auth.DomainFrom(c)
	userID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		RoleID int64 `json:"role_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "role_id 必填")
		return
	}
	if _, err := h.q.GetRole(c, store.GetRoleParams{ID: body.RoleID, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40402, "角色不存在或跨租户")
		return
	}
	u, err := h.q.GetUser(c, store.GetUserParams{ID: userID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	if err := h.q.AssignRole(c, store.AssignRoleParams{UserID: userID, RoleID: body.RoleID, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 500, 50007, "授权失败")
		return
	}
	codes, _ := h.q.ListRoleCodesByUser(c, userID)
	httpx.WriteOK(c, ToAPIUser(u, codes))
}

// RevokeRole 撤销角色（DELETE /admin/users/:id/roles/:roleId），回显撤销后的用户。
func (h *Handler) RevokeRole(c *gin.Context) {
	d := auth.DomainFrom(c)
	userID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	roleID, _ := strconv.ParseInt(c.Param("roleId"), 10, 64)
	u, err := h.q.GetUser(c, store.GetUserParams{ID: userID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	if err := h.q.RevokeRole(c, store.RevokeRoleParams{UserID: userID, RoleID: roleID, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 500, 50008, "撤销失败")
		return
	}
	codes, _ := h.q.ListRoleCodesByUser(c, userID)
	httpx.WriteOK(c, ToAPIUser(u, codes))
}
