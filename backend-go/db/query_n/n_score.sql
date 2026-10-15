-- N 域在线打分查询。列名/枚举以 design/15-专家与评审管理-N.ddl.sql → migrations n_review_score 段为准（小写）。
-- uk_n_score(task_id, expert_id) 支撑 UpsertScore 的 ON CONFLICT。

-- name: UpsertScore :one
INSERT INTO n_review_score (tenant_id, task_id, expert_id, target_type, target_id, dimension_scores, total_score, comment, status)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('task_id')::bigint, sqlc.arg('expert_id')::bigint,
  sqlc.narg('target_type')::text, sqlc.narg('target_id')::bigint, sqlc.arg('dimension_scores')::jsonb,
  sqlc.arg('total_score')::numeric, sqlc.narg('comment')::text, 'SUBMITTED')
ON CONFLICT (task_id, expert_id) DO UPDATE
SET dimension_scores=EXCLUDED.dimension_scores, total_score=EXCLUDED.total_score,
    comment=EXCLUDED.comment, status='SUBMITTED', submitted_at=now()
RETURNING *;

-- name: ListScores :many
SELECT * FROM n_review_score WHERE task_id=$1 ORDER BY expert_id;

-- name: CountScores :one
SELECT count(*) FROM n_review_score WHERE task_id=$1 AND status='SUBMITTED';
