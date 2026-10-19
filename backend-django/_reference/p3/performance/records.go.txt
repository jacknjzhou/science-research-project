package performance

import (
	"strconv"

	mstore "github.com/eplugger/ark/internal/modules/performance/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

var managerRoles = map[string]bool{"R-ADMIN": true, "R-MANAGER": true, "R-LEADER": true}
var payoutRoles = map[string]bool{"R-ADMIN": true, "R-MANAGER": true, "R-LEADER": true, "R-FINANCE": true}

func isManager(d auth.Domain) bool {
	for _, r := range d.Roles {
		if managerRoles[r] {
			return true
		}
	}
	return false
}

func canPayout(d auth.Domain) bool {
	for _, r := range d.Roles {
		if payoutRoles[r] {
			return true
		}
	}
	return false
}

// —— 记录列表 ——
func (h *Handler) ListRecords(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	var kw *string
	if v := optQuery(c, "keyword"); v != nil {
		w := "%" + *v + "%"
		kw = &w
	}
	// ABAC：非管理强制本人；管理可用查询里的 staff_user_id（可空=全部）。
	staff := optInt64(c, "staff_user_id")
	if !isManager(d) {
		uid := d.UserID
		staff = &uid
	}
	p := mstore.ListRecordsParams{
		TenantID: d.TenantID, SchemeID: optInt64(c, "scheme_id"), Period: optQuery(c, "period"),
		DeptID: optInt64(c, "dept_id"), StaffUserID: staff, Status: optQuery(c, "status"),
		Code: kw, Offset: offset, Limit: limit,
	}
	rows, err := h.q.ListRecords(c, p)
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	cp := mstore.CountRecordsParams{
		TenantID: d.TenantID, SchemeID: optInt64(c, "scheme_id"), Period: optQuery(c, "period"),
		DeptID: optInt64(c, "dept_id"), StaffUserID: staff, Status: optQuery(c, "status"), Code: kw,
	}
	total, _ := h.q.CountRecords(c, cp)
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIRecord(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// readRecordForABAC：取记录 + 判存在 + 判越权。ok=false 时已写响应。
func (h *Handler) readRecordForABAC(c *gin.Context, id int64, mgrOnly bool) (mstore.Record, bool) {
	d := auth.DomainFrom(c)
	rec, err := h.q.GetRecord(c, mstore.GetRecordParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "记录不存在")
		return mstore.Record{}, false
	}
	if mgrOnly {
		if !isManager(d) {
			httpx.WriteErr(c, 403, 40301, "无权限：需管理角色")
			return mstore.Record{}, false
		}
		return rec, true
	}
	if !isManager(d) && rec.StaffUserID != d.UserID {
		httpx.WriteErr(c, 403, 40301, "越权：只能访问本人记录")
		return mstore.Record{}, false
	}
	return rec, true
}

func (h *Handler) GetRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	rec, ok := h.readRecordForABAC(c, id, false)
	if !ok {
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) GetRecordDetail(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	rec, ok := h.readRecordForABAC(c, id, false)
	if !ok {
		return
	}
	items, _ := h.q.ListItems(c, rec.ID)
	httpx.WriteOK(c, ToAPIRecordDetail(rec, items))
}

func (h *Handler) ConfirmRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if _, ok := h.readRecordForABAC(c, id, false); !ok {
		return
	}
	rec, err := h.q.ConfirmRecord(c, mstore.ConfirmRecordParams{ID: id, TenantID: d.TenantID, ConfirmedBy: &d.UserID})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 CALCULATED 可确认）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) AppealRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	var body struct {
		Reason string `json:"reason" binding:"required"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	if _, ok := h.readRecordForABAC(c, id, false); !ok {
		return
	}
	reason := body.Reason
	rec, err := h.q.AppealRecord(c, mstore.AppealRecordParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID, AppealReason: &reason})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 CALCULATED/CONFIRMED 可申诉）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) ApproveRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if _, ok := h.readRecordForABAC(c, id, true); !ok { // mgrOnly
		return
	}
	rec, err := h.q.ApproveRecord(c, mstore.ApproveRecordParams{ID: id, TenantID: d.TenantID, ApproveBy: &d.UserID})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 CONFIRMED 可审批）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

func (h *Handler) VoidRecord(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	var body struct {
		Reason *string `json:"reason"`
	}
	_ = c.ShouldBindJSON(&body) // void body 可选
	if _, ok := h.readRecordForABAC(c, id, true); !ok {
		return
	}
	rec, err := h.q.VoidRecord(c, mstore.VoidRecordParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID, VoidReason: body.Reason})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（已发放记录不可作废）")
		return
	}
	httpx.WriteOK(c, ToAPIRecord(rec))
}

// —— 发放单 ——
func (h *Handler) ListPayouts(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	payee := optInt64(c, "payee_user_id")
	if !canPayout(d) {
		uid := d.UserID
		payee = &uid
	}
	rows, err := h.q.ListPayouts(c, mstore.ListPayoutsParams{
		TenantID: d.TenantID, Period: optQuery(c, "period"), Status: optQuery(c, "status"),
		PayeeUserID: payee, Offset: offset, Limit: limit,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountPayouts(c, mstore.CountPayoutsParams{
		TenantID: d.TenantID, Period: optQuery(c, "period"), Status: optQuery(c, "status"), PayeeUserID: payee,
	})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIPayout(r))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetPayout：读单张发放单。非发放角色只能看本人（payee_user_id=本人）。
func (h *Handler) GetPayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	p, err := h.q.GetPayout(c, mstore.GetPayoutParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "发放单不存在")
		return
	}
	if !canPayout(d) && p.PayeeUserID != d.UserID {
		httpx.WriteErr(c, 403, 40301, "越权：只能访问本人发放单")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) CreatePayout(c *gin.Context) {
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限：需发放权限角色")
		return
	}
	var b struct {
		RecordID   int64  `json:"record_id" binding:"required"`
		Amount     string `json:"amount" binding:"required"`
		PayChannel *string `json:"pay_channel"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	rec, err := h.q.GetRecord(c, mstore.GetRecordParams{ID: b.RecordID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "记录不存在")
		return
	}
	if rec.Status != "APPROVED" {
		httpx.WriteErr(c, 409, 40901, "仅 APPROVED 记录可发起发放")
		return
	}
	p, err := h.q.CreatePayout(c, mstore.CreatePayoutParams{
		TenantID: d.TenantID, CreatorID: d.UserID, RecordID: rec.ID, PayeeUserID: rec.StaffUserID,
		Column5: numeric(strPtr(b.Amount)), Period: strPtr(rec.Period), PayChannel: b.PayChannel, Column8: "INTERNAL",
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50002, "创建发放单失败")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) ApprovePayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限")
		return
	}
	p, err := h.q.ApprovePayout(c, mstore.ApprovePayoutParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 DRAFT/APPROVING 可审批）")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) PayPayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限")
		return
	}
	var body struct {
		VoucherCode *string `json:"voucher_code"`
	}
	_ = c.ShouldBindJSON(&body)
	p, err := h.q.PayPayout(c, mstore.PayPayoutParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID, VoucherCode: body.VoucherCode})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 APPROVED 可发放）")
		return
	}
	// 联动记录 → PAID（尽力而为，态不符忽略）。
	_, _ = h.q.MarkRecordPaid(c, mstore.MarkRecordPaidParams{ID: p.RecordID, TenantID: d.TenantID})
	httpx.WriteOK(c, ToAPIPayout(p))
}

