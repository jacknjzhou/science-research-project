-- T24 PI 画像真数据（跨读 E/R/M，最小列见 m_schema.sql）

-- name: PortraitProjectStats :one
SELECT count(*) AS project_count,
       CAST(COALESCE(SUM(total_budget), 0) AS numeric) AS budget_total
FROM e_project
WHERE tenant_id = sqlc.arg('tenant_id') AND deleted = 0
  AND (pi_user_id = sqlc.arg('uid')
       OR member_ids @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('uid')::bigint)));

-- name: PortraitOutputCount :one
SELECT count(*) FROM r_output
WHERE tenant_id = sqlc.arg('tenant_id') AND deleted = 0
  AND authors @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('uid')::bigint));

-- name: PortraitLatestScore :one
SELECT total_score FROM m_record
WHERE tenant_id = sqlc.arg('tenant_id') AND deleted = 0 AND staff_user_id = sqlc.arg('uid')
ORDER BY created_at DESC, id DESC
LIMIT 1;

-- name: PortraitUsedTotal :one
SELECT CAST(COALESCE(SUM(bl.amount_used), 0) AS numeric) AS used_total
FROM f_budget_line bl
JOIN f_budget b ON b.id = bl.budget_id AND b.deleted = 0
JOIN e_project p ON p.id = b.project_id AND p.deleted = 0
WHERE b.tenant_id = sqlc.arg('tenant_id')
  AND (p.pi_user_id = sqlc.arg('uid')
       OR p.member_ids @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('uid')::bigint)));
