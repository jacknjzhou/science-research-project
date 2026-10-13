package store

import (
	"context"
	"os"
	"testing"
)

func TestListApplications_TenantAndSoftDeleteFilter(t *testing.T) {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	// 约定：测试库已由任务4 migrate.Up 建表，并 seed 了 testdata/seed_p.sql
	pool := mustPool(t, u)
	defer pool.Close()
	q := New(pool)
	got, err := q.ListApplications(context.Background(), ListApplicationsParams{
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
