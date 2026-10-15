package output

import (
	"context"

	rstore "github.com/eplugger/ark/internal/modules/output/store"
)

// 本文件导出 R 域唯一的「单一写者」回写方法，供 N 域（专家评审）OUTPUT_EVAL 结论回写调用。
// 跨模块写纪律：N/O NEVER 直接 UPDATE R_OUTPUT；R 拥有 R_OUTPUT.status/is_claimed 的写权，
// 通过这里的 Handler 方法暴露回写动作。方法名与签名必须与规格 §3/§5/§10 及 Phase 3 调用点
// 逐字一致（记忆教训：签名漂移会连锁编译失败）。
//
// 权威签名（三处对齐）：
//   - 规格 §5.5：`R.ConcludeOutputEval(outputId, pass)`
//   - 计划 Phase 3 任务 3.6：`ConcludeOutputEval(ctx,int64,bool)`
//   - Phase 1 同款回写 `ConcludeFinalAccept(ctx, finalAcceptID int64, status string)` 的先例

// ConcludeOutputEval 供 N 域回写成果评价结论：
// pass=true → 认定（status=ASSIGNED_TO_PROJECT、is_claimed=true）；
// pass=false → 退回（status=REJECTED、is_claimed=false）。
// 目标 status token 均为 R_OUTPUT.status CHECK 枚举合法值（见 DDL §1）。
func (h *Handler) ConcludeOutputEval(ctx context.Context, outputID int64, pass bool) error {
	status := "REJECTED"
	isClaimed := false
	if pass {
		status = "ASSIGNED_TO_PROJECT"
		isClaimed = true
	}
	_, err := h.q.ConcludeOutputEval(ctx, rstore.ConcludeOutputEvalParams{
		ID: outputID, Status: status, IsClaimed: isClaimed,
	})
	return err
}
