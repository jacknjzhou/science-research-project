-- NF 通知中心查询

-- name: InsertNotification :one
INSERT INTO sys_notification (tenant_id, user_id, typ, title, content, biz_ref)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: ListByUser :many
SELECT * FROM sys_notification
WHERE user_id = $1
  AND (sqlc.narg('typ')::text IS NULL OR typ = sqlc.narg('typ')::text)
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountByUser :one
SELECT count(*) FROM sys_notification
WHERE user_id = $1
  AND (sqlc.narg('typ')::text IS NULL OR typ = sqlc.narg('typ')::text);

-- name: CountUnread :one
SELECT count(*) FROM sys_notification WHERE user_id = $1 AND read_at IS NULL;

-- name: MarkRead :exec
UPDATE sys_notification SET read_at = now()
WHERE id = $1 AND user_id = $2 AND read_at IS NULL;

-- name: MarkAllRead :exec
UPDATE sys_notification SET read_at = now()
WHERE user_id = $1 AND read_at IS NULL;

-- PushRole 扇出：某租户下持指定角色代码的全部启用用户（expires_at 未到期）。
-- name: UserIDsByRole :many
SELECT u.id FROM sys_user u
JOIN sys_user_role ur ON ur.user_id = u.id
JOIN sys_role r       ON r.id = ur.role_id
WHERE ur.tenant_id = $1 AND r.code = $2
  AND u.status = 'ACTIVE'
  AND (ur.expires_at IS NULL OR ur.expires_at > now());
