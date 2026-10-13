package db

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestConnect_InvalidURLFails(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := Connect(ctx, "not-a-valid-url"); err == nil {
		t.Fatal("期望非法连接串返回错误")
	}
}

func TestPing_LiveIfProvided(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL，跳过集成 Ping")
	}
	ctx := context.Background()
	pool, err := Connect(ctx, u)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := Ping(ctx, pool); err != nil {
		t.Fatalf("Ping 失败: %v", err)
	}
}
