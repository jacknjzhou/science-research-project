// Package project 域 E（项目过程管理）HTTP 层。mapper.go 把 sqlc 生成的 store model
// 转成契约 snake_case map[string]any，供 handler 直写 httpx.WriteOK。
//
// 助手函数逐字拷自 performance/mapper.go（两包各自私有，勿跨包引用）：
// fmtTime / fmtTimePtr / optStr / optInt64Ptr / numDec / numStrOrNil / jsonToAny。
package project

import (
	"encoding/json"
	"math/big"
	"strconv"
	"time"

	estore "github.com/eplugger/ark/internal/modules/project/store"
	"github.com/jackc/pgx/v5/pgtype"
)

// ---------- 通用助手（与 M/V 域同款） ----------

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

// tsStr：pgtype.Timestamptz → RFC3339；!Valid → nil。用于 sqlc 未 override 的时间列
// （多数 E 表的 updated_at 保留原生 pgtype.Timestamptz）。
func tsStr(t pgtype.Timestamptz) any {
	if !t.Valid {
		return nil
	}
	return t.Time.UTC().Format(time.RFC3339Nano)
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

// dateStr：pgtype.Date → "2006-01-02"；!Valid → nil。
func dateStr(d pgtype.Date) any {
	if !d.Valid {
		return nil
	}
	return d.Time.Format("2006-01-02")
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

// ---------- E 域 mapper ----------

func ToAPIProject(r estore.Project) map[string]any {
	return map[string]any{
		"id":              r.ID,
		"code":            optStr(r.Code),
		"tenant_id":       r.TenantID,
		"status":          r.Status,
		"deleted":         r.Deleted,
		"creator_id":      r.CreatorID,
		"modifier_id":     optInt64Ptr(r.ModifierID),
		"remark":          optStr(r.Remark),
		"created_at":      fmtTime(r.CreatedAt),
		"updated_at":      fmtTime(r.UpdatedAt),
		"application_id":  r.ApplicationID,
		"title":           r.Title,
		"project_type":    optStr(r.ProjectType),
		"pi_user_id":      r.PiUserID,
		"member_ids":      jsonToAny(r.MemberIds, []any{}),
		"department_id":   optInt64Ptr(r.DepartmentID),
		"legal_entity_id": r.LegalEntityID,
		"start_date":      dateStr(r.StartDate),
		"end_date":        dateStr(r.EndDate),
		"actual_end_date": dateStr(r.ActualEndDate),
		"total_budget":    numDec(r.TotalBudget, 2),
		"received_amount": numDec(r.ReceivedAmount, 2),
		"spent_amount":    numDec(r.SpentAmount, 2),
		"health_score":    r.HealthScore,
		"risk_level":      r.RiskLevel,
		"ethics_case_id":  optInt64Ptr(r.EthicsCaseID),
		"policy_pack_id":  optInt64Ptr(r.PolicyPackID),
		"security_level":  r.SecurityLevel,
	}
}

func ToAPITask(r estore.Task) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"tenant_id":        r.TenantID,
		"status":           r.Status,
		"deleted":          r.Deleted,
		"creator_id":       r.CreatorID,
		"modifier_id":      optInt64Ptr(r.ModifierID),
		"remark":           optStr(r.Remark),
		"created_at":       tsStr(r.CreatedAt),
		"updated_at":       tsStr(r.UpdatedAt),
		"project_id":       r.ProjectID,
		"parent_task_id":   optInt64Ptr(r.ParentTaskID),
		"name":             r.Name,
		"description":      optStr(r.Description),
		"owner_user_id":    optInt64Ptr(r.OwnerUserID),
		"member_ids":       jsonToAny(r.MemberIds, []any{}),
		"dep_task_ids":     jsonToAny(r.DepTaskIds, []any{}),
		"planned_start":    dateStr(r.PlannedStart),
		"planned_end":      dateStr(r.PlannedEnd),
		"actual_start":     dateStr(r.ActualStart),
		"actual_end":       dateStr(r.ActualEnd),
		"progress_percent": r.ProgressPercent,
		"weight":           numStrOrNil(r.Weight, 2),
	}
}

func ToAPIMilestone(r estore.Milestone) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"tenant_id":        r.TenantID,
		"status":           r.Status,
		"deleted":          r.Deleted,
		"creator_id":       r.CreatorID,
		"modifier_id":      optInt64Ptr(r.ModifierID),
		"remark":           optStr(r.Remark),
		"created_at":       tsStr(r.CreatedAt),
		"updated_at":       tsStr(r.UpdatedAt),
		"project_id":       r.ProjectID,
		"name":             r.Name,
		"due_date":         dateStr(r.DueDate),
		"actual_date":      dateStr(r.ActualDate),
		"evidence_docs":    jsonToAny(r.EvidenceDocs, []any{}),
		"owner_user_id":    optInt64Ptr(r.OwnerUserID),
		"deliverable_type": optStr(r.DeliverableType),
		"weight":           numStrOrNil(r.Weight, 2),
	}
}

