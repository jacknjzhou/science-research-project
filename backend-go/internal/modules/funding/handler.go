package funding

import (
	"context"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Notifier 通知触达接口（由 notify 模块实现并注入；nil 时业务触达点静默跳过）。
// 事务提交后调用方 best-effort 触达，通知失败不回滚业务。
type Notifier interface {
	Push(ctx context.Context, tenantID, userID int64, typ, title, content, bizRef string)
	// PushRole 推给某租户下持指定角色的全部启用用户（如报销审批链的 R-MANAGER）。
	PushRole(ctx context.Context, tenantID int64, role, typ, title, content, bizRef string)
}

// LLMClient AI 建议客户端（platform/llm 实现；nil 或不可用 → AI 端点降级 REVIEW）。
type LLMClient interface {
	ChatJSON(ctx context.Context, system, user string) (llmVerdict, error)
}

type Handler struct {
	q   *fstore.Queries
	db  *pgxpool.Pool
	nt  Notifier
	llm LLMClient
}

// NewHandler 经费域 handler；Notifier/LLM 通过 Set 注入（router 装配期）。
func NewHandler(pool *pgxpool.Pool) *Handler {
	return &Handler{q: fstore.New(pool), db: pool}
}

func (h *Handler) SetNotifier(n Notifier) { h.nt = n }

func (h *Handler) SetLLM(c LLMClient) { h.llm = c }

// notify 若通知器可用则触达；内部吞错（通知永不阻断业务）。
func (h *Handler) notify(userID int64, typ, title, content, bizRef string, tenantID int64) {
	if h.nt == nil || userID <= 0 {
		return
	}
	go func() {
		defer func() { _ = recover() }()
		h.nt.Push(context.Background(), tenantID, userID, typ, title, content, bizRef)
	}()
}

func (h *Handler) notifyRole(role, typ, title, content, bizRef string, tenantID int64) {
	if h.nt == nil {
		return
	}
	go func() {
		defer func() { _ = recover() }()
		h.nt.PushRole(context.Background(), tenantID, role, typ, title, content, bizRef)
	}()
}
