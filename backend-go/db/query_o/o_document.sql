-- name: ListDocuments :many
SELECT * FROM o_document WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source_module')::text IS NULL OR source_module = sqlc.narg('source_module')::text)
  AND (sqlc.narg('source_id')::bigint IS NULL OR source_id = sqlc.narg('source_id')::bigint)
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: SearchDocuments :many
SELECT *, ts_rank(to_tsvector('simple', coalesce(text_content,'')), plainto_tsquery('simple', sqlc.arg('q')::text))::float4 AS rank,
       ts_headline('simple', coalesce(text_content,''), plainto_tsquery('simple', sqlc.arg('q')::text), 'MaxFragments=2,MinWords=8,MaxWords=18')::text AS snippet
FROM o_document
WHERE deleted = 0 AND status = 'STORED'
  AND to_tsvector('simple', coalesce(text_content,'')) @@ plainto_tsquery('simple', sqlc.arg('q')::text)
ORDER BY rank DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: GetDocument :one
SELECT * FROM o_document WHERE id = $1 AND deleted = 0;

-- name: CreateDocument :one
INSERT INTO o_document
  (code, tenant_id, status, creator_id, security_level, name, doc_type, size_bytes,
   bucket, object_key, checksum_sha256, uploader_id, uploaded_at, source_module, source_id, text_content)
VALUES
  (sqlc.narg('code')::text, sqlc.arg('tenant_id')::bigint, sqlc.arg('status')::text, sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('name')::text, sqlc.narg('doc_type')::text,
   sqlc.narg('size_bytes')::bigint, sqlc.narg('bucket')::text, sqlc.narg('object_key')::text,
   sqlc.narg('checksum_sha256')::text, sqlc.narg('uploader_id')::bigint,
   COALESCE(sqlc.narg('uploaded_at')::timestamptz, now()),
   sqlc.narg('source_module')::text, sqlc.narg('source_id')::bigint, sqlc.narg('text_content')::text)
RETURNING *;

-- name: SetDocumentStatus :execrows
UPDATE o_document SET status = sqlc.arg('status')::text, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: SoftDeleteDocument :execrows
UPDATE o_document SET deleted = 1, status = 'MISSING', updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: CountDocuments :one
SELECT count(*) FROM o_document WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source_module')::text IS NULL OR source_module = sqlc.narg('source_module')::text);
