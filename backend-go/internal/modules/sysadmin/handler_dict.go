package sysadmin

import (
	"encoding/json"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
)

// ---------- 数据字典（PRD 2.8）：管理端 CRUD + 全员只读 ----------

type dictUpsertBody struct {
	Code   string `json:"code" binding:"required,max=64"`
	Name   string `json:"name" binding:"required,max=128"`
	Remark *string `json:"remark"`
}

// ListDicts 字典目录分页（keyword 匹配 code/name；本租户）。
func (h *Handler) ListDicts(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	var kw *string
	if v := optQuery(c, "keyword"); v != nil {
		w := "%" + *v + "%"
		kw = &w
	}
	rows, err := h.q.ListDicts(c, store.ListDictsParams{
		TenantID: d.TenantID, Keyword: kw, Limit: int64(limit), Offset: int64(offset),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountDicts(c, store.CountDictsParams{TenantID: d.TenantID, Keyword: kw})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIDict(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// UpsertDict 新建/按 code 更新（tenant+code 部分唯一索引，软删后同码可重建）。
func (h *Handler) UpsertDict(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b dictUpsertBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	r, err := h.q.UpsertDict(c, store.UpsertDictParams{
		TenantID: d.TenantID, Code: b.Code, Name: b.Name,
		Remark: b.Remark, ActorID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "保存失败")
		return
	}
	httpx.WriteOK(c, ToAPIDict(r))
}

// GetDict 详情（含全部条目，含停用/未生效）。
func (h *Handler) GetDict(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("dictId"), 10, 64)
	r, err := h.q.GetDict(c, store.GetDictParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "字典不存在")
		return
	}
	items, _ := h.q.ListDictItems(c, store.ListDictItemsParams{DictID: id, TenantID: d.TenantID})
	out := ToAPIDict(r)
	out["items"] = dictItemList(items)
	httpx.WriteOK(c, out)
}

// DeleteDict 软删（deleted=1；条目保留，随读随隐）。
func (h *Handler) DeleteDict(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("dictId"), 10, 64)
	n, err := h.q.SoftDeleteDict(c, store.SoftDeleteDictParams{ID: id, TenantID: d.TenantID, ActorID: &d.UserID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "字典不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}

type dictItemBody struct {
	ItemCode      string          `json:"item_code" binding:"required,max=64"`
	ItemLabel     string          `json:"item_label" binding:"required,max=128"`
	ParentID      *int64          `json:"parent_id"`
	Ext           json.RawMessage `json:"ext"`
	I18n          json.RawMessage `json:"i18n"`
	SortNo        *int32          `json:"sort_no"`
	EffectiveFrom *string         `json:"effective_from"`
	EffectiveTo   *string         `json:"effective_to"`
	Active        *bool           `json:"active"`
}

// parseDate 'YYYY-MM-DD' → pgtype.Date；nil/空/非法 → 零值（NULL）。
func parseDate(s *string) pgtype.Date {
	if s == nil || *s == "" {
		return pgtype.Date{}
	}
	t, err := time.Parse("2006-01-02", *s)
	if err != nil {
		return pgtype.Date{}
	}
	return pgtype.Date{Time: t, Valid: true}
}

// UpsertDictItem 新建/按 (item_code, 生效期) 更新条目。
func (h *Handler) UpsertDictItem(c *gin.Context) {
	d := auth.DomainFrom(c)
	dictID, _ := strconv.ParseInt(c.Param("dictId"), 10, 64)
	if _, err := h.q.GetDict(c, store.GetDictParams{ID: dictID, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "字典不存在")
		return
	}
	var b dictItemBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	sortNo := int32(0)
	if b.SortNo != nil {
		sortNo = *b.SortNo
	}
	active := true
	if b.Active != nil {
		active = *b.Active
	}
	r, err := h.q.UpsertDictItem(c, store.UpsertDictItemParams{
		DictID: dictID, TenantID: d.TenantID,
		ItemCode: b.ItemCode, ItemLabel: b.ItemLabel,
		ParentID: b.ParentID, ExtJson: jsonOrNil(b.Ext), I18nJson: jsonOrNil(b.I18n),
		SortNo: sortNo, Active: active,
		EffectiveFrom: parseDate(b.EffectiveFrom), EffectiveTo: parseDate(b.EffectiveTo),
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "条目冲突（同码同生效期已存在）或保存失败")
		return
	}
	httpx.WriteOK(c, ToAPIDictItem(r))
}

// UpdateDictItem 编辑条目（同 upsert 语义：item_code/生效期构成身份）。
func (h *Handler) UpdateDictItem(c *gin.Context) {
	h.UpsertDictItem(c)
}

// DeleteDictItem 硬删条目（叶子；被树形引用由 FK ON DELETE 行为约束不到——引用方 parent_id 无 FK，
// 删除后引用其作为父级的条目 parent 悬空为浅孤儿，前端渲染时归一到根，可接受）。
func (h *Handler) DeleteDictItem(c *gin.Context) {
	d := auth.DomainFrom(c)
	dictID, _ := strconv.ParseInt(c.Param("dictId"), 10, 64)
	itemID, _ := strconv.ParseInt(c.Param("itemId"), 10, 64)
	n, err := h.q.DeleteDictItem(c, store.DeleteDictItemParams{ID: itemID, DictID: dictID, TenantID: d.TenantID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "条目不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": itemID, "deleted": true})
}

// GetDictByCode 全员只读：业务下拉数据源（active + 生效期内条目）。
func (h *Handler) GetDictByCode(c *gin.Context) {
	d := auth.DomainFrom(c)
	r, err := h.q.GetDictByCode(c, store.GetDictByCodeParams{TenantID: d.TenantID, Code: c.Param("code")})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "字典不存在")
		return
	}
	items, _ := h.q.ListActiveDictItems(c, store.ListActiveDictItemsParams{DictID: r.ID, TenantID: d.TenantID})
	out := ToAPIDict(r)
	out["items"] = dictItemList(items)
	httpx.WriteOK(c, out)
}

func dictItemList(rows []store.DictItem) []map[string]any {
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIDictItem(r))
	}
	return list
}

// jsonOrNil 空 RawMessage → nil。
func jsonOrNil(b json.RawMessage) []byte {
	if len(b) == 0 {
		return nil
	}
	return b
}
