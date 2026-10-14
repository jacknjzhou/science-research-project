-- name: ListMyProjects :many
SELECT * FROM E_PROJECT
WHERE deleted = 0 AND pi_user_id = sqlc.arg('pi_user_id')::bigint
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY updated_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountMyProjects :one
SELECT count(*) FROM E_PROJECT
WHERE deleted = 0 AND pi_user_id = sqlc.arg('pi_user_id')::bigint
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: GetProject :one
SELECT * FROM E_PROJECT WHERE id = $1 AND deleted = 0;

-- name: UpdateProjectStatus :exec
UPDATE E_PROJECT SET status = $2, updated_at = now() WHERE id = $1 AND deleted = 0;
