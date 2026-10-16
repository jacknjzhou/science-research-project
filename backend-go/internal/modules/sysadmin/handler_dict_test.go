package sysadmin

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

// newDictEngine 带指定角色注入的测试引擎（字典权限用例需要区分 R-ADMIN / R-STAFF）。
func newDictEngine(t *testing.T, roles []string) *gin.Engine {
	t.Helper()
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { pool.Close() })
	enf, err := auth.NewEnforcer("../../platform/auth/model.conf", "../../platform/auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	// 模拟 middleware.Auth 的授权段（注入域 + Casbin 判权；JWT 段在单测中省略）：
	// 逐角色 Enforce，命中即放行，否则 403——与生产 policy 语义一致。
	e.Use(httpx.TraceID(), func(c *gin.Context) {
		c.Set(auth.CtxUserID, int64(1))
		c.Set(auth.CtxTenantID, int64(1))
		c.Set(auth.CtxSecurityLevel, "TOP_SECRET")
		c.Set(auth.CtxRoles, roles)
		allowed := false
		for _, role := range roles {
			if ok, _ := enf.Enforce(role, c.Request.URL.Path, c.Request.Method); ok {
				allowed = true
				break
			}
		}
		if !allowed {
			httpx.WriteErr(c, http.StatusForbidden, 40301, "无权限")
			c.Abort()
			return
		}
		c.Next()
	})
	Register(e.Group("/api/v1"), NewHandler(pool, enf))
	return e
}

func dictEnv(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	if w.Code != http.StatusOK {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int            `json:"code"`
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil || env.Code != 0 {
		t.Fatalf("bad envelope: %s", w.Body.String())
	}
	return env.Data
}

// TestDictLifecycle_RoleIsolation 覆盖：admin CRUD 闭环、item upsert 冲突语义、
// 生效期过滤、staff 只读、staff 写 403、软删后公开读取 404。
func TestDictLifecycle_RoleIsolation(t *testing.T) {
	admin := newDictEngine(t, []string{"R-ADMIN"})
	staff := newDictEngine(t, []string{"R-STAFF"})
	code := fmt.Sprintf("T-DICT-%d", time.Now().UnixNano()%100000000)

	// 1) admin upsert 字典
	w := httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/admin/dicts", strings.NewReader(`{"code":"`+code+`","name":"测试字典","remark":"plan v3"}`)))
	d := dictEnv(t, w)
	dictID := int64(d["id"].(float64))

	// 2) 同码二次 upsert → 更新不新增
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/admin/dicts", strings.NewReader(`{"code":"`+code+`","name":"测试字典·改名"}`)))
	if got := dictEnv(t, w)["name"]; got != "测试字典·改名" {
		t.Fatalf("同码 upsert 未更新 name: %v", got)
	}

	// 3) 条目 upsert ×2（NSFC / PROV）
	upItem := func(itemCode, label, effFrom string) map[string]any {
		body := `{"item_code":"` + itemCode + `","item_label":"` + label + `","sort_no":1`
		if effFrom != "" {
			body += `,"effective_from":"` + effFrom + `"`
		}
		body += `}`
		w := httptest.NewRecorder()
		admin.ServeHTTP(w, httptest.NewRequest("POST",
			fmt.Sprintf("/api/v1/admin/dicts/%d/items", dictID), strings.NewReader(body)))
		return dictEnv(t, w)
	}
	it1 := upItem("NSFC", "国家自然科学基金", "")
	if it1["item_code"] != "NSFC" {
		t.Fatalf("条目 upsert 异常: %v", it1)
	}
	// 同码同生效期（NULL）二次 upsert → 更新同一条
	upItem("NSFC", "国家自然科学基金·修订", "")
	// 同码不同生效期 → 新版本并存
	upItem("NSFC", "2027 版", "2027-01-01")

	// 4) 管理端详情：2 条（含未来生效）
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("GET", fmt.Sprintf("/api/v1/admin/dicts/%d", dictID), nil))
	d = dictEnv(t, w)
	items := d["items"].([]any)
	if len(items) != 2 {
		t.Fatalf("管理端应 2 条目，得 %d", len(items))
	}

	// 5) staff 公开读取：仅当前生效 1 条；且 staff 无 /admin 写权限
	w = httptest.NewRecorder()
	staff.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/dicts/"+code, nil))
	d = dictEnv(t, w)
	if act := d["items"].([]any); len(act) != 1 {
		t.Fatalf("公开读取应 1 条生效条目，得 %d", len(act))
	}
	w = httptest.NewRecorder()
	staff.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/admin/dicts", strings.NewReader(`{"code":"X","name":"X"}`)))
	if w.Code != http.StatusForbidden {
		t.Fatalf("staff 写 /admin/dicts 应 403，得 %d", w.Code)
	}

	// 6) 删除未来版本条目 → 管理端剩 1 条
	future := items[1].(map[string]any)
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("DELETE",
		fmt.Sprintf("/api/v1/admin/dicts/%d/items/%d", dictID, int64(future["id"].(float64))), nil))
	dictEnv(t, w)

	// 7) 软删字典 → 公开读取 404
	w = httptest.NewRecorder()
	admin.ServeHTTP(w, httptest.NewRequest("DELETE", fmt.Sprintf("/api/v1/admin/dicts/%d", dictID), nil))
	dictEnv(t, w)
	w = httptest.NewRecorder()
	staff.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/dicts/"+code, nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("软删后公开读取应 404，得 %d", w.Code)
	}
}
