-- name: ListRoles :many
SELECT id, code, name, is_builtin, tenant_id, created_at, updated_at
FROM sys_role WHERE tenant_id = $1 ORDER BY id;

-- name: ListRoleCodesByUser :many
SELECT r.code
FROM sys_role r JOIN sys_user_role ur ON ur.role_id = r.id
WHERE ur.user_id = $1
  AND (ur.expires_at IS NULL OR ur.expires_at > now());

-- name: ListRoleIDsByUser :many
SELECT ur.role_id FROM sys_user_role ur WHERE ur.user_id = $1;
