package auth

import (
	"strings"
	"testing"
)

func TestTokenRoundTrip(t *testing.T) {
	secret := "test-secret"
	tk, err := GenToken(secret, 60, Claims{
		UserID: 1001, TenantID: 1, SecurityLevel: "INTERNAL", Roles: []string{"R-ADMIN"},
	})
	if err != nil {
		t.Fatal(err)
	}
	c, err := ParseToken(secret, tk)
	if err != nil {
		t.Fatal(err)
	}
	if c.UserID != 1001 || c.TenantID != 1 || c.Roles[0] != "R-ADMIN" {
		t.Fatalf("claims 还原错误: %+v", c)
	}
}

func TestParseToken_InvalidFails(t *testing.T) {
	if _, err := ParseToken("a", "garbage"); err == nil {
		t.Fatal("期望非法令牌报错")
	}
}

func TestParseToken_WrongSecretFails(t *testing.T) {
	tk, err := GenToken("secret-A", 60, Claims{UserID: 1, Roles: []string{"R-ADMIN"}})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ParseToken("secret-B", tk); err == nil {
		t.Fatal("期望错误密钥导致校验失败")
	}
}

func TestParseToken_ExpiredFails(t *testing.T) {
	tk, err := GenToken("test-secret", -10, Claims{UserID: 1, Roles: []string{"R-ADMIN"}})
	if err != nil {
		t.Fatal(err)
	}
	_, err = ParseToken("test-secret", tk)
	if err == nil {
		t.Fatal("期望过期令牌报错")
	}
	if !strings.Contains(strings.ToLower(err.Error()), "expired") {
		t.Fatalf("期望过期类错误, 得: %v", err)
	}
}
