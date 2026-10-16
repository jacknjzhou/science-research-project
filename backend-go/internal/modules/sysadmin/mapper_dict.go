package sysadmin

import (
	"encoding/json"

	"github.com/jackc/pgx/v5/pgtype"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
)

// fmtTS TIMESTAMPTZ → RFC3339 字符串；NULL → nil。
func fmtTS(t pgtype.Timestamptz) any {
	if !t.Valid {
		return nil
	}
	return t.Time.UTC().Format("2006-01-02T15:04:05.999999999Z07:00")
}

// jsonPtr JSONB 列（[]byte）→ any；空/坏值归一为 nil（契约 object 可空）。
func jsonPtr(b []byte) any {
	if len(b) == 0 {
		return nil
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return nil
	}
	return v
}

// datePtr DATE 列 → 'YYYY-MM-DD' 或 nil。
func datePtr(d pgtype.Date) any {
	if !d.Valid {
		return nil
	}
	return d.Time.Format("2006-01-02")
}

// ToAPIDict 把字典行映射为契约 Dict 形状。List/Get/GetByCode/Upsert 四个 Row
// 类型字段同构，类型开关统一取值。
func ToAPIDict(row any) map[string]any {
	type d struct {
		id                         int64
		code, name                 string
		tenantID                   int64
		remark                     *string
		creatorID, modifierID      *int64
		createdAt, updatedAt       pgtype.Timestamptz
	}
	var r d
	switch v := row.(type) {
	case store.ListDictsRow:
		r = d{v.ID, v.Code, v.Name, v.TenantID, v.Remark, v.CreatorID, v.ModifierID, v.CreatedAt, v.UpdatedAt}
	case store.GetDictRow:
		r = d{v.ID, v.Code, v.Name, v.TenantID, v.Remark, v.CreatorID, v.ModifierID, v.CreatedAt, v.UpdatedAt}
	case store.GetDictByCodeRow:
		r = d{v.ID, v.Code, v.Name, v.TenantID, v.Remark, v.CreatorID, v.ModifierID, v.CreatedAt, v.UpdatedAt}
	case store.UpsertDictRow:
		r = d{v.ID, v.Code, v.Name, v.TenantID, v.Remark, v.CreatorID, v.ModifierID, v.CreatedAt, v.UpdatedAt}
	}
	return map[string]any{
		"id":          r.id,
		"code":        r.code,
		"name":        r.name,
		"tenant_id":   r.tenantID,
		"remark":      r.remark,
		"creator_id":  r.creatorID,
		"modifier_id": r.modifierID,
		"created_at":  fmtTS(r.createdAt),
		"updated_at":  fmtTS(r.updatedAt),
	}
}

// ToAPIDictItem 映射 sys_dict_item → 契约 DictItem（ext_json→ext、i18n_json→i18n）。
func ToAPIDictItem(r store.DictItem) map[string]any {
	return map[string]any{
		"id":             r.ID,
		"dict_id":        r.DictID,
		"item_code":      r.ItemCode,
		"item_label":     r.ItemLabel,
		"parent_id":      r.ParentID,
		"ext":            jsonPtr(r.ExtJson),
		"i18n":           jsonPtr(r.I18nJson),
		"sort_no":        r.SortNo,
		"effective_from": datePtr(r.EffectiveFrom),
		"effective_to":   datePtr(r.EffectiveTo),
		"active":         r.Active,
		"tenant_id":      r.TenantID,
	}
}
