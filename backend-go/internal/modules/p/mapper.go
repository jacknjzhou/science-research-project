package p

import (
	"encoding/json"
	"time"

	"github.com/eplugger/ark/internal/modules/p/store"
)

// ToAPIApplication 把 sqlc 行映射为契约 Application 形状（snake_case，与 design 一致）。
// total_budget 作 string、member_ids 作 JSON 数组。
func ToAPIApplication(r store.Application) map[string]any {
	var memberIDs any = []any{}
	if len(r.MemberIds) > 0 {
		_ = json.Unmarshal(r.MemberIds, &memberIDs)
	}
	out := map[string]any{
		"id":              r.ID,
		"tenant_id":       r.TenantID,
		"status":          r.Status,
		"deleted":         r.Deleted,
		"creator_id":      r.CreatorID,
		"title":           r.Title,
		"project_type":    r.ProjectType,
		"pi_user_id":      r.PiUserID,
		"member_ids":      memberIDs,
		"is_horizontal":   r.IsHorizontal,
		"ai_draft_marked": r.AiDraftMarked,
		"total_budget":    r.TotalBudget,
		"created_at":      r.CreatedAt.UTC().Format(time.RFC3339Nano),
		"updated_at":      r.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}
	putStr := func(k string, v *string) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putStr("code", r.Code)
	putStr("remark", r.Remark)
	putStr("abstract", r.Abstract)
	putStr("funding_channel", r.FundingChannel)
	if r.DurationMonths != nil {
		out["duration_months"] = *r.DurationMonths
	} else {
		out["duration_months"] = nil
	}
	if r.SubmitAt != nil {
		out["submit_at"] = r.SubmitAt.UTC().Format(time.RFC3339Nano)
	} else {
		out["submit_at"] = nil
	}
	return out
}
