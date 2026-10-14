-- name: ListPayouts :many
SELECT * FROM m_payout
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('period')::text          IS NULL OR period = sqlc.narg('period')::text)
  AND (sqlc.narg('status')::text          IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('payee_user_id')::bigint IS NULL OR payee_user_id = sqlc.narg('payee_user_id')::bigint)
ORDER BY id DESC
LIMIT $3 OFFSET $2;

-- name: CountPayouts :one
SELECT count(*)::int AS n
FROM m_payout
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('period')::text          IS NULL OR period = sqlc.narg('period')::text)
  AND (sqlc.narg('status')::text          IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('payee_user_id')::bigint IS NULL OR payee_user_id = sqlc.narg('payee_user_id')::bigint);

-- name: GetPayout :one
SELECT * FROM m_payout
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: CreatePayout :one
INSERT INTO m_payout (tenant_id, creator_id, status, record_id, payee_user_id, amount, period, pay_channel, security_level)
VALUES ($1, $2, 'DRAFT', $3, $4, $5::numeric, $6, $7, COALESCE($8::text,'INTERNAL'))
RETURNING *;

-- name: ApprovePayout :one
UPDATE m_payout
SET status='APPROVED', approved_at=now(), modifier_id=$3, updated_at=now(),
    approver_ids = approver_ids || jsonb_build_array(jsonb_build_object('userId',$3,'at',now(),'action','APPROVE'))
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status IN ('DRAFT','APPROVING')
RETURNING *;

-- name: PayPayout :one
UPDATE m_payout
SET status='PAID', paid_at=now(), voucher_code=COALESCE($4, voucher_code), modifier_id=$3, updated_at=now(),
    approver_ids = approver_ids || jsonb_build_array(jsonb_build_object('userId',$3,'at',now(),'action','PAY'))
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='APPROVED'
RETURNING *;

-- name: RejectPayout :one
UPDATE m_payout
SET status='REJECTED', reject_reason=COALESCE($4, reject_reason), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status IN ('DRAFT','APPROVING')
RETURNING *;
