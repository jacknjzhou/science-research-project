-- T20 任务中心（通知侧）：未读按类型过滤（待办聚合/三 tab 计数用）

-- name: ListUnreadByTyp :many
SELECT * FROM sys_notification
WHERE user_id = $1 AND read_at IS NULL
  AND (sqlc.narg('typ')::text IS NULL OR typ = sqlc.narg('typ')::text)
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountUnreadByTyp :one
SELECT count(*) FROM sys_notification
WHERE user_id = $1 AND read_at IS NULL
  AND (sqlc.narg('typ')::text IS NULL OR typ = sqlc.narg('typ')::text);

-- 跨域待办（我名下 PENDING 审批单）在 db/query_f/f_tasks.sql（fstore 生成，F 表在其 schema 内）

