// Package archive 域 O（科研档案管理）HTTP 层。mapper.go 把 sqlc 生成的 ostore model
// 转成契约 snake_case map[string]any，供 handler 直写 httpx.WriteOK。
//
// 助手函数逐字拷自 project/mapper.go（两包各自私有，勿跨包引用）：
// fmtTime / fmtTimePtr / optStr / optInt64Ptr / jsonToAny。
// O 域无 NUMERIC 金额列，故不引 numDec/numStrOrNil。
package archive

import (
	"encoding/json"
	"time"

	ostore "github.com/eplugger/ark/internal/modules/archive/store"
)

// ---------- 通用助手（与 E/M 域同款） ----------

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

func optStr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func optInt64Ptr(v *int64) any {
	if v == nil {
		return nil
	}
	return *v
}

// jsonToAny：jsonb []byte → 反序列化 any；空/非法 → fallback。
func jsonToAny(b []byte, fallback any) any {
	if len(b) == 0 {
		return fallback
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return fallback
	}
	return v
}

// ---------- O 域 mapper ----------

// ToAPIDocument 文档元数据视图。注意：**不输出 text_content**（仅全文检索内部用，
// 检索命中片段经 SearchDocuments 的 snippet 字段单独回传）。
func ToAPIDocument(r ostore.Document) map[string]any {
	return map[string]any{
		"id":              r.ID,
		"code":            optStr(r.Code),
		"tenant_id":       r.TenantID,
		"status":          r.Status,
		"name":            r.Name,
		"doc_type":        optStr(r.DocType),
		"size_bytes":      optInt64Ptr(r.SizeBytes),
		"bucket":          optStr(r.Bucket),
		"object_key":      optStr(r.ObjectKey),
		"checksum_sha256": optStr(r.ChecksumSha256),
		"source_module":   optStr(r.SourceModule),
		"source_id":       optInt64Ptr(r.SourceID),
		"security_level":  r.SecurityLevel,
		"uploaded_at":     fmtTimePtr(r.UploadedAt),
		"created_at":      fmtTime(r.CreatedAt),
	}
}

func ToAPIArchive(r ostore.Archive) map[string]any {
	return map[string]any{
		"id":              r.ID,
		"code":            optStr(r.Code),
		"title":           r.Title,
		"archive_type":    r.ArchiveType,
		"source_module":   optStr(r.SourceModule),
		"source_id":       optInt64Ptr(r.SourceID),
		"source_code":     optStr(r.SourceCode),
		"owner_dept_id":   optInt64Ptr(r.OwnerDeptID),
		"retention_years": r.RetentionYears,
		"status":          r.Status,
		"security_level":  r.SecurityLevel,
		"submitter_id":    optInt64Ptr(r.SubmitterID),
		"submit_at":       fmtTimePtr(r.SubmitAt),
		"archivist_id":    optInt64Ptr(r.ArchivistID),
		"filed_at":        fmtTimePtr(r.FiledAt),
		"created_at":      fmtTime(r.CreatedAt),
		"updated_at":      fmtTime(r.UpdatedAt),
	}
}

func ToAPIArchiveItem(r ostore.ArchiveItem) map[string]any {
	return map[string]any{
		"id":            r.ID,
		"archive_id":    r.ArchiveID,
		"category_code": r.CategoryCode,
		"category_name": optStr(r.CategoryName),
		"required":      r.Required,
		"doc_id":        optInt64Ptr(r.DocID),
		"status":        r.Status,
		"sort_no":       r.SortNo,
	}
}

func ToAPIArchiveCheck(r ostore.ArchiveCheck) map[string]any {
	return map[string]any{
		"id":         r.ID,
		"archive_id": r.ArchiveID,
		"check_type": r.CheckType,
		"result":     r.Result,
		"detail":     jsonToAny(r.Detail, map[string]any{}),
		"checked_at": fmtTimePtr(r.CheckedAt),
		"checker_id": optInt64Ptr(r.CheckerID),
	}
}

func ToAPIBorrow(r ostore.Borrow) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"archive_id":       r.ArchiveID,
		"archive_title":    nil, // 案卷标题需 join，本轮 SELECT * 不带；前端可另取（可空契约）
		"borrower_user_id": r.BorrowerUserID,
		"purpose":          optStr(r.Purpose),
		"borrow_type":      r.BorrowType,
		"status":           r.Status,
		"approved_by":      optInt64Ptr(r.ApprovedBy),
		"approved_at":      fmtTimePtr(r.ApprovedAt),
		"due_at":           fmtTimePtr(r.DueAt),
		"returned_at":      fmtTimePtr(r.ReturnedAt),
		"created_at":       fmtTime(r.CreatedAt),
	}
}
