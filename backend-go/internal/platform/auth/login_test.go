package auth

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
)

// nopCloserString 把 strings.Reader 包成 io.ReadCloser 以构造 httptest 请求体。
type nopCloserString struct{ *strings.Reader }

func (nopCloserString) Close() error { return nil }

// loginEnvelope 复刻 httpx.Envelope 的读取视图，只取关心的字段。
type loginEnvelope struct {
	Code int `json:"code"`
	Data struct {
		TokenType   string `json:"token_type"`
		AccessToken string `json:"access_token"`
		ExpiresIn   int64  `json:"expires_in"`
	} `json:"data"`
}

func postLogin(t *testing.T, h gin.HandlerFunc, body string) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.POST("/login", h)
	req := httptest.NewRequest(http.MethodPost, "/login", nopCloserString{strings.NewReader(body)})
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)
	return rec
}

// stubReader 是 auth.UserReader 的测试替身：按用户名返回预置 LoginUser。
type stubReader struct {
	tid    int64
	users  map[string]*LoginUser
	called bool
	err    error
}

func (s *stubReader) FindForLogin(_ context.Context, username string, tenantID int64) (*LoginUser, error) {
	s.called = true
	s.tid = tenantID
	if s.err != nil {
		return nil, s.err
	}
	u, ok := s.users[username]
	if !ok {
		return nil, nil // 不存在 → (nil,nil)
	}
	return u, nil
}

// ---------- dev 回退（reader==nil） ----------

func TestLoginDevFallback_OK(t *testing.T) {
	h := NewLoginHandler("s", 60, nil)
	rec := postLogin(t, h, `{"username":"ark","password":"ark"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("dev ark/ark=%d want 200 body=%s", rec.Code, rec.Body.String())
	}
	var env loginEnvelope
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	if env.Code != 0 || env.Data.AccessToken == "" || env.Data.TokenType != "Bearer" {
		t.Fatalf("签发结构不符: %+v", env)
	}
	c, err := ParseToken("s", env.Data.AccessToken)
	if err != nil {
		t.Fatalf("ParseToken: %v", err)
	}
	if c.UserID != 1 || c.TenantID != 1 || c.SecurityLevel != "INTERNAL" {
		t.Fatalf("dev claims 不符: %+v", c)
	}
}

func TestLoginDevFallback_WrongPassword(t *testing.T) {
	h := NewLoginHandler("s", 60, nil)
	rec := postLogin(t, h, `{"username":"ark","password":"wrong"}`)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("dev ark/wrong=%d want 401", rec.Code)
	}
}

// ---------- bcrypt 真实分支（reader!=nil） ----------

func TestLoginBcrypt_OK_IssuesRealDataDomain(t *testing.T) {
	hash, err := bcrypt.GenerateFromPassword([]byte("pw123"), bcrypt.MinCost)
	if err != nil {
		t.Fatal(err)
	}
	ph := string(hash)
	r := &stubReader{users: map[string]*LoginUser{
		"alice": {
			UserID: 1, TenantID: 1, LegalEntityID: 7,
			SecurityLevel: "TOP_SECRET", PasswordHash: ph,
			Roles: []string{"R-ADMIN", "R-MANAGER"}, Active: true,
		},
	}}
	h := NewLoginHandler("s", 60, r)
	rec := postLogin(t, h, `{"username":"alice","password":"pw123"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("bcrypt ok=%d want 200 body=%s", rec.Code, rec.Body.String())
	}
	if !r.called {
		t.Fatal("reader 未被调用")
	}
	if r.tid != 1 {
		t.Fatalf("默认 tenantID=%d want 1", r.tid)
	}
	var env loginEnvelope
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	c, err := ParseToken("s", env.Data.AccessToken)
	if err != nil {
		t.Fatalf("ParseToken: %v", err)
	}
	if c.UserID != 1 || c.SecurityLevel != "TOP_SECRET" || c.LegalEntityID != 7 {
		t.Fatalf("真实数据域 claims 不符: %+v", c)
	}
	if len(c.Roles) == 0 || c.Roles[0] != "R-ADMIN" {
		t.Fatalf("Roles 应含 R-ADMIN: %+v", c.Roles)
	}
}

func TestLoginBcrypt_TenantIDOverride(t *testing.T) {
	hash, _ := bcrypt.GenerateFromPassword([]byte("pw"), bcrypt.MinCost)
	ph := string(hash)
	r := &stubReader{users: map[string]*LoginUser{
		"bob": {UserID: 2, TenantID: 9, SecurityLevel: "PUBLIC", PasswordHash: ph, Roles: []string{"R-STAFF"}, Active: true},
	}}
	h := NewLoginHandler("s", 60, r)
	rec := postLogin(t, h, `{"username":"bob","password":"pw","tenant_id":9}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("override=%d want 200 body=%s", rec.Code, rec.Body.String())
	}
	if r.tid != 9 {
		t.Fatalf("tenantID 应被覆盖为 9，实际 %d", r.tid)
	}
}

func TestLoginBcrypt_WrongPassword(t *testing.T) {
	hash, _ := bcrypt.GenerateFromPassword([]byte("right"), bcrypt.MinCost)
	ph := string(hash)
	r := &stubReader{users: map[string]*LoginUser{
		"alice": {UserID: 1, PasswordHash: ph, Active: true},
	}}
	h := NewLoginHandler("s", 60, r)
	rec := postLogin(t, h, `{"username":"alice","password":"wrong"}`)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("wrong password=%d want 401", rec.Code)
	}
}

func TestLoginBcrypt_UnknownUser(t *testing.T) {
	r := &stubReader{users: map[string]*LoginUser{}}
	h := NewLoginHandler("s", 60, r)
	rec := postLogin(t, h, `{"username":"ghost","password":"pw"}`)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("unknown user=%d want 401", rec.Code)
	}
}

func TestLoginBcrypt_NoPasswordHash(t *testing.T) {
	r := &stubReader{users: map[string]*LoginUser{
		"nohash": {UserID: 3, PasswordHash: "", Active: true},
	}}
	h := NewLoginHandler("s", 60, r)
	rec := postLogin(t, h, `{"username":"nohash","password":"pw"}`)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("no password_hash=%d want 401", rec.Code)
	}
}

func TestLoginBcrypt_InactiveForbidden(t *testing.T) {
	hash, _ := bcrypt.GenerateFromPassword([]byte("pw"), bcrypt.MinCost)
	ph := string(hash)
	r := &stubReader{users: map[string]*LoginUser{
		"locked": {UserID: 4, PasswordHash: ph, Active: false},
	}}
	h := NewLoginHandler("s", 60, r)
	rec := postLogin(t, h, `{"username":"locked","password":"pw"}`)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("inactive=%d want 403", rec.Code)
	}
}
