package migrations

import (
	"os"
	"regexp"
	"strings"
	"testing"
)

func TestGenerateUp_StripsClickHouse(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	// 真实 ClickHouse DDL 语法 token 必须全部消失（PG parser 遇之即 5 号报错）
	for _, bad := range []string{
		"UInt64",
		"ENGINE = MergeTree",
		"ENGINE=MergeTree",
		"CREATE TABLE dwh.",
		"CREATE TABLE DWH.",
		"LowCardinality(",
	} {
		if strings.Contains(up, bad) {
			t.Fatalf("生成的 up.sql 不应含 ClickHouse DDL token: %q（ADR-003 双引擎：CK 段应由 stripNonPostgres 剔除）", bad)
		}
	}
	// 同时确认 design/08 第一部分 PostgreSQL OLTP 表未误伤
	for _, want := range []string{
		"CREATE TABLE D_EXPORT",
		"CREATE TABLE D_METRIC",
	} {
		if !strings.Contains(up, want) {
			t.Fatalf("生成的 up.sql 缺少 D 模块 PG 侧对象: %s（strip 过早/过狠？）", want)
		}
	}
}

func TestGenerateFromDesign(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"CREATE TABLE sys_user", "CREATE TABLE p_application", "CREATE TABLE seq_prefix_registry"} {
		if !strings.Contains(strings.ToLower(up), strings.ToLower(want)) {
			t.Fatalf("生成的 up.sql 缺少: %s", want)
		}
	}
	// common 必须先于模块：sys_user 出现在 p_application 之前
	if strings.Index(strings.ToLower(up), "sys_user") > strings.Index(strings.ToLower(up), "p_application") {
		t.Fatal("00-common.sql 应最先拼接")
	}
}

// TestGenerateUp_NoForwardReferences 静态守卫：生成的 up.sql 里 CREATE TABLE 内联列
// REFERENCES 的目标必须先前已由同文件（或前置 00-common.sql）里的 CREATE TABLE 建过；
// 否则 PostgreSQL 会在 CREATE 阶段报 `relation "xxx" does not exist`——正是
// docker compose 首启动 design/02 E_FINAL_ACCEPT→E_ARCHIVE_CHECKLIST 前向 FK 的翻车姿势。
// ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY 是延迟外键位，允许前向。
func TestGenerateUp_NoForwardReferences(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	// PG 会把未加引号的标识符折叠成小写；比对统一 lower()
	reCreate := regexp.MustCompile(`(?i)CREATE\s+TABLE\s+([A-Za-z_][\w\.]*)`)
	reRef := regexp.MustCompile(`(?i)REFERENCES\s+([A-Za-z_][\w\.]*)\s*\(`)
	reAlter := regexp.MustCompile(`(?i)^\s*ALTER\s+TABLE\b`)

	created := map[string]bool{}
	inCreateBlock := false
	inAlterBlock := false

	lines := strings.Split(up, "\n")
	for i, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "--") {
			continue
		}
		// 语句块进入
		if reCreate.MatchString(line) {
			inCreateBlock = true
		} else if reAlter.MatchString(line) {
			inAlterBlock = true
		}

		// CREATE TABLE 头一行也计入 created（同文件的下一个 REFERENCES 视为已就绪）
		for _, m := range reCreate.FindAllStringSubmatch(line, -1) {
			created[strings.ToLower(m[1])] = true
		}

		// ALTER 段的 REFERENCES 允许前向
		if !inAlterBlock && inCreateBlock {
			for _, m := range reRef.FindAllStringSubmatch(line, -1) {
				target := strings.ToLower(m[1])
				if !created[target] {
					t.Fatalf("前向 REFERENCES: up.sql 第 %d 行 CREATE TABLE 内联 REFERENCES %s，但该表尚未创建（PG 会报 relation %q does not exist）\n  行: %s",
						i+1, m[1], target, line)
				}
			}
		}

		// 语句结束（同一行含 ");" 视为收束，够 DDL 场景）
		if strings.Contains(line, ");") {
			inCreateBlock = false
			inAlterBlock = false
		}
	}
}
