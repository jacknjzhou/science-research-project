package funding

import (
	"fmt"
	"net/http"
	"testing"
)

// TestSubjectTreeCRUD：多级科目创建（level 递推）→ 树 → 更新 → 删除守卫 → 删除叶子。
func TestSubjectTreeCRUD(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newFundingEngine(t, pool, injectDomain([]string{"R-MANAGER", "R-LEADER"}, 1, 1))

	// 1) 一级科目
	w := doPost(r, "/api/v1/subjects", `{"name":"T15一级-设备费","category":"DIRECT","code":"T15-A"}`)
	if w.Code != 200 {
		t.Fatalf("创建一级科目应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	root := dataMap(t, w.Body.Bytes())
	rootID := int(root["id"].(float64))
	if int(root["level"].(float64)) != 1 {
		t.Fatalf("根科目 level 应 1，得 %v", root["level"])
	}

	// 2) 二级科目（parent 引用）
	w = doPost(r, "/api/v1/subjects", fmt.Sprintf(`{"name":"T15二级-显微镜","category":"DIRECT","parent_id":%d}`, rootID))
	if w.Code != 200 {
		t.Fatalf("创建二级科目应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	child := dataMap(t, w.Body.Bytes())
	childID := int(child["id"].(float64))
	if int(child["level"].(float64)) != 2 {
		t.Fatalf("子科目 level 应 2，得 %v", child["level"])
	}

	// 3) 树包含两级
	w = doGet(r, "/api/v1/subjects/tree")
	if !containsTree(w.Body.String(), rootID, childID) {
		t.Fatalf("树应包含 root %d 与 child %d：%s", rootID, childID, w.Body.String())
	}

	// 4) 更新
	w = doPut(r, fmt.Sprintf("/api/v1/subjects/%d", childID), `{"name":"T15二级-显微镜(改)","sort_no":5}`)
	if w.Code != 200 {
		t.Fatalf("更新应 200，得 %d body=%s", w.Code, w.Body.String())
	}

	// 5) 删除守卫：有子级禁删
	if w = doDelete(r, fmt.Sprintf("/api/v1/subjects/%d", rootID)); w.Code != http.StatusConflict {
		t.Fatalf("有子级删除应 409，得 %d body=%s", w.Code, w.Body.String())
	}

	// 6) 删除叶子成功
	if w = doDelete(r, fmt.Sprintf("/api/v1/subjects/%d", childID)); w.Code != 200 {
		t.Fatalf("叶子删除应 200，得 %d body=%s", w.Code, w.Body.String())
	}
}

// TestWarnConfigCRUD：创建（枚举校验）→ 列表过滤 → 更新 → 删除。
func TestWarnConfigCRUD(t *testing.T) {
	pool := poolForTest(t)
	runSeed(t, pool)
	r := newFundingEngine(t, pool, injectDomain([]string{"R-MANAGER", "R-LEADER"}, 1, 1))

	// 1) 非法 warn_kind → 400
	if w := doPost(r, "/api/v1/funding/warn-configs", `{"warn_kind":"NOPE"}`); w.Code != http.StatusBadRequest {
		t.Fatalf("非法 warn_kind 应 400，得 %d", w.Code)
	}
	// 2) 合法创建
	w := doPost(r, "/api/v1/funding/warn-configs", `{"warn_kind":"EXEC_RATE","threshold_pct":"0.75","level":"P1","channel":"CRON","cron_expr":"0 8 * * 1","template":"项目 {project} 执行率 {rate} 低于阈值"}`)
	if w.Code != 200 {
		t.Fatalf("创建应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	cfg := dataMap(t, w.Body.Bytes())
	cid := int(cfg["id"].(float64))
	if cfg["enabled"] != true {
		t.Fatalf("默认应 enabled=true，得 %v", cfg["enabled"])
	}
	// 3) 过滤列表
	w = doGet(r, "/api/v1/funding/warn-configs?warn_kind=EXEC_RATE&enabled=true")
	if !containsAny(w.Body.String(), `"warn_kind":"EXEC_RATE"`) {
		t.Fatalf("过滤列表应含 EXEC_RATE：%s", w.Body.String())
	}
	// 4) 更新禁用
	w = doPut(r, fmt.Sprintf("/api/v1/funding/warn-configs/%d", cid), `{"enabled":false,"level":"P2"}`)
	if w.Code != 200 {
		t.Fatalf("更新应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := dataMap(t, w.Body.Bytes()); got["enabled"] != false {
		t.Fatalf("更新后 enabled 应 false，得 %v", got["enabled"])
	}
	// 5) 删除
	if w = doDelete(r, fmt.Sprintf("/api/v1/funding/warn-configs/%d", cid)); w.Code != 200 {
		t.Fatalf("删除应 200，得 %d", w.Code)
	}
}

// containsTree 粗校验树 JSON 同时含两科目 id 字段值。
func containsTree(body string, rootID, childID int) bool {
	return containsAny(body, fmt.Sprintf(`"id":%d`, rootID)) && containsAny(body, fmt.Sprintf(`"id":%d`, childID))
}

func containsAny(s, sub string) bool {
	return len(s) >= len(sub) && (func() bool {
		for i := 0; i+len(sub) <= len(s); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	})()
}
