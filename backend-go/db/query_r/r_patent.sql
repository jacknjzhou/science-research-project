-- T18 专利生命周期 + 年费

-- name: SetPatentStage :execrows
UPDATE R_OUTPUT SET stage = $2, updated_at = now() WHERE id = $1 AND deleted = 0 AND output_type = 'PATENT';

-- name: CreatePatentFee :one
INSERT INTO R_PATENT_FEE (tenant_id, patent_id, year, amount, paid_at, status)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: ListPatentFees :many
SELECT * FROM R_PATENT_FEE WHERE tenant_id = $1 AND patent_id = $2 ORDER BY year;

-- name: CreateAgency :one
INSERT INTO R_AGENCY (tenant_id, name, contact) VALUES ($1, $2, $3) RETURNING *;

-- name: ListAgencies :many
SELECT * FROM R_AGENCY WHERE deleted = 0 AND tenant_id = $1 ORDER BY id;

-- 年费扫描：GRANTED 专利 annual_fee_due 在 ahead 天内 / 已过期未缴
-- name: ListPatentsFeeDue :many
SELECT id, title, annual_fee_due, stage FROM R_OUTPUT
WHERE deleted = 0 AND tenant_id = $1 AND output_type = 'PATENT' AND stage = 'GRANTED'
  AND annual_fee_due IS NOT NULL
  AND annual_fee_due <= now() + make_interval(days => $2::int);

-- name: GetPatentStage :one
SELECT stage FROM R_OUTPUT WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND output_type = 'PATENT';
