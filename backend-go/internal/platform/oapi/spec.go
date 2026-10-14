package oapi

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// Doc 是一份已解析的 OpenAPI 文档（design/*.openapi.yaml）。
type Doc struct {
	Name string
	Raw  map[string]any
}

// Spec 是全模块契约的运行期索引，供合规测试（任务 8）与 passthrough（任务 11/12）消费。
type Spec struct {
	Docs []*Doc
	// index: "METHOD /template/path" -> *Op
	index map[string]*Op
	// ops 保存全部操作，供 Match 做模板匹配时遍历。
	ops []*Op
}

// Op 是一条操作（method + 模板路径 + 原始 operation 节点）。
type Op struct {
	doc    *Doc
	method string
	path   string
	raw    map[string]any
	// rx/lit 在 LoadDir 时预编译，Match 只读，避免并发下重复编译与数据竞争。
	rx  *regexp.Regexp
	lit int
}

// Method 返回小写 HTTP 方法。
func (o *Op) Method() string { return o.method }

// Path 返回 OpenAPI 模板路径（含 {var}）。
func (o *Op) Path() string { return o.path }

// Doc 返回所属契约文档。
func (o *Op) Doc() *Doc { return o.doc }

// DataSchema 取 200/201 application/json 响应里 ApiResponse.data 子 schema，
// 解析 allOf 覆写并把结果 schema 的 allOf 链合并成扁平 properties，
// 以便下游直接读取 data["properties"]。无结构化 data 时可能返回泛型子 schema 或 nil。
func (o *Op) DataSchema() map[string]any {
	resp := o.raw["responses"]
	m, _ := resp.(map[string]any)
	if m == nil {
		return nil
	}
	var r any = m["200"]
	if r == nil {
		r = m["201"]
	}
	rm, _ := r.(map[string]any)
	if rm == nil {
		return nil
	}
	// $ref 解引用（本模块内 #/...）
	if ref, ok := rm["$ref"].(string); ok {
		rm = o.doc.deref(ref)
	}
	content, _ := rm["content"].(map[string]any)
	jsonc, _ := content["application/json"].(map[string]any)
	sch, _ := jsonc["schema"].(map[string]any)
	if sch == nil {
		return nil
	}
	d := o.extractData(sch)
	if d == nil {
		return nil
	}
	return o.doc.flatten(d)
}

func isStructured(d map[string]any) bool {
	if d == nil {
		return false
	}
	if d["$ref"] != nil || d["allOf"] != nil || d["oneOf"] != nil || d["anyOf"] != nil || d["items"] != nil {
		return true
	}
	if p, ok := d["properties"].(map[string]any); ok && len(p) > 0 {
		return true
	}
	return false
}

// extractData：从 allOf[ApiResponse, {data:...}] 里取出内联覆写的结构化 data；否则泛型。
// 与 Node schema.js 的 extractDataSchema 同构：优先内联覆写的 data，跳过 ApiResponse 泛型 data。
func (o *Op) extractData(rs map[string]any) map[string]any {
	if p, ok := rs["properties"].(map[string]any); ok {
		if d, ok := p["data"].(map[string]any); ok {
			return d
		}
	}
	if all, ok := rs["allOf"].([]any); ok {
		var generic map[string]any
		for _, sub := range all {
			sm, _ := sub.(map[string]any)
			if ref, ok := sm["$ref"].(string); ok {
				sm = o.doc.deref(ref)
			}
			if sm == nil {
				continue
			}
			props, _ := sm["properties"].(map[string]any)
			d, _ := props["data"].(map[string]any)
			if isStructured(d) {
				return d
			}
			if d != nil && generic == nil {
				generic = d
			}
		}
		return generic
	}
	return nil
}

// flatten：把 data 子 schema 的 allOf 链合并成单一 properties（$ref 解引用后叠加，
// 后者覆盖前者）。无 allOf 时原样返回，绝不修改原始文档节点。
func (d *Doc) flatten(s map[string]any) map[string]any {
	if s == nil {
		return nil
	}
	all, ok := s["allOf"].([]any)
	if !ok {
		return s
	}
	out := map[string]any{}
	props := map[string]any{}
	// 保留同级的其它键（如 type/description/properties）
	for k, v := range s {
		if k == "allOf" {
			continue
		}
		if k == "properties" {
			if p, ok := v.(map[string]any); ok {
				for k2, v2 := range p {
					props[k2] = v2
				}
			}
			continue
		}
		out[k] = v
	}
	for _, sub := range all {
		sm, _ := sub.(map[string]any)
		if sm == nil {
			continue
		}
		if ref, ok := sm["$ref"].(string); ok {
			sm = d.deref(ref)
			if sm == nil {
				continue
			}
		}
		sm = d.flatten(sm) // 递归展平嵌套 allOf
		for k, v := range sm {
			if k == "properties" {
				continue
			}
			out[k] = v
		}
		if p, ok := sm["properties"].(map[string]any); ok {
			for k2, v2 := range p {
				props[k2] = v2
			}
		}
	}
	out["properties"] = props
	return out
}

func (d *Doc) deref(ref string) map[string]any {
	if !strings.HasPrefix(ref, "#/") {
		return nil
	}
	var cur any = d.Raw
	for _, seg := range strings.Split(strings.TrimPrefix(ref, "#/"), "/") {
		m, ok := cur.(map[string]any)
		if !ok {
			return nil
		}
		cur = m[seg]
	}
	out, _ := cur.(map[string]any)
	return out
}

// Find 按精确模板路径查操作："GET" + "/apply/applications"。
func (s *Spec) Find(method, path string) *Op {
	return s.index[strings.ToUpper(method)+" "+path]
}

// Ops 返回已索引的操作数。
func (s *Spec) Ops() int { return len(s.ops) }

// Paths 返回去重后的模板路径数。
func (s *Spec) Paths() int {
	set := map[string]struct{}{}
	for _, op := range s.ops {
		set[op.path] = struct{}{}
	}
	return len(set)
}

// LoadDir 读取 dir 下全部 *.openapi.yaml 并建索引。
func LoadDir(dir string) (*Spec, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("读 design: %w", err)
	}
	var names []string
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".openapi.yaml") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	s := &Spec{index: map[string]*Op{}}
	for _, n := range names {
		b, err := os.ReadFile(filepath.Join(dir, n))
		if err != nil {
			return nil, err
		}
		var raw map[string]any
		if err := yaml.Unmarshal(b, &raw); err != nil {
			return nil, fmt.Errorf("解析 %s: %w", n, err)
		}
		doc := &Doc{Name: n, Raw: raw}
		s.Docs = append(s.Docs, doc)
		paths, _ := raw["paths"].(map[string]any)
		var pnames []string
		for p := range paths {
			pnames = append(pnames, p)
		}
		sort.Strings(pnames)
		for _, p := range pnames {
			item := paths[p]
			im, _ := item.(map[string]any)
			var mnames []string
			for m := range im {
				mnames = append(mnames, m)
			}
			sort.Strings(mnames)
			for _, m := range mnames {
				ml := strings.ToLower(m)
				if ml != "get" && ml != "post" && ml != "put" && ml != "delete" && ml != "patch" {
					continue
				}
				om, _ := im[m].(map[string]any)
				op := &Op{doc: doc, method: ml, path: p, raw: om, rx: compileTemplate(p), lit: literalLen(p)}
				s.index[strings.ToUpper(ml)+" "+p] = op
				s.ops = append(s.ops, op)
			}
		}
	}
	return s, nil
}
