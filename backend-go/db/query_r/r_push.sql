-- T17 网推成果推送池

-- name: CreatePushItem :one
INSERT INTO R_PUSH_ITEM (tenant_id, type, source_db, title, authors, year, raw_doi, dedup_key)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
RETURNING *;

-- name: ListPushItems :many
SELECT * FROM R_PUSH_ITEM
WHERE deleted = 0 AND tenant_id = $1
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('typ')::text IS NULL OR type = sqlc.narg('typ')::text)
ORDER BY pushed_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountPushItems :one
SELECT count(*) FROM R_PUSH_ITEM
WHERE deleted = 0 AND tenant_id = $1
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('typ')::text IS NULL OR type = sqlc.narg('typ')::text);

-- name: GetPushItem :one
SELECT * FROM R_PUSH_ITEM WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: MarkPushItemImported :exec
UPDATE R_PUSH_ITEM SET status = 'IMPORTED', output_id = $2 WHERE id = $1;

-- name: MarkPushItemIgnored :exec
UPDATE R_PUSH_ITEM SET status = 'IGNORED' WHERE id = $1;

-- name: GetOutputByTitleHash :one
SELECT id, title, status FROM R_OUTPUT WHERE title_hash = $1 AND deleted = 0 LIMIT 1;

-- name: FindSimilarOutputs :many
SELECT id, title, status FROM R_OUTPUT
WHERE deleted = 0 AND title % $1
ORDER BY similarity(title, $1) DESC
LIMIT 5;

-- name: CreatePushedOutput :one
INSERT INTO R_OUTPUT (tenant_id, creator_id, status, output_type, title, authors, external_author_names, project_ids, affiliations, source, publish_date, legal_entity_id)
VALUES ($1, $2, 'AUTO_FETCHED', $3, $4, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, $5, $6, 1)
RETURNING *;
