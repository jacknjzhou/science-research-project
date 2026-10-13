package config

import "testing"

func TestLoad_DefaultsAndEnv(t *testing.T) {
	t.Setenv("ARK_HTTP_PORT", "9000")
	t.Setenv("ARK_DATABASE_URL", "postgres://u:p@h:5432/db?sslmode=disable")
	t.Setenv("ARK_REDIS_ADDR", "redis:6379")
	t.Setenv("ARK_JWT_SECRET", "s3cr3t")
	t.Setenv("DESIGN_DIR", "/srv/design")

	c := Load()
	if c.HTTPPort != 9000 {
		t.Fatalf("HTTPPort=%d", c.HTTPPort)
	}
	if c.DatabaseURL == "" || c.RedisAddr == "" || c.JWTSecret != "s3cr3t" {
		t.Fatalf("必填项未加载: %+v", c)
	}
	if c.DesignDir != "/srv/design" {
		t.Fatalf("DesignDir=%s", c.DesignDir)
	}
	if c.MigrationsDir == "" {
		t.Fatal("MigrationsDir 应有默认值")
	}
	if c.JWTTTLSec == 0 {
		t.Fatal("JWTTTLSec 应有默认值")
	}
}
