package funding

// llmVerdict：LLM 结构化建议（AiReviewResult 契约子集）。
type llmVerdict struct {
	Verdict    string   `json:"verdict"` // PASS / REVIEW / REJECT
	Confidence float64  `json:"confidence"`
	Issues     []llmIssue `json:"issues"`
}

type llmIssue struct {
	Rule   string `json:"rule"`
	Reason string `json:"reason"`
}
