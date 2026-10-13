package config

import (
	"os"
	"strconv"
)

type Config struct {
	Env           string
	HTTPPort      int
	DatabaseURL   string
	RedisAddr     string
	RedisPassword string
	JWTSecret     string
	JWTTTLSec     int64
	MigrationsDir string
	DesignDir     string
}

func get(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func Load() *Config {
	return &Config{
		Env:           get("ARK_ENV", "dev"),
		HTTPPort:      getInt("ARK_HTTP_PORT", 8787),
		DatabaseURL:   os.Getenv("ARK_DATABASE_URL"),
		RedisAddr:     get("ARK_REDIS_ADDR", "127.0.0.1:6379"),
		RedisPassword: get("ARK_REDIS_PASSWORD", ""),
		JWTSecret:     get("ARK_JWT_SECRET", "dev-secret-change-me"),
		JWTTTLSec:     int64(getInt("ARK_JWT_TTL_SEC", 7200)),
		MigrationsDir: get("ARK_MIGRATIONS_DIR", "./migrations"),
		DesignDir:     get("DESIGN_DIR", "../design"),
	}
}
