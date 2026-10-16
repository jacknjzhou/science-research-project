// Package seeddemo 提供演示数据播种（非 migration，避免污染测试库断言）。
// 由 main 在 migrate.Up 之后调用，env ARK_SEED_DEMO=1 开启；幂等：
// e_project 已存在 code LIKE 'DEMO-%' 时整体跳过，事务原子执行。
package seeddemo

import (
	"context"
	_ "embed"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed seed_demo.sql
var sqlDemo string

// Apply 在单个事务内执行演示数据播种（幂等）。
func Apply(ctx context.Context, pool *pgxpool.Pool) error {
	tx, err := pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("seeddemo 开启事务: %w", err)
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, sqlDemo); err != nil {
		return fmt.Errorf("seeddemo 执行: %w", err)
	}
	return tx.Commit(ctx)
}
