package archive

import (
	"crypto/sha256"
	"encoding/hex"
)

type docFact struct {
	DocID    int64
	Expected string // 期望 sha256（存于 o_document.checksum_sha256）
	Got      string // 实取对象算出的 sha256（hex 小写）
	Usable   bool   // 格式可读（doc_type 命中可解析白名单 或 text_content 非空）
}

type facts struct {
	RequiredTotal  int
	RequiredFilled int
	Docs           []docFact
	SecurityOK     bool // 案卷密级在操作人 clearance 内
}

type checkResult struct {
	CheckType string
	Result    string // PASS/FAIL/WARN
	Detail    map[string]any
}

func sha256hex(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

// evaluateFourProperties 纯函数：给定事实算四性。authenticity 用 hex-equal（Got 由调用方
// 对 MinIO 取回字节算得，此处仅比较，避免 DB/存储耦合）。
func evaluateFourProperties(f facts) []checkResult {
	// 真实性
	authRes, authBad := "PASS", []int64{}
	for _, d := range f.Docs {
		if d.Expected != "" && d.Expected != d.Got {
			authRes = "FAIL"
			authBad = append(authBad, d.DocID)
		}
	}
	// 完整性
	integRes := "PASS"
	if f.RequiredFilled < f.RequiredTotal {
		integRes = "FAIL"
	}
	// 可用性：全部可读=PASS；部分不可读=WARN；全不可用或无件=FAIL
	unusable := 0
	for _, d := range f.Docs {
		if !d.Usable {
			unusable++
		}
	}
	usaRes := "PASS"
	switch {
	case len(f.Docs) == 0 || unusable == len(f.Docs):
		usaRes = "FAIL"
	case unusable > 0:
		usaRes = "WARN"
	}
	// 安全性
	secRes := "PASS"
	if !f.SecurityOK {
		secRes = "FAIL"
	}
	return []checkResult{
		{"AUTHENTICITY", authRes, map[string]any{"mismatch_doc_ids": authBad, "checked": len(f.Docs)}},
		{"INTEGRITY", integRes, map[string]any{"required_total": f.RequiredTotal, "required_filled": f.RequiredFilled}},
		{"USABILITY", usaRes, map[string]any{"total": len(f.Docs), "unusable": unusable}},
		{"SECURITY", secRes, map[string]any{"security_ok": f.SecurityOK}},
	}
}

// allPassed 供 handler 判定 CHECKING→PASSED/REJECTED；测试亦复用（故定义在生产文件，非 _test.go）。
func allPassed(res []checkResult) bool {
	for _, r := range res {
		if r.Result != "PASS" {
			return false
		}
	}
	return true
}

// byType 同置于生产文件 check.go，供 handler 取单项结果、测试亦复用。
func byType(res []checkResult, typ string) checkResult {
	for _, r := range res {
		if r.CheckType == typ {
			return r
		}
	}
	return checkResult{}
}
