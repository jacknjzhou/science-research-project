package config

import (
	"os"
	"strconv"
)

type Config struct {
	Env            string
	HTTPPort       int
	DatabaseURL    string
	RedisAddr      string
	RedisPassword  string
	JWTSecret      string
	JWTTTLSec      int64
	MigrationsDir  string
	DesignDir      string
	AuthModelPath  string
	AuthPolicyPath string
	S3Endpoint     string
	S3AccessKey    string
	S3SecretKey    string
	S3Bucket       string
	S3UseSSL       bool
	LLMBaseURL     string
	LLMAPIKey      string
	LLMModel       string
	LLMTimeoutSec  int
	SeedDemo       bool
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
		Env:            get("ARK_ENV", "dev"),
		HTTPPort:       getInt("ARK_HTTP_PORT", 8787),
		DatabaseURL:    os.Getenv("ARK_DATABASE_URL"),
		RedisAddr:      get("ARK_REDIS_ADDR", "127.0.0.1:6379"),
		RedisPassword:  get("ARK_REDIS_PASSWORD", ""),
		JWTSecret:      get("ARK_JWT_SECRET", "dev-secret-change-me"),
		JWTTTLSec:      int64(getInt("ARK_JWT_TTL_SEC", 7200)),
		MigrationsDir:  get("ARK_MIGRATIONS_DIR", "./migrations"),
		DesignDir:      get("DESIGN_DIR", "../design"),
		AuthModelPath:  get("ARK_AUTH_MODEL_PATH", "./internal/platform/auth/model.conf"),
		AuthPolicyPath: get("ARK_AUTH_POLICY_PATH", "./internal/platform/auth/policy.csv"),
		S3Endpoint:     get("ARK_S3_ENDPOINT", ""),
		S3AccessKey:    get("ARK_S3_ACCESS_KEY", "minioadmin"),
		S3SecretKey:    get("ARK_S3_SECRET_KEY", "minioadmin"),
		S3Bucket:       get("ARK_S3_BUCKET", "ark-docs"),
		S3UseSSL:       get("ARK_S3_USE_SSL", "false") == "true",
		LLMBaseURL:     os.Getenv("ARK_LLM_BASE_URL"),
		LLMAPIKey:      os.Getenv("ARK_LLM_API_KEY"),
		LLMModel:       get("ARK_LLM_MODEL", "gpt-4o-mini"),
		LLMTimeoutSec:  getInt("ARK_LLM_TIMEOUT_SEC", 30),
		SeedDemo:       get("ARK_SEED_DEMO", "") == "1" || get("ARK_SEED_DEMO", "") == "true",
	}
}
