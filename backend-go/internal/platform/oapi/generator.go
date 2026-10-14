package oapi

import (
	"math/rand"
	"time"
)

// Generate 依 data 子 schema 造一个合规示例值（移植 Node generator.js 的 generate）。
// 无结构化 data 时回退空对象，保证包络仍为合法 JSON。
func (o *Op) Generate() any {
	d := o.DataSchema()
	if d == nil {
		return map[string]any{}
	}
	return genValue(o.doc, d, 0)
}

// genValue 递归地把一个 JSON Schema 节点变成示例值：
// 处理 $ref（经 Doc.deref 的本模块内解引用）、allOf 合并、array（含 PageResult 补全）、
// object、string（enum/format）、integer/number、boolean。depth>8 时收敛为 nil 防环。
func genValue(doc *Doc, node map[string]any, depth int) any {
	if node == nil || depth > 8 {
		return nil
	}
	if ref, ok := node["$ref"].(string); ok {
		return genValue(doc, doc.deref(ref), depth+1)
	}
	if all, ok := node["allOf"].([]any); ok {
		out := map[string]any{}
		for _, s := range all {
			if sm, ok := s.(map[string]any); ok {
				if v, ok := genValue(doc, sm, depth+1).(map[string]any); ok {
					for k, x := range v {
						out[k] = x
					}
				}
			}
		}
		return out
	}
	switch node["type"] {
	case "array":
		items, _ := node["items"].(map[string]any)
		n := 3
		if node["x-count"] != nil {
			if c, ok := node["x-count"].(int); ok {
				n = c
			}
		}
		arr := make([]any, 0, n)
		for i := 0; i < n; i++ {
			arr = append(arr, genValue(doc, items, depth+1))
		}
		return arr
	case "object":
		props, _ := node["properties"].(map[string]any)
		out := map[string]any{}
		for k, ps := range props {
			pm, _ := ps.(map[string]any)
			out[k] = genValue(doc, pm, depth+1)
		}
		// PageResult 常见形状补全：有 list 则同步 total/page/size
		if list, ok := out["list"].([]any); ok {
			out["total"] = len(list)
			out["page"] = 1
			out["size"] = len(list)
		}
		return out
	case "string":
		return genString(node)
	case "integer", "number":
		return genNumber(node)
	case "boolean":
		return true
	default:
		return nil
	}
}

// genString：优先取 enum（跳过 null 候选，避免产出 "null"），再按 format 造日期/UUID，兜底 "sample"。
func genString(node map[string]any) any {
	if enum, ok := node["enum"].([]any); ok && len(enum) > 0 {
		var cand []any
		for _, e := range enum {
			if e != nil {
				cand = append(cand, e)
			}
		}
		if len(cand) > 0 {
			if s, ok := cand[rand.Intn(len(cand))].(string); ok {
				return s
			}
		}
	}
	switch node["format"] {
	case "date-time":
		return time.Now().UTC().Format(time.RFC3339Nano)
	case "date":
		return time.Now().UTC().Format("2006-01-02")
	case "uuid":
		return "00000000-0000-0000-0000-000000000000"
	}
	return "sample"
}

// genNumber：integer 造 [0,1000)，number 造两位小数的浮点。
func genNumber(node map[string]any) any {
	if node["type"] == "integer" {
		return rand.Intn(1000)
	}
	return float64(rand.Intn(100000)) / 100
}
