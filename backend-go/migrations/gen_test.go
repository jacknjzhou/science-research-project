package migrations

import (
	"os"
	"regexp"
	"strings"
	"testing"
)

func TestGenerateUp_StripsClickHouse(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	// 真实 ClickHouse DDL 语法 token 必须全部消失（PG parser 遇之即 5 号报错）
	for _, bad := range []string{
		"UInt64",
		"ENGINE = MergeTree",
		"ENGINE=MergeTree",
		"CREATE TABLE dwh.",
		"CREATE TABLE DWH.",
		"LowCardinality(",
	} {
		if strings.Contains(up, bad) {
			t.Fatalf("生成的 up.sql 不应含 ClickHouse DDL token: %q（ADR-003 双引擎：CK 段应由 stripNonPostgres 剔除）", bad)
		}
	}
	// 同时确认 design/08 第一部分 PostgreSQL OLTP 表未误伤
	for _, want := range []string{
		"CREATE TABLE D_EXPORT",
		"CREATE TABLE D_METRIC",
	} {
		if !strings.Contains(up, want) {
			t.Fatalf("生成的 up.sql 缺少 D 模块 PG 侧对象: %s（strip 过早/过狠？）", want)
		}
	}
}

func TestGenerateFromDesign(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"CREATE TABLE sys_user", "CREATE TABLE p_application", "CREATE TABLE seq_prefix_registry", "CREATE TABLE v_activity"} {
		if !strings.Contains(strings.ToLower(up), strings.ToLower(want)) {
			t.Fatalf("生成的 up.sql 缺少: %s", want)
		}
	}
	// common 必须先于模块：sys_user 出现在 p_application 之前
	if strings.Index(strings.ToLower(up), "sys_user") > strings.Index(strings.ToLower(up), "p_application") {
		t.Fatal("00-common.sql 应最先拼接")
	}
}

// TestGenerateUp_HasVActivity 守卫 V 模块建表进入迁移；一旦 design/13 被漏排/改名，compose 后无表可写。
func TestGenerateUp_HasVActivity(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"CREATE TABLE v_activity", "CREATE TABLE v_activity_participant", "CREATE TABLE v_activity_review"} {
		if !strings.Contains(strings.ToLower(up), strings.ToLower(want)) {
			t.Fatalf("迁移缺少 V 模块对象: %s", want)
		}
	}
	if !strings.Contains(up, "'ACT'") {
		t.Fatal("seq_prefix_registry 未登记 ACT 前缀")
	}
}

// TestGenerateUp_HasMScheme 守卫 M 模块建表进入迁移；一旦 design/14 被漏排/改名，compose 后无表可写。
func TestGenerateUp_HasMScheme(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, tbl := range []string{"m_scheme", "m_scheme_factor", "m_record", "m_record_item", "m_payout"} {
		if !strings.Contains(strings.ToLower(up), strings.ToLower("CREATE TABLE "+tbl)) {
			t.Fatalf("迁移缺少 M 模块对象: CREATE TABLE %s", tbl)
		}
	}
	if !strings.Contains(up, "'PERF'") {
		t.Fatal("seq_prefix_registry 未登记 PERF 前缀")
	}
	if !strings.Contains(up, "'PAY'") {
		t.Fatal("seq_prefix_registry 未登记 PAY 前缀")
	}
}

