package archive

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/storage"
	"github.com/gin-gonic/gin"
)

// injectDomain：测试内手工塞数据域（tenant=1/user=100，与 seed 约定一致）。
// 不经 Casbin 中间件——角色门控由 policy 层单测（caps_archive_test.go）覆盖，此处只验业务链路。
func injectDomain(c *gin.Context) {
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxUserID, int64(100))
	c.Next()
}

// newArchiveEngine：DB-gated。缺 ARK_TEST_DATABASE_URL → SKIP。注入内存 Fake storage，
// 使上传/下载/删除端点无需 MinIO 即可跑通（真实 MinIO 集成另用 ARK_S3_ENDPOINT 门控）。
func newArchiveEngine(t *testing.T) *gin.Engine {
	t.Helper()
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectDomain)
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool, storage.NewFake()))
	return e
}

// envData 解包统一信封：HTTP 200 + 业务码 0，返回 data map。
func envData(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int             `json:"code"`
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
		t.Fatalf("envelope decode 失败: %v body=%s", err, w.Body.String())
	}
	if env.Code != 0 {
		t.Fatalf("业务码非 0: %s", w.Body.String())
	}
	var m map[string]any
	if err := json.Unmarshal(env.Data, &m); err != nil {
		t.Fatalf("data decode 失败: %v", err)
	}
	return m
}

func doJSON(t *testing.T, e *gin.Engine, method, path, body string) map[string]any {
	t.Helper()
	w := httptest.NewRecorder()
	var r io.Reader
	if body != "" {
		r = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, r)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	e.ServeHTTP(w, req)
	return envData(t, w)
}

// uploadDoc multipart 上传已知字节，返回 (id, checksum_sha256, object_key)。
func uploadDoc(t *testing.T, e *gin.Engine, filename string, content []byte) (int64, string, string) {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := fw.Write(content); err != nil {
		t.Fatal(err)
	}
	if err := mw.WriteField("name", "e2e.pdf"); err != nil {
		t.Fatal(err)
	}
	if err := mw.Close(); err != nil {
		t.Fatal(err)
	}
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/documents", &buf)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	e.ServeHTTP(w, req)
	m := envData(t, w)
	sum, _ := m["checksum_sha256"].(string)
	key, _ := m["object_key"].(string)
	return toInt64(m["id"]), sum, key
}

func checkArchive(t *testing.T, e *gin.Engine, archiveID int64) map[string]any {
	t.Helper()
	return doJSON(t, e, "POST", "/api/v1/archives/"+strconv.FormatInt(archiveID, 10)+"/check", `{}`)
}

// integrityResult 从 check data.list 里挑 INTEGRITY 的 result。
func integrityResult(chk map[string]any) string {
	list, _ := chk["list"].([]any)
	for _, it := range list {
		m, _ := it.(map[string]any)
		if ct, _ := m["check_type"].(string); ct == "INTEGRITY" {
			s, _ := m["result"].(string)
			return s
		}
	}
	return ""
}

func toInt64(v any) int64 {
	if f, ok := v.(float64); ok {
		return int64(f)
	}
	return 0
}

