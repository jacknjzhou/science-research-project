package notify

import (
	"time"

	nfstore "github.com/eplugger/ark/internal/modules/notify/store"
)

func fmtTime(t time.Time) string { return t.Format("2006-01-02 15:04:05") }

func fmtTimePtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.Format("2006-01-02 15:04:05")
}

func optStr(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func ToAPINotification(n nfstore.SysNotification) map[string]any {
	read := false
	if n.ReadAt != nil {
		read = true
	}
	return map[string]any{
		"id": n.ID, "typ": n.Typ, "title": n.Title,
		"content": optStr(n.Content), "biz_ref": optStr(n.BizRef),
		"read": read, "read_at": fmtTimePtr(n.ReadAt),
		"created_at": fmtTime(n.CreatedAt),
	}
}
