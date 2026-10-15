// Package llm：NewAPI/OpenAI 兼容 /v1/chat/completions 客户端（T9）。
// 仅做结构化 JSON 建议输出；失败一律返回 error，由调用方决定降级路径（AI 仅建议，不阻塞业务）。
package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// Verdict LLM 结构化建议（AiReviewResult 契约子集）。
type Verdict struct {
	Verdict    string  `json:"verdict"` // PASS / REVIEW / REJECT
	Confidence float64 `json:"confidence"`
	Issues     []Issue `json:"issues"`
}

// Issue 命中的规则与原因。
type Issue struct {
	Rule   string `json:"rule"`
	Reason string `json:"reason"`
}

type Client struct {
	http    *http.Client
	baseURL string
	apiKey  string
	model   string
}

func New(baseURL, apiKey, model string, timeout time.Duration) *Client {
	return &Client{
		http:    &http.Client{Timeout: timeout},
		baseURL: strings.TrimRight(baseURL, "/"),
		apiKey:  apiKey,
		model:   model,
	}
}

type chatRequest struct {
	Model          string        `json:"model"`
	Messages       []chatMessage `json:"messages"`
	Temperature    float64       `json:"temperature"`
	ResponseFormat *respFormat   `json:"response_format,omitempty"`
}

type respFormat struct{ Type string `json:"type"` }

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

// ChatJSON 发起对话并解析 JSON 输出。任何网络/协议/解析错误都作为 error 返回。
func (c *Client) ChatJSON(ctx context.Context, system, user string) (Verdict, error) {
	if c == nil || c.baseURL == "" {
		return Verdict{}, fmt.Errorf("llm 未配置")
	}
	reqBody, err := json.Marshal(chatRequest{
		Model:          c.model,
		Messages:       []chatMessage{{Role: "system", Content: system}, {Role: "user", Content: user}},
		Temperature:    0.2,
		ResponseFormat: &respFormat{Type: "json_object"},
	})
	if err != nil {
		return Verdict{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/chat/completions", bytes.NewReader(reqBody))
	if err != nil {
		return Verdict{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return Verdict{}, err
	}
	defer resp.Body.Close()
	var cr chatResponse
	if err := json.NewDecoder(resp.Body).Decode(&cr); err != nil {
		return Verdict{}, fmt.Errorf("响应解析失败: %w", err)
	}
	if cr.Error != nil {
		return Verdict{}, fmt.Errorf("上游错误: %s", cr.Error.Message)
	}
	if resp.StatusCode != http.StatusOK {
		return Verdict{}, fmt.Errorf("上游状态 %d", resp.StatusCode)
	}
	if len(cr.Choices) == 0 {
		return Verdict{}, fmt.Errorf("上游无 choices")
	}
	var v Verdict
	if err := json.Unmarshal([]byte(cr.Choices[0].Message.Content), &v); err != nil {
		return Verdict{}, fmt.Errorf("输出非 JSON: %w", err)
	}
	return v, nil
}
