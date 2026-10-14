-- name: ListSchemes :many
SELECT * FROM m_scheme
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('period_type')::text      IS NULL OR period_type = sqlc.narg('period_type')::text)
  AND (sqlc.narg('effective_period')::text IS NULL OR effective_period = sqlc.narg('effective_period')::text)
  AND (sqlc.narg('scope_dept_id')::bigint  IS NULL OR scope_dept_id = sqlc.narg('scope_dept_id')::bigint)
  AND (sqlc.narg('status')::text           IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('name')::text             IS NULL OR name ILIKE sqlc.narg('name')::text)
ORDER BY id DESC
LIMIT $3 OFFSET $2;

-- name: CountSchemes :one
SELECT count(*)::int AS n
FROM m_scheme
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('period_type')::text      IS NULL OR period_type = sqlc.narg('period_type')::text)
  AND (sqlc.narg('effective_period')::text IS NULL OR effective_period = sqlc.narg('effective_period')::text)
  AND (sqlc.narg('scope_dept_id')::bigint  IS NULL OR scope_dept_id = sqlc.narg('scope_dept_id')::bigint)
  AND (sqlc.narg('status')::text           IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('name')::text             IS NULL OR name ILIKE sqlc.narg('name')::text);

-- name: GetScheme :one
SELECT * FROM m_scheme
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: CreateScheme :one
INSERT INTO m_scheme (tenant_id, creator_id, status, security_level, legal_entity_id, policy_pack_id,
                      name, period_type, scope_dept_id, scope_staff_type, effective_period, version, active, remark)
VALUES ($1, $2, 'DRAFT', COALESCE($3::text,'INTERNAL'), $4, $5,
        $6, $7, $8, $9, $10, 1, FALSE, $11)
RETURNING *;

-- name: UpdateScheme :one
UPDATE m_scheme SET
  name = COALESCE($3::text, name),
  period_type = COALESCE($4::text, period_type),
  scope_dept_id = COALESCE($5::bigint, scope_dept_id),
  scope_staff_type = COALESCE($6::text, scope_staff_type),
  effective_period = COALESCE($7::text, effective_period),
  remark = COALESCE($8::text, remark),
  modifier_id = $9, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'DRAFT'
RETURNING *;

-- name: SoftDeleteScheme :execrows
UPDATE m_scheme SET deleted = 1, modifier_id = $3, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: SupersedeActiveInScope :exec
-- 启用前置：把同维度（tenant+period_type+effective_period+scope_dept+scope_staff_type）当前 active 的方案转 SUPERSEDED
UPDATE m_scheme SET active = FALSE, status = 'SUPERSEDED', updated_at = now()
WHERE deleted = 0 AND active = TRUE AND tenant_id = $1 AND period_type = $2 AND effective_period = $3
  AND COALESCE(scope_dept_id,0) = COALESCE($4::bigint,0)
  AND COALESCE(scope_staff_type,'') = COALESCE($5::text,'');

-- name: ActivateScheme :one
UPDATE m_scheme SET active = TRUE, status = 'ACTIVE', updated_at = now(), modifier_id = $3
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
RETURNING *;
