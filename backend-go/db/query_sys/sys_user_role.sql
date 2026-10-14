-- name: AssignRole :exec
INSERT INTO sys_user_role (user_id, role_id, tenant_id)
VALUES ($1, $2, $3)
ON CONFLICT (user_id, role_id) DO NOTHING;

-- name: RevokeRole :exec
DELETE FROM sys_user_role WHERE user_id = $1 AND role_id = $2 AND tenant_id = $3;
