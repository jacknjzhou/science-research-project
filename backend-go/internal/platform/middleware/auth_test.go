package middleware

import (
	"net/http/httptest"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

func build(t *testing.T) *gin.Engine {
	enf, err := auth.NewEnforcer("../auth/model.conf", "../auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), Auth("test-secret", enf))
	e.GET("/api/v1/apply/applications", func(c *gin.Context) {
		httpx.WriteOK(c, gin.H{"tenant": auth.DomainFrom(c).TenantID})
	})
	return e
}

func TestAuth_MissingToken401(t *testing.T) {
	w := httptest.NewRecorder()
	build(t).ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/apply/applications", nil))
	if w.Code != 401 {
		t.Fatalf("期望 401，得 %d", w.Code)
	}
}

func TestAuth_AdminAllowedAndTenantInjected(t *testing.T) {
	tk, _ := auth.GenToken("test-secret", 60, auth.Claims{UserID: 1, TenantID: 7, Roles: []string{"R-ADMIN"}})
	req := httptest.NewRequest("GET", "/api/v1/apply/applications", nil)
	req.Header.Set("Authorization", "Bearer "+tk)
	w := httptest.NewRecorder()
	build(t).ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("期望 200，得 %d body=%s", w.Code, w.Body.String())
	}
	if !contains(w.Body.String(), "\"tenant\":7") {
		t.Fatalf("数据域未注入: %s", w.Body.String())
	}
}

func TestAuth_STAFFDenied403(t *testing.T) {
	tk, _ := auth.GenToken("test-secret", 60, auth.Claims{UserID: 2, TenantID: 7, Roles: []string{"R-STAFF-NOACCESS"}})
	req := httptest.NewRequest("GET", "/api/v1/apply/applications", nil)
	req.Header.Set("Authorization", "Bearer "+tk)
	w := httptest.NewRecorder()
	build(t).ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatalf("期望 403，得 %d", w.Code)
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (indexOf(s, sub) >= 0)
}
func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
