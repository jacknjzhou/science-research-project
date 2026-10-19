// F-15 AI 发票/报销智能审核（仅建议、永不直写业务，PRD 2.4）。
// LLM 经 NewAPI（OpenAI 兼容）调用；nil/不可用/低置信 → 降级 REVIEW。
package funding

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

const aiConfidenceFloor = 0.85

// AiInvoiceReview POST /expense/ai-invoice-review {expenseId}
// 组装单据结构化上下文 → LLM 输出严格 JSON 建议 → 低置信回落人工。
func (h *Handler) AiInvoiceReview(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		ExpenseID  int64   `json:"expenseId" binding:"required"`
		InvoiceIDs []int64 `json:"invoiceIds"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	exp, err := h.q.GetExpense(c, b.ExpenseID)
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "报销单不存在")
		return
	}
	// LLM 不可用 → 降级建议（不阻塞业务）
	if h.llm == nil {
		httpx.WriteOK(c, degradedReview("AI 审核通道未配置"))
		return
	}
	exec := h.executionOf(c, d.TenantID, exp.ProjectID)
	ctxPayload, _ := json.Marshal(map[string]any{
		"expense": ToAPIExpense(exp),
		"execution": map[string]any{
			"budgetApproved": exec["budgetApproved"], "used": exec["used"],
			"frozen": exec["frozen"], "execRateByBudget": exec["execRateByBudget"],
		},
		"rules": []string{
			"报销金额不得超过该预算科目可支余额",
			"同一发票（号码+金额+开票日期）仅可报销一次",
			"劳务费/专家咨询费需核对人员名单合理性",
			"差旅费需与项目研究内容相关",
		},
	})
	system := "你是科研经费合规审核助手。只输出一个 JSON 对象，" +
		`格式 {"verdict":"PASS|REVIEW|REJECT","confidence":0到1,"issues":[{"rule":"...","reason":"..."}]}，不要输出其它文字。` +
		"AI 结论仅是建议，不确定时用 REVIEW。"
	verdict, err := h.llm.ChatJSON(c, system, string(ctxPayload))
	if err != nil {
		httpx.WriteOK(c, degradedReview("AI 服务暂不可用："+err.Error()))
		return
	}
	verdict.Verdict = normalizeVerdict(verdict.Verdict)
	// 低置信强制回落人工（PRD 2.4）
	if verdict.Confidence < aiConfidenceFloor {
		verdict.Verdict = "REVIEW"
		if verdict.Confidence <= 0 {
			verdict.Confidence = 0
		}
	}
	issues := make([]map[string]any, 0, len(verdict.Issues))
	for _, i := range verdict.Issues {
		issues = append(issues, map[string]any{"rule": i.Rule, "reason": i.Reason})
	}
	httpx.WriteOK(c, map[string]any{
		"verdict":    verdict.Verdict,
		"confidence": verdict.Confidence,
		"issues":     issues,
		"available":  true,
	})
}

func degradedReview(reason string) map[string]any {
	return map[string]any{
		"verdict":    "REVIEW",
		"confidence": 0,
		"issues": []map[string]any{
			{"rule": "SERVICE_DEGRADED", "reason": reason},
		},
		"available": false,
	}
}

// 编译期防呆：确保 verdict 枚举合法（LLM 输出兜底）。
func normalizeVerdict(v string) string {
	switch strings.ToUpper(v) {
	case "PASS":
		return "PASS"
	case "REJECT":
		return "REJECT"
	default:
		return "REVIEW"
	}
}

var _ = fmt.Sprintf // 占位保留 fmt（后续扩展上下文模板）
