// Package approval 通用两级审核服务（T19）。
// 不是业务模块，而是可被任何域复用的服务库：两级角色配置、审核动作流水（sys_approval_log）、
// 编辑锁规则矩阵。业务表 status 仍是状态真源，本包只负责「流水 + 规则 + 开关」。
package approval

import (
	"context"
	"os"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// TwoStep 两级审核配置：FirstRole 首审（学院/秘书）、SecondRole 终审（学校/科研处）。
type TwoStep struct {
	FirstRole  string
	SecondRole string
}

// Service 审核服务。
type Service struct {
	pool *pgxpool.Pool
}

func New(pool *pgxpool.Pool) *Service { return &Service{pool: pool} }

// Enabled 两级审核全局开关（env ARK_APPROVAL_TWOSTEP=on 开，默认关——行为与单级一致）。
func Enabled() bool {
	return os.Getenv("ARK_APPROVAL_TWOSTEP") == "on"
}

// LogParam 审核动作流水条目。
type LogParam struct {
	TenantID  int64
	BizType   string
	BizID     int64
	Step      int    // 0=提交 1=首审 2=终审
	ActorID   int64
	ActorRole string
	Action    string // SUBMIT/APPROVE/REJECT/RETURN
	Comment   string
	ActedAt   time.Time
}

const insertLogSQL = `INSERT INTO sys_approval_log (tenant_id, biz_type, biz_id, step, actor_id, actor_role, action, comment)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,NULLIF($8,''))`

// Log 包级便利：handler 无 Service 实例时用池直写流水。
func Log(ctx context.Context, pool *pgxpool.Pool, p LogParam) error {
	_, err := pool.Exec(ctx, insertLogSQL,
		p.TenantID, p.BizType, p.BizID, p.Step, p.ActorID, p.ActorRole, p.Action, p.Comment)
	return err
}

// Log 写审核动作流水（best-effort：流水失败不阻断业务事务之外的调用路径）。
func (s *Service) Log(ctx context.Context, p LogParam) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO sys_approval_log (tenant_id, biz_type, biz_id, step, actor_id, actor_role, action, comment)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,NULLIF($8,''))`,
		p.TenantID, p.BizType, p.BizID, p.Step, p.ActorID, p.ActorRole, p.Action, p.Comment)
	return err
}

// LogTx 事务内写流水（与业务状态变更同事务）。
func LogTx(ctx context.Context, tx pgx.Tx, p LogParam) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO sys_approval_log (tenant_id, biz_type, biz_id, step, actor_id, actor_role, action, comment)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,NULLIF($8,''))`,
		p.TenantID, p.BizType, p.BizID, p.Step, p.ActorID, p.ActorRole, p.Action, p.Comment)
	return err
}

// ListLogs 业务单据的审核流水（时间升序）。
func (s *Service) ListLogs(ctx context.Context, tenantID int64, bizType string, bizID int64) ([]LogParam, error) {
	rows, err := s.pool.Query(ctx,
		`SELECT tenant_id, biz_type, biz_id, step, actor_id, COALESCE(actor_role,''), action, COALESCE(comment,''), acted_at
		 FROM sys_approval_log WHERE tenant_id=$1 AND biz_type=$2 AND biz_id=$3 ORDER BY acted_at, id`,
		tenantID, bizType, bizID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []LogParam
	for rows.Next() {
		var p LogParam
		if err := rows.Scan(&p.TenantID, &p.BizType, &p.BizID, &p.Step, &p.ActorID, &p.ActorRole, &p.Action, &p.Comment, &p.ActedAt); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// Editable 编辑锁规则矩阵（spec A 组）：
//   - 学校通过（SCHOOL_PASSED/APPROVED/EFFECTIVE）→ 全员锁（任何角色 false）
//   - 学院通过（COLLEGE_PASSED）→ 提交人锁（仅 R-ADMIN 可解锁编辑）
//   - 审批中（APPROVING/SUBMITTED）→ 全员锁
//   - 其余（DRAFT/RETURNED/REJECTED 等）→ 可编辑
func Editable(status, role string) bool {
	switch status {
	case "SCHOOL_PASSED", "APPROVED", "EFFECTIVE":
		return false
	case "APPROVING", "SUBMITTED":
		return false
	case "COLLEGE_PASSED":
		return role == "R-ADMIN"
	default:
		return true
	}
}

// HasRole 角色包含判断（R-ADMIN 直通由调用方决定是否叠加）。
func HasRole(roles []string, want string) bool {
	for _, r := range roles {
		if r == want {
			return true
		}
	}
	return false
}

// NextStep 两级推进：给当前单据状态（PENDING/无步 = 0），返回下一步编号；
// 单级模式恒返回 1。两级：0→1（首审）→2（终审）。
func (t TwoStep) NextStep(enabled bool, doneSteps int) int {
	if !enabled {
		return 1
	}
	return doneSteps + 1
}
