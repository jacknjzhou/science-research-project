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
// 注意：仅拼入 PostgreSQL 目标段；design/08 含第二部分 ClickHouse OLAP（MergeTree/内联列 COMMENT
// 等非 PG 语法），ADR-003 双引擎落地——由 stripNonPostgres 剔除。
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
	b.WriteString("-- 非 PostgreSQL 段（ClickHouse OLAP / Doris 等）已由 gen.go::stripNonPostgres 剔除，ADR-003。\n")
	for _, f := range files {
		data, err := os.ReadFile(filepath.Join(designDir, f))
		if err != nil {
			return "", err
		}
		data, stripped := stripNonPostgres(data)
		b.WriteString(fmt.Sprintf("\n-- ===== %s =====\n", f))
		b.Write(data)
		if stripped {
			b.WriteString("\n-- ↑ 该文件后半段（第二部分 · ClickHouse OLAP）非 PostgreSQL 目标，已剔除\n")
		}
		b.WriteString("\n")
	}
	return b.String(), nil
}

// stripNonPostgres 截掉一个 design DDL 文件里 "第二部分 · ClickHouse ..." 起（含前置 -- ### 分界线）
// 之后的所有内容——这些是 ClickHouse / Doris 侧的数仓 DDL，PostgreSQL 语法解析不了（列内 COMMENT /
// UInt64 / ENGINE = MergeTree 等）。返回 (裁剪后字节, 是否发生裁剪)。
func stripNonPostgres(data []byte) ([]byte, bool) {
	lines := strings.Split(string(data), "\n")
	for i, ln := range lines {
		t := strings.TrimSpace(ln)
		// 中文注释头：允许前后空格；识别 marker：同一行同时含 "第二部分" 与 "OLAP"。
		// 单靠 "第二部分" 或 "ClickHouse" 会命中文件顶部 TOC 与说明注释，必须锁定 "OLAP"
		// 这一 section-header 独有词（design/08 第 414 行）。
		if strings.HasPrefix(t, "--") &&
			strings.Contains(t, "第二部分") &&
			strings.Contains(t, "OLAP") {
			cut := i
			// 若前一行是 "-- ####..." 分界线，一并去掉，保持拼接后视觉干净
			if cut > 0 {
				prev := strings.TrimSpace(lines[cut-1])
				if strings.HasPrefix(prev, "-- ###") {
					cut--
				}
			}
			kept := strings.Join(lines[:cut], "\n")
			return []byte(kept), true
		}
	}
	return data, false
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
