// 通知中心（NF）：站内通知的写入（含 PushRole 角色扇出）与个人收件箱。
// 同时实现 funding.Notifier 接口（结构化匹配，无 import 依赖），由 router 装配期注入。
package notify

import (
	"context"
	"net/http"
	"strconv"

	nfstore "github.com/eplugger/ark/internal/modules/notify/store"
	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	q  *nfstore.Queries
	fq *fstore.Queries // T20 任务中心跨域待办读模型（F_EXPENSE_APPROVAL join）
}

func NewHandler(pool *pgxpool.Pool) *Handler {
	return &Handler{q: nfstore.New(pool), fq: fstore.New(pool)}
}

// Push 单用户触达（funding.Notifier）。
func (h *Handler) Push(ctx context.Context, tenantID, userID int64, typ, title, content, bizRef string) {
	_, _ = h.q.InsertNotification(ctx, nfstore.InsertNotificationParams{
		TenantID: tenantID, UserID: userID, Typ: normType(typ),
		Title: title, Content: &content, BizRef: &bizRef,
	})
}

// PushRole 角色扇出：按角色代码查启用用户逐个落行（读模型简单化）。
func (h *Handler) PushRole(ctx context.Context, tenantID int64, role, typ, title, content, bizRef string) {
	ids, err := h.q.UserIDsByRole(ctx, nfstore.UserIDsByRoleParams{TenantID: tenantID, Code: role})
	if err != nil {
		return
	}
	for _, uid := range ids {
		_, _ = h.q.InsertNotification(ctx, nfstore.InsertNotificationParams{
			TenantID: tenantID, UserID: uid, Typ: normType(typ),
			Title: title, Content: &content, BizRef: &bizRef,
		})
	}
}

func normType(t string) string {
	switch t {
	case "MESSAGE", "WARNING", "ANNOUNCE":
		return t
	default:
		return "TODO"
	}
}

// List GET /notifications?typ=&page=&size= —— 个人收件箱。
func (h *Handler) List(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	typ := optQuery(c, "typ")
	rows, err := h.q.ListByUser(c, nfstore.ListByUserParams{
		UserID: d.UserID, Typ: typ, Limit: int32(limit), Offset: int32(offset),
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, err := h.q.CountByUser(c, nfstore.CountByUserParams{UserID: d.UserID, Typ: typ})
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

// UnreadCount GET /notifications/unread-count。
func (h *Handler) UnreadCount(c *gin.Context) {
	d := auth.DomainFrom(c)
	n, err := h.q.CountUnread(c, d.UserID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	httpx.WriteOK(c, gin.H{"unread": n})
}

// MarkRead POST /notifications/:id/read。
func (h *Handler) MarkRead(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "id 非法")
		return
	}
	if err := h.q.MarkRead(c, nfstore.MarkReadParams{ID: id, UserID: d.UserID}); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "已读失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id})
}

// MarkAllRead POST /notifications/read-all。
func (h *Handler) MarkAllRead(c *gin.Context) {
	d := auth.DomainFrom(c)
	if err := h.q.MarkAllRead(c, d.UserID); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "已读失败")
		return
	}
	httpx.WriteOK(c, gin.H{"ok": true})
}
