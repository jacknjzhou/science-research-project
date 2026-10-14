-- name: CreateFinalAccept :one
-- DDL 校正：计划正文用 report_id/summary，但 E_FINAL_ACCEPT 无此列；
-- report_id -> finance_report_id（同义 03 F 决算报告 FK，BIGINT 可空）；
-- summary 无 TEXT 等价列（output_summary 为 JSONB 只读引用，语义/类型不符，已删列待 1.3 复核）。
INSERT INTO E_FINAL_ACCEPT
  (code, tenant_id, status, creator_id, project_id, finance_report_id)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'APPLIED',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint,
   sqlc.narg('finance_report_id')::bigint)
RETURNING *;

-- name: GetFinalAccept :one
SELECT * FROM E_FINAL_ACCEPT WHERE id = $1 AND deleted = 0;

-- name: ConcludeFinalAccept :execrows
UPDATE E_FINAL_ACCEPT SET status = sqlc.arg('status')::text, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;
