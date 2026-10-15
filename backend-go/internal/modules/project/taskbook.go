// T22 LLM PDF 任务书解析：multipart pdf → 本地抽文本 → LLM 结构化抽取 →
// {project_name, pi, members, budget_lines, period, confidence}；confidence<0.85 附 raw_text 提示人工录入。
// 解析结果仅回填表单用，不直接落库。
package project

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"

	"github.com/ledongthuc/pdf"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// TaskbookLLM 任务书抽取 LLM 接口（llm.Client 实现；测试注入 fake）。
type TaskbookLLM interface {
	ExtractJSON(ctx context.Context, system, user string) (string, error)
}

// SetTaskbookLLM 装配期注入。
func (h *Handler) SetTaskbookLLM(l TaskbookLLM) { h.tbLLM = l }

const taskbookSystem = "你是科研任务书解析助手。从任务书文本抽取结构化信息，只输出 JSON 对象：" +
	`{"project_name":string,"pi":string,"members":[string],"budget_lines":[{"name":string,"amount":string}],` +
	`"period":{"start":string,"end":string},"confidence":number}` +
	"。confidence 为 0-1 的抽取置信度；无法确定的字段填空串/空数组，不要编造。"

// ExtractTaskbook POST /projects/extract-taskbook（multipart：file 字段，pdf）。
func (h *Handler) ExtractTaskbook(c *gin.Context) {
	fh, err := c.FormFile("file")
	if err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "缺少 file 字段（multipart pdf）")
		return
	}
	f, err := fh.Open()
	if err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "文件读取失败")
		return
	}
	defer f.Close()
	raw, err := io.ReadAll(f)
	if err != nil || len(raw) == 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "文件内容为空")
		return
	}
	// 本地抽文本（仅支持文本版 PDF；扫描件明确报错 → 降级人工录入）
	text, terr := extractPDFText(raw)
	if terr != nil || strings.TrimSpace(text) == "" {
		httpx.WriteOK(c, gin.H{
			"ok": false, "confidence": 0,
			"message": "PDF 文本抽取失败（可能为扫描件），请人工录入",
		})
		return
	}
	if h.tbLLM == nil {
		httpx.WriteOK(c, gin.H{
			"ok": false, "confidence": 0, "raw_text": truncate(text, 2000),
			"message": "LLM 未配置，请人工录入",
		})
		return
	}
	content, lerr := h.tbLLM.ExtractJSON(c, taskbookSystem, "任务书文本：\n"+truncate(text, 12000))
	if lerr != nil {
		httpx.WriteOK(c, gin.H{
			"ok": false, "confidence": 0, "raw_text": truncate(text, 2000),
			"message": "LLM 解析失败：" + lerr.Error() + "，请人工录入",
		})
		return
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(content), &parsed); err != nil {
		httpx.WriteOK(c, gin.H{
			"ok": false, "confidence": 0, "raw_text": truncate(text, 2000),
			"message": "LLM 输出非合法 JSON，请人工录入",
		})
		return
	}
	conf, _ := parsed["confidence"].(float64)
	parsed["ok"] = true
	if conf < 0.85 {
		parsed["raw_text"] = truncate(text, 2000)
		parsed["message"] = "置信度不足 0.85，请核对字段后人工录入"
	}
	httpx.WriteOK(c, parsed)
}

// extractPDFText 文本版 PDF 抽取（ledongthuc/pdf；逐页拼接）。
func extractPDFText(raw []byte) (string, error) {
	r, err := pdf.NewReader(strings.NewReader(string(raw)), int64(len(raw)))
	if err != nil {
		return "", err
	}
	var sb strings.Builder
	for i := 1; i <= r.NumPage(); i++ {
		p := r.Page(i)
		// 快速文本抽取（无字体还原；扫描件返回空）
		txt, err := p.GetPlainText(nil)
		if err == nil {
			sb.WriteString(txt)
			sb.WriteString("\n")
		}
	}
	return sb.String(), nil
}

func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}
