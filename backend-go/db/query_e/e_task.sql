-- name: ListTasks :many
SELECT * FROM E_TASK WHERE project_id = sqlc.arg('project_id')::bigint AND deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
ORDER BY id;

-- name: GetTask :one
SELECT * FROM E_TASK WHERE id = $1 AND project_id = $2 AND deleted = 0;

-- name: UpdateTask :execrows
UPDATE E_TASK
SET status = sqlc.arg('status')::text,
    owner_user_id = sqlc.narg('owner_user_id')::bigint,
    progress_percent = sqlc.arg('progress_percent')::int,
    updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND project_id = sqlc.arg('project_id')::bigint AND deleted = 0;

-- name: ListMilestones :many
SELECT * FROM E_MILESTONE WHERE project_id = $1 AND deleted = 0 ORDER BY due_date NULLS LAST, id;
