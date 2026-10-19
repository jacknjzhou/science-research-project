package expertreview

import "math/rand"

// drawRule 是评审抽取规则（来自 n_review_task.draw_rule jsonb + 项目方回避快照）。
// FieldTags 领域匹配；OrgDiversity 单位去重优先；Exclude* 为项目/PI 侧强制回避（单位名/人员 user_id）。
type drawRule struct {
	FieldTags      []string `json:"field_tags"`
	MinTitle       string   `json:"min_title"`
	OrgDiversity   bool     `json:"org_diversity"`
	ExcludeUserIDs []int64  `json:"exclude_user_ids"`
	ExcludeOrgs    []string `json:"exclude_orgs"`
}

// candidate 是一个可抽取专家候选（DB 侧由 n_expert 映射而来）。
// AvoidOrg/AvoidUsr 承载专家本人登记的回避单位/人员，供 handler 侧并入回避判定。
type candidate struct {
	ExpertID int64
	UserID   int64
	OrgName  string
	Fields   []string
	AvoidOrg []string
	AvoidUsr []int64
}

func contains(ss []string, s string) bool {
	for _, x := range ss {
		if x == s {
			return true
		}
	}
	return false
}

func containsI64(is []int64, v int64) bool {
	for _, x := range is {
		if x == v {
			return true
		}
	}
	return false
}

// eligible 判定候选是否通过领域匹配 + 回避（项目/PI 侧 exclude + 传入的回避快照）。
// avoidOrgs/avoidUserIDs 是 handler 侧并入的项目成员回避快照（纯测传 nil）。
func eligible(c candidate, rule drawRule, avoidOrgs []string, avoidUserIDs []int64) bool {
	if len(rule.FieldTags) > 0 {
		hit := false
		for _, f := range rule.FieldTags {
			if contains(c.Fields, f) {
				hit = true
				break
			}
		}
		if !hit {
			return false
		}
	}
	// 项目/PI 侧强制回避候选所在单位。
	if contains(rule.ExcludeOrgs, c.OrgName) || contains(avoidOrgs, c.OrgName) {
		return false
	}
	// 候选本人回避目标单位（handler 把目标 org 放进 avoidOrgs）。
	if c.OrgName != "" {
		for _, o := range c.AvoidOrg {
			if contains(avoidOrgs, o) || contains(rule.ExcludeOrgs, o) {
				return false
			}
		}
	}
	// 回避人员（本人 user_id 命中 exclude/快照，或候选本人登记回避的 user_id 命中）。
	if c.UserID != 0 && (containsI64(rule.ExcludeUserIDs, c.UserID) || containsI64(avoidUserIDs, c.UserID)) {
		return false
	}
	for _, u := range c.AvoidUsr {
		if containsI64(rule.ExcludeUserIDs, u) || containsI64(avoidUserIDs, u) {
			return false
		}
	}
	return true
}

// drawExperts 过滤回避 → 洗牌（seed 确定性，铁律 11：注入 seed，勿用全局 rand）→ 取 n；
// OrgDiversity 时按单位去重优先，不足再回填其余候选。
func drawExperts(pool []candidate, rule drawRule, n int, seed int64) []int64 {
	var ok []candidate
	for _, c := range pool {
		if eligible(c, rule, nil, nil) {
			ok = append(ok, c)
		}
	}
	rnd := rand.New(rand.NewSource(seed))
	rnd.Shuffle(len(ok), func(i, j int) { ok[i], ok[j] = ok[j], ok[i] })
	if rule.OrgDiversity {
		seen := map[string]bool{}
		var dedup []candidate
		for _, c := range ok {
			if !seen[c.OrgName] {
				seen[c.OrgName] = true
				dedup = append(dedup, c)
			}
		}
		// 不足则回填其余
		for _, c := range ok {
			if len(dedup) >= n {
				break
			}
			if !containsID(dedup, c.ExpertID) {
				dedup = append(dedup, c)
			}
		}
		ok = dedup
	}
	if n > len(ok) {
		n = len(ok)
	}
	out := make([]int64, 0, n)
	for _, c := range ok[:n] {
		out = append(out, c.ExpertID)
	}
	return out
}

// drawExpertsWithAvoid 是 handler 侧入口：并入项目/PI 回避快照后再抽取。
func drawExpertsWithAvoid(pool []candidate, rule drawRule, avoidOrgs []string, avoidUserIDs []int64, n int, seed int64) []int64 {
	var ok []candidate
	for _, c := range pool {
		if eligible(c, rule, avoidOrgs, avoidUserIDs) {
			ok = append(ok, c)
		}
	}
	rnd := rand.New(rand.NewSource(seed))
	rnd.Shuffle(len(ok), func(i, j int) { ok[i], ok[j] = ok[j], ok[i] })
	if rule.OrgDiversity {
		seen := map[string]bool{}
		var dedup []candidate
		for _, c := range ok {
			if !seen[c.OrgName] {
				seen[c.OrgName] = true
				dedup = append(dedup, c)
			}
		}
		for _, c := range ok {
			if len(dedup) >= n {
				break
			}
			if !containsID(dedup, c.ExpertID) {
				dedup = append(dedup, c)
			}
		}
		ok = dedup
	}
	if n > len(ok) {
		n = len(ok)
	}
	out := make([]int64, 0, n)
	for _, c := range ok[:n] {
		out = append(out, c.ExpertID)
	}
	return out
}

// hitAvoid 判定被回避候选是否本应命中（供落审计 avoid_hit）。
func hitAvoid(c candidate, rule drawRule, avoidOrgs []string, avoidUserIDs []int64) bool {
	if contains(rule.ExcludeOrgs, c.OrgName) || contains(avoidOrgs, c.OrgName) {
		return true
	}
	if c.UserID != 0 && (containsI64(rule.ExcludeUserIDs, c.UserID) || containsI64(avoidUserIDs, c.UserID)) {
		return true
	}
	return false
}

func containsID(cs []candidate, id int64) bool {
	for _, c := range cs {
		if c.ExpertID == id {
			return true
		}
	}
	return false
}