func TestArchiveE2E(t *testing.T) {
	e := newArchiveEngine(t)

	// 1) 上传已知字节 → 断言落库 checksum 与本地 sha256hex 一致。
	content := []byte("ark-o-e2e-payload-")
	expectedSum := sha256hex(string(content))
	docID, docSum, objectKey := uploadDoc(t, e, "结题报告.pdf", content)
	if docSum != expectedSum {
		t.Fatalf("落库 checksum 不符: 期望 %s 实得 %s", expectedSum, docSum)
	}
	if objectKey == "" {
		t.Fatalf("object_key 为空")
	}

	// 2) 下载得非空 presign url。
	d := doJSON(t, e, "GET", "/api/v1/documents/"+strconv.FormatInt(docID, 10)+"/download", "")
	if u, _ := d["url"].(string); u == "" {
		t.Fatalf("download url 为空: %v", d)
	}

	// 3) 建案卷 + 提交。
	a := doJSON(t, e, "POST", "/api/v1/archives",
		`{"title":"E2E 科研档案","archive_type":"PROJECT","source_module":"E","source_code":"PRJ-2024-0001"}`)
	archiveID := toInt64(a["id"])
	if archiveID == 0 {
		t.Fatal("建案卷未返回 id")
	}
	doJSON(t, e, "POST", "/api/v1/archives/"+strconv.FormatInt(archiveID, 10)+"/submit", `{}`)

	// 4) 3 个必填门类：前 2 件挂同一文档（FILLED），第 3 件留空（MISSING）。
	base := "/api/v1/archives/" + strconv.FormatInt(archiveID, 10) + "/items"
	docIDStr := strconv.FormatInt(docID, 10)
	doJSON(t, e, "POST", base, `{"category_code":"C1","required":true,"doc_id":`+docIDStr+`}`)
	doJSON(t, e, "POST", base, `{"category_code":"C2","required":true,"doc_id":`+docIDStr+`}`)
	itemC := doJSON(t, e, "POST", base, `{"category_code":"C3","required":true}`)
	missingItemID := toInt64(itemC["id"])
	if missingItemID == 0 {
		t.Fatal("第 3 门类未返回 id")
	}

	// 5) 检测 → INTEGRITY=FAIL、整体未通过、状态 REJECTED。
	chk := checkArchive(t, e, archiveID)
	if passed, _ := chk["passed"].(bool); passed {
		t.Fatalf("缺件应未通过，实得 passed=%v", chk["passed"])
	}
	if got := integrityResult(chk); got != "FAIL" {
		t.Fatalf("期望 INTEGRITY=FAIL，实得 %q", got)
	}
	g := doJSON(t, e, "GET", "/api/v1/archives/"+strconv.FormatInt(archiveID, 10), "")
	if st, _ := g["status"].(string); st != "REJECTED" {
		t.Fatalf("检测未过应 REJECTED，实得 %v", g["status"])
	}

	// 6) 补齐第 3 件（复用同一文档保证 checksum 命中）→ 再提交 → 检测 PASSED。
	doJSON(t, e, "PUT", base+"/"+strconv.FormatInt(missingItemID, 10), `{"doc_id":`+docIDStr+`}`)
	doJSON(t, e, "POST", "/api/v1/archives/"+strconv.FormatInt(archiveID, 10)+"/submit", `{}`) // REJECTED→SUBMITTED
	chk2 := checkArchive(t, e, archiveID)
	if passed, _ := chk2["passed"].(bool); !passed {
		t.Fatalf("补齐后应全部通过: %v", chk2)
	}
	if got := integrityResult(chk2); got != "PASS" {
		t.Fatalf("期望 INTEGRITY=PASS，实得 %q", got)
	}
	g = doJSON(t, e, "GET", "/api/v1/archives/"+strconv.FormatInt(archiveID, 10), "")
	if st, _ := g["status"].(string); st != "PASSED" {
		t.Fatalf("检测通过应 PASSED，实得 %v", g["status"])
	}

	// 7) 入库 → ARCHIVED。
	f := doJSON(t, e, "POST", "/api/v1/archives/"+strconv.FormatInt(archiveID, 10)+"/file", `{}`)
	if st, _ := f["status"].(string); st != "ARCHIVED" {
		t.Fatalf("应 ARCHIVED，实得 %v", f["status"])
	}

	// 8) 借阅：申请 → 审批 → 归还。
	b := doJSON(t, e, "POST", "/api/v1/borrows",
		`{"archive_id":`+strconv.FormatInt(archiveID, 10)+`,"purpose":"E2E 借阅","borrow_type":"READ"}`)
	borrowID := toInt64(b["id"])
	if borrowID == 0 {
		t.Fatal("建借阅未返回 id")
	}
	if st, _ := b["status"].(string); st != "SUBMITTED" {
		t.Fatalf("借阅应 SUBMITTED，实得 %v", b["status"])
	}
	bp := "/api/v1/borrows/" + strconv.FormatInt(borrowID, 10)
	ap := doJSON(t, e, "POST", bp+"/approve", `{}`)
	if st, _ := ap["status"].(string); st != "APPROVED" {
		t.Fatalf("应 APPROVED，实得 %v", ap["status"])
	}
	rp := doJSON(t, e, "POST", bp+"/return", `{}`)
	if st, _ := rp["status"].(string); st != "RETURNED" {
		t.Fatalf("应 RETURNED，实得 %v", rp["status"])
	}
}
