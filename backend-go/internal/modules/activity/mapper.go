package activity

import (
	"encoding/json"
	"time"

	vstore "github.com/eplugger/ark/internal/modules/activity/store"
)

// jsonToAny 把 []byte(JSONB) 解成 any；空/坏回落 []any{}（契约要求数组字段恒为数组）。
func jsonToAny(b []byte, fallback any) any {
	if len(b) == 0 {
		return fallback
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return fallback
	}
	return v
}

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

// ToAPIActivity 映射 v_activity 行为契约 Activity（snake_case）。
func ToAPIActivity(r vstore.Activity) map[string]any {
	out := map[string]any{
		"id":              r.ID,
		"tenant_id":       r.TenantID,
		"status":          r.Status,
		"security_level":  r.SecurityLevel,
		"activity_type":   r.ActivityType,
		"title":           r.Title,
		"invited_experts": jsonToAny(r.InvitedExperts, []any{}),
		"agenda":          jsonToAny(r.Agenda, []any{}),
		"attachment_ids":  jsonToAny(r.AttachmentIds, []any{}),
		"hold_proof_ids":  jsonToAny(r.HoldProofIds, []any{}),
		"budget_amount":   r.BudgetAmount, // 已是 string（::text）；无值时为 ""→契约允许 null，下面兜
		"creator_id":      r.CreatorID,
		"deleted":         r.Deleted,
		"created_at":      fmtTime(r.CreatedAt),
		"updated_at":      fmtTime(r.UpdatedAt),
	}
	if r.BudgetAmount == "" {
		out["budget_amount"] = nil
	}
	putStr := func(k string, v *string) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putStr("code", r.Code)
	putStr("level", r.Level)
	putStr("host_mode", r.HostMode)
	putStr("theme", r.Theme)
	putStr("venue", r.Venue)
	putStr("online_url", r.OnlineUrl)
	putStr("host_unit", r.HostUnit)
	putStr("budget_subject_code", r.BudgetSubjectCode)
	putStr("minutes_rich", r.MinutesRich)
	putStr("cancel_reason", r.CancelReason)
	putStr("remark", r.Remark)
	// 可空整型
	putInt := func(k string, v *int64) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putInt("organizer_dept_id", r.OrganizerDeptID)
	putInt("project_id", r.ProjectID)
	putSmallInt := func(k string, v *int32) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putSmallInt("est_attendees", r.EstAttendees)
	putSmallInt("sign_in_count", r.SignInCount)
	if r.ModifierID != nil {
		out["modifier_id"] = *r.ModifierID
	} else {
		out["modifier_id"] = nil
	}
	out["start_at"] = fmtTimePtr(r.StartAt)
	out["end_at"] = fmtTimePtr(r.EndAt)
	out["submit_at"] = fmtTimePtr(r.SubmitAt)
	out["approve_at"] = fmtTimePtr(r.ApproveAt)
	out["archive_at"] = fmtTimePtr(r.ArchiveAt)
	out["cancel_at"] = fmtTimePtr(r.CancelAt)
	return out
}

func ToAPIParticipant(r vstore.VActivityParticipant) map[string]any {
	return map[string]any{
		"id":           r.ID,
		"activity_id":  r.ActivityID,
		"user_id":      r.UserID,
		"guest_name":   r.GuestName,
		"role":         r.Role,
		"report_title": r.ReportTitle,
	}
}

func ToAPIReview(r vstore.VActivityReview) map[string]any {
	return map[string]any{
		"id":           r.ID,
		"activity_id":  r.ActivityID,
		"review_level": r.ReviewLevel,
		"reviewer_id":  r.ReviewerID,
		"action":       r.Action,
		"opinion":      r.Opinion,
		"acted_at":     fmtTime(r.ActedAt),
	}
}
