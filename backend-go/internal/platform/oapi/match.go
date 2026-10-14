package oapi

import (
	"regexp"
	"strings"
)

// 本文件是路由匹配的归属地（任务 11）：模板路径 -> 锚定正则的编译、字面量长度优先级、
// 以及运行期 Spec.Match。LoadDir 建索引时预编译 rx/lit（见 spec.go），Match 只读遍历 s.ops，
// 避免并发下重复编译与数据竞争。

var splitRe = regexp.MustCompile(`(\{[^/}]+\})`)
var varRe = regexp.MustCompile(`^\{[^/}]+\}$`)

// compileTemplate：OpenAPI 模板路径 -> 锚定正则。{var} 支持整段（如 /{id}:score 中的 {id}）。
// 用 FindAllStringSubmatchIndex 保留 {var} 分隔符（Go 的 Regexp.Split 不会回带捕获组）。
func compileTemplate(tpl string) *regexp.Regexp {
	locs := splitRe.FindAllStringSubmatchIndex(tpl, -1)
	var b strings.Builder
	b.WriteString("^")
	last := 0
	for _, loc := range locs {
		b.WriteString(regexp.QuoteMeta(tpl[last:loc[0]])) // {var} 之前的字面量段
		b.WriteString(`([^/]+?)`)                         // {var} -> 单段通配
		last = loc[1]
	}
	b.WriteString(regexp.QuoteMeta(tpl[last:])) // 尾随字面量段（如 ":score"）
	b.WriteString("$")
	return regexp.MustCompile(b.String())
}

// literalLen：去掉 {var} 后的字面量字符数，越大越"具体"。
func literalLen(tpl string) int {
	return len(varRe.ReplaceAllString(tpl, ""))
}

// Match 按实际请求路径匹配操作：先剥离查询串与 /api/v1 前缀，再精确命中索引，
// 最后按模板正则匹配（{var} 通配，字面量更长者优先，避免 /{id} 抢走 /{id}:score）。
// 供 passthrough 生成器（任务 11/12）使用。
func (s *Spec) Match(method, urlPath string) *Op {
	p := urlPath
	if i := strings.IndexByte(p, '?'); i >= 0 {
		p = p[:i]
	}
	p = strings.TrimPrefix(p, "/api/v1")
	if !strings.HasPrefix(p, "/") {
		p = "/" + p
	}
	mu := strings.ToUpper(method)
	if op := s.index[mu+" "+p]; op != nil {
		return op
	}
	var best *Op
	bestLit := -1
	for _, op := range s.ops {
		if strings.ToUpper(op.method) != mu {
			continue
		}
		if !op.rx.MatchString(p) {
			continue
		}
		if op.lit > bestLit {
			bestLit = op.lit
			best = op
		}
	}
	return best
}
