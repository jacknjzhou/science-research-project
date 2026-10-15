-- T14 结转（F-25）

-- name: CreateCarryover :one
INSERT INTO F_CARRYOVER (tenant_id, creator_id, project_id, fiscal_year, target_year, amount, remark)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;

-- name: GetCarryover :one
SELECT * FROM F_CARRYOVER WHERE id = $1 AND deleted = 0;

-- name: ListCarryovers :many
SELECT * FROM F_CARRYOVER
WHERE deleted = 0 AND tenant_id = $1
ORDER BY id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountCarryovers :one
SELECT count(*) FROM F_CARRYOVER WHERE deleted = 0 AND tenant_id = $1;

-- 结题守卫由 handler 查 E_PROJECT；批复（单级：科研处 R-MANAGER 即科研管理岗终审）
-- name: ApproveCarryover :one
UPDATE F_CARRYOVER
SET status = 'APPROVED', updated_at = now(), remark = COALESCE(remark || ' | ', '') || sqlc.arg('note')::text
WHERE id = $1 AND status = 'PENDING' AND deleted = 0
RETURNING *;

-- name: RejectCarryover :one
UPDATE F_CARRYOVER
SET status = 'REJECTED', updated_at = now()
WHERE id = $1 AND status = 'PENDING' AND deleted = 0
RETURNING *;

-- 批复后回填生成的到款行
-- name: SetCarryoverIncome :exec
UPDATE F_CARRYOVER SET income_id = $2, updated_at = now() WHERE id = $1;

-- 结题项目校验
-- name: GetProjectStatusForGuard :one
SELECT id, status, title FROM E_PROJECT WHERE id = $1 AND deleted = 0;
