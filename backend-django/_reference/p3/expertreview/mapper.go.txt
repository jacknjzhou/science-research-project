// Package expertreview 域 N（专家与评审管理）HTTP 层。mapper.go 把 sqlc 生成的 store
// model 转成契约 snake_case map[string]any，供 handler 直写 httpx.WriteOK。
//
// 助手函数逐字拷自 project/mapper.go（两包各自私有，勿跨包引用）：
// fmtTime / fmtTimePtr / optStr / optInt64Ptr / numDec / numStrOrNil / jsonToAny。
package expertreview

import (
	"encoding/json"
	"strconv"
	"time"

	nstore "github.com/eplugger/ark/internal/modules/expertreview/store"
	"github.com/jackc/pgx/v5/pgtype"
)

// ---------- 通用助手（与 E/M 域同款） ----------

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

func optStr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func optInt64Ptr(v *int64) any {
	if v == nil {
		return nil
	}
	return *v
}

// numDec：pgtype.Numeric → 定标字符串（d 位小数）；无效/!Valid → "0"。
func numDec(n pgtype.Numeric, d int) string {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return "0"
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

// numStrOrNil：pgtype.Numeric → 定标字符串；无效/!Valid → nil。
func numStrOrNil(n pgtype.Numeric, d int) any {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return nil
	}
	return strconv.FormatFloat(f.Float64, 'f', d, 64)
}

// jsonToAny：jsonb []byte → 反序列化 any；空/非法 → fallback。
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

// ---------- N 域 mapper ----------

func ToAPIExpert(r nstore.Expert) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"tenant_id":        r.TenantID,
		"status":           r.Status,
		"name":             r.Name,
		"gender":           optStr(r.Gender),
		"title":            optStr(r.Title),
		"org_name":         optStr(r.OrgName),
		"user_id":          optInt64Ptr(r.UserID),
		"source":           r.Source,
		"field_tags":       jsonToAny(r.FieldTags, []any{}),
		"expertise_level":  r.ExpertiseLevel,
		"avoid_orgs":       jsonToAny(r.AvoidOrgs, []any{}),
		"avoid_person_ids": jsonToAny(r.AvoidPersonIds, []any{}),
		"security_level":   r.SecurityLevel,
		"last_review_at":   fmtTimePtr(r.LastReviewAt),
		"review_count":     r.ReviewCount,
		"created_at":       fmtTime(r.CreatedAt),
		"updated_at":       fmtTime(r.UpdatedAt),
	}
}

func ToAPIReviewTask(r nstore.ReviewTask) map[string]any {
	return map[string]any{
		"id":             r.ID,
		"code":           optStr(r.Code),
		"tenant_id":      r.TenantID,
		"biz_type":       r.BizType,
		"target_type":    optStr(r.TargetType),
		"target_id":      optInt64Ptr(r.TargetID),
		"project_id":     optInt64Ptr(r.ProjectID),
		"title":          r.Title,
		"review_method":  r.ReviewMethod,
		"plan_count":     r.PlanCount,
		"draw_rule":      jsonToAny(r.DrawRule, map[string]any{}),
		"status":         r.Status,
		"conclusion":     optStr(r.Conclusion),
		"score_summary":  jsonToAny(r.ScoreSummary, nil),
		"security_level": r.SecurityLevel,
		"drawn_at":       fmtTimePtr(r.DrawnAt),
		"started_at":     fmtTimePtr(r.StartedAt),
		"concluded_at":   fmtTimePtr(r.ConcludedAt),
		"created_at":     fmtTime(r.CreatedAt),
		"updated_at":     fmtTime(r.UpdatedAt),
	}
}

func ToAPIInvitation(r nstore.ListInvitationsRow) map[string]any {
	return map[string]any{
		"id":          r.ID,
		"task_id":     r.TaskID,
		"expert_id":   r.ExpertID,
		"expert_name": r.ExpertName,
		"seat_no":     r.SeatNo,
		"avoid_hit":   r.AvoidHit,
		"response":    r.Response,
	}
}

func ToAPIScore(r nstore.Score) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"task_id":          r.TaskID,
		"expert_id":        r.ExpertID,
		"target_type":      optStr(r.TargetType),
		"target_id":        optInt64Ptr(r.TargetID),
		"dimension_scores": jsonToAny(r.DimensionScores, []any{}),
		"total_score":      numStrOrNil(r.TotalScore, 2),
		"comment":          optStr(r.Comment),
		"status":           r.Status,
	}
}
