package sysadmin

import (
	"github.com/gin-gonic/gin"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
)

// ---------- 页面可见性矩阵（PRD 2.9）：全员只读 / R-ADMIN 全量替换 ----------
// 白名单制：page_name × role_code；role_code='*' 表示所有已登录角色。
// R-ADMIN 恒可见由前端硬编码兜底（防管理员自锁），不入库不参与编辑。

type pageGrantItem struct {
	PageName string `json:"page_name" binding:"required,max=64"`
	RoleCode string `json:"role_code" binding:"required,max=64"`
}

type pageGrantSaveBody struct {
	Grants []pageGrantItem `json:"grants"`
}

// ListPageGrants 全量授权行（任意已登录角色；前端路由守卫/菜单消费）。
func (h *Handler) ListPageGrants(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListPageGrants(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, 500, 50009, "查询失败")
		return
	}
	grants := make([]gin.H, 0, len(rows))
	for _, r := range rows {
		grants = append(grants, gin.H{"page_name": r.PageName, "role_code": r.RoleCode})
	}
	httpx.WriteOK(c, gin.H{"grants": grants})
}

// SavePageGrants 全量替换（事务内先删后插；角色码白名单校验，未知值 400）。
// 页面清单由前端上报（router.options.routes 过滤 public），后端校验角色存在性。
func (h *Handler) SavePageGrants(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b pageGrantSaveBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	// 角色码校验：'*' 语义内置；其余必须存在于本租户 sys_role。
	for _, g := range b.Grants {
		if g.RoleCode == "*" {
			continue
		}
		if _, err := h.q.GetRoleByCode(c, store.GetRoleByCodeParams{TenantID: d.TenantID, Code: g.RoleCode}); err != nil {
			httpx.WriteErr(c, 400, 40002, "未知角色码："+g.RoleCode)
			return
		}
	}
	tx, err := h.pool.Begin(c)
	if err != nil {
		httpx.WriteErr(c, 500, 50010, "事务开启失败")
		return
	}
	defer func() { _ = tx.Rollback(c) }()
	qtx := h.q.WithTx(tx)
	if _, err := qtx.DeleteAllPageGrants(c, d.TenantID); err != nil {
		httpx.WriteErr(c, 500, 50011, "替换失败")
		return
	}
	for _, g := range b.Grants {
		if err := qtx.InsertPageGrant(c, store.InsertPageGrantParams{
			TenantID: d.TenantID, PageName: g.PageName, RoleCode: g.RoleCode,
		}); err != nil {
			httpx.WriteErr(c, 500, 50012, "替换失败")
			return
		}
	}
	if err := tx.Commit(c); err != nil {
		httpx.WriteErr(c, 500, 50013, "提交失败")
		return
	}
	rows, err := h.q.ListPageGrants(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, 500, 50009, "查询失败")
		return
	}
	grants := make([]gin.H, 0, len(rows))
	for _, r := range rows {
		grants = append(grants, gin.H{"page_name": r.PageName, "role_code": r.RoleCode})
	}
	httpx.WriteOK(c, gin.H{"grants": grants})
}
