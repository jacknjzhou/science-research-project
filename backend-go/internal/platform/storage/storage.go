package storage

import (
	"context"
	"io"
)

// Storage 抽象对象存储（MinIO/S3）。handler 只依赖接口，便于假实现单测与无 MinIO 兜底。
type Storage interface {
	Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error
	Get(ctx context.Context, key string) (io.ReadCloser, int64, error)
	PresignGet(ctx context.Context, key string) (string, error)
	Remove(ctx context.Context, key string) error
}
