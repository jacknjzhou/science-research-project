package storage

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"sync"
)

// Fake 内存实现，供单测与无 MinIO 环境兜底。
type Fake struct {
	mu   sync.Mutex
	data map[string][]byte
}

func NewFake() *Fake { return &Fake{data: map[string][]byte{}} }

func (f *Fake) Put(_ context.Context, key string, r io.Reader, _ int64, _ string) error {
	b, err := io.ReadAll(r)
	if err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.data[key] = b
	return nil
}

func (f *Fake) Get(_ context.Context, key string) (io.ReadCloser, int64, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	b, ok := f.data[key]
	if !ok {
		return nil, 0, fmt.Errorf("storage: key %q not found", key)
	}
	return io.NopCloser(bytes.NewReader(b)), int64(len(b)), nil
}

func (f *Fake) PresignGet(_ context.Context, key string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if _, ok := f.data[key]; !ok {
		return "", fmt.Errorf("storage: key %q not found", key)
	}
	return "fake://" + key, nil
}

func (f *Fake) Remove(_ context.Context, key string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.data, key)
	return nil
}
