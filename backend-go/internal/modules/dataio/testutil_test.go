package dataio

import (
	"bytes"
	"context"
	"mime/multipart"
	"strings"
)

func context0() context.Context { return context.Background() }

func c0() context.Context { return context.Background() }

// multipartBody 组装 multipart/form-data（单文件字段 file），返回 body 与 Content-Type。
func multipartBody(filename string, content []byte) (*bytes.Reader, string) {
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		return nil, ""
	}
	_, _ = fw.Write(content)
	_ = mw.Close()
	return bytes.NewReader(buf.Bytes()), mw.FormDataContentType()
}

var _ = strings.TrimSpace
