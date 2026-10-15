package expertreview

import "context"

// concludeWriteback 按 biz_type 把评审结论回写到被评审对象（经被写模块导出的「单一写者」方法）。
// 跨模块写纪律（铁律）：N NEVER 直接 UPDATE E_/R_ 表；只调 E/R Handler 导出方法。
// 签名权威（勿漂移）：
//   - E.SetMidCheckExperts(ctx, midCheckID int64, expertUserIDs []int64) error
//   - E.ConcludeMidCheck(ctx, midCheckID, projectID int64, conclusion string, scoreDetail any) error
//   - E.ConcludeFinalAccept(ctx, finalAcceptID int64, status string) error
//   - R.ConcludeOutputEval(ctx, outputID int64, pass bool) error  // conclusion=="PASS"→true
func (h *Handler) concludeWriteback(ctx context.Context, bizType string, targetID, projectID int64, conclusion string, summary any) error {
	switch bizType {
	case "MID_CHECK":
		return h.e.ConcludeMidCheck(ctx, targetID, projectID, conclusion, summary)
	case "FINAL_ACCEPT":
		status := map[string]string{
			"PASS":       "APPROVED",
			"REJECT":     "REJECTED",
			"SUPPLEMENT": "NEED_SUPPLEMENT",
		}[conclusion]
		if status == "" {
			return nil // 非法/缺省结论不动技术轨状态，避免 CHECK 违例
		}
		return h.e.ConcludeFinalAccept(ctx, targetID, status)
	case "OUTPUT_EVAL":
		return h.r.ConcludeOutputEval(ctx, targetID, conclusion == "PASS")
	}
	return nil // PROJECT_APPLY/OTHER 暂无被写对象，no-op
}
