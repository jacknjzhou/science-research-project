package store

import (
	"context"
	"testing"

	"github.com/eplugger/ark/internal/platform/db"
	"github.com/jackc/pgx/v5/pgxpool"
)

func mustPool(t *testing.T, url string) *pgxpool.Pool {
	t.Helper()
	p, err := db.Connect(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	return p
}
