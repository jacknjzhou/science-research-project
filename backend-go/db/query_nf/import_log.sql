-- T13 导入日志查询（dataio）。

-- name: InsertImportLog :one
INSERT INTO sys_import_log (tenant_id, module, row_count, success_count, fail_count, operator_id, snapshot)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;

-- name: ListImportLogs :many
SELECT * FROM sys_import_log
WHERE tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('module')::text IS NULL OR module = sqlc.narg('module')::text)
  AND (sqlc.narg('from_at')::timestamptz IS NULL OR created_at >= sqlc.narg('from_at')::timestamptz)
  AND (sqlc.narg('to_at')::timestamptz IS NULL OR created_at <= sqlc.narg('to_at')::timestamptz)
ORDER BY created_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountImportLogs :one
SELECT count(*) FROM sys_import_log
WHERE tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('module')::text IS NULL OR module = sqlc.narg('module')::text)
  AND (sqlc.narg('from_at')::timestamptz IS NULL OR created_at >= sqlc.narg('from_at')::timestamptz)
  AND (sqlc.narg('to_at')::timestamptz IS NULL OR created_at <= sqlc.narg('to_at')::timestamptz);

-- name: GetImportLog :one
SELECT * FROM sys_import_log WHERE id = $1 AND tenant_id = $2;
