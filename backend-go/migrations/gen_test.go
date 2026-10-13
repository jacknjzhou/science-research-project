package migrations

import (
	"os"
	"strings"
	"testing"
)

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