func (h *Handler) RejectPayout(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	d := auth.DomainFrom(c)
	if !canPayout(d) {
		httpx.WriteErr(c, 403, 40301, "无权限")
		return
	}
	var body struct {
		Reason *string `json:"reason"`
	}
	_ = c.ShouldBindJSON(&body)
	p, err := h.q.RejectPayout(c, mstore.RejectPayoutParams{ID: id, TenantID: d.TenantID, ModifierID: &d.UserID, RejectReason: body.Reason})
	if err != nil {
		httpx.WriteErr(c, 409, 40901, "非法状态迁移（仅 DRAFT/APPROVING 可驳回）")
		return
	}
	httpx.WriteOK(c, ToAPIPayout(p))
}

// —— 个人视图 / 排行 ——
func (h *Handler) MyPerformance(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListMyRecords(c, mstore.ListMyRecordsParams{
		TenantID: d.TenantID, StaffUserID: d.UserID, Period: optQuery(c, "period"),
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		items, _ := h.q.ListItems(c, r.ID)
		list = append(list, ToAPIRecordDetail(r, items))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

func (h *Handler) PerfRanking(c *gin.Context) {
	d := auth.DomainFrom(c)
	if !isManager(d) {
		httpx.WriteErr(c, 403, 40301, "无权限：排行仅管理角色可见")
		return
	}
	schemeID := optInt64(c, "scheme_id")
	period := optQuery(c, "period")
	if schemeID == nil || period == nil {
		httpx.WriteErr(c, 400, 40001, "缺少 scheme_id / period")
		return
	}
	top := int32(20)
	if v := c.Query("top"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			if n > 500 {
				n = 500
			}
			top = int32(n)
		}
	}
	rows, err := h.q.RankedRecords(c, mstore.RankedRecordsParams{
		TenantID: d.TenantID, SchemeID: *schemeID, Period: *period, Limit: top,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIRank(r))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}
