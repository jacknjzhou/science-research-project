package migrations

import (
	"os"
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
