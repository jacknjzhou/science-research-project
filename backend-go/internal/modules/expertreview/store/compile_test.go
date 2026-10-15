package nstore

import "testing"

// TestModelsCompile 冒烟：确认 sqlc 用小写 rename key 生成出的 model 名是
// Expert/ReviewTask/Invitation/Score/ReviewFee（非默认驼峰 NExpert/NReviewTask）。
// 铁律：DDL CREATE TABLE n_expert 未加引号 → sqlc 折小写存内部标识符 →
// rename/overrides key 必须小写，否则大写 key 静默 no-op。
func TestModelsCompile(t *testing.T) {
	_ = Expert{}
	_ = ReviewTask{}
	_ = Invitation{}
	_ = Score{}
	_ = ReviewFee{}
	_ = ExpertGroup{}
}
