-- name: ListBorrows :many
SELECT * FROM o_borrow WHERE deleted = 0
  AND (sqlc.narg('borrower_user_id')::bigint IS NULL OR borrower_user_id = sqlc.narg('borrower_user_id')::bigint)
  AND (sqlc.narg('archive_id')::bigint IS NULL OR archive_id = sqlc.narg('archive_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountBorrows :one
SELECT count(*) FROM o_borrow WHERE deleted = 0
  AND (sqlc.narg('borrower_user_id')::bigint IS NULL OR borrower_user_id = sqlc.narg('borrower_user_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text);

-- name: GetBorrow :one
SELECT * FROM o_borrow WHERE id = $1 AND deleted = 0;

-- name: CreateBorrow :one
INSERT INTO o_borrow(code, tenant_id, status, creator_id, archive_id, borrower_user_id, purpose, borrow_type, due_at)
VALUES (sqlc.narg('code')::text, sqlc.arg('tenant_id')::bigint, 'SUBMITTED', sqlc.arg('creator_id')::bigint,
  sqlc.arg('archive_id')::bigint, sqlc.arg('borrower_user_id')::bigint, sqlc.narg('purpose')::text,
  COALESCE(sqlc.narg('borrow_type')::text,'READ'), sqlc.narg('due_at')::timestamptz)
RETURNING *;

-- name: SetBorrowStatus :execrows
UPDATE o_borrow SET status=sqlc.arg('status')::text,
  approved_by=COALESCE(sqlc.narg('approved_by')::bigint, approved_by),
  approved_at=COALESCE(sqlc.narg('approved_at')::timestamptz, approved_at),
  returned_at=COALESCE(sqlc.narg('returned_at')::timestamptz, returned_at),
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0 AND status = sqlc.narg('from_status')::text;
