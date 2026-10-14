package sysadmin

import (
	"strconv"

	"github.com/casbin/casbin/v2"
	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
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
