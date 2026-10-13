package migrations

//go:generate go run ./cmd/gen

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// GenerateUp 读取 designDir 下 00-common.sql 与各 *.ddl.sql（按文件名排序），
// 拼成单个 up.sql 内容。顺序：common → 01..11 模块。
func GenerateUp(designDir string) (string, error) {
	entries, err := os.ReadDir(designDir)
	if err != nil {
		return "", fmt.Errorf("读 design 目录: %w", err)
	}
	var files []string
	for _, e := range entries {
		n := e.Name()
		if n == "00-common.sql" {
			files = append([]string{n}, files...) // common 置顶
		} else if strings.HasSuffix(n, ".ddl.sql") {
			files = append(files, n)
		}
	}
	sort.SliceStable(files, func(i, j int) bool {
		if files[i] == "00-common.sql" {
			return true
		}
		if files[j] == "00-common.sql" {
			return false
		}
		return files[i] < files[j]
	})

	var b strings.Builder
	b.WriteString("-- 由 design/*.sql 自动生成，勿手改。来源：\n")
	for _, f := range files {
		data, err := os.ReadFile(filepath.Join(designDir, f))
		if err != nil {
			return "", err
		}
		b.WriteString(fmt.Sprintf("\n-- ===== %s =====\n", f))
		b.Write(data)
		b.WriteString("\n")
	}
	return b.String(), nil
}

// WriteFiles 生成 up/down 到当前目录（供 go:generate）。
func WriteFiles(designDir string) error {
	up, err := GenerateUp(designDir)
	if err != nil {
		return err
	}
	upName := filepath.Join(".", "000001_init.up.sql")
	downName := filepath.Join(".", "000001_init.down.sql")
	if err := os.WriteFile(upName, []byte(up), 0o644); err != nil {
		return err
	}
	down := "-- 回滚：清空 public schema 中由本次迁移创建的表。\nDROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n"
	return os.WriteFile(downName, []byte(down), 0o644)
}
