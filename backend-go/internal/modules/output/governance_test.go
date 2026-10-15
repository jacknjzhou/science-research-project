package output

import (
	"fmt"
	"net/http"
	"strings"
	"testing"
)

// TestJournalResolve：源+级别挂接 → 按名称+年度 resolve 命中 / 年度窗外未命中 null。
func TestJournalResolve(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newOutputEngine(t, pool, 1, 1)

	// 建源（覆盖 2024-2026）+ 级别 + 挂接
	w := doPost(r, "/api/v1/journal-sources", `{"name":"先进制造学报","issn":"1005-XXXX","year_from":2024,"year_to":2026}`)
	if w.Code != 200 {
		t.Fatalf("建源应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	srcID := int(dataOf(t, w.Body.Bytes())["id"].(float64))
	w = doPost(r, "/api/v1/journal-levels", `{"code":"T16-SCI2","name":"SCI 二区","paper_type":"期刊论文"}`)
	lvID := int(dataOf(t, w.Body.Bytes())["id"].(float64))
	w = doPost(r, fmt.Sprintf("/api/v1/journal-levels/%d/sources", lvID), fmt.Sprintf(`{"source_id":%d,"year_from":2024,"year_to":2026}`, srcID))
	if w.Code != 200 {
		t.Fatalf("挂接应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	// 命中
	w = doGet(r, "/api/v1/journal-levels/resolve?name=先进制造学报&year=2025")
	if !strings.Contains(w.Body.String(), "T16-SCI2") {
		t.Fatalf("resolve 应命中：%s", w.Body.String())
	}
	// 年度窗外（2023）→ null
	w = doGet(r, "/api/v1/journal-levels/resolve?name=先进制造学报&year=2023")
	if !strings.Contains(w.Body.String(), `"data":null`) {
		t.Fatalf("窗外 resolve 应 null：%s", w.Body.String())
	}
	// 转载登记（先建 PAPER 成果，避免硬编码自增 id）
	w = doPost(r, "/api/v1/output", `{"output_type":"PAPER","title":"转载源论文 Journal Reprint","source":"MANUAL"}`)
	if w.Code != 200 {
		t.Fatalf("建 PAPER 应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	paperID := int(dataOf(t, w.Body.Bytes())["id"].(float64))
	w = doPost(r, fmt.Sprintf("/api/v1/papers/%d/reprints", paperID), `{"name":"人大复印资料","type":"全文转载","reprint_date":"2025-06-01"}`)
	if w.Code != 200 {
		t.Fatalf("转载登记应 200，得 %d body=%s", w.Code, w.Body.String())
	}
}

// TestPushItemDedup：精确重复 40905 → 相似确认 force 导入 → 忽略幂等。
func TestPushItemDedup(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newOutputEngine(t, pool, 1, 1)
	title := "Push Dedup Test Paper on Robotic Grinding"

	// 1) 造已存在成果（同标题）→ 推送项导入应 40905
	w := doPost(r, "/api/v1/output", fmt.Sprintf(`{"output_type":"PAPER","title":"%s","source":"MANUAL"}`, title))
	if w.Code != 200 {
		t.Fatalf("建成果应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	pushSeed(t, pool, 1, "PAPER", "WOS", title, 2025)
	w = doGet(r, "/api/v1/push-items?status=PUSHED")
	if !strings.Contains(w.Body.String(), "Push Dedup Test Paper") {
		t.Fatalf("推送列表应含该条：%s", w.Body.String())
	}
	pid1 := extractPushID(w.Body.String(), title)
	if pid1 == 0 {
		t.Fatalf("未找到推送项：%s", w.Body.String())
	}
	w = doPost(r, fmt.Sprintf("/api/v1/push-items/%d/import", pid1), "")
	if w.Code != http.StatusConflict || !strings.Contains(w.Body.String(), "40905") {
		t.Fatalf("精确重复应 40905，得 %d body=%s", w.Code, w.Body.String())
	}

	// 2) 新标题（无精确重复、无相似）→ 直接导入
	title2 := "Unique Title Nobody Wrote About QX-77"
	pushSeed(t, pool, 1, "PAPER", "CNKI", title2, 2025)
	// 找到该推送项 id
	w = doGet(r, "/api/v1/push-items?status=PUSHED")
	pid := extractPushID(w.Body.String(), title2)
	if pid == 0 {
		t.Fatalf("未找到推送项：%s", w.Body.String())
	}
	w = doPost(r, fmt.Sprintf("/api/v1/push-items/%d/import", pid), "")
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"output_id"`) {
		t.Fatalf("导入应 200 含 output_id，得 %d body=%s", w.Code, w.Body.String())
	}
	oid := int(dataOf(t, w.Body.Bytes())["output_id"].(float64))
	if oid == 0 {
		t.Fatalf("output_id 应非零")
	}
	// 3) 忽略另一条（幂等）
	title3 := "Ignored Item About XY-88"
	pushSeed(t, pool, 1, "PATENT", "CNIPA", title3, 2025)
	w = doGet(r, "/api/v1/push-items?status=PUSHED")
	pid3 := extractPushID(w.Body.String(), title3)
	_ = doPost(r, fmt.Sprintf("/api/v1/push-items/%d/ignore", pid3), "")
	w2 := doPost(r, fmt.Sprintf("/api/v1/push-items/%d/ignore", pid3), "")
	if w2.Code != 200 {
		t.Fatalf("忽略应幂等 200，得 %d", w2.Code)
	}
}

// TestPatentStageGuard：PRE_APPLY→APPLIED 合法；PRE_APPLY→GRANTED 40901；年费登记。
func TestPatentStageGuard(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newOutputEngine(t, pool, 1, 1)

	// 造 PATENT 成果
	w := doPost(r, "/api/v1/output", `{"output_type":"PATENT","title":"T18 测试专利","source":"MANUAL"}`)
	pid := int(dataOf(t, w.Body.Bytes())["id"].(float64))

	// 跳级 → 40901
	w = doPost(r, fmt.Sprintf("/api/v1/patents/%d/stage", pid), `{"stage":"GRANTED"}`)
	if w.Code != http.StatusConflict {
		t.Fatalf("跳级应 409，得 %d body=%s", w.Code, w.Body.String())
	}
	// 按序 +1
	w = doPost(r, fmt.Sprintf("/api/v1/patents/%d/stage", pid), `{"stage":"APPLIED"}`)
	if w.Code != 200 {
		t.Fatalf("按序流转应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	// 年费登记 + 列表
	w = doPost(r, fmt.Sprintf("/api/v1/patents/%d/fees", pid), `{"year":2026,"amount":"900.00","status":"UNPAID"}`)
	if w.Code != 200 {
		t.Fatalf("年费登记应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	w = doGet(r, fmt.Sprintf("/api/v1/patents/%d/fees", pid))
	if !strings.Contains(w.Body.String(), "900.00") {
		t.Fatalf("年费列表应含金额：%s", w.Body.String())
	}
	// 代理机构
	w = doPost(r, "/api/v1/agencies", `{"name":"T18 测试代理所","contact":"13800000000"}`)
	if w.Code != 200 {
		t.Fatalf("建机构应 200，得 %d", w.Code)
	}
}
