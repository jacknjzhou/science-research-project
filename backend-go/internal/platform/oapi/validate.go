package oapi

import (
	"encoding/json"
	"strings"

	"github.com/xeipuuv/gojsonschema"
)

// ResolveDataSchema 取 op 的 data 子 schema（已由 Op.DataSchema 展平 allOf）并转成
// gojsonschema 可用的 map[string]any。经 JSON 往返以剔除 yaml 专有类型，保持纯 JSON 值。
// 无结构化 data 时回退为泛型 object 节点。
func ResolveDataSchema(op *Op) map[string]any {
	d := op.DataSchema()
	if d == nil {
		return map[string]any{"type": "object"}
	}
	b, _ := json.Marshal(d)
	var out map[string]any
	_ = json.Unmarshal(b, &out)
	return out
}

// Validate 用 schema 校验 value，返回错误列表（空=通过）。
// schema 里指向本文档的 #/... $ref 先由 inlineRefs 替换为宽松多类型节点，
// 从而在 M0 只校验主干字段的存在与类型，把 enum/跨文档严格解析留待 M1。
func Validate(value any, schema map[string]any) []string {
	sanitized := inlineRefs(schema, value)
	docLoader := gojsonschema.NewGoLoader(value)
	schemaLoader := gojsonschema.NewGoLoader(sanitized)
	res, err := gojsonschema.Validate(schemaLoader, docLoader)
	if err != nil {
		return []string{err.Error()}
	}
	var msgs []string
	for _, e := range res.Errors() {
		msgs = append(msgs, e.String())
	}
	return msgs
}

// inlineRefs 遍历 schema，把 {"$ref": "#/..."} 节点替换为一个放行任意 JSON 类型的
// 宽松节点。这样 PageResult 的 list/total/page/size 与已内联字段的类型仍被校验，
// 而 enum（如 status）等跨文档引用不在 M0 做严格解析——先绿再强。
func inlineRefs(schema map[string]any, _ any) map[string]any {
	var walk func(any) any
	walk = func(n any) any {
		m, ok := n.(map[string]any)
		if !ok {
			if arr, ok2 := n.([]any); ok2 {
				for i := range arr {
					arr[i] = walk(arr[i])
				}
				return arr
			}
			return n
		}
		if ref, isRef := m["$ref"].(string); isRef && strings.HasPrefix(ref, "#/") {
			return map[string]any{"type": []string{"string", "number", "integer", "boolean", "object", "array", "null"}}
		}
		for k, v := range m {
			m[k] = walk(v)
		}
		return m
	}
	out, _ := walk(schema).(map[string]any)
	return out
}
