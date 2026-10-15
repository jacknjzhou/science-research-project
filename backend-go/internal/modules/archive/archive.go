package archive

import (
	"strconv"

	ostore "github.com/eplugger/ark/internal/modules/archive/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// ---------- 请求体 ----------

type archiveCreateBody struct {
	Title          string  `json:"title" binding:"required"`
	ArchiveType    *string `json:"archive_type"`
	SourceModule   *string `json:"source_module"`
	SourceID       *int64  `json:"source_id"`
	SourceCode     *string `json:"source_code"`
	OwnerDeptID    *int64  `json:"owner_dept_id"`
	RetentionYears *int32  `json:"retention_years"`
	SecurityLevel  *string `json:"security_level"`
}

type archiveUpdateBody struct {
	Title          string  `json:"title"`
	ArchiveType    *string `json:"archive_type"`
	RetentionYears *int32  `json:"retention_years"`
	SecurityLevel  *string `json:"security_level"`
}

type itemAddBody struct {
	CategoryCode string  `json:"category_code" binding:"required"`
	CategoryName *string `json:"category_name"`
	Required     *bool   `json:"required"`
	SortNo       *int32  `json:"sort_no"`
	DocID        *int64  `json:"doc_id"`
}

type itemFillBody struct {
	DocID int64 `json:"doc_id" binding:"required"`
}

type ingestBody struct {
	CategoryCode string  `json:"category_code" binding:"required"`
	CategoryName *string `json:"category_name"`
	DocID        *int64  `json:"doc_id"`
	SourceModule *string `json:"source_module"`
	SourceID     *int64  `json:"source_id"`
}

func parseArchiveID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "id 非法")
		return 0, false
	}
	return id, true
}

func parseItemID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("itemId"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "itemId 非法")
		return 0, false
	}
	return id, true
}

// ---------- 案卷 CRUD ----------

