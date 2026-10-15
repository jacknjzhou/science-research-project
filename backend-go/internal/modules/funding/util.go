// 共享小工具：路径 ID、分页、可选查询参数、状态冲突错误。
package funding

import (
	"encoding/json"
	"errors"
	"math/big"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgtype"
)

// parseDatePtr "2006-01-02" → *time.Time（空串/非法 → nil）。
func parseDatePtr(s *string) *time.Time {
	if s == nil || *s == "" {
		return nil
	}
	if t, err := time.Parse("2006-01-02", *s); err == nil {
		return &t
	}
	return nil
}

func pathID(c *gin.Context) int64 {
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	if id == 0 {
		if v := c.Param("lineId"); v != "" {
			id, _ = strconv.ParseInt(v, 10, 64)
		}
		if v := c.Param("incomeId"); v != "" {
			id, _ = strconv.ParseInt(v, 10, 64)
		}
		if v := c.Param("expenseId"); v != "" {
			id, _ = strconv.ParseInt(v, 10, 64)
		}
	}
	return id
}

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

// stateConflict：业务状态守卫失败（映射 HTTP 409 + code 40901）。
type stateConflict struct{ msg string }

func (e *stateConflict) Error() string { return e.msg }

func errStateConflict(msg string) error { return &stateConflict{msg: msg} }

var errNoRows = errors.New("no rows")

// errInsufficient：预算行可支余额不足（F-10 冻结校验）。
var errInsufficient = errors.New("insufficient budget remaining")

func jsonMarshal(v any) ([]byte, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return []byte("{}"), nil
	}
	return b, nil
}

// ratStr：float → 4 位小数字符串（费率）。
func ratStr(f float64) string { return strconv.FormatFloat(f, 'f', 4, 64) }

// ratToNum：big.Rat → pgtype.Numeric（2 位小数）。
func ratToNum(r *big.Rat) (n pgtype.Numeric) {
	_ = n.Scan(r.FloatString(2))
	return n
}

// defaultEntity：批量导入/缺省主法人 id（与 seed 保持一致）。
const defaultEntity int64 = 1

// strconvI int64 → string（T14 outward/carryover 通知文案用）。
func strconvI(n int64) string { return strconv.FormatInt(n, 10) }

// setCode best-effort 写业务编号（codeOf 生成 OUT/CRO/INC 前缀；失败静默，编号非关键路径）。
