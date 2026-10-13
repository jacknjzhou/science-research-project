-- name: ListApplications :many
SELECT id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, guideline_id, template_id, title,
       project_type, pi_user_id, member_ids, department_id, abstract,
       research_target, technical_route, expected_output, duration_months,
       total_budget::text AS total_budget, is_horizontal, funding_channel,
       ai_draft_marked, submit_at, withdraw_at, withdraw_reason
FROM p_application
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text)
ORDER BY id DESC
LIMIT @limit_ OFFSET @offset_;

-- name: CountApplications :one
SELECT count(*)::int AS n
FROM p_application
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text);

-- name: GetApplication :one
SELECT id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, guideline_id, template_id, title,
       project_type, pi_user_id, member_ids, department_id, abstract,
       research_target, technical_route, expected_output, duration_months,
       total_budget::text AS total_budget, is_horizontal, funding_channel,
       ai_draft_marked, submit_at, withdraw_at, withdraw_reason
FROM p_application
WHERE id = $1 AND deleted = 0
LIMIT 1;

-- name: CreateApplication :one
INSERT INTO p_application (
  tenant_id, status, creator_id, title, project_type, pi_user_id,
  member_ids, department_id, abstract, total_budget, is_horizontal
) VALUES (
  $1, $2, $3, $4, $5, $6,
  $7, $8, $9, $10::numeric, $11
)
RETURNING id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, guideline_id, template_id, title,
       project_type, pi_user_id, member_ids, department_id, abstract,
       research_target, technical_route, expected_output, duration_months,
       total_budget::text AS total_budget, is_horizontal, funding_channel,
       ai_draft_marked, submit_at, withdraw_at, withdraw_reason;
