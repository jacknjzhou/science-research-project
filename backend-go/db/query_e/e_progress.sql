-- name: CreateProgressReport :one
INSERT INTO E_PROGRESS_REPORT
  (code, tenant_id, status, creator_id, project_id, period, report_type, content_rich,
   progress_percent, issues_text, next_plan, attachment_ids)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'DRAFT',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint, sqlc.arg('period')::text,
   sqlc.arg('report_type')::text, sqlc.narg('content_rich')::text,
   sqlc.arg('progress_percent')::int, sqlc.narg('issues_text')::text, sqlc.narg('next_plan')::text,
   COALESCE(sqlc.narg('attachment_ids')::jsonb, '[]'::jsonb))
RETURNING *;

-- name: SubmitProgressReport :execrows
UPDATE E_PROGRESS_REPORT SET status='SUBMITTED', submitted_at=now(), updated_at=now()
WHERE id=$1 AND project_id=$2 AND status='DRAFT' AND deleted=0;
