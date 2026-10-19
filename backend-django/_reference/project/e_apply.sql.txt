-- T25 申报计划 + 申报单

-- name: CreateApplyPlan :one
INSERT INTO e_apply_plan (tenant_id, name, category_id, source, start_at, end_at, need_review, guide_file_id, status)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'DRAFT')
RETURNING *;

-- name: ListApplyPlans :many
SELECT * FROM e_apply_plan WHERE tenant_id = $1
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountApplyPlans :one
SELECT count(*) FROM e_apply_plan WHERE tenant_id = $1;

-- name: GetApplyPlan :one
SELECT * FROM e_apply_plan WHERE id = $1 AND tenant_id = $2;

-- name: SetApplyPlanStatus :execrows
UPDATE e_apply_plan SET status = sqlc.arg('to_status')::text, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND status = sqlc.arg('from_status')::text;

-- name: CreateApplication :one
INSERT INTO e_application (tenant_id, plan_id, project_name, apply_amount, applicant_id, attachment_ids)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('plan_id')::bigint, sqlc.arg('project_name')::text,
        COALESCE(sqlc.arg('apply_amount')::numeric, 0), sqlc.arg('applicant_id')::bigint, sqlc.arg('attachment_ids')::jsonb)
RETURNING *;

-- name: GetApplication :one
SELECT * FROM e_application WHERE id = $1 AND tenant_id = $2;

-- name: ListApplicationsByPlan :many
-- 形式审查视图：附申请人「主持+参与」项目摘要（数量与经费合计）
SELECT a.*,
       (SELECT count(*) FROM e_project p WHERE p.deleted = 0
          AND (p.pi_user_id = a.applicant_id
               OR p.member_ids @> jsonb_build_array(jsonb_build_object('user_id', a.applicant_id)))) AS pi_project_count,
       (SELECT CAST(COALESCE(SUM(p.total_budget),0) AS numeric) FROM e_project p WHERE p.deleted = 0
          AND (p.pi_user_id = a.applicant_id
               OR p.member_ids @> jsonb_build_array(jsonb_build_object('user_id', a.applicant_id)))) AS pi_budget_total
FROM e_application a
WHERE a.tenant_id = $1 AND a.plan_id = $2
ORDER BY a.created_at DESC, a.id DESC;

-- name: AdvanceApplication :execrows
UPDATE e_application SET status = sqlc.arg('to_status')::text, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND status = sqlc.arg('from_status')::text;

-- name: BindApplicationProject :execrows
UPDATE e_application SET project_id = $2, updated_at = now()
WHERE id = $1 AND project_id IS NULL;

-- name: AutoStopExpiredPlans :execrows
UPDATE e_apply_plan SET status = 'STOPPED', updated_at = now()
WHERE tenant_id = $1 AND status = 'OPEN' AND end_at < CURRENT_DATE;

-- name: CreateProjectDraft :one
-- 注：E_PROJECT status CHECK 无草稿态，转立项落 EXECUTING（申报通过即可执行）
INSERT INTO e_project (tenant_id, status, creator_id, application_id, title, project_type,
    pi_user_id, member_ids, legal_entity_id, total_budget)
VALUES ($1, 'EXECUTING', $2, $3, $4, $5, $6, '[]'::jsonb, 1, $7)
RETURNING *;
