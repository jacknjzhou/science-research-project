-- name: CreateChangeRequest :one
-- 变更申请提交即送审：status=SUBMITTED（DRAFT 无法进入审批流——
-- approve 仅接受 SUBMITTED/APPROVING），approval_status 走默认 PENDING。
INSERT INTO E_CHANGE_REQUEST
  (code, tenant_id, status, creator_id, project_id, change_type, old_value, new_value, reason)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'SUBMITTED',
   sqlc.arg('creator_id')::bigint, sqlc.arg('project_id')::bigint, sqlc.arg('change_type')::text,
   sqlc.narg('old_value')::jsonb, sqlc.narg('new_value')::jsonb, sqlc.narg('reason')::text)
RETURNING *;

-- name: ApproveChangeRequest :execrows
UPDATE E_CHANGE_REQUEST SET status='EFFECTIVE', updated_at=now()
WHERE id=$1 AND project_id=$2 AND status IN ('SUBMITTED','APPROVING') AND deleted=0;

-- name: AdvanceChangeRequest :execrows
-- T19 两级审核推进：SUBMITTED→APPROVING（首审）→EFFECTIVE（终审）
UPDATE E_CHANGE_REQUEST SET status=sqlc.arg('to_status')::text, updated_at=now()
WHERE id=$1 AND project_id=$2 AND status=sqlc.arg('from_status')::text AND deleted=0;

-- name: GetChangeRequest :one
SELECT * FROM E_CHANGE_REQUEST WHERE id=$1 AND deleted=0;
