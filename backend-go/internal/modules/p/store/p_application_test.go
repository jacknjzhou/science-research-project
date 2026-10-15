package store

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestListApplications_TenantAndSoftDeleteFilter(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	// 幂等清表后自加载 testdata/seed_p.sql：
	// seed 提供 tenant=1 未删 2 行、tenant=2 1 行、tenant=1 已删 1 行，覆盖过滤期望。
	pool := mustPool(t, u)
	defer pool.Close()
	ctx := context.Background()
	if _, err := pool.Exec(ctx, `DELETE FROM p_application WHERE tenant_id IN (1,2)`); err != nil {
		t.Fatalf("清理 p_application 失败: %v", err)
	}
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "testdata", "seed_p.sql"))
	if err != nil {
		t.Fatalf("seed_p 读取失败: %v", err)
	}
	if _, err := pool.Exec(ctx, string(b)); err != nil {
		t.Fatalf("seed_p 执行失败: %v", err)
	}
	q := New(pool)
	got, err := q.ListApplications(ctx, ListApplicationsParams{
		TenantID: 1, Limit: 20, Offset: 0, Status: nil, ProjectType: nil,
	})
	if err != nil {
		t.Fatal(err)
	}
	// seed 固定：tenant=1 未删 2 行；tenant=2 与 deleted=1 各 1 行不应出现
	if len(got) != 2 {
		t.Fatalf("期望 2 行(仅 tenant=1 且 deleted=0)，实得 %d", len(got))
	}
	for _, r := range got {
		if r.TenantID != 1 || r.Deleted != 0 {
			t.Fatalf("过滤失效: %+v", r)
		}
	}
}
