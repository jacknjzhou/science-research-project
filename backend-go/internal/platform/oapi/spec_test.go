package oapi

import (
	"os"
	"testing"
)

func designDir() string {
	if d := os.Getenv("DESIGN_DIR"); d != "" {
		return d
	}
	// 测试工作目录 = backend-go/internal/platform/oapi；上溯 4 级至仓库根的 design/
	return "../../../../design"
}

func TestSpec_ExtractDataSchema_ListApplications(t *testing.T) {
	s, err := LoadDir(designDir())
	if err != nil {
		t.Fatal(err)
	}
	op := s.Find("GET", "/apply/applications")
	if op == nil {
		t.Fatal("未找到 GET /apply/applications")
	}
	data := op.DataSchema() // 解析 allOf 覆写出的 PageResult{list:Application}
	if data == nil {
		t.Fatal("data 子 schema 为空")
	}
	// data 应含 list:array，items $ref → Application
	props, _ := data["properties"].(map[string]any)
	list, _ := props["list"].(map[string]any)
	if list == nil || list["type"] != "array" {
		t.Fatalf("list 结构不符: %+v", list)
	}
}

func TestSpec_Find(t *testing.T) {
	s, err := LoadDir(designDir())
	if err != nil {
		t.Fatal(err)
	}
	if got := s.Find("post", "/apply/applications"); got == nil {
		t.Fatal("Find 应大小写无关地命中 POST /apply/applications")
	} else if got.Method() != "post" {
		t.Fatalf("method=%q", got.Method())
	}
	if got := s.Find("GET", "/apply/nope"); got != nil {
		t.Fatal("不存在的模板路径应返回 nil")
	}
}

func TestSpec_Match_Template(t *testing.T) {
	s, err := LoadDir(designDir())
	if err != nil {
		t.Fatal(err)
	}
	// 具体路径命中模板 /apply/applications/{id}
	op := s.Match("GET", "/apply/applications/123")
	if op == nil {
		t.Fatal("Match 未命中 GET /apply/applications/{id}")
	}
	if op.Path() != "/apply/applications/{id}" {
		t.Fatalf("期望模板路径 /apply/applications/{id}，实际 %q", op.Path())
	}
	// 查询串应被剥离
	if op := s.Match("GET", "/apply/applications?status=DRAFT&page=1"); op == nil || op.Path() != "/apply/applications" {
		t.Fatalf("Match 应剥离查询串并精确命中集合，实际 %+v", op)
	}
}

func TestSpec_LoadCounts(t *testing.T) {
	s, err := LoadDir(designDir())
	if err != nil {
		t.Fatal(err)
	}
	if len(s.Docs) != 11 {
		t.Fatalf("期望加载 11 份 *.openapi.yaml，实际 %d", len(s.Docs))
	}
	t.Logf("LoadDir: docs=%d paths=%d operations=%d", len(s.Docs), s.Paths(), s.Ops())
	if s.Ops() == 0 {
		t.Fatal("未索引到任何操作")
	}
}
