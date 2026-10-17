// xlsx 模板生成 / 导入解析 / 选择性导出（excelize）。
package dataio

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/big"
	"net/http"
	"strings"
	"time"

	fstore "github.com/eplugger/ark/internal/modules/funding/store"
	nfstore "github.com/eplugger/ark/internal/modules/notify/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/xuri/excelize/v2"
)

const ModIncome = "funding.income"

// moduleSpec 模块注册表：表头 + 示例行 + 说明 + 行导入。
type moduleSpec struct {
	headers  []string
	sample   []string
	hints    []string
	importFn func(h *Handler, c *gin.Context, tenantID, userID int64, rows [][]string) (imported int, skipped int, errs []map[string]any, snapshot []string)
}

var specs = map[string]*moduleSpec{
	ModIncome: {
		headers: []string{"收款编号", "收款日期", "金额", "付款单位", "摘要", "银行流水号"},
		sample:  []string{"", "2026-01-15", "50000.00", "示例科技有限公司", "纵向课题 2026 年度拨款", "BK2026011500001"},
		hints: []string{
			"收款日期格式 YYYY-MM-DD；金额两位小数",
			"银行流水号必填且同租户唯一（重复行自动跳过，幂等）",
			"导入成功后可在「导入日志」中整体撤销（未认领状态下）",
		},
		importFn: importIncomeRows,
	},
}

// Template GET /dataio/template?module=
func (h *Handler) Template(c *gin.Context) {
	spec, ok := specs[c.Query("module")]
	if !ok {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "未知模块，支持："+joinKeys(specs))
		return
	}
	f := excelize.NewFile()
	sheet := "导入模板"
	f.SetSheetName("Sheet1", sheet)
	for i, hd := range spec.headers {
		cell, _ := excelize.CoordinatesToCellName(i+1, 1)
		_ = f.SetCellValue(sheet, cell, hd)
	}
	for i, v := range spec.sample {
		cell, _ := excelize.CoordinatesToCellName(i+1, 2)
		_ = f.SetCellValue(sheet, cell, v)
	}
	if _, err := f.NewSheet("校验说明"); err == nil {
		for i, hint := range spec.hints {
			cell, _ := excelize.CoordinatesToCellName(1, i+1)
			_ = f.SetCellValue("校验说明", cell, hint)
		}
	}
	buf, err := f.WriteToBuffer()
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "模板生成失败")
		return
	}
	c.DataFromReader(http.StatusOK, int64(buf.Len()),
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		bytes.NewReader(buf.Bytes()), nil)
}

// Import POST /dataio/import?module= （multipart 字段 file）
func (h *Handler) Import(c *gin.Context) {
	d := auth.DomainFrom(c)
	mod := c.Query("module")
	spec, ok := specs[mod]
	if !ok {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "未知模块，支持："+joinKeys(specs))
		return
	}
	fh, err := c.FormFile("file")
	if err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "multipart 字段 file 必填")
		return
	}
	src, err := fh.Open()
	if err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "文件读取失败")
		return
	}
	defer src.Close()
	xl, err := excelize.OpenReader(src)
	if err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "仅支持 xlsx 格式")
		return
	}
	sheet := xl.GetSheetList()[0]
	table, err := xl.Rows(sheet)
	if err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "工作表读取失败")
		return
	}
	var body [][]string
	first := true
	for table.Next() {
		row, _ := table.Columns()
		if first {
			first = false
			continue
		}
		if isBlankRow(row) {
			continue
		}
		body = append(body, row)
	}
	if len(body) == 0 {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "无数据行")
		return
	}
	imported, skipped, errs, snapshot := spec.importFn(h, c, d.TenantID, d.UserID, body)
	snapBytes, _ := json.Marshal(snapshot)
	if _, err := h.nf.InsertImportLog(c, nfstore.InsertImportLogParams{
		TenantID: d.TenantID, Module: mod,
		RowCount: int32(len(body)), SuccessCount: int32(imported), FailCount: int32(len(errs)),
		OperatorID: d.UserID, Snapshot: snapBytes,
	}); err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "导入日志写入失败")
		return
	}
	httpx.WriteOK(c, gin.H{"imported": imported, "skipped": skipped, "errors": errs})
}