func ToAPIMidCheck(r estore.MidCheck) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"tenant_id":        r.TenantID,
		"status":           r.Status,
		"deleted":          r.Deleted,
		"creator_id":       r.CreatorID,
		"modifier_id":      optInt64Ptr(r.ModifierID),
		"remark":           optStr(r.Remark),
		"created_at":       fmtTime(r.CreatedAt),
		"updated_at":       tsStr(r.UpdatedAt),
		"project_id":       r.ProjectID,
		"check_round":      r.CheckRound,
		"check_date":       dateStr(r.CheckDate),
		"plan_id":          optInt64Ptr(r.PlanID),
		"template_id":      optInt64Ptr(r.TemplateID),
		"expert_ids":       jsonToAny(r.ExpertIds, []any{}),
		"conclusion":       optStr(r.Conclusion),
		"score_detail":     jsonToAny(r.ScoreDetail, nil),
		"report_id":        optInt64Ptr(r.ReportID),
		"correct_deadline": dateStr(r.CorrectDeadline),
		"status_overdue":   r.StatusOverdue,
	}
}

func ToAPIChangeRequest(r estore.ChangeRequest) map[string]any {
	return map[string]any{
		"id":              r.ID,
		"code":            optStr(r.Code),
		"tenant_id":       r.TenantID,
		"status":          r.Status,
		"deleted":         r.Deleted,
		"creator_id":      r.CreatorID,
		"modifier_id":     optInt64Ptr(r.ModifierID),
		"remark":          optStr(r.Remark),
		"created_at":      fmtTime(r.CreatedAt),
		"updated_at":      tsStr(r.UpdatedAt),
		"project_id":      r.ProjectID,
		"change_type":     r.ChangeType,
		"old_value":       jsonToAny(r.OldValue, nil),
		"new_value":       jsonToAny(r.NewValue, nil),
		"reason":          optStr(r.Reason),
		"effective_from":  dateStr(r.EffectiveFrom),
		"approval_status": r.ApprovalStatus,
		"approved_at":     tsStr(r.ApprovedAt),
		"impact_analysis": jsonToAny(r.ImpactAnalysis, nil),
		"conflict_flag":   r.ConflictFlag,
		"snapshot_ref":    optStr(r.SnapshotRef),
	}
}

func ToAPIFinalAccept(r estore.FinalAccept) map[string]any {
	return map[string]any{
		"id":                   r.ID,
		"code":                 optStr(r.Code),
		"tenant_id":            r.TenantID,
		"status":               r.Status,
		"deleted":              r.Deleted,
		"creator_id":           r.CreatorID,
		"modifier_id":          optInt64Ptr(r.ModifierID),
		"remark":               optStr(r.Remark),
		"created_at":           fmtTime(r.CreatedAt),
		"updated_at":           tsStr(r.UpdatedAt),
		"project_id":           r.ProjectID,
		"apply_at":             tsStr(r.ApplyAt),
		"accept_at":            tsStr(r.AcceptAt),
		"output_summary":       jsonToAny(r.OutputSummary, nil),
		"finance_report_id":    optInt64Ptr(r.FinanceReportID),
		"expert_ids":           jsonToAny(r.ExpertIds, []any{}),
		"conclusion":           optStr(r.Conclusion),
		"attachment_ids":       jsonToAny(r.AttachmentIds, []any{}),
		"archive_checklist_id": optInt64Ptr(r.ArchiveChecklistID),
	}
}

func ToAPIProgressReport(r estore.ProgressReport) map[string]any {
	return map[string]any{
		"id":               r.ID,
		"code":             optStr(r.Code),
		"tenant_id":        r.TenantID,
		"status":           r.Status,
		"deleted":          r.Deleted,
		"creator_id":       r.CreatorID,
		"modifier_id":      optInt64Ptr(r.ModifierID),
		"remark":           optStr(r.Remark),
		"created_at":       fmtTime(r.CreatedAt),
		"updated_at":       tsStr(r.UpdatedAt),
		"project_id":       r.ProjectID,
		"period":           r.Period,
		"report_type":      r.ReportType,
		"content_rich":     optStr(r.ContentRich),
		"progress_percent": r.ProgressPercent,
		"issues_text":      optStr(r.IssuesText),
		"next_plan":        optStr(r.NextPlan),
		"attachment_ids":   jsonToAny(r.AttachmentIds, []any{}),
		"submitted_at":     fmtTimePtr(r.SubmittedAt),
	}
}

// ToAPICategory T21 项目分类 API 映射。
func ToAPICategory(r estore.EProjectCategory) map[string]any {
	dateOr := func(d pgtype.Date) any {
		if !d.Valid {
			return nil
		}
		return d.Time.Format("2006-01-02")
	}
	var pct any
	if r.MgmtFeePct.Valid {
		rat := new(big.Rat).SetInt(r.MgmtFeePct.Int)
		if r.MgmtFeePct.Exp < 0 {
			rat.Mul(rat, new(big.Rat).SetFrac(big.NewInt(1), new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(-r.MgmtFeePct.Exp)), nil)))
		} else if r.MgmtFeePct.Exp > 0 {
			rat.Mul(rat, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(r.MgmtFeePct.Exp)), nil)))
		}
		pct = rat.FloatString(2)
	}
	return map[string]any{
		"id": r.ID, "code": r.Code, "name": r.Name, "level": r.Level,
		"mgmt_fee_pct": pct,
		"midcheck_from": dateOr(r.MidcheckFrom), "midcheck_to": dateOr(r.MidcheckTo),
		"closing_from": dateOr(r.ClosingFrom), "closing_to": dateOr(r.ClosingTo),
		"created_at": fmtTz(r.CreatedAt),
	}
}


// fmtTz pgtype.Timestamptz → RFC3339（无效值返回空串）。
func fmtTz(t pgtype.Timestamptz) string {
	if !t.Valid {
		return ""
	}
	return t.Time.Format(time.RFC3339)
}
