-- name: ListArchives :many
SELECT * FROM o_archive WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('archive_type')::text IS NULL OR archive_type = sqlc.narg('archive_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountArchives :one
SELECT count(*) FROM o_archive WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('archive_type')::text IS NULL OR archive_type = sqlc.narg('archive_type')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: GetArchive :one
SELECT * FROM o_archive WHERE id = $1 AND deleted = 0;

-- name: CreateArchive :one
INSERT INTO o_archive
  (code, tenant_id, status, creator_id, security_level, title, archive_type,
   source_module, source_id, source_code, owner_dept_id, retention_years)
VALUES
  (sqlc.narg('code')::text, sqlc.arg('tenant_id')::bigint, 'PENDING_SUBMIT', sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('title')::text,
   COALESCE(sqlc.narg('archive_type')::text,'OTHER'), sqlc.narg('source_module')::text,
   sqlc.narg('source_id')::bigint, sqlc.narg('source_code')::text, sqlc.narg('owner_dept_id')::bigint,
   COALESCE(sqlc.narg('retention_years')::int, 10))
RETURNING *;

-- name: UpdateArchive :execrows
UPDATE o_archive SET title=sqlc.arg('title')::text, archive_type=sqlc.arg('archive_type')::text,
  retention_years=sqlc.arg('retention_years')::int, security_level=sqlc.arg('security_level')::text,
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0 AND status IN ('PENDING_SUBMIT','REJECTED');

-- name: SoftDeleteArchive :execrows
UPDATE o_archive SET deleted=1, modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0 AND status IN ('PENDING_SUBMIT','REJECTED');

-- name: SetArchiveStatus :execrows
UPDATE o_archive SET status=sqlc.arg('status')::text,
  submitter_id=COALESCE(sqlc.narg('submitter_id')::bigint, submitter_id),
  submit_at=COALESCE(sqlc.narg('submit_at')::timestamptz, submit_at),
  archivist_id=COALESCE(sqlc.narg('archivist_id')::bigint, archivist_id),
  filed_at=COALESCE(sqlc.narg('filed_at')::timestamptz, filed_at),
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0
  AND status = sqlc.narg('from_status')::text;   -- 乐观并发：仅当前态匹配才迁移

-- name: ListItems :many
SELECT * FROM o_archive_item WHERE archive_id = $1 ORDER BY sort_no ASC, id ASC;

-- name: GetItem :one
SELECT * FROM o_archive_item WHERE id = $1 AND archive_id = $2;

-- name: CreateItem :one
INSERT INTO o_archive_item(tenant_id, archive_id, category_code, category_name, required, doc_id, status, sort_no)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('archive_id')::bigint, sqlc.arg('category_code')::text,
  sqlc.narg('category_name')::text, COALESCE(sqlc.narg('required')::bool, TRUE), sqlc.narg('doc_id')::bigint,
  CASE WHEN sqlc.narg('doc_id')::bigint IS NULL THEN 'MISSING' ELSE 'FILLED' END,
  COALESCE(sqlc.narg('sort_no')::int, 0))
RETURNING *;

-- name: FillItem :execrows
UPDATE o_archive_item SET doc_id=sqlc.arg('doc_id')::bigint, status='FILLED'
WHERE id=sqlc.arg('id')::bigint AND archive_id=sqlc.arg('archive_id')::bigint;

-- name: DeleteItem :execrows
DELETE FROM o_archive_item WHERE id=sqlc.arg('id')::bigint AND archive_id=sqlc.arg('archive_id')::bigint;

-- name: ListRequiredItems :many
SELECT * FROM o_archive_item WHERE archive_id = $1 AND required = TRUE;

-- name: UpsertCheck :one
INSERT INTO o_archive_check(tenant_id, archive_id, check_type, result, detail, checked_at, checker_id)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('archive_id')::bigint, sqlc.arg('check_type')::text,
  sqlc.arg('result')::text, sqlc.arg('detail')::jsonb, now(), sqlc.narg('checker_id')::bigint)
ON CONFLICT (archive_id, check_type) DO UPDATE
  SET result=EXCLUDED.result, detail=EXCLUDED.detail, checked_at=now(), checker_id=EXCLUDED.checker_id
RETURNING *;

-- name: ListChecks :many
SELECT * FROM o_archive_check WHERE archive_id = $1 ORDER BY check_type ASC;
