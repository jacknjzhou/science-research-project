package sysadmin

import (
	"strconv"

	"github.com/gin-gonic/gin"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
)

// ---------- 角色目录维护（管理员可增/改/删；粒度②策略仍由 policy.csv 承载） ----------

type roleUpsertBody struct {
	Code string `json:"code" binding:"required,max=32"`
	Name string `json:"name" binding:"required,max=64"`
}

// CreateRole 新增自定义角色（is_builtin=FALSE）。
// 注意：code 需同时在 Casbin 策略中配置 API 授权，角色方能实际访问接口。
func (h *Handler) CreateRole(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b roleUpsertBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	r, err := h.q.CreateRole(c, store.CreateRoleParams{Code: b.Code, Name: b.Name, TenantID: d.TenantID})
	if err != nil {
		// uk_role_code (tenant_id, code) 唯一冲突
		httpx.WriteErr(c, 409, 40901, "角色编码已存在")
		return
	}
	httpx.WriteOK(c, ToAPIRole(r))
}

// UpdateRole 仅改名称（code 与 Casbin/用户绑定关联，不可变）。
func (h *Handler) UpdateRole(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("roleId"), 10, 64)
	var b struct {
		Name string `json:"name" binding:"required,max=64"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	r, err := h.q.UpdateRole(c, store.UpdateRoleParams{ID: id, TenantID: d.TenantID, Name: b.Name})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "角色不存在")
		return
	}
	httpx.WriteOK(c, ToAPIRole(r))
}

// DeleteRole 删除自定义角色：内置 409；已绑定用户 409（FK 约束前置校验，报错可读）。
func (h *Handler) DeleteRole(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("roleId"), 10, 64)
	r, err := h.q.GetRoleByID(c, store.GetRoleByIDParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "角色不存在")
		return
	}
	if r.IsBuiltin {
		httpx.WriteErr(c, 409, 40901, "内置角色不可删除")
		return
	}
	n, _ := h.q.CountRoleUsers(c, id)
	if n > 0 {
		httpx.WriteErr(c, 409, 40901, "角色已绑定 "+strconv.FormatInt(n, 10)+" 个用户，请先解除绑定")
		return
	}
	_, err = h.q.DeleteRole(c, store.DeleteRoleParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "删除失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}
