package funding

import (
	"context"
	"encoding/json"
	"io"
	"strings"
	"testing"
)

func testCtx() context.Context { return context.Background() }

func strReader(s string) io.Reader { return strings.NewReader(s) }

// parse 解析信封，data 再落 target（可空）。
func parse(t *testing.T, body []byte, target any) {
	t.Helper()
	var env struct {
		Code  int             `json:"code"`
		Msg   string          `json:"message"`
		Data  json.RawMessage `json:"data"`
		Trace string          `json:"traceId"`
	}
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("响应非 JSON: %v body=%s", err, string(body))
	}
	if target != nil && len(env.Data) > 0 {
		if err := json.Unmarshal(env.Data, target); err != nil {
			t.Fatalf("data 解析失败: %v body=%s", err, env.Data)
		}
	}
}

// numToStr：data 内金额字段统一按 string 断言的便捷读取。
func dataMap(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var env struct {
		Data map[string]any `json:"data"`
	}
	_ = json.Unmarshal(body, &env)
	return env.Data
}
