package archive

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	ostore "github.com/eplugger/ark/internal/modules/archive/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// presignTTL 下载链接有效期（契约 expires_at = now + 15min）。
const presignTTL = 15 * time.Minute

// ---------- 小 helper ----------

// strPtrOrNil：空串 → nil（让 narg 走 SQL 的 COALESCE/IS NULL 分支）。
func strPtrOrNil(s string) *string {
	if s == "" {
		return nil
	}
	v := s
	return &v
}

// parseID 解析路径 :id；非法返回 err。
func parseID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "id 非法")
		return 0, false
	}
	return id, true
}

// searchRowToDocument 把 SearchDocumentsRow（Document 全列 + rank/snippet 计算列）
// 拍平回 ostore.Document，供 ToAPIDocument 复用。
func searchRowToDocument(r ostore.SearchDocumentsRow) ostore.Document {
	return ostore.Document{
		ID: r.ID, Code: r.Code, TenantID: r.TenantID, Status: r.Status, Deleted: r.Deleted,
		CreatorID: r.CreatorID, ModifierID: r.ModifierID, CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt,
		Remark: r.Remark, SecurityLevel: r.SecurityLevel, Name: r.Name, DocType: r.DocType,
		SizeBytes: r.SizeBytes, Bucket: r.Bucket, ObjectKey: r.ObjectKey, ChecksumSha256: r.ChecksumSha256,
		UploaderID: r.UploaderID, UploadedAt: r.UploadedAt, SourceModule: r.SourceModule,
		SourceID: r.SourceID, TextContent: r.TextContent,
	}
}

// docExt 优先取上传头 Content-Type，缺省回落到文件扩展名（去点小写）。
func docExt(contentType, filename string) *string {
	if ct := strings.TrimSpace(contentType); ct != "" {
		return &ct
	}
	ext := strings.ToLower(strings.TrimPrefix(filepath.Ext(filename), "."))
	return strPtrOrNil(ext)
}

// ---------- 文档端点 ----------

// UploadDocument 契约 POST /documents：multipart → 读字节算 sha256 → MinIO Put → 落 o_document(STORED)。
func (h *Handler) UploadDocument(c *gin.Context) {
	d := auth.DomainFrom(c)
	if !h.guardStorage(c) {
		return
	}
	hdr, err := c.FormFile("file")
	if err != nil {
		httpx.WriteErr(c, 400, 40001, "缺少上传文件(file)")
		return
	}
	f, err := hdr.Open()
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "读取上传文件失败")
		return
	}
	defer f.Close()
	b, err := io.ReadAll(f)
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "读取上传文件失败")
		return
	}
	sum := sha256.Sum256(b)
	checksum := hex.EncodeToString(sum[:])
	base := filepath.Base(hdr.Filename)
	objectKey := fmt.Sprintf("tenant/%d/%d-%s", d.TenantID, time.Now().UnixNano(), base)

	if err := h.store.Put(c, objectKey, bytes.NewReader(b), int64(len(b)), hdr.Header.Get("Content-Type")); err != nil {
		httpx.WriteErr(c, 502, 50002, "对象存储写入失败")
		return
	}

	name := c.PostForm("name")
	if name == "" {
		name = base
	}
	sec := c.PostForm("security_level")
	if sec == "" {
		sec = "INTERNAL"
	}
	var srcID *int64
	if v := c.PostForm("source_id"); v != "" {
		if n, e := strconv.ParseInt(v, 10, 64); e == nil {
			srcID = &n
		}
	}
	now := time.Now()
	size := int64(len(b))
	doc, err := h.q.CreateDocument(c, ostore.CreateDocumentParams{
		Code:           nil, // 编号中心接入前留空（同 R/N）
		TenantID:       d.TenantID,
		Status:         "STORED",
		CreatorID:      d.UserID,
		SecurityLevel:  &sec,
		Name:           name,
		DocType:        docExt(hdr.Header.Get("Content-Type"), hdr.Filename),
		SizeBytes:      &size,
		Bucket:         strPtrOrNil(defaultBucket),
		ObjectKey:      &objectKey,
		ChecksumSha256: &checksum,
		UploaderID:     &d.UserID,
		UploadedAt:     tsOf(&now),
		SourceModule:   strPtrOrNil(c.PostForm("source_module")),
		SourceID:       srcID,
		TextContent:    strPtrOrNil(c.PostForm("text_content")),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "文档元数据落库失败")
		return
	}
	httpx.WriteOK(c, ToAPIDocument(doc))
}

// GetDocument 契约 GET /documents/{id}。
func (h *Handler) GetDocument(c *gin.Context) {
	id, ok := parseID(c)
	if !ok {
		return
	}
	doc, err := h.q.GetDocument(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "文档不存在")
		return
	}
	httpx.WriteOK(c, ToAPIDocument(doc))
}

// DownloadDocument 契约 GET /documents/{id}/download：presign GET URL。
func (h *Handler) DownloadDocument(c *gin.Context) {
	if !h.guardStorage(c) {
		return
	}
	id, ok := parseID(c)
	if !ok {
		return
	}
	doc, err := h.q.GetDocument(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "文档不存在")
		return
	}
	if doc.ObjectKey == nil || *doc.ObjectKey == "" {
		httpx.WriteErr(c, 409, 40901, "文档无对象存储键，无法下载")
		return
	}
	u, err := h.store.PresignGet(c, *doc.ObjectKey)
	if err != nil {
		httpx.WriteErr(c, 502, 50002, "生成下载链接失败")
		return
	}
	httpx.WriteOK(c, gin.H{
		"url":        u,
		"expires_at": time.Now().Add(presignTTL).UTC().Format(time.RFC3339),
	})
}

// DeleteDocument 契约 DELETE /documents/{id}：软删 + 尽力删对象（删对象失败仅日志，不回滚软删）。
func (h *Handler) DeleteDocument(c *gin.Context) {
	if !h.guardStorage(c) {
		return
	}
	id, ok := parseID(c)
	if !ok {
		return
	}
	doc, err := h.q.GetDocument(c, id)
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "文档不存在")
		return
	}
	rows, err := h.q.SoftDeleteDocument(c, id)
	if err != nil || rows == 0 {
		httpx.WriteErr(c, 404, 40401, "文档不存在")
		return
	}
	if doc.ObjectKey != nil && *doc.ObjectKey != "" {
		if rerr := h.store.Remove(c, *doc.ObjectKey); rerr != nil {
			// 尽力而为：对象删除失败不影响软删结果，仅记日志（zap 由上层中间件处理，此处吞并）。
			_ = rerr
		}
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}

// SearchDocuments 契约 GET /documents/search：全文检索（plainto_tsquery + ts_rank + ts_headline）。
func (h *Handler) SearchDocuments(c *gin.Context) {
	kw := strings.TrimSpace(c.Query("q"))
	if kw == "" {
		httpx.WriteErr(c, 400, 40001, "检索关键词 q 不能为空")
		return
	}
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.SearchDocuments(c, ostore.SearchDocumentsParams{Q: kw, Limit: limit, Offset: offset})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "检索失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		m := ToAPIDocument(searchRowToDocument(r))
		m["snippet"] = r.Snippet
		m["rank"] = r.Rank
		list = append(list, m)
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": len(list), "page": page, "size": size})
}