// TestGenerateUp_NoForwardReferences 静态守卫：生成的 up.sql 里 CREATE TABLE 内联列
// REFERENCES 的目标必须先前已由同文件（或前置 00-common.sql）里的 CREATE TABLE 建过；
// 否则 PostgreSQL 会在 CREATE 阶段报 `relation "xxx" does not exist`——正是
// docker compose 首启动 design/02 E_FINAL_ACCEPT→E_ARCHIVE_CHECKLIST 前向 FK 的翻车姿势。
// ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY 是延迟外键位，允许前向。
func TestGenerateUp_NoForwardReferences(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	// PG 会把未加引号的标识符折叠成小写；比对统一 lower()
	reCreate := regexp.MustCompile(`(?i)CREATE\s+TABLE\s+([A-Za-z_][\w\.]*)`)
	reRef := regexp.MustCompile(`(?i)REFERENCES\s+([A-Za-z_][\w\.]*)\s*\(`)
	reAlter := regexp.MustCompile(`(?i)^\s*ALTER\s+TABLE\b`)

	created := map[string]bool{}
	inCreateBlock := false
	inAlterBlock := false

	lines := strings.Split(up, "\n")
	for i, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "--") {
			continue
		}
		// 语句块进入
		if reCreate.MatchString(line) {
			inCreateBlock = true
		} else if reAlter.MatchString(line) {
			inAlterBlock = true
		}

		// CREATE TABLE 头一行也计入 created（同文件的下一个 REFERENCES 视为已就绪）
		for _, m := range reCreate.FindAllStringSubmatch(line, -1) {
			created[strings.ToLower(m[1])] = true
		}

		// ALTER 段的 REFERENCES 允许前向
		if !inAlterBlock && inCreateBlock {
			for _, m := range reRef.FindAllStringSubmatch(line, -1) {
				target := strings.ToLower(m[1])
				if !created[target] {
					t.Fatalf("前向 REFERENCES: up.sql 第 %d 行 CREATE TABLE 内联 REFERENCES %s，但该表尚未创建（PG 会报 relation %q does not exist）\n  行: %s",
						i+1, m[1], target, line)
				}
			}
		}

		// 语句结束（同一行含 ");" 视为收束，够 DDL 场景）
		if strings.Contains(line, ");") {
			inCreateBlock = false
			inAlterBlock = false
		}
	}
}

// TestGenerateUp_InstallsPgTrgmBeforeUse 守卫 pg_trgm 扩展在 gin_trgm_ops 索引之前建。
// postgres:15 镜像已带 contrib 但扩展需显式 CREATE；一旦 design 加了 trigram 索引忘配扩展，
// docker compose 迁移会报 `operator class "gin_trgm_ops" does not exist for access method "gin"`。
// 只要 up.sql 里 `CREATE EXTENSION ... pg_trgm` 首次出现位置早于 `gin_trgm_ops` 首次出现即安全。
func TestGenerateUp_InstallsPgTrgmBeforeUse(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	reExt := regexp.MustCompile(`(?i)CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?pg_trgm`)
	idxExt := reExt.FindStringIndex(up)
	idxUse := strings.Index(up, "gin_trgm_ops")
	if idxUse < 0 {
		return // 本版本 design 暂未用 trigram，视为通过；未来加了会由下面分支拦
	}
	if idxExt == nil {
		t.Fatalf("up.sql 出现 gin_trgm_ops 索引却无 `CREATE EXTENSION pg_trgm`——docker compose 首启动必报 operator class not exist")
	}
	if idxExt[0] > idxUse {
		t.Fatalf("CREATE EXTENSION pg_trgm 位置(%d)晚于首个 gin_trgm_ops 使用(%d)——扩展必须先于依赖它的索引建立", idxExt[0], idxUse)
	}
}

// TestGenerateUp_UniqueIndexNames 守卫 up.sql 内 CREATE [UNIQUE] INDEX 名称全局唯一。
// PostgreSQL 索引住在 schema namespace（非 per-table），两个模块用同名（例如历史 F 与 T
// 都写 idx_approval_approver / uk_income_bankflow）会让第二个 CREATE INDEX 报
// `relation "idx_approval_approver" already exists`，compose 首启动即挂。改名规范：加模块首字母前缀。
func TestGenerateUp_UniqueIndexNames(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	reIdx := regexp.MustCompile(`(?i)CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+CONCURRENTLY)?\s+(?:IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w]*)`)
	lines := strings.Split(up, "\n")
	seen := map[string]int{} // lower(name) -> first line number (1-based)
	for i, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "--") {
			continue
		}
		for _, m := range reIdx.FindAllStringSubmatch(line, -1) {
			name := strings.ToLower(m[1])
			if prev, dup := seen[name]; dup {
				t.Fatalf("重复索引名 %q：首次 up.sql:%d，重复 up.sql:%d —— 请为跨模块同名索引加模块首字母前缀(F_/T_/…)避免 schema namespace 冲突\n  A: %s\n  B: %s",
					m[1], prev, i+1, strings.TrimSpace(lines[prev-1]), line)
			}
			seen[name] = i + 1
		}
	}
}

