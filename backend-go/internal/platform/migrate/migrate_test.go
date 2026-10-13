package migrate

import (
	"os"
	"testing"
)

func TestUpDown_LiveIfProvided(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	dir := os.Getenv("ARK_MIGRATIONS_DIR")
	if dir == "" {
		dir = "../../migrations"
	}
	if err := Up(u, dir); err != nil {
		t.Fatal(err)
	}
	// 断言关键表存在
	if _, err := queryExists(u, "p_application"); err != nil {
		t.Fatalf("迁移后 p_application 不存在: %v", err)
	}
	if err := Down(u, dir); err != nil {
		t.Fatalf("Down 失败: %v", err)
	}
}
