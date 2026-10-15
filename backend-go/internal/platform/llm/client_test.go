package llm

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// TestChatJSONPass：上游返回合法 JSON → 解析成功。
func TestChatJSONPass(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "Bearer sk-test" {
			t.Errorf("Authorization 应 Bearer sk-test，得 %q", got)
		}
		if r.URL.Path != "/v1/chat/completions" {
			t.Errorf("path 应 /v1/chat/completions，得 %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"{\"verdict\":\"PASS\",\"confidence\":0.93,\"issues\":[]}"}}]}`))
	}))
	defer srv.Close()

	c := New(srv.URL, "sk-test", "gpt-x", 5*time.Second)
	v, err := c.ChatJSON(context.Background(), "sys", "usr")
	if err != nil {
		t.Fatalf("应成功，得 %v", err)
	}
	if v.Verdict != "PASS" || v.Confidence != 0.93 {
		t.Fatalf("解析错误，得 %+v", v)
	}
}

// TestChatJSONDegraded：上游 500 / 非 JSON 输出 / 超时 → error（调用方降级）。
func TestChatJSONDegraded(t *testing.T) {
	// 500
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":{"message":"boom"}}`))
	}))
	defer srv.Close()
	c := New(srv.URL, "k", "m", 2*time.Second)
	if _, err := c.ChatJSON(context.Background(), "s", "u"); err == nil {
		t.Fatal("500 应返回 error")
	}

	// 非 JSON 输出
	srv2 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"我觉得没问题"}}]}`))
	}))
	defer srv2.Close()
	c2 := New(srv2.URL, "k", "m", 2*time.Second)
	if _, err := c2.ChatJSON(context.Background(), "s", "u"); err == nil {
		t.Fatal("非 JSON 输出应返回 error")
	}

	// 超时
	srv3 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(200 * time.Millisecond)
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv3.Close()
	c3 := New(srv3.URL, "k", "m", 50*time.Millisecond)
	if _, err := c3.ChatJSON(context.Background(), "s", "u"); err == nil {
		t.Fatal("超时应返回 error")
	}

	// 未配置
	var nilClient *Client
	if _, err := nilClient.ChatJSON(context.Background(), "s", "u"); err == nil {
		t.Fatal("未配置应返回 error")
	}
}