// splitStatements 按 `;` 结束符把 up.sql 切成一条条语句；跳过纯注释与空行。
// 简化：不处理 $$ 里的函数体（design 无 PL/pgSQL）与字符串里的分号。够 DDL 场景。
func splitStatements(up string) []struct {
	start int // 1-based 行号
	sql   string
} {
	var out []struct {
		start int
		sql   string
	}
	lines := strings.Split(up, "\n")
	var buf []string
	start := 0
	for i, raw := range lines {
		s := strings.TrimSpace(raw)
		// 去行内 -- 之后
		if idx := strings.Index(s, "--"); idx >= 0 {
			s = strings.TrimSpace(s[:idx])
		}
		if s == "" {
			continue
		}
		if len(buf) == 0 {
			start = i + 1
		}
		buf = append(buf, s)
		if strings.HasSuffix(s, ";") {
			out = append(out, struct {
				start int
				sql   string
			}{start, strings.Join(buf, " ")})
			buf = nil
		}
	}
	if len(buf) > 0 {
		out = append(out, struct {
			start int
			sql   string
		}{start, strings.Join(buf, " ")})
	}
	return out
}

// TestGenerateUp_UniqueRelationNames 守卫 up.sql 内 pg_class/pg_namespace 全局对象名唯一：
// TABLE / VIEW / MATERIALIZED VIEW / SEQUENCE / TYPE / DOMAIN / FUNCTION / SCHEMA。
// PostgreSQL 这些对象都住在 schema namespace，同名第二次 CREATE 报 `relation "x" already exists`。
func TestGenerateUp_UniqueRelationNames(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	// 顺序敏感：先长句避免 "MATERIALIZED VIEW" 被 "VIEW" 抢匹配
	patterns := []*regexp.Regexp{
		regexp.MustCompile(`(?i)^CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+(?:UNIQUE\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+MATERIALIZED\s+VIEW(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+(?:OR\s+REPLACE\s+)?VIEW(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+SEQUENCE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+TYPE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+DOMAIN(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+([A-Za-z_][\w\.]*)`),
		regexp.MustCompile(`(?i)^CREATE\s+SCHEMA(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w\.]*)`),
	}
	seen := map[string]int{}
	for _, st := range splitStatements(up) {
		head := strings.TrimSpace(st.sql)
		for _, rx := range patterns {
			m := rx.FindStringSubmatch(head)
			if m == nil {
				continue
			}
			name := strings.ToLower(m[1])
			if prev, dup := seen[name]; dup {
				t.Fatalf("重复对象名 %q：首次 up.sql:%d，重复 up.sql:%d —— schema namespace 冲突\n  A: %s\n  B: %s",
					m[1], prev, st.start, head[:80], head[:80])
			}
			seen[name] = st.start
			break
		}
	}
}

// splitTopLevelCommas 按顶层逗号切分 CREATE TABLE 括号内的列/约束定义。
func splitTopLevelCommas(s string) []string {
	depth := 0
	var parts []string
	var cur strings.Builder
	for _, ch := range s {
		switch ch {
		case '(':
			depth++
			cur.WriteRune(ch)
		case ')':
			depth--
			cur.WriteRune(ch)
		case ',':
			if depth == 0 {
				parts = append(parts, cur.String())
				cur.Reset()
			} else {
				cur.WriteRune(ch)
			}
		default:
			cur.WriteRune(ch)
		}
	}
	if strings.TrimSpace(cur.String()) != "" {
		parts = append(parts, cur.String())
	}
	return parts
}

// 常见 PG 类型前缀（用于判定一行是否是 "colname <TYPE> ..." 形式的列定义）。
var typePrefix = regexp.MustCompile(`(?i)^(VARCHAR|CHAR|CHARACTER|INT|INTEGER|BIGINT|SMALLINT|SERIAL|BIGSERIAL|NUMERIC|DECIMAL|REAL|DOUBLE|FLOAT|TEXT|DATE|TIME|TIMESTAMP|TIMESTAMPTZ|INTERVAL|MONEY|XML|JSON|JSONB|BYTEA|UUID|BOOLEAN|INET|CIDR|MACADDR|TSVECTOR|TSQUERY|POINT|LINE|LSEG|BOX|PATH|POLYGON|CIRCLE)\b`)

// tableLevelStarters 是 CREATE TABLE 内以关键字起头的表级子句（非列）。
var tableLevelStarters = map[string]bool{
	"CHECK": true, "CONSTRAINT": true, "UNIQUE": true, "PRIMARY": true,
	"FOREIGN": true, "EXCLUDE": true, "LIKE": true, "INDEX": true,
}

