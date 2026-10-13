package migrate

import (
	"context"
	"errors"
	"fmt"

	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/postgres"
	_ "github.com/golang-migrate/migrate/v4/source/file"

	"github.com/eplugger/ark/internal/platform/db"
)

// Up 应用全部迁移到最新版本。
func Up(databaseURL, dir string) error {
	m, err := migrate.New("file://"+dir, databaseURL)
	if err != nil {
		return fmt.Errorf("初始化迁移器: %w", err)
	}
	defer m.Close()
	if err := m.Up(); err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return fmt.Errorf("执行迁移: %w", err)
	}
	return nil
}

// Down 回滚全部迁移。
func Down(databaseURL, dir string) error {
	m, err := migrate.New("file://"+dir, databaseURL)
	if err != nil {
		return err
	}
	defer m.Close()
	if err := m.Down(); err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return err
	}
	return nil
}

// queryExists 断言 public schema 下某表存在（供集成测试用）。
func queryExists(databaseURL, table string) (bool, error) {
	pool, err := db.Connect(context.Background(), databaseURL)
	if err != nil {
		return false, err
	}
	defer pool.Close()
	var reg *string
	if err := pool.QueryRow(context.Background(),
		"SELECT to_regclass('public.'||$1)::text", table).Scan(&reg); err != nil {
		return false, err
	}
	return reg != nil, nil
}
