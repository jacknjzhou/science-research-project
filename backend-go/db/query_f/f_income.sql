-- F-05/F-06 到款登记 / 认领 / 批量导入

-- name: CreateIncome :one
INSERT INTO F_INCOME (tenant_id, status, creator_id, legal_entity_id, receipt_no, receipt_date, amount, payer_name, payer_bank, purpose_text, bank_flow_no, claim_status)
VALUES ($1, 'ACTIVE', $2, $3, $4, $5, $6, $7, $8, $9, $10, 'UNCLAIMED')
RETURNING *;

-- name: SetIncomeCode :exec
UPDATE F_INCOME SET code = $2, updated_at = now() WHERE id = $1;

-- name: GetIncome :one
SELECT * FROM F_INCOME WHERE id = $1 AND deleted = 0;

-- name: GetIncomeForUpdate :one
SELECT * FROM F_INCOME WHERE id = $1 AND deleted = 0 FOR UPDATE;

-- name: IncomeFlowNoExists :one
SELECT EXISTS(
  SELECT 1 FROM F_INCOME
  WHERE tenant_id = $1 AND bank_flow_no = $2 AND deleted = 0
) AS exists_;

-- name: ListIncomes :many
SELECT * FROM F_INCOME
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('claim_status')::text IS NULL OR claim_status = sqlc.narg('claim_status')::text)
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_id = sqlc.narg('project_id')::bigint)
  AND (sqlc.narg('kw')::text IS NULL OR payer_name ILIKE ('%'||sqlc.narg('kw')::text||'%') OR receipt_no ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountIncomes :one
SELECT count(*) FROM F_INCOME
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('claim_status')::text IS NULL OR claim_status = sqlc.narg('claim_status')::text)
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_id = sqlc.narg('project_id')::bigint)
  AND (sqlc.narg('kw')::text IS NULL OR payer_name ILIKE ('%'||sqlc.narg('kw')::text||'%') OR receipt_no ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: ClaimIncome :one
UPDATE F_INCOME
SET project_id = $2, claimed_by = $3, claimed_at = now(), claim_status = 'CLAIMED', updated_at = now()
WHERE id = $1 AND claim_status = 'UNCLAIMED' AND deleted = 0
RETURNING *;
