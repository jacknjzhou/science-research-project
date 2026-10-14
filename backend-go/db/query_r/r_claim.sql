-- R 域认领工作流查询（R-05）。列名以 design/04-科研成果管理-R.ddl.sql R_CLAIM_RECORD 段为准。

-- name: ListPendingClaim :many
-- 待认领：claim_status ∈ (UNCLAIMED/PENDING/DOUBTFUL) 且命中本人署名 authors.user_id。
-- min_confidence 过滤（契约默认 0.7）；match_confidence 降序（高置信优先，R-04 智能匹配）。
SELECT * FROM R_OUTPUT
WHERE deleted = 0
  AND claim_status IN ('UNCLAIMED','PENDING','DOUBTFUL')
  AND authors @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('user_id')::bigint))
  AND (sqlc.narg('min_confidence')::numeric IS NULL OR match_confidence >= sqlc.narg('min_confidence')::numeric)
ORDER BY match_confidence DESC NULLS LAST, created_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountPendingClaim :one
SELECT count(*) FROM R_OUTPUT
WHERE deleted = 0
  AND claim_status IN ('UNCLAIMED','PENDING','DOUBTFUL')
  AND authors @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('user_id')::bigint))
  AND (sqlc.narg('min_confidence')::numeric IS NULL OR match_confidence >= sqlc.narg('min_confidence')::numeric);

-- name: SetClaimStatus :execrows
-- 认领/拒绝/非我：改 claim_status + 生命周期 status + is_claimed（token 由 handler 按动作选 DDL 合法枚举）。
UPDATE R_OUTPUT SET claim_status = sqlc.arg('claim_status')::text,
  status = sqlc.arg('status')::text, is_claimed = sqlc.arg('is_claimed')::bool, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: InsertClaimRecord :one
-- DDL 校正：计划正文用 actor_user_id/note，R_CLAIM_RECORD 实际列是 user_id/reason（DDL 无 actor_user_id/note）。
-- status 有默认 'DONE'、action_at/created_at 默认 now()，不显式供值。
INSERT INTO R_CLAIM_RECORD (tenant_id, creator_id, output_id, user_id, action, reason, batch_id)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('creator_id')::bigint,
  sqlc.arg('output_id')::bigint, sqlc.arg('user_id')::bigint,
  sqlc.arg('action')::text, sqlc.narg('reason')::text, sqlc.narg('batch_id')::text)
RETURNING *;

-- name: GetClaimRecord :one
SELECT * FROM R_CLAIM_RECORD WHERE id = $1 AND deleted = 0;

-- name: ListClaimRecordsByOutput :many
SELECT * FROM R_CLAIM_RECORD WHERE output_id = $1 AND deleted = 0 ORDER BY action_at DESC;