// ListArchives 契约 GET /archives：状态/门类/关键词筛选分页。
func (h *Handler) ListArchives(c *gin.Context) {
	page, size, limit, offset := pageArgs(c)
	status := optQuery(c, "status")
	atype := optQuery(c, "archive_type")
	kw := optQuery(c, "kw")
	rows, err := h.q.ListArchives(c, ostore.ListArchivesParams{
		Status: status, ArchiveType: atype, Kw: kw, Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountArchives(c, ostore.CountArchivesParams{
		Status: status, ArchiveType: atype, Kw: kw,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIArchive(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetArchive 契约 GET /archives/{id}。
func (h *Handler) GetArchive(c *gin.Context) {
	id, ok := parseArchiveID(c)
	if !ok {
		return
	}
	r, err := h.q.GetArchive(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "案卷不存在")
		return
	}
	httpx.WriteOK(c, ToAPIArchive(r))
}

// CreateArchive 契约 POST /archives：分配编号留空（同 R/N），落 PENDING_SUBMIT。
func (h *Handler) CreateArchive(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b archiveCreateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	r, err := h.q.CreateArchive(c, ostore.CreateArchiveParams{
		Code: nil, TenantID: d.TenantID, CreatorID: d.UserID,
		SecurityLevel: b.SecurityLevel, Title: b.Title, ArchiveType: b.ArchiveType,
		SourceModule: b.SourceModule, SourceID: b.SourceID, SourceCode: b.SourceCode,
		OwnerDeptID: b.OwnerDeptID, RetentionYears: b.RetentionYears,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, ToAPIArchive(r))
}

// UpdateArchive 契约 PUT /archives/{id}：仅 PENDING_SUBMIT/REJECTED 可编辑（execrows 0 行→40901/40401）。
func (h *Handler) UpdateArchive(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := parseArchiveID(c)
	if !ok {
		return
	}
	cur, err := h.q.GetArchive(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "案卷不存在")
		return
	}
	var b archiveUpdateBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	// 合并：body 缺省回落现有值（SQL 四字段皆必填）。
	title := cur.Title
	if b.Title != "" {
		title = b.Title
	}
	atype := cur.ArchiveType
	if b.ArchiveType != nil && *b.ArchiveType != "" {
		atype = *b.ArchiveType
	}
	sec := cur.SecurityLevel
	if b.SecurityLevel != nil && *b.SecurityLevel != "" {
		sec = *b.SecurityLevel
	}
	ret := cur.RetentionYears
	if b.RetentionYears != nil {
		ret = *b.RetentionYears
	}
	rows, err := h.q.UpdateArchive(c, ostore.UpdateArchiveParams{
		Title: title, ArchiveType: atype, RetentionYears: ret, SecurityLevel: sec,
		ModifierID: d.UserID, ID: id,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "更新失败")
		return
	}
	if rows == 0 {
		// 存在但态不匹配（GetArchive 已成功→存在）→ 状态不允许编辑
		httpx.WriteErr(c, 409, 40901, "仅 PENDING_SUBMIT/REJECTED 可编辑")
		return
	}
	r, _ := h.q.GetArchive(c, id)
	httpx.WriteOK(c, ToAPIArchive(r))
}

// DeleteArchive 契约 DELETE /archives/{id}：软删，仅 PENDING_SUBMIT/REJECTED。
func (h *Handler) DeleteArchive(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := parseArchiveID(c)
	if !ok {
		return
	}
	if _, err := h.q.GetArchive(c, id); err != nil {
		httpx.WriteErr(c, 404, 40401, "案卷不存在")
		return
	}
	rows, err := h.q.SoftDeleteArchive(c, ostore.SoftDeleteArchiveParams{ID: id, ModifierID: d.UserID})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "删除失败")
		return
	}
	if rows == 0 {
		httpx.WriteErr(c, 409, 40901, "仅 PENDING_SUBMIT/REJECTED 可删除")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}

// ---------- 门类清单 items ----------

// ListItems 契约 GET /archives/{id}/items。
func (h *Handler) ListItems(c *gin.Context) {
	id, ok := parseArchiveID(c)
	if !ok {
		return
	}
	rows, err := h.q.ListItems(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIArchiveItem(r))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

// AddItem 契约 POST /archives/{id}/items：required 缺 doc→MISSING，带 doc→FILLED（SQL CASE 定）。
func (h *Handler) AddItem(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := parseArchiveID(c)
	if !ok {
		return
	}
	if _, err := h.q.GetArchive(c, id); err != nil {
		httpx.WriteErr(c, 404, 40401, "案卷不存在")
		return
	}
	var b itemAddBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	// 带 doc 时须为已存在且 STORED 的文档（可空 doc_id → MISSING）。
	if b.DocID != nil {
		if _, err := h.q.GetDocument(c, *b.DocID); err != nil {
			httpx.WriteErr(c, 404, 40401, "文档不存在")
			return
		}
	}
	r, err := h.q.CreateItem(c, ostore.CreateItemParams{
		TenantID: d.TenantID, ArchiveID: id, CategoryCode: b.CategoryCode,
		CategoryName: b.CategoryName, Required: b.Required, DocID: b.DocID, SortNo: b.SortNo,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "新增条目失败")
		return
	}
	httpx.WriteOK(c, ToAPIArchiveItem(r))
}

// FillItem 契约 PUT /archives/{id}/items/{itemId}：doc_id 非空且文档须 STORED。
func (h *Handler) FillItem(c *gin.Context) {
	archiveID, ok := parseArchiveID(c)
	if !ok {
		return
	}
	itemID, ok := parseItemID(c)
	if !ok {
		return
	}
	var b itemFillBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	doc, err := h.q.GetDocument(c, b.DocID)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "文档不存在")
		return
	}
	if doc.Status != "STORED" {
		httpx.WriteErr(c, 400, 40001, "文档非 STORED，不可挂载")
		return
	}
	if _, err := h.q.GetItem(c, ostore.GetItemParams{ID: itemID, ArchiveID: archiveID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "条目不存在")
		return
	}
	rows, err := h.q.FillItem(c, ostore.FillItemParams{DocID: b.DocID, ID: itemID, ArchiveID: archiveID})
	if err != nil || rows == 0 {
		httpx.WriteErr(c, 404, 40401, "条目不存在")
		return
	}
	r, _ := h.q.GetItem(c, ostore.GetItemParams{ID: itemID, ArchiveID: archiveID})
	httpx.WriteOK(c, ToAPIArchiveItem(r))
}

// DeleteItem 契约 DELETE /archives/{id}/items/{itemId}。
func (h *Handler) DeleteItem(c *gin.Context) {
	archiveID, ok := parseArchiveID(c)
	if !ok {
		return
	}
	itemID, ok := parseItemID(c)
	if !ok {
		return
	}
	rows, err := h.q.DeleteItem(c, ostore.DeleteItemParams{ID: itemID, ArchiveID: archiveID})
	if err != nil || rows == 0 {
		httpx.WriteErr(c, 404, 40401, "条目不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": itemID, "deleted": true})
}

// IngestSource 契约 POST /archives/{id}/ingest：从来源对象拉取文档建清单条目（等价带 doc 的 AddItem）。
// 本轮不接 E 域文档直读，直接引用已上传的 o_document（doc_id）挂入案卷门类。
func (h *Handler) IngestSource(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := parseArchiveID(c)
	if !ok {
		return
	}
	if _, err := h.q.GetArchive(c, id); err != nil {
		httpx.WriteErr(c, 404, 40401, "案卷不存在")
		return
	}
	var b ingestBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if b.DocID != nil {
		if _, err := h.q.GetDocument(c, *b.DocID); err != nil {
			httpx.WriteErr(c, 404, 40401, "来源文档不存在")
			return
		}
	}
	r, err := h.q.CreateItem(c, ostore.CreateItemParams{
		TenantID: d.TenantID, ArchiveID: id, CategoryCode: b.CategoryCode,
		CategoryName: b.CategoryName, DocID: b.DocID,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "摄取条目失败")
		return
	}
	httpx.WriteOK(c, ToAPIArchiveItem(r))
}
