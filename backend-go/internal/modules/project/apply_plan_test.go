package project

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

// TestApplyPlanLifecycle：建计划 → 时间窗外提交 40901 → start 开窗 → 提交 →
// 两级审批（off 模式一步）→ to-project 幂等 → auto-stop。
func TestApplyPlanLifecycle(t *testing.T) {
	pool := poolForE(t)
	t.Setenv("ARK_APPROVAL_TWOSTEP", "off")
	r := newRolesEngine(t, pool, []string{"R-MANAGER"})
	staff := newRolesEngine(t, pool, []string{"R-STAFF"})
	ts := time.Now().UnixNano()

	// 1) 建 DRAFT 计划（未来时间窗）
	w := ePost(r, "/api/v1/apply-plans", fmt.Sprintf(
		`{"name":"T25 国自然面上 %d","source":"NSFC","start_at":"2031-01-01","end_at":"2031-12-31"}`, ts))
	if w.Code != 200 {
		t.Fatalf("建计划应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	planID := int64(eData(t, w.Body.Bytes())["id"].(float64))

	// 2) 时间窗外提交（DRAFT）→ 40901
	w = ePost(staff, fmt.Sprintf("/api/v1/apply-plans/%d/applications", planID),
		`{"project_name":"T25 申报项目","apply_amount":"800000.00"}`)
	if w.Code == 200 {
		t.Fatalf("DRAFT 计划提交应被拒，得 200 body=%s", w.Body.String())
	}

	// 3) start 开窗（把窗口改为覆盖今天）→ 提交成功
	if _, err := pool.Exec(testCtx(),
		`UPDATE e_apply_plan SET start_at=CURRENT_DATE-1, end_at=CURRENT_DATE+30 WHERE id=$1`, planID); err != nil {
		t.Fatalf("调窗: %v", err)
	}
	w = ePost(r, fmt.Sprintf("/api/v1/apply-plans/%d/start", planID), `{}`)
	if w.Code != 200 {
		t.Fatalf("start 应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	w = ePost(staff, fmt.Sprintf("/api/v1/apply-plans/%d/applications", planID),
		`{"project_name":"T25 申报项目","apply_amount":"800000.00"}`)
	if w.Code != 200 {
		t.Fatalf("开窗提交应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	appID := int64(eData(t, w.Body.Bytes())["id"].(float64))

	// 4) 单级模式一步审批 → SCHOOL_PASSED
	w = ePost(r, fmt.Sprintf("/api/v1/applications/%d/approve", appID), `{"action":"APPROVE","comment":"同意"}`)
	if w.Code != 200 {
		t.Fatalf("审批应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if got := eData(t, w.Body.Bytes())["status"]; got != "SCHOOL_PASSED" {
		t.Fatalf("单级审批后应 SCHOOL_PASSED，得 %v", got)
	}

	// 5) to-project → 生成草稿；重复调用幂等
	w = ePost(r, fmt.Sprintf("/api/v1/applications/%d/to-project", appID), `{}`)
	if w.Code != 200 {
		t.Fatalf("to-project 应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	pid1 := int64(eData(t, w.Body.Bytes())["project_id"].(float64))
	w = ePost(r, fmt.Sprintf("/api/v1/applications/%d/to-project", appID), `{}`)
	pid2 := int64(eData(t, w.Body.Bytes())["project_id"].(float64))
	if pid1 == 0 || pid1 != pid2 || eData(t, w.Body.Bytes())["duplicated"] != true {
		t.Fatalf("to-project 应幂等（同 project_id + duplicated=true），得 %d/%d", pid1, pid2)
	}

	// 6) 形式审查视图：附申请人项目摘要
	w = eGet(r, fmt.Sprintf("/api/v1/apply-plans/%d/applications", planID))
	if w.Code != 200 || !strings.Contains(w.Body.String(), "pi_project_count") {
		t.Fatalf("形式审查视图应含 pi_project_count：%s", w.Body.String())
	}

	// 7) auto-stop：把 end_at 置昨天 → 扫描 → STOPPED
	if _, err := pool.Exec(testCtx(), `UPDATE e_apply_plan SET end_at=CURRENT_DATE-1 WHERE id=$1`, planID); err != nil {
		t.Fatalf("置过期: %v", err)
	}
	w = ePost(r, "/api/v1/apply-plans/auto-stop", `{}`)
	if w.Code != 200 {
		t.Fatalf("auto-stop 应 200，得 %d", w.Code)
	}
	w = eGet(r, "/api/v1/apply-plans")
	if !strings.Contains(w.Body.String(), `"status":"STOPPED"`) {
		t.Fatalf("到期计划应 STOPPED：%s", w.Body.String())
	}

	// 清理
	t.Cleanup(func() {
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_application WHERE plan_id=$1`, planID)
		_, _ = pool.Exec(testCtx(), `UPDATE e_project SET deleted=1 WHERE application_id=$1`, appID)
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_apply_plan WHERE id=$1`, planID)
	})
}

// TestApplyPlanTwoStep：两级开启——R-MANAGER 首审 COLLEGE_PASSED → R-MANAGER 终审 403 →
// R-LEADER SCHOOL_PASSED；驳回路径 COLLEGE_REJECTED。
func TestApplyPlanTwoStep(t *testing.T) {
	pool := poolForE(t)
	t.Setenv("ARK_APPROVAL_TWOSTEP", "on")
	r := newRolesEngine(t, pool, []string{"R-MANAGER"})
	ldr := newRolesEngine(t, pool, []string{"R-LEADER"})
	ts := time.Now().UnixNano()

	w := ePost(r, "/api/v1/apply-plans", fmt.Sprintf(
		`{"name":"T25 两级 %d","start_at":"2020-01-01","end_at":"2040-12-31"}`, ts))
	planID := int64(eData(t, w.Body.Bytes())["id"].(float64))
	_, _ = pool.Exec(testCtx(), `UPDATE e_apply_plan SET status='OPEN' WHERE id=$1`, planID)

	w = ePost(r, fmt.Sprintf("/api/v1/apply-plans/%d/applications", planID),
		`{"project_name":"T25 两级申报","apply_amount":"50000.00"}`)
	appID := int64(eData(t, w.Body.Bytes())["id"].(float64))

	// 首审 → COLLEGE_PASSED
	w = ePost(r, fmt.Sprintf("/api/v1/applications/%d/approve", appID), `{"action":"APPROVE"}`)
	if w.Code != 200 || eData(t, w.Body.Bytes())["status"] != "COLLEGE_PASSED" {
		t.Fatalf("首审应 COLLEGE_PASSED，得 %d %s", w.Code, w.Body.String())
	}
	// R-MANAGER 终审 → 403
	w = ePost(r, fmt.Sprintf("/api/v1/applications/%d/approve", appID), `{"action":"APPROVE"}`)
	if w.Code != 403 {
		t.Fatalf("R-MANAGER 终审应 403，得 %d", w.Code)
	}
	// R-LEADER 终审 → SCHOOL_PASSED
	w = ePost(ldr, fmt.Sprintf("/api/v1/applications/%d/approve", appID), `{"action":"APPROVE","comment":"学校通过"}`)
	if w.Code != 200 || eData(t, w.Body.Bytes())["status"] != "SCHOOL_PASSED" {
		t.Fatalf("终审应 SCHOOL_PASSED，得 %d %s", w.Code, w.Body.String())
	}

	// 驳回路径：新单 SUBMITTED → COLLEGE_REJECTED
	w = ePost(r, fmt.Sprintf("/api/v1/apply-plans/%d/applications", planID), `{"project_name":"T25 驳回单"}`)
	if w.Code != 200 {
		t.Fatalf("提交驳回单应 200，得 %d body=%s", w.Code, w.Body.String())
	}
	app2 := int64(eData(t, w.Body.Bytes())["id"].(float64))
	w = ePost(r, fmt.Sprintf("/api/v1/applications/%d/approve", app2), `{"action":"REJECT"}`)
	if w.Code != 200 || eData(t, w.Body.Bytes())["status"] != "COLLEGE_REJECTED" {
		t.Fatalf("驳回应 COLLEGE_REJECTED，得 %d %s", w.Code, w.Body.String())
	}

	t.Cleanup(func() {
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_application WHERE plan_id=$1`, planID)
		_, _ = pool.Exec(testCtx(), `DELETE FROM e_apply_plan WHERE id=$1`, planID)
	})
}
