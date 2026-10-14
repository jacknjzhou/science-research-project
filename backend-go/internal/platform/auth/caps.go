package auth

import (
	"sort"
	"strings"

	"github.com/casbin/casbin/v2"
)

// BuildCaps 依当前用户角色，从 Casbin 策略集派生能力集合，每项形如 "<obj模板> <METHOD>"。
// 与服务端传输层鉴权同源（同一 model+policy）；前端 auth.can() 据此做按钮/操作级门控。
func BuildCaps(enf *casbin.Enforcer, roles []string) []string {
	if enf == nil {
		return []string{}
	}
	rules, err := enf.GetPolicy()
	if err != nil {
		return []string{}
	}
	in := make(map[string]bool, len(roles))
	for _, r := range roles {
		in[r] = true
	}
	set := map[string]struct{}{}
	for _, p := range rules {
		if len(p) < 3 || !in[p[0]] {
			continue
		}
		set[strings.TrimSpace(p[1]+" "+strings.ToUpper(p[2]))] = struct{}{}
	}
	out := make([]string, 0, len(set))
	for s := range set {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}
