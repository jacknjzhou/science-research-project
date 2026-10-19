package performance

import (
	"encoding/json"
	"strconv"
	"time"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Handler 同时持 pool：ActivateScheme 的两步（Supersede+Activate）须在一个事务内，
// sqlc 生成的是 `Queries.WithTx(tx pgx.Tx) *Queries`（不是回调式），需从 pool Begin 出 tx。
type Handler struct {
	q     *mstore.Queries
	pool  *pgxpool.Pool
}

func NewHandler(pool *pgxpool.Pool) *Handler { return &Handler{q: mstore.New(pool), pool: pool} }

// —— 共享助手 ——
func pageArgs(c *gin.Context) (page, size, limit, offset int32) {
	p, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	s, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if p < 1 {
		p = 1
	}
	if s < 1 {
		s = 20
	}
	if s > 200 {
		s = 200
	}
	return int32(p), int32(s), int32(s), int32((p - 1) * s)
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

func optInt64(c *gin.Context, k string) *int64 {
	if v := c.Query(k); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return &n
		}
	}
	return nil
}

func pathID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "非法 id")
		return 0, false
	}
	return id, true
}

func jsonOrEmpty(b json.RawMessage, def string) []byte {
	if len(b) == 0 {
		return []byte(def)
	}
	return b
}

func numeric(s *string) pgtype.Numeric {
	var n pgtype.Numeric
	if s != nil && *s != "" {
		_ = n.Scan(*s)
	}
	return n
}

// —— 方案请求体 ——
type schemeBody struct {
	Name            string  `json:"name" binding:"required"`
	PeriodType      string  `json:"period_type" binding:"required"`
	EffectivePeriod string  `json:"effective_period" binding:"required"`
	ScopeDeptID     *int64  `json:"scope_dept_id"`
	ScopeStaffType  *string `json:"scope_staff_type"`
	SecurityLevel   *string `json:"security_level"`
	LegalEntityID   *int64  `json:"legal_entity_id"`
	PolicyPackID    *int64  `json:"policy_pack_id"`
	Remark          *string `json:"remark"`
}

// —— 因子请求体 ——
type factorBody struct {
	FactorCode  string          `json:"factor_code" binding:"required"`
	FactorName  *string         `json:"factor_name"`
	Weight      *string         `json:"weight"`
	ScoringRule json.RawMessage `json:"scoring_rule" binding:"required"`
	MaxScore    *string         `json:"max_score"`
	DataSource  string          `json:"data_source" binding:"required"`
	ClauseRef   *string         `json:"clause_ref"`
	SortNo      *int32          `json:"sort_no"`
}

// —— 方案 handler ——
func (h *Handler) ListSchemes(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	rows, err := h.q.ListSchemes(c, mstore.ListSchemesParams{
		TenantID: d.TenantID, PeriodType: optQuery(c, "period_type"),
		EffectivePeriod: optQuery(c, "effective_period"), ScopeDeptID: optInt64(c, "scope_dept_id"),
		Status: optQuery(c, "status"), Name: optQuery(c, "keyword"),
		Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountSchemes(c, mstore.CountSchemesParams{
		TenantID: d.TenantID, PeriodType: optQuery(c, "period_type"),
		EffectivePeriod: optQuery(c, "effective_period"), ScopeDeptID: optInt64(c, "scope_dept_id"),
		Status: optQuery(c, "status"), Name: optQuery(c, "keyword"),
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIScheme(r)) // ListSchemes SELECT * → []mstore.Scheme，无需转换
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

func (h *Handler) GetScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	s, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	factors, _ := h.q.ListFactors(c, id)
	out := ToAPIScheme(s)
	fl := make([]map[string]any, 0, len(factors))
	for _, f := range factors {
		fl = append(fl, ToAPIFactor(f))
	}
	out["factors"] = fl
	httpx.WriteOK(c, out)
}

func (h *Handler) CreateScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b schemeBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	s, err := h.q.CreateScheme(c, mstore.CreateSchemeParams{
		TenantID: d.TenantID, CreatorID: d.UserID, Column3: coalesceStr(b.SecurityLevel, "INTERNAL"),
		LegalEntityID: b.LegalEntityID, PolicyPackID: b.PolicyPackID,
		Name: b.Name, PeriodType: b.PeriodType, ScopeDeptID: b.ScopeDeptID,
		ScopeStaffType: b.ScopeStaffType, EffectivePeriod: b.EffectivePeriod, Remark: b.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建失败")
		return
	}
	// M0 回写 code（PERF-年-id 补零）；生产替换为 svc-numbering 分配
	code := "PERF-" + strconv.Itoa(yearOf(s.CreatedAt)) + "-" + zeroPad(s.ID, 6)
	httpx.WriteOK(c, ToAPIScheme(withSchemeCode(s, code)))
}

func (h *Handler) UpdateScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	var b schemeBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	s, err := h.q.UpdateScheme(c, mstore.UpdateSchemeParams{
		ID: id, TenantID: d.TenantID, Column3: b.Name, Column4: b.PeriodType,
		Column5: derefI64(b.ScopeDeptID), Column6: coalesceStr(b.ScopeStaffType, ""),
		Column7: b.EffectivePeriod, Column8: coalesceStr(b.Remark, ""), ModifierID: &d.UserID,
	})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "方案不存在或状态不可编辑（仅 DRAFT）")
		return
	}
	httpx.WriteOK(c, ToAPIScheme(s)) // UpdateScheme RETURNING * → mstore.Scheme
}

func (h *Handler) DeleteScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	n, err := h.q.SoftDeleteScheme(c, mstore.SoftDeleteSchemeParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}

