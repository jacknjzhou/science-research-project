package storage

import (
	"context"
	"io"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type MinIO struct {
	client *minio.Client
	bucket string
}

// NewMinIO 连接 MinIO 并确保 bucket 存在。失败返回 error（调用方决定降级为 nil）。
func NewMinIO(ctx context.Context, endpoint, accessKey, secretKey, bucket string, useSSL bool) (*MinIO, error) {
	c, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, err
	}
	found, err := c.BucketExists(ctx, bucket)
	if err != nil {
		return nil, err
	}
	if !found {
		if err := c.MakeBucket(ctx, bucket, minio.MakeBucketOptions{}); err != nil {
			return nil, err
		}
	}
	return &MinIO{client: c, bucket: bucket}, nil
}

func (m *MinIO) Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error {
	_, err := m.client.PutObject(ctx, m.bucket, key, r, size, minio.PutObjectOptions{ContentType: contentType})
	return err
}

func (m *MinIO) Get(ctx context.Context, key string) (io.ReadCloser, int64, error) {
	o, err := m.client.GetObject(ctx, m.bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, 0, err
	}
	st, err := o.Stat()
	if err != nil {
		o.Close()
		return nil, 0, err
	}
	return o, st.Size, nil
}

func (m *MinIO) PresignGet(ctx context.Context, key string) (string, error) {
	u, err := m.client.PresignedGetObject(ctx, m.bucket, key, time.Hour, nil)
	if err != nil {
		return "", err
	}
	return u.String(), nil
}

func (m *MinIO) Remove(ctx context.Context, key string) error {
	return m.client.RemoveObject(ctx, m.bucket, key, minio.RemoveObjectOptions{})
}
