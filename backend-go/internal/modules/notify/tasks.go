// T20 任务中心 + 站内消息：我的待办聚合（未读 TODO 通知 + 我名下 PENDING 审批单）、
// 今日待办摘要、点对点消息（type=MESSAGE）。
package notify

import (
	"math/big"
	"net/http"
	"strconv"
	"strings"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	nfstore "github.com/eplugger/ark/internal/modules/notify/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
)

// Tasks GET /tasks?size= —— 我的待办：未读 TODO 通知 + 我名下 PENDING 单据。
func (h *Handler) Tasks(c *gin.Context) {
	d := auth.DomainFrom(c)
	size := atoiDefault(c.Query("size"), 50)
	out := make([]gin.H, 0, 8)
	total := 0

	// 1) 未读 TODO 通知（待办类）
	rows, err := h.q.ListUnreadByTyp(c, nfstore.ListUnreadByTypParams{
		UserID: d.UserID, Typ: strPtr("TODO"), Limit: int32(size), Offset: 0,
	})
	if err == nil {
		for _, n := range rows {
			out = append(out, gin.H{
				"kind": "NOTIFICATION", "id": n.ID, "title": n.Title,
				"content": n.Content, "biz_ref": n.BizRef, "created_at": n.CreatedAt,
			})
			total++
		}
	}

	// 2) 我名下 PENDING 审批单（角色匹配当前步骤）
	if len(d.Roles) > 0 {
		prows, perr := h.fq.ListPendingExpenseApprovals(c, fstore.ListPendingExpenseApprovalsParams{
			Roles: d.Roles, Limit: int32(size), Offset: 0,
		})
		if perr == nil {
			for _, p := range prows {
				out = append(out, gin.H{
					"kind": "APPROVAL", "biz_type": "EXPENSE", "id": p.ID, "title": "报销单待审批",
					"code": p.Code, "amount": numStr(p.Amount), "status": p.Status,
					"expense_type": p.ExpenseType, "step_order": p.StepOrder,
					"role": p.Role, "created_at": p.CreatedAt,
				})
				total++
			}
		}
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total})
}

// TasksSummary GET /tasks/summary —— 三 tab 计数：todo/message/warning（全部未读口径）。
func (h *Handler) TasksSummary(c *gin.Context) {
	d := auth.DomainFrom(c)
	sum := gin.H{"todo": 0, "message": 0, "warning": 0}
	for _, typ := range []string{"TODO", "MESSAGE", "WARNING"} {
		n, err := h.q.CountUnreadByTyp(c, nfstore.CountUnreadByTypParams{UserID: d.UserID, Typ: strPtr(typ)})
		if err != nil {
			httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
			return
		}
		sum[strings.ToLower(typ)] = n
	}
	// 待办计数补上 PENDING 审批单
	if len(d.Roles) > 0 {
		if n, err := h.fq.CountPendingExpenseApprovals(c, d.Roles); err == nil {
			sum["todo"] = sum["todo"].(int64) + n
		}
	}
	httpx.WriteOK(c, sum)
}

// SendMessage POST /messages {to_user_ids[], title, body} —— 点对点站内消息。
func (h *Handler) SendMessage(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		ToUserIDs []int64 `json:"to_user_ids" binding:"required,min=1"`
		Title     string  `json:"title" binding:"required"`
		Body      string  `json:"body"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	sent := 0
	for _, uid := range b.ToUserIDs {
		if _, err := h.q.InsertNotification(c, nfstore.InsertNotificationParams{
			TenantID: d.TenantID, UserID: uid, Typ: "MESSAGE",
			Title: b.Title, Content: &b.Body, BizRef: strPtr("message/from/" + strconv.FormatInt(d.UserID, 10)),
		}); err == nil {
			sent++
		}
	}
	httpx.WriteOK(c, gin.H{"sent": sent, "total": len(b.ToUserIDs)})
}

// ListMessages GET /messages —— 收件箱（type=MESSAGE 过滤，复用收件箱查询）。
func (h *Handler) ListMessages(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListByUser(c, nfstore.ListByUserParams{
		UserID: d.UserID, Typ: strPtr("MESSAGE"), Limit: int32(limit), Offset: int32(offset),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, err := h.q.CountByUser(c, nfstore.CountByUserParams{UserID: d.UserID, Typ: strPtr("MESSAGE")})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, n := range rows {
		out = append(out, ToAPINotification(n))
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// strPtr 字符串指针。
func strPtr(s string) *string { return &s }

// numStr pgtype.Numeric → "1234.56"（big.Rat × 10^Exp 格式化；无效值返回 "0.00"）。
// 同 funding mapper numDec 语义：Numeric 无 MarshalText，手格式化避免反射。
func numStr(n pgtype.Numeric) string {
	if !n.Valid || n.NaN || n.Int == nil {
		return "0.00"
	}
	r := new(big.Rat).SetInt(n.Int)
	if n.Exp < 0 {
		r.Mul(r, new(big.Rat).SetFrac(big.NewInt(1), new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(-n.Exp)), nil)))
	} else if n.Exp > 0 {
		r.Mul(r, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(n.Exp)), nil)))
	}
	return r.FloatString(2)
}