// ActivateScheme：同维度旧 active → SUPERSEDED，本方案 → ACTIVE（一个事务内两步）。
func (h *Handler) ActivateScheme(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	s, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	tx, err := h.pool.Begin(c) // gin.Context 满足 context.Context
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "启用失败：开启事务出错")
		return
	}
	defer func() { _ = tx.Rollback(c) }() // Commit 后 Rollback 返回 ErrTxClosed，忽略
	qtx := h.q.WithTx(tx)                // sqlc 生成：返回绑定该 tx 的新 Queries
	if err := qtx.SupersedeActiveInScope(c, mstore.SupersedeActiveInScopeParams{
		TenantID: d.TenantID, PeriodType: s.PeriodType, EffectivePeriod: s.EffectivePeriod,
		Column4: derefI64(s.ScopeDeptID), Column5: coalesceStr(s.ScopeStaffType, ""),
	}); err != nil {
		httpx.WriteErr(c, 409, 40901, "启用失败："+err.Error())
		return
	}
	if _, err := qtx.ActivateScheme(c, mstore.ActivateSchemeParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID}); err != nil {
		httpx.WriteErr(c, 409, 40901, "启用失败："+err.Error())
		return
	}
	if err := tx.Commit(c); err != nil {
		httpx.WriteErr(c, 500, 50002, "启用失败：提交出错")
		return
	}
	out, _ := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID})
	httpx.WriteOK(c, ToAPIScheme(out))
}

// —— 因子 handler ——
func (h *Handler) ListFactors(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	if _, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	rows, err := h.q.ListFactors(c, id)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, f := range rows {
		list = append(list, ToAPIFactor(f))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

func (h *Handler) UpsertFactor(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	if _, err := h.q.GetScheme(c, mstore.GetSchemeParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "方案不存在")
		return
	}
	var b factorBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	f, err := h.q.UpsertFactor(c, mstore.UpsertFactorParams{
		SchemeID: id, TenantID: d.TenantID, CreatorID: d.UserID, FactorCode: b.FactorCode,
		FactorName: b.FactorName, Column6: numeric(b.Weight), Column7: jsonOrEmpty(b.ScoringRule, "{}"),
		MaxScore: numeric(b.MaxScore), DataSource: b.DataSource, ClauseRef: b.ClauseRef, Column11: derefI32(b.SortNo),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "保存因子失败")
		return
	}
	httpx.WriteOK(c, ToAPIFactor(f))
}

func (h *Handler) UpdateFactor(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	fid, ok2 := pathID2(c, "factorId")
	if !ok2 {
		return
	}
	var b factorBody
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	f, err := h.q.UpdateFactor(c, mstore.UpdateFactorParams{
		ID: fid, SchemeID: id, TenantID: d.TenantID, Column4: coalesceStr(b.FactorName, ""),
		Column5: numeric(b.Weight), Column6: jsonOrEmpty(b.ScoringRule, "{}"), Column7: numeric(b.MaxScore),
		Column8: b.DataSource, Column9: coalesceStr(b.ClauseRef, ""), Column10: derefI32(b.SortNo),
	})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "因子不存在")
		return
	}
	httpx.WriteOK(c, ToAPIFactor(f))
}

func (h *Handler) DeleteFactor(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, ok := pathID(c)
	if !ok {
		return
	}
	fid, ok2 := pathID2(c, "factorId")
	if !ok2 {
		return
	}
	n, err := h.q.DeleteFactor(c, mstore.DeleteFactorParams{ID: fid, SchemeID: id, TenantID: d.TenantID})
	if err != nil || n == 0 {
		httpx.WriteErr(c, 404, 40401, "因子不存在")
		return
	}
	httpx.WriteOK(c, gin.H{"factor_id": fid, "deleted": true})
}

// —— 小助手：解引用/构造 ——
func deref(s *string) *string         { return s }
func derefI32(v *int32) int32         { if v != nil { return *v }; return 0 }
func strPtr(s string) *string         { return &s }

func pathID2(c *gin.Context, name string) (int64, bool) {
	id, err := strconv.ParseInt(c.Param(name), 10, 64)
	if err != nil || id <= 0 {
		httpx.WriteErr(c, 400, 40001, "非法 "+name)
		return 0, false
	}
	return id, true
}

func yearOf(t time.Time) int { return t.Year() }

func zeroPad(v int64, width int) string {
	s := strconv.FormatInt(v, 10)
	for len(s) < width {
		s = "0" + s
	}
	return s
}

// withSchemeCode：CreateScheme RETURNING 无 code（IDENTITY 先行、code 后写），
// M0 演示直接以 Go 侧回写值构造 map，省一次 UPDATE。若 mstore.Scheme 无 Code 字段可赋值处，
// 则 ToAPIScheme 用生成行 + 覆盖 code。见下 ToAPISchemeWithCode。
func withSchemeCode(s mstore.Scheme, code string) mstore.Scheme {
	s.Code = &code
	return s
}

// coalesceStr：*string→string，nil/空串取默认（用于 sqlc 把 COALESCE($n::text,...) 参数生成成
// 非指针 string 的位，如 CreateScheme.Column3(security_level 默认 INTERNAL)）。
func coalesceStr(s *string, def string) string {
	if s == nil || *s == "" {
		return def
	}
	return *s
}

// derefI64：*int64→int64，nil 取 0（用于 COALESCE 位如 scope_dept_id 生成成非指针 int64 的列）。
func derefI64(v *int64) int64 {
	if v == nil {
		return 0
	}
	return *v
}
