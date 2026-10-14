package storage

import (
	"bytes"
	"context"
	"testing"
)

func TestFakeStorage_PutGetPresignRemove(t *testing.T) {
	f := NewFake()
	ctx := context.Background()
	if err := f.Put(ctx, "a/b.txt", bytes.NewReader([]byte("hello")), 5, "text/plain"); err != nil {
		t.Fatal(err)
	}
	rc, n, err := f.Get(ctx, "a/b.txt")
	if err != nil || n != 5 {
		t.Fatalf("Get err=%v n=%d", err, n)
	}
	buf := new(bytes.Buffer)
	buf.ReadFrom(rc)
	rc.Close()
	if buf.String() != "hello" {
		t.Fatalf("got %q", buf.String())
	}
	if u, err := f.PresignGet(ctx, "a/b.txt"); err != nil || u == "" {
		t.Fatalf("presign err=%v url=%q", err, u)
	}
	if err := f.Remove(ctx, "a/b.txt"); err != nil {
		t.Fatal(err)
	}
	if _, _, err := f.Get(ctx, "a/b.txt"); err == nil {
		t.Fatal("expected error after remove")
	}
}
