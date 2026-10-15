-- T14 外拨（F-24）

-- name: CreateOutward :one
INSERT INTO F_OUTWARD (tenant_id, creator_id, project_id, budget_id, budget_line_id, amount, to_unit, reason)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
RETURNING *;

-- name: GetOutward :one
SELECT * FROM F_OUTWARD WHERE id = $1 AND deleted = 0;

-- name: ListOutwards :many
SELECT * FROM F_OUTWARD
WHERE deleted = 0 AND tenant_id = $1
ORDER BY id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountOutwards :one
SELECT count(*) FROM F_OUTWARD WHERE deleted = 0 AND tenant_id = $1;

-- 一级审批（R-MANAGER）：PENDING 且未一级批复
-- name: ApproveOutwardFirst :one
UPDATE F_OUTWARD
SET first_approved_by = $2, first_approved_at = now(), updated_at = now()
WHERE id = $1 AND status = 'PENDING' AND first_approved_by IS NULL AND deleted = 0
RETURNING *;

-- 二级审批（R-LEADER）：一级已批
-- name: ApproveOutwardFinal :one
UPDATE F_OUTWARD
SET status = 'APPROVED', approved_by = $2, approved_at = now(), updated_at = now()
WHERE id = $1 AND status = 'PENDING' AND first_approved_by IS NOT NULL AND deleted = 0
RETURNING *;

-- name: RejectOutward :one
UPDATE F_OUTWARD
SET status = 'REJECTED', approved_by = $2, approved_at = now(), updated_at = now()
WHERE id = $1 AND status = 'PENDING' AND deleted = 0
RETURNING *;

-- 外拨批复后从预算行实扣（余额充足才可扣）
-- name: DeductLineForOutward :execrows
UPDATE F_BUDGET_LINE
SET amount_used = amount_used + $2, updated_at = now()
WHERE id = $1 AND deleted = 0
  AND (amount_planned + amount_adjusted - amount_frozen - amount_used - amount_released) >= $2;