// Export POST /dataio/export {module, fields[], kw?, claim_status?}
// fields 允许选择性字段与顺序；缺省全字段。
func (h *Handler) Export(c *gin.Context) {
	d := auth.DomainFrom(c)
	var body struct {
		Module      string   `json:"module" binding:"required"`
		Fields      []string `json:"fields"`
		Kw          *string  `json:"kw"`
		ClaimStatus *string  `json:"claim_status"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "module 必填")
		return
	}
	if body.Module != ModIncome {
		httpx.WriteErr(c, http.StatusBadRequest, 40001, "该模块暂不支持导出")
		return
	}
	fields := body.Fields
	if len(fields) == 0 {
		fields = INCOME_EXPORT_FIELDS
	}
	rows, err := h.fs.ListIncomes(c, fstore.ListIncomesParams{
		TenantID: d.TenantID, Kw: body.Kw, ClaimStatus: body.ClaimStatus,
		ProjectID: nil, Limit: 10000, Offset: 0,
	})
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "导出查询失败")
		return
	}
	f := excelize.NewFile()
	sheet := "导出结果"
	f.SetSheetName("Sheet1", sheet)
	valid := map[string]bool{}
	for _, fl := range INCOME_EXPORT_FIELDS {
		valid[fl] = true
	}
	cols := make([]string, 0, len(fields))
	for _, fl := range fields {
		if valid[fl] {
			cols = append(cols, fl)
		}
	}
	for i, fl := range cols {
		cell, _ := excelize.CoordinatesToCellName(i+1, 1)
		_ = f.SetCellValue(sheet, cell, INCOME_EXPORT_LABEL[fl])
	}
	for r, e := range rows {
		rec := incomeRecord(e)
		for i, fl := range cols {
			cell, _ := excelize.CoordinatesToCellName(i+1, r+2)
			_ = f.SetCellValue(sheet, cell, rec[fl])
		}
	}
	buf, err := f.WriteToBuffer()
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50002, "导出失败")
		return
	}
	filename := "income_export_" + time.Now().Format("20060102150405") + ".xlsx"
	c.Header("Content-Disposition", "attachment; filename="+filename)
	c.DataFromReader(http.StatusOK, int64(buf.Len()),
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		bytes.NewReader(buf.Bytes()), nil)
}

// —— funding.income 行导入（幂等：bank_flow_no 同租户唯一）——

func importIncomeRows(h *Handler, c *gin.Context, tenantID, userID int64, rows [][]string) (int, int, []map[string]any, []string) {
	var imported, skipped int
	var errs []map[string]any
	var snapshot []string
	for i, row := range rows {
		lineNo := i + 2 // xlsx 行号（含表头）
		if len(row) < 6 {
			errs = append(errs, gin.H{"row": lineNo, "error": "列数不足 6"})
			continue
		}
		flowNo := strings.TrimSpace(row[5])
		if flowNo == "" {
			errs = append(errs, gin.H{"row": lineNo, "error": "银行流水号必填"})
			continue
		}
		amount := strings.TrimSpace(row[2])
		amt, ok := parseNumeric(amount)
		if !ok {
			errs = append(errs, gin.H{"row": lineNo, "error": "金额非法：" + amount})
			continue
		}
		exists, err := h.fs.IncomeFlowNoExists(c, fstore.IncomeFlowNoExistsParams{
			TenantID: tenantID, BankFlowNo: &flowNo,
		})
		if err != nil {
			errs = append(errs, gin.H{"row": lineNo, "error": "幂等检查失败"})
			continue
		}
		if exists {
			skipped++
			continue
		}
		_, err = h.fs.CreateIncome(c, fstore.CreateIncomeParams{
			TenantID: tenantID, CreatorID: userID, LegalEntityID: 1,
			ReceiptNo:   optText(strings.TrimSpace(row[0])),
			ReceiptDate: datePtr(strings.TrimSpace(row[1])),
			Amount:      amt,
			PayerName:   optText(strings.TrimSpace(row[3])),
			PurposeText: optText(strings.TrimSpace(row[4])),
			BankFlowNo:  &flowNo,
		})
		if err != nil {
			errs = append(errs, gin.H{"row": lineNo, "error": "入库失败：" + err.Error()})
			continue
		}
		imported++
		snapshot = append(snapshot, flowNo)
	}
	return imported, skipped, errs, snapshot
}

// —— 工具 ——

var INCOME_EXPORT_FIELDS = []string{
	"id", "code", "receipt_no", "receipt_date", "amount",
	"payer_name", "purpose_text", "bank_flow_no", "claim_status", "created_at",
}

var INCOME_EXPORT_LABEL = map[string]string{
	"id": "ID", "code": "到款编号", "receipt_no": "收款编号", "receipt_date": "收款日期",
	"amount": "金额", "payer_name": "付款单位", "purpose_text": "摘要",
	"bank_flow_no": "银行流水号", "claim_status": "认领状态", "created_at": "创建时间",
}

func incomeRecord(e fstore.FIncome) map[string]string {
	str := func(p *string) string {
		if p != nil {
			return *p
		}
		return ""
	}
	recDate := ""
	if e.ReceiptDate != nil {
		recDate = e.ReceiptDate.Format("2006-01-02")
	}
	return map[string]string{
		"id": fmt.Sprint(e.ID), "code": str(e.Code),
		"receipt_no": str(e.ReceiptNo), "receipt_date": recDate,
		"amount": numericDec(e.Amount), "payer_name": str(e.PayerName),
		"purpose_text": str(e.PurposeText), "bank_flow_no": str(e.BankFlowNo),
		"claim_status": e.ClaimStatus,
		"created_at":   e.CreatedAt.Format("2006-01-02 15:04:05"),
	}
}

// parseNumeric 金额字符串 → pgtype.Numeric。
func parseNumeric(s string) (pgtype.Numeric, bool) {
	var n pgtype.Numeric
	if err := n.Scan(s); err != nil {
		return n, false
	}
	return n, true
}

// numericDec NUMERIC → 两位小数字符串（NULL → "0.00"）。pgtype.Numeric = Int × 10^Exp。
func numericDec(n pgtype.Numeric) string {
	if !n.Valid || n.Int == nil {
		return "0.00"
	}
	r := new(big.Rat).SetInt(n.Int)
	if n.Exp >= 0 {
		r.Mul(r, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(n.Exp)), nil)))
	} else {
		r.Quo(r, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(-n.Exp)), nil)))
	}
	return r.FloatString(2)
}

func isBlankRow(row []string) bool {
	for _, v := range row {
		if strings.TrimSpace(v) != "" {
			return false
		}
	}
	return true
}

func datePtr(s string) *time.Time {
	if s == "" {
		return nil
	}
	if t, err := time.Parse("2006-01-02", s); err == nil {
		return &t
	}
	return nil
}

func tsPtr(s string) pgtype.Timestamptz {
	var t pgtype.Timestamptz
	if s != "" {
		if v, err := time.Parse("2006-01-02", s); err == nil {
			_ = t.Scan(v)
		}
	}
	return t
}

func joinKeys(m map[string]*moduleSpec) string {
	ks := make([]string, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	return strings.Join(ks, " | ")
}
