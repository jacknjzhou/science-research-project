package main

import (
	"context"
	"log"
	"strconv"
	"time"

	"github.com/eplugger/ark/internal"
	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/modules/sysadmin"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/migrate"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/eplugger/ark/internal/platform/storage"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

func main() {
	l, _ := zap.NewProduction()
	defer l.Sync()

	cfg := config.Load()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// 1) 连接 Postgres
	pool, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		l.Fatal("连接数据库失败", zap.Error(err))
	}
	defer pool.Close()
	if err := db.Ping(ctx, pool); err != nil {
		l.Fatal("数据库探活失败", zap.Error(err))
	}

	// 2) 迁移到最新（golang-migrate 拥有 schema，取代 Node 时代 postgres initdb）
	if err := migrate.Up(cfg.DatabaseURL, cfg.MigrationsDir); err != nil {
		l.Fatal("数据库迁移失败", zap.Error(err))
	}

	// 3) Casbin RBAC enforcer
	enf, err := auth.NewEnforcer(cfg.AuthModelPath, cfg.AuthPolicyPath)
	if err != nil {
		l.Fatal("初始化 Casbin 失败", zap.Error(err))
	}

	// 4) 运行时契约（passthrough 兜底 + 校验用）
	spec, err := oapi.LoadDir(cfg.DesignDir)
	if err != nil {
		l.Fatal("加载 OpenAPI 契约失败", zap.Error(err), zap.String("dir", cfg.DesignDir))
	}

	// 5) Redis（幂等热存储）
	rdb := redis.NewClient(&redis.Options{Addr: cfg.RedisAddr, Password: cfg.RedisPassword})
	defer rdb.Close()

	// 6) 登录身份读取器：接库后经 bcrypt 校验真实账号；pool==nil 时留空走 dev 回退。
	var loginReader auth.UserReader
	if pool != nil {
		loginReader = sysadmin.NewAuthReader(pool)
	}

	// 6.5) 对象存储（MinIO）：未配置 endpoint 或连接失败 → 置 nil，依赖它的端点返回 50301。
	var store storage.Storage
	if cfg.S3Endpoint != "" {
		sctx, scancel := context.WithTimeout(context.Background(), 5*time.Second)
		mo, err := storage.NewMinIO(sctx, cfg.S3Endpoint, cfg.S3AccessKey, cfg.S3SecretKey, cfg.S3Bucket, cfg.S3UseSSL)
		scancel()
		if err != nil {
			l.Warn("MinIO 初始化失败，文件端点将返回 50301", zap.Error(err))
		} else {
			store = mo
		}
	}

	// 7) 装配 router 并监听
	e := internal.Build(internal.RouterDeps{
		Logger:      l,
		Cfg:         cfg,
		Pool:        pool,
		Redis:       rdb,
		Enforcer:    enf,
		Spec:        spec,
		LoginReader: loginReader,
		Storage:     store,
	})
	addr := ":" + strconv.Itoa(cfg.HTTPPort)
	l.Info("ark-go 启动", zap.String("addr", addr), zap.String("env", cfg.Env))
	if err := e.Run(addr); err != nil {
		log.Fatal(err)
	}
}
