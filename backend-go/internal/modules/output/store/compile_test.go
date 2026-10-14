package rstore

import "testing"

// TestModelsCompile 冒烟：确认 sqlc 用小写 rename key 生成出的 model 名是 Output/ClaimRecord
// （非默认驼峰 ROutput/RClaimRecord）。铁律：DDL CREATE TABLE R_OUTPUT 未加引号 → sqlc 折小写存
// 内部标识符 → rename/overrides key 必须小写，否则大写 key 静默 no-op。
func TestModelsCompile(t *testing.T) {
	_ = Output{}
	_ = ClaimRecord{}
	_ = OutputProject{}
}
