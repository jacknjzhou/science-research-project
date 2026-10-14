-- name: GetUserByUsername :one
SELECT * FROM sys_user
WHERE username = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: GetUser :one
SELECT * FROM sys_user
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: ListUsers :many
SELECT * FROM sys_user
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('keyword')::text IS NULL
       OR username   ILIKE sqlc.narg('keyword')
       OR real_name  ILIKE sqlc.narg('keyword')
       OR email      ILIKE sqlc.narg('keyword'))
ORDER BY id DESC
LIMIT @limit_ OFFSET @offset_;

-- name: CountUsers :one
SELECT count(*)::int AS n
FROM sys_user
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('keyword')::text IS NULL
       OR username   ILIKE sqlc.narg('keyword')
       OR real_name  ILIKE sqlc.narg('keyword')
       OR email      ILIKE sqlc.narg('keyword'));

-- name: CreateUser :one
INSERT INTO sys_user (
  username, real_name, password_hash, email, phone, staff_no,
  employment_status, security_level, status, tenant_id, legal_entity_id, creator_id
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
)
RETURNING *;

-- name: UpdateUser :one
UPDATE sys_user SET
  real_name      = $3,
  email          = $4,
  phone          = $5,
  security_level = $6,
  status         = $7,
  updated_at     = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
RETURNING *;

-- name: UpdateUserPassword :exec
UPDATE sys_user SET password_hash = $3, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: SoftDeleteUser :exec
UPDATE sys_user SET deleted = 1, status = 'DISABLED', updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;
