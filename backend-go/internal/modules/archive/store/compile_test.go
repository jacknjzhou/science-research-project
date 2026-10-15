package ostore

import "testing"

// TestStoreCompiles 冒烟：确认 sqlc 用小写 rename key 生成出的 model 名是
// Document/Archive/ArchiveItem/ArchiveCheck/Borrow（非默认驼峰 ODocument/OArchive）。
// 铁律：DDL CREATE TABLE o_document 未加引号 → sqlc 折小写存内部标识符 →
// rename/overrides key 必须小写，否则大写 key 静默 no-op。
func TestStoreCompiles(t *testing.T) {
	_ = Document{}
	_ = Archive{}
	_ = ArchiveItem{}
	_ = ArchiveCheck{}
	_ = Borrow{}
}
