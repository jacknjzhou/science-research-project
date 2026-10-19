package archive

import (
	"strconv"
	"time"

	ostore "github.com/eplugger/ark/internal/modules/archive/store"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/eplugger/ark/internal/platform/storage"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

// defaultBucket 与 docker-compose backend env ARK_S3_BUCKET 一致（storage.Storage 接口未暴露
// bucket，且 NewHandler 只吃 pool+Storage，故文档落库的 bucket 固定用此常量）。
const defaultBucket = "ark-docs"

// Handler 承载 O 竖切所有 HTTP 端点。store 由 sqlc 生成的 ostore.Queries 提供；
// O 是唯一持有 storage.Storage 的域 Handler——依赖对象存储的端点（上传/下载/删除/四性检测）
// 在 store==nil 时统一返回 50301「对象存储不可用」（见 guardStorage）。
type Handler struct {
	q     *ostore.Queries
	store storage.Storage // 可为 nil：依赖它的端点返回 50301
}

// NewHandler 用 pgxpool + storage.Storage（可 nil）构造 Handler。
func NewHandler(pool *pgxpool.Pool, s storage.Storage) *Handler {
	return &Handler{q: ostore.New(pool), store: s}
}

// ---------- 请求/分页 helper（逐字拷自 activity/handler.go） ----------

func pageArgs(c *gin.Context) (page, size, limit, offset int32) {
	p, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	s, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if p < 1 {
		p = 1
	}
	if s < 1 {
		s = 20
	}
	if s > 200 {
		s = 200
	}
	return int32(p), int32(s), int32(s), int32((p - 1) * s)
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

func optInt64(c *gin.Context, k string) *int64 {
	if v := c.Query(k); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return &n
		}
	}
	return nil
}

// guardStorage 依赖对象存储的端点先行守卫：nil → 503/50301，返 false 令调用方直接 return。
func (h *Handler) guardStorage(c *gin.Context) bool {
	if h.store == nil {
		httpx.WriteErr(c, 503, 50301, "对象存储不可用")
		return false
	}
	return true
}

// ---------- 时间/解析 helper ----------

// parseTS 支持 RFC3339 与 "2006-01-02"；空/解析失败 → nil。
func parseTS(s *string) *time.Time {
	if s == nil || *s == "" {
		return nil
	}
	for _, layout := range []string{time.RFC3339, "2006-01-02T15:04:05", "2006-01-02"} {
		if t, err := time.Parse(layout, *s); err == nil {
			return &t
		}
	}
	return nil
}

// tsOf 把 *time.Time 转成 sqlc 参数用的 pgtype.Timestamptz；nil → NULL(Valid=false)。
func tsOf(t *time.Time) pgtype.Timestamptz {
	if t == nil {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: *t, Valid: true}
}
