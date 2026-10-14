package project

import (
	"context"
	"encoding/json"

	estore "github.com/eplugger/ark/internal/modules/project/store"
)

// 本文件导出 3 个「单一写者」方法给 N 域（专家评审）调用。
// 跨模块写纪律：N/O NEVER 直接 UPDATE E_* 表；E 拥有 E_MID_CHECK/E_FINAL_ACCEPT/
// E_PROJECT 的写权，通过这里的 Handler 方法暴露回写动作。方法名与调用点必须逐字一致，
// 参见规格 §3/§5/§10（记忆教训：签名漂移会连锁编译失败）。

// SetMidCheckExperts 由 N 域专家抽取完成后回填 E_MID_CHECK.expert_ids（jsonb 数组）。
func (h *Handler) SetMidCheckExperts(ctx context.Context, midCheckID int64, expertUserIDs []int64) error {
	b, err := json.Marshal(expertUserIDs)
	if err != nil {
		return err
	}
	_, err = h.q.SetMidCheckExperts(ctx, estore.SetMidCheckExpertsParams{
		ID: midCheckID, ExpertIds: b,
	})
	return err
}

// ConcludeMidCheck 写中检结论 + score_detail 并按结论推进项目状态：
// CONTINUE→EXECUTING / CORRECT→CORRECTING / TERMINATE→TERMINATED。
// 其它 conclusion 值只回写 mid_check，不改项目状态。
func (h *Handler) ConcludeMidCheck(ctx context.Context, midCheckID, projectID int64, conclusion string, scoreDetail any) error {
	b, err := json.Marshal(scoreDetail)
	if err != nil {
		return err
	}
	if _, err := h.q.ConcludeMidCheck(ctx, estore.ConcludeMidCheckParams{
		ID: midCheckID, Conclusion: conclusion, ScoreDetail: b,
	}); err != nil {
		return err
	}
	projStatus := map[string]string{
		"CONTINUE":  "EXECUTING",
		"CORRECT":   "CORRECTING",
		"TERMINATE": "TERMINATED",
	}[conclusion]
	if projStatus == "" {
		return nil
	}
	return h.q.UpdateProjectStatus(ctx, estore.UpdateProjectStatusParams{ID: projectID, Status: projStatus})
}

// ConcludeFinalAccept 写结题技术轨结论（APPROVED / REJECTED / NEED_SUPPLEMENT）。
// 财务轨由 F 域独立推进；E_FINAL_ACCEPT.status 是双轨合成的技术轨槽位。
func (h *Handler) ConcludeFinalAccept(ctx context.Context, finalAcceptID int64, status string) error {
	_, err := h.q.ConcludeFinalAccept(ctx, estore.ConcludeFinalAcceptParams{
		ID: finalAcceptID, Status: status,
	})
	return err
}