// TestGenerateUp_NoDuplicateColumns 守卫同一 CREATE TABLE 内列名不重复。
// PG 报 `column "x" specified more than once`。
func TestGenerateUp_NoDuplicateColumns(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	reCreateTblBody := regexp.MustCompile(`(?is)^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w\.]*)\s*\((.*)\)\s*;?\s*$`)
	for _, st := range splitStatements(up) {
		m := reCreateTblBody.FindStringSubmatch(strings.TrimSpace(st.sql))
		if m == nil {
			continue
		}
		tbl := m[1]
		body := m[2]
		seen := map[string]int{}
		for _, part := range splitTopLevelCommas(body) {
			s := strings.TrimSpace(part)
			if s == "" {
				continue
			}
			first := regexp.MustCompile(`^([A-Za-z_][\w]*)`).FindStringSubmatch(s)
			if first == nil {
				continue
			}
			tok := first[1]
			if tableLevelStarters[strings.ToUpper(tok)] {
				continue
			}
			// 判定为列定义：token 后必须紧跟类型前缀
			rest := strings.TrimSpace(s[len(tok):])
			if !typePrefix.MatchString(rest) {
				continue
			}
			key := strings.ToLower(tok)
			if prev, dup := seen[key]; dup {
				t.Fatalf("表 %s 内列名 %q 重复出现（首次位置 %d 段，再遇）——PG 会报 column specified more than once\n  body片段: %s",
					tbl, tok, prev, s[:min(80, len(s))])
			}
			seen[key] = len(seen) + 1
		}
	}
}

// TestGenerateUp_NoReservedIdentifiers 守卫 CREATE TABLE 的表名与列名不裸用 PG 保留字。
// PG 报 `syntax error at or near "order"` 或列名歧义。
func TestGenerateUp_NoReservedIdentifiers(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	reserved := map[string]bool{}
	for _, w := range []string{
		"order", "user", "group", "table", "check", "view", "index", "function",
		"trigger", "constraint", "primary", "unique", "references", "default",
		"select", "from", "where", "all", "and", "or", "not", "in", "is", "as", "on",
		"limit", "offset", "fetch", "only", "column", "into", "update", "delete", "insert",
	} {
		reserved[w] = true
	}
	reCreateTblBody := regexp.MustCompile(`(?is)^CREATE\s+TABLE\s+([A-Za-z_][\w\.]*)\s*\((.*)\)\s*;?\s*$`)
	for _, st := range splitStatements(up) {
		head := strings.TrimSpace(st.sql)
		m := reCreateTblBody.FindStringSubmatch(head)
		if m == nil {
			continue
		}
		tbl := m[1]
		// 表名保留字（末段 leaf）
		leaf := strings.ToLower(tbl)
		if i := strings.LastIndex(leaf, "."); i >= 0 {
			leaf = leaf[i+1:]
		}
		if reserved[leaf] {
			t.Fatalf("表名裸用保留字 %q (up.sql:%d) —— 需加双引号或改名", tbl, st.start)
		}
		body := m[2]
		for _, part := range splitTopLevelCommas(body) {
			s := strings.TrimSpace(part)
			if s == "" {
				continue
			}
			first := regexp.MustCompile(`^([A-Za-z_][\w]*)`).FindStringSubmatch(s)
			if first == nil {
				continue
			}
			tok := first[1]
			if tableLevelStarters[strings.ToUpper(tok)] {
				continue
			}
			if !reserved[strings.ToLower(tok)] {
				continue
			}
			rest := strings.TrimSpace(s[len(tok):])
			if !typePrefix.MatchString(rest) {
				continue
			}
			t.Fatalf("表 %s 内列名裸用保留字 %q (up.sql:%d) —— 需加双引号或改名\n  %s",
				tbl, tok, st.start, s[:min(80, len(s))])
		}
	}
}

// TestGenerateUp_HasPasswordHash 守卫用户口令哈希列进入迁移：bcrypt 真实登录（任务7）
// 依赖 sys_user.password_hash；一旦 design 误删该列，compose 迁移后登录必 500。
func TestGenerateUp_HasPasswordHash(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(strings.ToLower(up), "password_hash") {
		t.Fatal("sys_user 缺 password_hash 列——bcrypt 登录无从存储口令哈希")
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
