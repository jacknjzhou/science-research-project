package archive

import "testing"

func TestFourPropertiesIntegrityFailWhenRequiredMissing(t *testing.T) {
	res := evaluateFourProperties(facts{
		RequiredTotal: 3, RequiredFilled: 2,
		Docs:       []docFact{{Expected: "aa", Got: "aa", Usable: true}},
		SecurityOK: true,
	})
	if byType(res, "INTEGRITY").Result != "FAIL" {
		t.Fatalf("required 缺应 INTEGRITY FAIL，得 %+v", byType(res, "INTEGRITY"))
	}
}

func TestFourPropertiesAuthenticityFailOnChecksumMismatch(t *testing.T) {
	res := evaluateFourProperties(facts{
		RequiredTotal: 1, RequiredFilled: 1,
		Docs:       []docFact{{Expected: "abc", Got: "xyz", Usable: true}},
		SecurityOK: true,
	})
	if byType(res, "AUTHENTICITY").Result != "FAIL" {
		t.Fatalf("checksum 不符应 AUTHENTICITY FAIL")
	}
}

func TestFourPropertiesAllPass(t *testing.T) {
	res := evaluateFourProperties(facts{
		RequiredTotal: 2, RequiredFilled: 2,
		Docs:       []docFact{{Expected: "a", Got: "a", Usable: true}, {Expected: "b", Got: "b", Usable: true}},
		SecurityOK: true,
	})
	for _, want := range []string{"AUTHENTICITY", "INTEGRITY", "USABILITY", "SECURITY"} {
		if byType(res, want).Result != "PASS" {
			t.Fatalf("%s 应 PASS，得 %+v", want, byType(res, want))
		}
	}
	if !allPassed(res) {
		t.Fatalf("allPassed 应为 true")
	}
}
