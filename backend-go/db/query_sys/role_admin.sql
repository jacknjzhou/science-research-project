-- 角色目录维护（管理员可增/改/删；内置角色与已绑定角色由 handler 拦截）。

-- name: CreateRole :one
INSERT INTO sys_role (code, name, is_builtin, tenant_id)
VALUES (@code, @name, FALSE, @tenant_id)
RETURNING id, code, name, is_builtin, tenant_id, created_at, updated_at;

-- name: UpdateRole :one
-- code 不可改（Casbin 策略/用户绑定均以 code 关联）；仅允许改名称。
UPDATE sys_role SET name = @name, updated_at = now()
WHERE id = @id AND tenant_id = @tenant_id
RETURNING id, code, name, is_builtin, tenant_id, created_at, updated_at;

-- name: GetRoleByID :one
SELECT id, code, name, is_builtin, tenant_id, created_at, updated_at
FROM sys_role WHERE id = @id AND tenant_id = @tenant_id;

-- name: CountRoleUsers :one
SELECT count(*) FROM sys_user_role WHERE role_id = @role_id;

-- name: DeleteRole :execrows
-- is_builtin=FALSE 双保险（handler 已拦截内置角色）。
DELETE FROM sys_role WHERE id = @id AND tenant_id = @tenant_id AND is_builtin = FALSE;
