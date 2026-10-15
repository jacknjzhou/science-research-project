-- N 域评审任务/邀请查询。列名/枚举以 design/15-专家与评审管理-N.ddl.sql → migrations n_review_task/n_review_invitation 段为准（小写）。

-- name: ListReviews :many
SELECT * FROM n_review_task WHERE deleted = 0
  AND (sqlc.narg('biz_type')::text IS NULL OR biz_type = sqlc.narg('biz_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountReviews :one
SELECT count(*) FROM n_review_task WHERE deleted = 0
  AND (sqlc.narg('biz_type')::text IS NULL OR biz_type = sqlc.narg('biz_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text);

-- name: GetReviewTask :one
SELECT * FROM n_review_task WHERE id = $1 AND deleted = 0;

-- name: CreateReviewTask :one
INSERT INTO n_review_task
  (code, tenant_id, status, creator_id, security_level, biz_type, target_type, target_id, project_id,
   title, review_method, plan_count, draw_rule)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'DRAFT', sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('biz_type')::text, sqlc.narg('target_type')::text,
   sqlc.narg('target_id')::bigint, sqlc.narg('project_id')::bigint, sqlc.arg('title')::text,
   COALESCE(sqlc.narg('review_method')::text,'RANDOM'), sqlc.arg('plan_count')::int,
   COALESCE(sqlc.narg('draw_rule')::jsonb,'{}'::jsonb))
RETURNING *;

-- name: UpdateReviewStatus :execrows
UPDATE n_review_task SET status=sqlc.arg('status')::text, updated_at=now()
  WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: MarkReviewDrawn :execrows
UPDATE n_review_task SET status='DRAWN', drawn_at=now(), updated_at=now()
  WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: MarkReviewStarted :execrows
UPDATE n_review_task SET status='IN_REVIEW', started_at=now(), updated_at=now()
  WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: ConcludeReviewTask :execrows
UPDATE n_review_task SET status='CONCLUDED', conclusion=sqlc.arg('conclusion')::text,
  score_summary=sqlc.arg('score_summary')::jsonb, concluded_at=now(), updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: InsertInvitation :one
INSERT INTO n_review_invitation (tenant_id, task_id, expert_id, seat_no, avoid_hit, response)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('task_id')::bigint, sqlc.arg('expert_id')::bigint,
  sqlc.arg('seat_no')::int, sqlc.arg('avoid_hit')::bool, sqlc.arg('response')::text) RETURNING *;

-- name: ListInvitations :many
SELECT i.*, e.name AS expert_name FROM n_review_invitation i
JOIN n_expert e ON e.id = i.expert_id
WHERE i.task_id = $1 ORDER BY i.seat_no;

-- name: ListAcceptedExperts :many
SELECT e.id AS expert_id, e.user_id, e.name, e.org_name FROM n_review_invitation i
JOIN n_expert e ON e.id = i.expert_id
WHERE i.task_id = $1 AND i.response = 'ACCEPT';

-- name: RespondInvitation :execrows
UPDATE n_review_invitation SET response=sqlc.arg('response')::text, responded_at=now()
WHERE task_id=sqlc.arg('task_id')::bigint AND expert_id=sqlc.arg('expert_id')::bigint;

-- name: CountAccepted :one
SELECT count(*) FROM n_review_invitation WHERE task_id=$1 AND response='ACCEPT';
