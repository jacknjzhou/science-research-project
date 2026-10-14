package sysadmin

import (
	"testing"
	"time"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
)

func TestToAPIUser_OmitsPasswordHash(t *testing.T) {
	h := "$2a$10$secretmaterial"
	em := "a@b.co"
	u := store.SysUser{
		ID: 1, Username: "admin", RealName: "管理员",
		EmploymentStatus: "ONBOARD", SecurityLevel: "TOP_SECRET", Status: "ACTIVE",
		PasswordHash: &h, Email: &em, TenantID: 1,
		CreatedAt: time.Now(), UpdatedAt: time.Now(),
	}
	m := ToAPIUser(u, []string{"R-ADMIN"})
	if _, leak := m["password_hash"]; leak {
		t.Fatal("password_hash 泄漏到对外形状")
	}
	if m["username"] != "admin" {
		t.Fatalf("username 缺: %v", m["username"])
	}
	if r, ok := m["roles"].([]string); !ok || len(r) != 1 {
		t.Fatalf("roles 形状错: %#v", m["roles"])
	}
	if m["email"] != "a@b.co" {
		t.Fatalf("email 缺: %v", m["email"])
	}
}

func TestToAPIUser_NilRolesIsEmptyArray(t *testing.T) {
	u := store.SysUser{ID: 2, Username: "staff", Status: "ACTIVE", CreatedAt: time.Now(), UpdatedAt: time.Now()}
	m := ToAPIUser(u, nil)
	if r, ok := m["roles"].([]string); !ok || len(r) != 0 {
		t.Fatalf("nil roles 应序列化为空数组: %#v", m["roles"])
	}
}
