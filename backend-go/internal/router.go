package internal

import (
	"time"

	"github.com/casbin/casbin/v2"
	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/modules/activity"
	"github.com/eplugger/ark/internal/modules/p"
	"github.com/eplugger/ark/internal/modules/sysadmin"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/middleware"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

// RouterDeps 是装配主 router 所需的全部协作者。
// Pool/Redis 允许为 nil（仅单测公开路由/401 短路时用）；生产必须注入。
type RouterDeps struct {
	Logger   *zap.Logger
	Cfg      *config.Config
	Pool     *pgxpool.Pool
	Redis    *redis.Client
	Enforcer *casbin.Enforcer
	Spec     *oapi.Spec
	// LoginReader 为 nil 时登录走内置 ark/ark dev 回退（未接库的单测/冒烟零回归）；
	// 非 nil 时经 bcrypt 校验真实账号并签发真实数据域 JWT。
	LoginReader auth.UserReader
}

// Build 组装 Gin 引擎：横切中间件 + 公开路由 + 受保护 /api/v1（鉴权/幂等/P 竖切）+ passthrough 兜底。
func Build(d RouterDeps) *gin.Engine {
	e := gin.New()
	e.Use(httpx.TraceID(), middleware.Recover(d.Logger))

	// 公开：健康检查 + 开发登录
	e.GET("/healthz", func(c *gin.Context) {
		httpx.WriteOK(c, gin.H{"ok": true, "env": d.Cfg.Env})
	})
	e.POST("/api/v1/auth/login", auth.NewLoginHandler(d.Cfg.JWTSecret, d.Cfg.JWTTTLSec, d.LoginReader))

	// 受保护分组：JWT+Casbin 鉴权 → 写方法幂等
	api := e.Group("/api/v1")
	api.Use(middleware.Auth(d.Cfg.JWTSecret, d.Enforcer))
	api.Use(middleware.Idempotency(d.Redis, 24*time.Hour))

	// P 竖切挂到受保护分组（内部只写 /apply 前缀）
	if d.Pool != nil {
		p.Register(api, p.NewHandler(d.Pool))
		sysadmin.Register(api, sysadmin.NewHandler(d.Pool, d.Enforcer))
		activity.Register(api, activity.NewHandler(d.Pool))
	}

	// 兜底：命中契约但未手工实现的路由 → passthrough（NoRoute 不经分组中间件，M0 可接受）
	e.NoRoute(oapi.Passthrough(d.Spec))

	return e
}
