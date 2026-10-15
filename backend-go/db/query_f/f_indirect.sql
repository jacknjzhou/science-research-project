-- F-12 间接费用计提（费用提取）

-- name: GetIndirectFeeByProject :one
SELECT * FROM F_INDIRECT_FEE
WHERE project_id = $1 AND tenant_id = $2 AND deleted = 0
ORDER BY id DESC LIMIT 1;

-- name: CreateIndirectFee :one
INSERT INTO F_INDIRECT_FEE (tenant_id, status, creator_id, project_id, legal_entity_id, period, total_budget, actual_income, actual_expense, indirect_rate, indirect_amount, performance_rate, performance_amount, calc_detail)
VALUES ($1, 'CALCULATED', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
RETURNING *;

-- name: UpdateIndirectFee :one
UPDATE F_INDIRECT_FEE
SET status = 'CALCULATED', period = $3, total_budget = $4, actual_income = $5, actual_expense = $6,
    indirect_rate = $7, indirect_amount = $8, performance_rate = $9, performance_amount = $10,
    calc_detail = $11, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
RETURNING *;
