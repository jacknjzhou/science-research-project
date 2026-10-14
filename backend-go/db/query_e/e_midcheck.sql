-- name: CreateMidCheck :one
INSERT INTO E_MID_CHECK
  (code, tenant_id, status, creator_id, project_id, check_round, check_date, plan_id, template_id, expert_ids)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'PLANNED',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint, sqlc.arg('check_round')::int,
   sqlc.narg('check_date')::date, sqlc.narg('plan_id')::bigint, sqlc.narg('template_id')::bigint,
   COALESCE(sqlc.narg('expert_ids')::jsonb, '[]'::jsonb))
RETURNING *;

-- name: GetMidCheck :one
SELECT * FROM E_MID_CHECK WHERE id = $1 AND deleted = 0;

-- name: SetMidCheckExperts :execrows
UPDATE E_MID_CHECK SET expert_ids = sqlc.arg('expert_ids')::jsonb,
  status = CASE WHEN status='PLANNED' THEN 'IN_REVIEW' ELSE status END, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: ConcludeMidCheck :execrows
UPDATE E_MID_CHECK SET status='CONCLUDED', conclusion = sqlc.arg('conclusion')::text,
  score_detail = sqlc.arg('score_detail')::jsonb, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;
