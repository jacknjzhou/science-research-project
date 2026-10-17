// Package output 域 R（科研成果管理）HTTP 层。mapper.go 把 sqlc 生成的 rstore model
// 转成契约 snake_case map[string]any（对齐 design/04-科研成果管理-R.openapi.yaml 的 Output schema）。
//
// 助手函数逐字拷自 project/mapper.go（两包各自私有，勿跨包引用）：
// fmtTime / fmtTimePtr / tsStr / optStr / optInt64Ptr / dateStr / numDec / numStrOrNil / jsonToAny。
// 额外新增 numFloatOrNil：契约 match_confidence 声明为 number（非 string），故转 float64 而非定标字符串。
package output

import (
	"encoding/json"
	"strconv"
	"time"

	rstore "github.com/eplugger/ark/internal/modules/output/store"
	"github.com/jackc/pgx/v5/pgtype"
)

// ---------- 通用助手（与 E/V/M 域同款，逐字拷入本包私有） ----------

func fmtTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}

// tsStr：pgtype.Timestamptz → RFC3339；!Valid → nil。
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

// numFloatOrNil：pgtype.Numeric → float64；无效/!Valid → nil。
// 用于契约声明为 number 的列（match_confidence/confidence/contribution_pct）。
func numFloatOrNil(n pgtype.Numeric) any {
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return nil
	}
	return f.Float64
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

// ---------- R 域 mapper ----------

// ToAPIOutput 把成果主档 model 映射为契约 Output（snake_case）。
// 覆盖 design/04 Output schema 全部字段；额外带 external_author_names（DDL 有，前端作者展示用，
// OpenAPI 无 additionalProperties:false，附加键合法）。
func ToAPIOutput(r rstore.Output) map[string]any {
	return map[string]any{
		"id":                    r.ID,
		"code":                  optStr(r.Code),
		"tenant_id":             r.TenantID,
		"status":                r.Status,
		"output_type":           r.OutputType,
		"title":                 r.Title,
		"title_en":              optStr(r.TitleEn),
		"abstract":              optStr(r.Abstract),
		"publish_date":          dateStr(r.PublishDate),
		"authors":               jsonToAny(r.Authors, []any{}),
		"external_author_names": jsonToAny(r.ExternalAuthorNames, []any{}),
		"affiliations":          jsonToAny(r.Affiliations, []any{}),
		"project_ids":           jsonToAny(r.ProjectIds, []any{}),
		"language":              optStr(r.Language),
		"source":                r.Source,
		"is_claimed":            r.IsClaimed,
		"claim_status":          r.ClaimStatus,
		"match_confidence":      numFloatOrNil(r.MatchConfidence),
		"department_id":         optInt64Ptr(r.DepartmentID),
		"legal_entity_id":       r.LegalEntityID,
		"security_level":        r.SecurityLevel,
		"created_at":            fmtTime(r.CreatedAt),
		"updated_at":            fmtTime(r.UpdatedAt),
		"remark":                optStr(r.Remark),
	}
}

// ToAPIClaimRecord 把认领流水映射为 snake_case map（契约无独立 ClaimRecord schema，
// 供 getOutput 内联认领历史或未来端点复用）。
func ToAPIClaimRecord(r rstore.ClaimRecord) map[string]any {
	return map[string]any{
		"id":            r.ID,
		"code":          optStr(r.Code),
		"tenant_id":     r.TenantID,
		"status":        r.Status,
		"output_id":     r.OutputID,
		"user_id":       r.UserID,
		"action":        r.Action,
		"edited_fields": jsonToAny(r.EditedFields, nil),
		"reason":        optStr(r.Reason),
		"confidence":    numFloatOrNil(r.Confidence),
		"action_at":     fmtTime(r.ActionAt),
		"batch_id":      optStr(r.BatchID),
		"created_at":    fmtTime(r.CreatedAt),
		"updated_at":    fmtTime(r.UpdatedAt),
		"remark":        optStr(r.Remark),
	}
}
