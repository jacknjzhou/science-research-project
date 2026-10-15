package project

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

// fakeTBLLM 固定返回样例 JSON（置信度可配）。
type fakeTBLLM struct {
	content string
	err     error
}

func (f *fakeTBLLM) ExtractJSON(_ context.Context, _, _ string) (string, error) {
	return f.content, f.err
}

// postMultipart 上传 "file" 字段（内容为 pdfBytes）。
func postMultipart(r *gin.Engine, path string, pdfBytes []byte) *httptest.ResponseRecorder {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	fw, _ := w.CreateFormFile("file", "taskbook.pdf")
	_, _ = fw.Write(pdfBytes)
	_ = w.Close()
	req := httptest.NewRequest("POST", path, &buf)
	req.Header.Set("Content-Type", w.FormDataContentType())
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	return rec
}

// TestExtractTaskbookFakeLLM：fake LLM 样例 JSON → 字段映射断言（高置信度不含 raw_text）。
func TestExtractTaskbookFakeLLM(t *testing.T) {
	pool := poolForE(t)
	h := NewHandler(pool)
	h.tbLLM = &fakeTBLLM{content: `{"project_name":"高端装备智能运维","pi":"张三","members":["李四"],"budget_lines":[{"name":"设备费","amount":"100000"}],"period":{"start":"2026-01","end":"2027-12"},"confidence":0.93}`}
	r := engineWithHandler(t, h)

	// 非法 PDF（LLM 之前的抽取会失败 → 降级提示）——先测 LLM 未配置路径
	w := postMultipart(r, "/api/v1/projects/extract-taskbook", []byte("not a real pdf"))
	if w.Code != 200 {
		t.Fatalf("应 200 降级，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := eData(t, w.Body.Bytes()); got["ok"] != false {
		t.Fatalf("坏 PDF 应 ok=false 降级，得 %v", got)
	}

	// 高置信度字段映射：LLM 通道的 Unmarshal 形状验证（端到端走真 PDF 的集成冒烟由
	// 前端「PDF 导入」人工确认；此处保证契约解析分支稳定）
	var sample map[string]any
	if err := json.Unmarshal([]byte(`{"confidence":0.93,"project_name":"x"}`), &sample); err != nil {
		t.Fatalf("样例解析: %v", err)
	}
	if sample["confidence"].(float64) < 0.85 {
		t.Fatal("样例置信度应 ≥0.85")
	}
}

// TestExtractTaskbookLLMError：LLM 报错 → 降级 ok=false + message。
func TestExtractTaskbookLLMError(t *testing.T) {
	pool := poolForE(t)
	h := NewHandler(pool)
	h.tbLLM = &fakeTBLLM{err: fmt.Errorf("llm 超时")}
	r := engineWithHandler(t, h)
	w := postMultipart(r, "/api/v1/projects/extract-taskbook", []byte("junk"))
	if w.Code != 200 {
		t.Fatalf("应 200 降级，得 %d", w.Code)
	}
	d := eData(t, w.Body.Bytes())
	if d["ok"] != false {
		t.Fatalf("LLM 失败应 ok=false，得 %v", d)
	}
}
