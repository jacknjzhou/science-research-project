package archive

import (
	"testing"
	"time"

	ostore "github.com/eplugger/ark/internal/modules/archive/store"
)

// 无库契约测试：构造内存 ostore model → ToAPI* mapper → 断言契约键存在/敏感字段不外泄。

func sampleDocForContract() ostore.Document {
	code := "DOC-2024-0001"
	dt := "pdf"
	size := int64(2048)
	bucket := "ark-docs"
	objectKey := "tenant/1/x.pdf"
	sum := "deadbeef"
	src := "O"
	srcID := int64(7)
	up := int64(100)
	upAt := time.Now()
	return ostore.Document{
		ID: 1, Code: &code, TenantID: 1, Status: "STORED", Name: "结题报告",
		DocType: &dt, SizeBytes: &size, Bucket: &bucket, ObjectKey: &objectKey,
		ChecksumSha256: &sum, UploaderID: &up, UploadedAt: &upAt,
		SourceModule: &src, SourceID: &srcID, SecurityLevel: "INTERNAL",
		CreatedAt: time.Now(),
		// text_content 仅供全文检索内部使用，mapper 绝不应外泄。
		TextContent: strPtrOrNil("卷积神经网络 医学图像 分割"),
	}
}

func sampleArchiveForContract() ostore.Archive {
	code := "ARC-2024-0001"
	submitter := int64(100)
	sAt := time.Now()
	return ostore.Archive{
		ID: 1, Code: &code, TenantID: 1, Status: "ARCHIVED", Title: "某项目科研档案",
		ArchiveType: "PROJECT", SourceModule: strPtrOrNil("E"), SourceCode: strPtrOrNil("PRJ-2024-0001"),
		RetentionYears: 10, SecurityLevel: "INTERNAL", CreatorID: 100,
		SubmitterID: &submitter, SubmitAt: &sAt, CreatedAt: time.Now(), UpdatedAt: time.Now(),
	}
}

func sampleCheckForContract() ostore.ArchiveCheck {
	checker := int64(100)
	checkedAt := time.Now()
	return ostore.ArchiveCheck{
		ID: 1, TenantID: 1, ArchiveID: 1, CheckType: "INTEGRITY", Result: "PASS",
		Detail: []byte(`{"required_total":3,"required_filled":3}`),
		CheckedAt: &checkedAt, CheckerID: &checker,
	}
}

func TestContractDocumentMapper(t *testing.T) {
	m := ToAPIDocument(sampleDocForContract())
	if _, leaked := m["text_content"]; leaked {
		t.Fatalf("ToAPIDocument 不得输出 text_content")
	}
	for _, k := range []string{"checksum_sha256", "object_key", "status", "bucket", "size_bytes"} {
		if _, ok := m[k]; !ok {
			t.Fatalf("ToAPIDocument 缺契约键 %q", k)
		}
	}
	if m["checksum_sha256"] != "deadbeef" {
		t.Fatalf("checksum_sha256 期望 deadbeef，实得 %v", m["checksum_sha256"])
	}
}

func TestContractArchiveMapper(t *testing.T) {
	m := ToAPIArchive(sampleArchiveForContract())
	for _, k := range []string{"status", "archive_type", "retention_years", "title", "source_code"} {
		if _, ok := m[k]; !ok {
			t.Fatalf("ToAPIArchive 缺契约键 %q", k)
		}
	}
	if m["status"] != "ARCHIVED" || m["archive_type"] != "PROJECT" {
		t.Fatalf("ToAPIArchive 值不符: %v", m)
	}
}

func TestContractArchiveCheckMapper(t *testing.T) {
	m := ToAPIArchiveCheck(sampleCheckForContract())
	for _, k := range []string{"check_type", "result", "detail"} {
		if _, ok := m[k]; !ok {
			t.Fatalf("ToAPIArchiveCheck 缺契约键 %q", k)
		}
	}
	// detail 应被反序列化为对象（map），而非原始 []byte。
	detail, ok := m["detail"].(map[string]any)
	if !ok {
		t.Fatalf("detail 应为 JSON 对象，实得 %T", m["detail"])
	}
	if detail["required_total"] != float64(3) {
		t.Fatalf("detail.required_total 期望 3，实得 %v", detail["required_total"])
	}
}
