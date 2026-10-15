-- T15 科目树形管理 + 预警配置 CRUD

-- 科目树：租户内全部启用科目（handler 组装树）
-- name: ListSubjectsAll :many
SELECT * FROM F_SUBJECT WHERE deleted = 0 AND tenant_id = $1 ORDER BY sort_no, id;

-- name: CountSubjectChildren :one
SELECT count(*) FROM F_SUBJECT WHERE parent_id = $1 AND deleted = 0;

-- name: CountSubjectBudgetRefs :one
SELECT count(*) FROM F_BUDGET_LINE WHERE subject_id = $1 AND deleted = 0;

-- name: CreateSubject :one
INSERT INTO F_SUBJECT (code, tenant_id, creator_id, name, parent_id, level, category, is_leaf, ratio_limit, applies_to, sort_no)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
RETURNING *;

-- name: UpdateSubject :one
UPDATE F_SUBJECT
SET name = sqlc.narg('name')::text, ratio_limit = sqlc.narg('ratio_limit')::numeric,
    sort_no = sqlc.narg('sort_no')::int, remark = sqlc.narg('remark')::text,
    modifier_id = sqlc.narg('modifier_id')::bigint, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0
RETURNING *;

-- name: DeleteSubject :execrows
UPDATE F_SUBJECT SET deleted = 1, updated_at = now() WHERE id = $1 AND deleted = 0;

-- 预警配置
-- name: CreateWarnConfig :one
INSERT INTO F_WARN_CONFIG (tenant_id, creator_id, project_category_id, warn_kind, threshold_pct, ahead_days, level, channel, cron_expr, template, enabled, remark)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
RETURNING *;

-- name: GetWarnConfig :one
SELECT * FROM F_WARN_CONFIG WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: ListWarnConfigs :many
SELECT * FROM F_WARN_CONFIG
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('warn_kind')::text IS NULL OR warn_kind = sqlc.narg('warn_kind')::text)
  AND (sqlc.narg('enabled')::boolean IS NULL OR enabled = sqlc.narg('enabled')::boolean)
ORDER BY id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountWarnConfigs :one
SELECT count(*) FROM F_WARN_CONFIG
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('warn_kind')::text IS NULL OR warn_kind = sqlc.narg('warn_kind')::text)
  AND (sqlc.narg('enabled')::boolean IS NULL OR enabled = sqlc.narg('enabled')::boolean);

-- name: UpdateWarnConfig :one
UPDATE F_WARN_CONFIG
SET threshold_pct = COALESCE(sqlc.narg('threshold_pct')::numeric, threshold_pct),
    ahead_days = COALESCE(sqlc.narg('ahead_days')::int, ahead_days),
    level = COALESCE(sqlc.narg('level')::text, level),
    channel = COALESCE(sqlc.narg('channel')::text, channel),
    cron_expr = COALESCE(sqlc.narg('cron_expr')::text, cron_expr),
    template = COALESCE(sqlc.narg('template')::text, template),
    enabled = COALESCE(sqlc.narg('enabled')::boolean, enabled),
    remark = COALESCE(sqlc.narg('remark')::text, remark), updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND tenant_id = sqlc.arg('tenant_id')::bigint AND deleted = 0
RETURNING *;

-- name: DeleteWarnConfig :execrows
UPDATE F_WARN_CONFIG SET deleted = 1, updated_at = now() WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- 启用配置扫描（T18/T21 cron 消费）
-- name: ListEnabledWarnConfigs :many
SELECT * FROM F_WARN_CONFIG WHERE deleted = 0 AND tenant_id = $1 AND enabled = TRUE;
