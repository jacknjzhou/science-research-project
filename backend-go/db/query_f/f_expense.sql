-- F-07 报销申请（三重指纹查重，F-10 提交冻结由事务编排）

-- name: CreateExpense :one
INSERT INTO F_EXPENSE (tenant_id, status, creator_id, project_id, budget_line_id, legal_entity_id, applicant_user_id, amount, expense_category, expense_type, description, invoice_ids, fingerprint_invoice_no, fingerprint_amount, fingerprint_invoice_date, fingerprint_hash, submit_mode)
VALUES ($1, 'DRAFT', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
RETURNING *;

-- name: SetExpenseCode :exec
UPDATE F_EXPENSE SET code = $2, updated_at = now() WHERE id = $1;

-- name: GetExpense :one
SELECT * FROM F_EXPENSE WHERE id = $1 AND deleted = 0;

-- name: GetExpenseForUpdate :one
SELECT * FROM F_EXPENSE WHERE id = $1 AND deleted = 0 FOR UPDATE;

-- name: FingerprintTaken :one
SELECT id FROM F_EXPENSE
WHERE tenant_id = $1 AND fingerprint_hash = $2 AND deleted = 0
  AND status NOT IN ('REJECTED','RETURNED')
LIMIT 1;

-- name: ListExpenses :many
SELECT * FROM F_EXPENSE
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_id = sqlc.narg('project_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('applicant_user_id')::bigint IS NULL OR applicant_user_id = sqlc.narg('applicant_user_id')::bigint)
ORDER BY id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountExpenses :one
SELECT count(*) FROM F_EXPENSE
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_id = sqlc.narg('project_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('applicant_user_id')::bigint IS NULL OR applicant_user_id = sqlc.narg('applicant_user_id')::bigint);

-- name: SubmitExpense :one
UPDATE F_EXPENSE
SET status = 'SUBMITTED', submitted_at = now(), frozen_at = now(), updated_at = now()
WHERE id = $1 AND status = 'DRAFT' AND deleted = 0
RETURNING *;

-- name: SetExpenseStatus :exec
UPDATE F_EXPENSE SET status = $2, updated_at = now() WHERE id = $1 AND deleted = 0;
