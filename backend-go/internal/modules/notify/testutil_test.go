package notify

import (
	"encoding/json"
	"io"
	"strings"
	"testing"
)

func strReader(s string) io.Reader { return strings.NewReader(s) }

// bodyJSON 解析统一信封，返回 data 对象（失败即 Fatal）。
func bodyJSON(t *testing.T, b []byte) map[string]any {
	t.Helper()
	var env struct {
		Code int             `json:"code"`
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(b, &env); err != nil {
		t.Fatalf("响应非 JSON: %v body=%s", err, string(b))
	}
	if env.Code != 0 {
		t.Fatalf("业务码应 0，得 %d body=%s", env.Code, string(b))
	}
	var m map[string]any
	if err := json.Unmarshal(env.Data, &m); err != nil {
		t.Fatalf("data 解析失败: %v body=%s", err, env.Data)
	}
	return m
}

var _ = testing.Short
