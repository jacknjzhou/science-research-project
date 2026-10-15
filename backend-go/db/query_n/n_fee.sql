-- N 域评审费查询。列名/枚举以 design/15-专家与评审管理-N.ddl.sql → migrations n_review_fee 段为准（小写）。

-- name: InsertFee :one
INSERT INTO n_review_fee (code, tenant_id, status, creator_id, task_id, expert_id, amount, pay_channel)
VALUES (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'UNPAID', sqlc.arg('creator_id')::bigint,
  sqlc.arg('task_id')::bigint, sqlc.arg('expert_id')::bigint, sqlc.arg('amount')::numeric,
  sqlc.narg('pay_channel')::text)
RETURNING *;

-- name: ListFeesByTask :many
SELECT * FROM n_review_fee WHERE task_id = $1 AND deleted = 0 ORDER BY expert_id;

-- name: CountFeesByTask :one
SELECT count(*) FROM n_review_fee WHERE task_id = $1 AND deleted = 0;
