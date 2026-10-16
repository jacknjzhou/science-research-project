package p

import (
	"encoding/json"
	"strconv"
	"time"

	"github.com/eplugger/ark/internal/modules/p/store"
	"github.com/jackc/pgx/v5/pgtype"
)

// tsPtr 把 pgtype.Timestamptz 映射为 RFC3339 字符串或 nil（契约 date-time 可空）。
func tsPtr(t pgtype.Timestamptz) any {
	if !t.Valid {
		return nil
	}
	return t.Time.UTC().Format(time.RFC3339Nano)
}

// jsonArr 把 JSONB 列（[]byte）解为数组；空/坏值兜底空数组。
func jsonArr(b []byte) any {
	var v any = []any{}
	if len(b) > 0 {
		_ = json.Unmarshal(b, &v)
	}
	if v == nil {
		return []any{}
	}
	return v
}

// numEnv 把 NUMERIC 列格式化为契约 string（2 位小数）或 null。
func numEnv(n pgtype.Numeric) any {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return nil
	}
	return strconv.FormatFloat(f.Float64, 'f', 2, 64)
}

// ToAPIGuideline 把 sqlc 指南行（List/Get/Upsert 三查询现均直接返回 PGuideline 模型）
// 映射为契约 Guideline 形状（snake_case，与 design 一致）。
func ToAPIGuideline(r store.PGuideline) map[string]any {
	return map[string]any{
		"id":                 r.ID,
		"code":               r.Code,
		"status":             r.Status,
		"modifier_id":        r.ModifierID,
		"created_at":         tsPtr(r.CreatedAt),
		"updated_at":         tsPtr(r.UpdatedAt),
		"remark":             r.Remark,
		"apply_start_at":     tsPtr(r.ApplyStartAt),
		"apply_end_at":       tsPtr(r.ApplyEndAt),
		"publish_at":         tsPtr(r.PublishAt),
		"funding_source":     r.FundingSource,
		"target_disciplines": jsonArr(r.TargetDisciplines),
		"total_envelope":     numEnv(r.TotalEnvelope),
		"content_rich":       r.ContentRich,
		"attachment_ids":     jsonArr(r.AttachmentIds),
		"title":              r.Title,
		"project_type":       r.ProjectType,
	}
}


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
