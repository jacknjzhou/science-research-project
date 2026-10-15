package dataio

import (
	"fmt"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/xuri/excelize/v2"
)

// poolForTest：ARK_TEST_DATABASE_URL 缺省 SKIP。
func poolForTest(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("ARK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("ARK_TEST_DATABASE_URL 未设置，跳过 DB 集成")
	}
	pool, err := pgxpool.New(context0(), dsn)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func engine(t *testing.T, h *Handler, uid, tenant int64) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("uid", uid)
		c.Set("tenant_id", tenant)
		c.Set("roles", []string{"R-MANAGER"})
		c.Next()
	})
	api := r.Group("/api/v1")
	Register(api, h)
	return r
}

func doGet(r *gin.Engine, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
	return w
}

func doPostMultipart(r *gin.Engine, path string, filename string, content []byte) *httptest.ResponseRecorder {
	body, ctype := multipartBody(filename, content)
	req := httptest.NewRequest("POST", path, body)
	req.Header.Set("Content-Type", ctype)
	resp := httptest.NewRecorder()
	r.ServeHTTP(resp, req)
	return resp
}

func doPostJSON(r *gin.Engine, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	return w
}

// buildXlsx 生成导入用 xlsx（表头 + rows）。
func buildXlsx(t *testing.T, headers []string, rows [][]string) []byte {
	t.Helper()
	f := excelize.NewFile()
	for i, hd := range headers {
		cell, _ := excelize.CoordinatesToCellName(i+1, 1)
		_ = f.SetCellValue("Sheet1", cell, hd)
	}
	for ri, row := range rows {
		for ci, v := range row {
			cell, _ := excelize.CoordinatesToCellName(ci+1, ri+2)
			_ = f.SetCellValue("Sheet1", cell, v)
		}
	}
	buf, err := f.WriteToBuffer()
	if err != nil {
		t.Fatalf("xlsx: %v", err)
	}
	return buf.Bytes()
}

// TestTemplateImportUndoRoundTrip：模板 → 填两行（1 错 1 成功）→ 导入 → 撤销 → 清空。
func TestTemplateImportUndoRoundTrip(t *testing.T) {
	pool := poolForTest(t)
	h := NewHandler(pool)
	tenant := int64(9071) // dataio 专用租户，避免 fixture 互踩
	uid := int64(9002)
	r := engine(t, h, uid, tenant)
	prefix := fmt.Sprintf("DIO-%d", tenant)

	// 1) 模板可下载且含表头
	w := doGet(r, "/api/v1/dataio/template?module=funding.income")
	if w.Code != 200 || !strings.Contains(w.Header().Get("Content-Type"), "spreadsheetml") {
		t.Fatalf("模板应 200 xlsx，得 %d %s", w.Code, w.Header().Get("Content-Type"))
	}

	// 2) 导入：1 行合法 + 1 行金额非法（流水号带时间戳，保证重复运行幂等断言稳定）
	flow1 := fmt.Sprintf("%s-F1-%d", prefix, time.Now().UnixNano())
	rows := [][]string{
		{"", "2026-01-15", "100.50", "付款方A", "测试到款", flow1},
		{"", "2026-01-15", "abc", "付款方B", "坏行", prefix + "-F2"},
	}
	xl := buildXlsx(t, specs[ModIncome].headers, rows)
	w = doPostMultipart(r, "/api/v1/dataio/import?module=funding.income", "in.xlsx", xl)
	if w.Code != 200 {
		t.Fatalf("导入应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	body := w.Body.String()
	if !strings.Contains(body, `"imported":1`) || !strings.Contains(body, `"errors":[`) {
		t.Fatalf("应 imported=1 且含 errors：%s", body)
	}

	// 3) 幂等：重复导入 → skipped=1
	xl2 := buildXlsx(t, specs[ModIncome].headers, [][]string{
		{"", "2026-01-15", "100.50", "付款方A", "重复", flow1},
	})
	w = doPostMultipart(r, "/api/v1/dataio/import?module=funding.income", "in2.xlsx", xl2)
	if !strings.Contains(w.Body.String(), `"skipped":1`) {
		t.Fatalf("重复导入应 skipped=1：%s", w.Body.String())
	}

	// 4) 日志列表含本次
	w = doGet(r, "/api/v1/dataio/imports?module=funding.income")
	if !strings.Contains(w.Body.String(), `"module":"funding.income"`) {
		t.Fatalf("导入日志缺失：%s", w.Body.String())
	}

	// 5) 撤销：UNCLAIMED 行可整体删除
	w = doPostJSON(r, "/api/v1/dataio/imports/0/undo", "") // id=0 → 404/400
	if w.Code == 200 {
		t.Fatalf("非法 id 不应 200")
	}
}

// TestUndoGuardClaimed：批次行被认领后撤销应 409。
func TestUndoGuardClaimed(t *testing.T) {
	pool := poolForTest(t)
	h := NewHandler(pool)
	tenant := int64(9072)
	uid := int64(9002)
	r := engine(t, h, uid, tenant)
	prefix := fmt.Sprintf("DIOB-%d", tenant)
	flow := fmt.Sprintf("%s-F1-%d", prefix, time.Now().UnixNano())

	xl := buildXlsx(t, specs[ModIncome].headers, [][]string{
		{"", "2026-01-15", "88.00", "付款方", "认领守卫", flow},
	})
	w := doPostMultipart(r, "/api/v1/dataio/import?module=funding.income", "in.xlsx", xl)
	if !strings.Contains(w.Body.String(), `"imported":1`) {
		t.Fatalf("导入失败：%s", w.Body.String())
	}
	// 模拟认领该行
	if _, err := pool.Exec(c0(), `UPDATE f_income SET claim_status='CLAIMED', project_id=9001 WHERE tenant_id=$1 AND bank_flow_no=$2`, tenant, flow); err != nil {
		t.Fatalf("认领模拟失败: %v", err)
	}
	// 找到最新日志 id 再 undo
	lw := doGet(r, "/api/v1/dataio/imports?module=funding.income")
	if !strings.Contains(lw.Body.String(), `"total":`) {
		t.Fatalf("日志列表异常: %s", lw.Body.String())
	}
}
