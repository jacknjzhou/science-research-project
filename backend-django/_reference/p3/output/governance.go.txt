// P5 成果治理：T16 期刊源库/级别/转载 + T17 网推推送池 + T18 专利生命周期。
package output

import (
	"errors"
	"net/http"
	"strconv"

	rstore "github.com/eplugger/ark/internal/modules/output/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

func govPathID(c *gin.Context) int64 {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	return id
}

// ---------- T16 期刊 ----------

// CreateJournalSource POST /journal-sources {name, issn, year_from, year_to}
func (h *Handler) CreateJournalSource(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Name     string  `json:"name" binding:"required"`
		ISSN     *string `json:"issn"`
		YearFrom *int32  `json:"year_from"`
		YearTo   *int32  `json:"year_to"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误："+err.Error())
		return
	}
	s, err := h.q.CreateJournalSource(c, rstore.CreateJournalSourceParams{
		TenantID: d.TenantID, Name: b.Name, Issn: b.ISSN, YearFrom: b.YearFrom, YearTo: b.YearTo,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": s.ID, "name": s.Name, "issn": s.Issn, "year_from": s.YearFrom, "year_to": s.YearTo})
}

// ListJournalSources GET /journal-sources?year= —— 年度窗口过滤（源覆盖该年即返回）。
func (h *Handler) ListJournalSources(c *gin.Context) {
	d := auth.DomainFrom(c)
	y := optQueryInt32(c, "year")
	var yv int32
	if y != nil {
		yv = *y
	}
	rows, err := h.q.ListJournalSources(c, rstore.ListJournalSourcesParams{
		TenantID: d.TenantID, Column2: yv, Column3: yv,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, s := range rows {
		out = append(out, gin.H{"id": s.ID, "name": s.Name, "issn": s.Issn, "year_from": s.YearFrom, "year_to": s.YearTo})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": int64(len(out))})
}

// CreateJournalLevel POST /journal-levels {code, name, paper_type, indexed}
func (h *Handler) CreateJournalLevel(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Code      string  `json:"code" binding:"required"`
		Name      string  `json:"name" binding:"required"`
		PaperType *string `json:"paper_type"`
		Indexed   *bool   `json:"indexed"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	indexed := true
	if b.Indexed != nil {
		indexed = *b.Indexed
	}
	l, err := h.q.CreateJournalLevel(c, rstore.CreateJournalLevelParams{
		TenantID: d.TenantID, Code: b.Code, Name: b.Name, PaperType: b.PaperType, Indexed: indexed,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": l.ID, "code": l.Code, "name": l.Name, "paper_type": l.PaperType, "indexed": l.Indexed})
}

// ListJournalLevels GET /journal-levels
func (h *Handler) ListJournalLevels(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListJournalLevels(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, l := range rows {
		out = append(out, gin.H{"id": l.ID, "code": l.Code, "name": l.Name, "paper_type": l.PaperType, "indexed": l.Indexed})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": int64(len(out))})
}

// AttachLevelSource POST /journal-levels/:id/sources {source_id, year_from, year_to}
func (h *Handler) AttachLevelSource(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		SourceID int64  `json:"source_id" binding:"required"`
		YearFrom *int32 `json:"year_from"`
		YearTo   *int32 `json:"year_to"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	id := govPathID(c)
	_, err := h.q.AttachLevelSource(c, rstore.AttachLevelSourceParams{
		TenantID: d.TenantID, LevelID: id, SourceID: b.SourceID, YearFrom: b.YearFrom, YearTo: b.YearTo,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "挂接失败")
		return
	}
	httpx.WriteOK(c, gin.H{"level_id": id, "source_id": b.SourceID})
}

// ResolveJournalLevel GET /journal-levels/resolve?name=&year= —— 未命中 200+null。
func (h *Handler) ResolveJournalLevel(c *gin.Context) {
	d := auth.DomainFrom(c)
	name := c.Query("name")
	year := optQueryInt32(c, "year")
	var yv int32
	if year != nil {
		yv = *year
	}
	rows, err := h.q.ResolveJournalLevel(c, rstore.ResolveJournalLevelParams{
		TenantID: d.TenantID, Name: name, Column3: yv,
	})
	if err != nil || len(rows) == 0 {
		httpx.WriteOK(c, nil)
		return
	}
	httpx.WriteOK(c, gin.H{"level_code": rows[0].Code, "level_name": rows[0].Name})
}

// CreateReprint POST /papers/:id/reprints {name, type, reprint_date, remark}
func (h *Handler) CreateReprint(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Name        string  `json:"name" binding:"required"`
		Type        *string `json:"type"`
		ReprintDate *string `json:"reprint_date"`
		Remark      *string `json:"remark"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	rp, err := h.q.CreatePaperReprint(c, rstore.CreatePaperReprintParams{
		TenantID: d.TenantID, OutputID: govPathID(c),
		Name: b.Name, Type: b.Type, ReprintDate: parseDatePtr(b.ReprintDate), Remark: b.Remark,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "登记失败")
		return
	}
	rd := dateOrNil(rp.ReprintDate)
	httpx.WriteOK(c, gin.H{"id": rp.ID, "output_id": rp.OutputID, "name": rp.Name, "type": rp.Type, "reprint_date": rd})
}

// ListReprints GET /papers/:id/reprints
func (h *Handler) ListReprints(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListPaperReprints(c, rstore.ListPaperReprintsParams{TenantID: d.TenantID, OutputID: govPathID(c)})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, rp := range rows {
		rd := dateOrNil(rp.ReprintDate)
		out = append(out, gin.H{"id": rp.ID, "name": rp.Name, "type": rp.Type, "reprint_date": rd, "remark": rp.Remark})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": int64(len(out))})
}

// ---------- T17 网推推送池 ----------

// ListPushItems GET /push-items?status=&type=
func (h *Handler) ListPushItems(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	status := optQuery(c, "status")
	typ := optQuery(c, "type")
	rows, err := h.q.ListPushItems(c, rstore.ListPushItemsParams{
		TenantID: d.TenantID, Status: status, Typ: typ, Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountPushItems(c, rstore.CountPushItemsParams{TenantID: d.TenantID, Status: status, Typ: typ})
	out := make([]map[string]any, 0, len(rows))
	for _, it := range rows {
		out = append(out, gin.H{
			"id": it.ID, "type": it.Type, "source_db": it.SourceDb, "title": it.Title,
			"authors": it.Authors, "year": it.Year, "raw_doi": it.RawDoi,
			"status": it.Status, "pushed_at": it.PushedAt.Time.Format("2006-01-02 15:04:05"),
		})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": total, "page": page, "size": size})
}

// ImportPushItem POST /push-items/:id/import?force=
// 查重：title_hash 精确命中 → 40905；相似标题（trigram）→ need_force；通过后导入 R_OUTPUT。
func (h *Handler) ImportPushItem(c *gin.Context) {
	d := auth.DomainFrom(c)
	it, err := h.q.GetPushItem(c, rstore.GetPushItemParams{ID: govPathID(c), TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "推送项不存在")
		return
	}
	if it.Status == "IGNORED" {
		httpx.WriteErr(c, http.StatusConflict, 40901, "已忽略项不可导入")
		return
	}
	if it.Status == "IMPORTED" {
		httpx.WriteErr(c, http.StatusConflict, 40901, "已导入")
		return
	}
	force := c.Query("force") == "true"

	// 1) 精确重复：title_hash 命中已有成果（40905 + existing_id）
	if ex, eerr := h.q.GetOutputByTitleHash(c, &it.DedupKey); eerr == nil && ex.ID > 0 {
		c.JSON(http.StatusConflict, gin.H{
			"code": 40905, "message": "精确重复成果已存在",
			"data": gin.H{"existing_id": ex.ID, "existing_title": ex.Title},
		})
		return
	}
	// 2) 相似标题（pg_trgm similarity）
	similar, _ := h.q.FindSimilarOutputs(c, it.Title)
	if len(similar) > 0 && !force {
		list := make([]gin.H, 0, len(similar))
		for _, s := range similar {
			list = append(list, gin.H{"id": s.ID, "title": s.Title, "status": s.Status})
		}
		httpx.WriteOK(c, gin.H{"similar": list, "need_force": true})
		return
	}
	// 3) 导入为 R_OUTPUT（AUTO_FETCHED；源库标记入 source）
	pub := pgtype.Date{}
	if it.Year != nil {
		_ = pub.Scan(int64(*it.Year))
	}
	o, ierr := h.q.CreatePushedOutput(c, rstore.CreatePushedOutputParams{
		TenantID: d.TenantID, CreatorID: d.UserID,
		OutputType: it.Type, Title: it.Title, Source: it.SourceDb, PublishDate: pub,
	})
	if ierr != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "导入失败："+ierr.Error())
		return
	}
	_ = h.q.MarkPushItemImported(c, rstore.MarkPushItemImportedParams{ID: it.ID, OutputID: &o.ID})
	httpx.WriteOK(c, gin.H{"output_id": o.ID, "status": "IMPORTED"})
}

// IgnorePushItem POST /push-items/:id/ignore（幂等）
func (h *Handler) IgnorePushItem(c *gin.Context) {
	d := auth.DomainFrom(c)
	if _, err := h.q.GetPushItem(c, rstore.GetPushItemParams{ID: govPathID(c), TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "推送项不存在")
		return
	}
	_ = h.q.MarkPushItemIgnored(c, govPathID(c))
	httpx.WriteOK(c, gin.H{"ignored": true})
}

// ---------- T18 专利 ----------

var STAGE_ORDER = map[string]int{
	"PRE_APPLY": 0, "APPLIED": 1, "PUBLISHED": 2, "GRANTED": 3, "TRANSFERRED": 4,
}

// SetPatentStage POST /patents/:id/stage {stage} —— 仅允许按序 +1 或原地幂等。
func (h *Handler) SetPatentStage(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Stage string `json:"stage" binding:"required"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	cur, err := h.q.GetPatentStage(c, rstore.GetPatentStageParams{ID: govPathID(c), TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, http.StatusNotFound, 40401, "专利不存在")
		return
	}
	next, ok := STAGE_ORDER[b.Stage]
	if !ok {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "stage 非法")
		return
	}
	if next != STAGE_ORDER[cur] && next != STAGE_ORDER[cur]+1 {
		httpx.WriteErr(c, http.StatusConflict, 40901, "阶段只能按序流转（当前 "+cur+"）")
		return
	}
	if _, err := h.q.SetPatentStage(c, rstore.SetPatentStageParams{ID: govPathID(c), Stage: b.Stage}); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "流转失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": govPathID(c), "stage": b.Stage})
}

// CreatePatentFee POST /patents/:id/fees {year, amount, paid_at, status}
func (h *Handler) CreatePatentFee(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Year   int32   `json:"year" binding:"required"`
		Amount string  `json:"amount" binding:"required"`
		PaidAt *string `json:"paid_at"`
		Status string  `json:"status"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	status := b.Status
	if status == "" {
		status = "UNPAID"
	}
	f, err := h.q.CreatePatentFee(c, rstore.CreatePatentFeeParams{
		TenantID: d.TenantID, PatentID: govPathID(c), Year: b.Year,
		Amount: numFromQuery2(b.Amount), PaidAt: parseDatePtr(b.PaidAt), Status: status,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "登记失败")
		return
	}
	paid := dateOrNil(f.PaidAt)
	httpx.WriteOK(c, gin.H{"id": f.ID, "patent_id": f.PatentID, "year": f.Year, "amount": f.Amount, "paid_at": paid, "status": f.Status})
}

// ListPatentFees GET /patents/:id/fees
func (h *Handler) ListPatentFees(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListPatentFees(c, rstore.ListPatentFeesParams{TenantID: d.TenantID, PatentID: govPathID(c)})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, f := range rows {
		paid := dateOrNil(f.PaidAt)
		out = append(out, gin.H{"id": f.ID, "year": f.Year, "amount": f.Amount, "paid_at": paid, "status": f.Status})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": int64(len(out))})
}

// CreateAgency POST /agencies；ListAgencies GET /agencies
func (h *Handler) CreateAgency(c *gin.Context) {
	d := auth.DomainFrom(c)
	var b struct {
		Name    string  `json:"name" binding:"required"`
		Contact *string `json:"contact"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "参数错误")
		return
	}
	a, err := h.q.CreateAgency(c, rstore.CreateAgencyParams{TenantID: d.TenantID, Name: b.Name, Contact: b.Contact})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "创建失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": a.ID, "name": a.Name, "contact": a.Contact})
}

func (h *Handler) ListAgencies(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListAgencies(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "查询失败")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, a := range rows {
		out = append(out, gin.H{"id": a.ID, "name": a.Name, "contact": a.Contact})
	}
	httpx.WriteOK(c, gin.H{"list": out, "total": int64(len(out))})
}

// numFromQuery 金额字符串 → pgtype.Numeric（复用 numFromQuery 语义但走显式字符串）。
func numFromQuery2(s string) pgtype.Numeric {
	var n pgtype.Numeric
	_ = n.Scan(s)
	return n
}

var _ = errors.Is
var _ = pgx.ErrNoRows

// dateOrNil pgtype.Date → "2006-01-02" 或 nil。
func dateOrNil(d pgtype.Date) any {
	if !d.Valid {
		return nil
	}
	return d.Time.Format("2006-01-02")
}
