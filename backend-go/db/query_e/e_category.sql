-- T21 项目分类 CRUD + 中检/结项窗口扫描

-- name: CreateProjectCategory :one
INSERT INTO e_project_category
  (tenant_id, code, name, level, mgmt_fee_pct, midcheck_from, midcheck_to, closing_from, closing_to)
VALUES ($1, $2, $3, sqlc.narg('level')::text, $4, $5, $6, $7, $8)
RETURNING *;

-- name: ListProjectCategories :many
SELECT * FROM e_project_category
WHERE tenant_id = $1 AND deleted = 0
ORDER BY id;

-- name: GetProjectCategory :one
SELECT * FROM e_project_category WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: UpdateProjectCategory :one
UPDATE e_project_category SET
  name        = COALESCE(sqlc.narg('name')::text, name),
  level       = COALESCE(sqlc.narg('level')::text, level),
  mgmt_fee_pct = COALESCE(sqlc.narg('mgmt_fee_pct')::numeric, mgmt_fee_pct),
  midcheck_from = COALESCE(sqlc.narg('midcheck_from')::date, midcheck_from),
  midcheck_to   = COALESCE(sqlc.narg('midcheck_to')::date, midcheck_to),
  closing_from  = COALESCE(sqlc.narg('closing_from')::date, closing_from),
  closing_to    = COALESCE(sqlc.narg('closing_to')::date, closing_to),
  updated_at  = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
RETURNING *;

-- name: DeleteProjectCategory :execrows
UPDATE e_project_category SET deleted = 1, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: CountProjectsByCategory :one
SELECT count(*) FROM e_project
WHERE category_id = $1 AND deleted = 0;

-- name: AttachProjectCategory :execrows
UPDATE e_project SET category_id = $2, updated_at = now()
WHERE id = $1 AND deleted = 0;

-- name: DeleteCategoryGuard :one
SELECT count(*) AS children FROM e_project_category
WHERE deleted = 0 AND id = $1;

-- T21 预警扫描：EXECUTING 项目 × 分类窗口（中检/结项），pi_user 为接收人
-- name: ListMidcheckDueProjects :many
SELECT p.id, p.title, p.pi_user_id, p.category_id,
       c.midcheck_from, c.midcheck_to, c.closing_from, c.closing_to
FROM e_project p
JOIN e_project_category c ON c.id = p.category_id AND c.deleted = 0
WHERE p.deleted = 0 AND p.status = 'EXECUTING'
  AND (
    (c.midcheck_from IS NOT NULL AND CURRENT_DATE BETWEEN (c.midcheck_from - INTERVAL '15 day') AND c.midcheck_to)
    OR (c.closing_from IS NOT NULL AND CURRENT_DATE BETWEEN (c.closing_from - INTERVAL '15 day') AND c.closing_to)
  );

