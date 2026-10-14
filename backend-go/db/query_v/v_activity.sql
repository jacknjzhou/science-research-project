-- name: ListActivities :many
SELECT id, code, tenant_id, status, security_level, activity_type, level, host_mode,
       title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
       invited_experts, est_attendees, project_id, budget_subject_code,
       budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
       sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
       cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted
FROM v_activity
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('status')::text            IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('activity_type')::text     IS NULL OR activity_type = sqlc.narg('activity_type')::text)
  AND (sqlc.narg('level')::text             IS NULL OR level = sqlc.narg('level')::text)
  AND (sqlc.narg('host_mode')::text         IS NULL OR host_mode = sqlc.narg('host_mode')::text)
  AND (sqlc.narg('organizer_dept_id')::bigint IS NULL OR organizer_dept_id = sqlc.narg('organizer_dept_id')::bigint)
  AND (sqlc.narg('from_at')::timestamptz    IS NULL OR start_at >= sqlc.narg('from_at')::timestamptz)
  AND (sqlc.narg('to_at')::timestamptz      IS NULL OR start_at <= sqlc.narg('to_at')::timestamptz)
  AND (sqlc.narg('keyword')::text           IS NULL OR title ILIKE sqlc.narg('keyword')::text OR theme ILIKE sqlc.narg('keyword')::text)
ORDER BY id DESC
LIMIT $2 OFFSET $3;

-- name: CountActivities :one
SELECT count(*)::int AS n
FROM v_activity
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('status')::text            IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('activity_type')::text     IS NULL OR activity_type = sqlc.narg('activity_type')::text)
  AND (sqlc.narg('level')::text             IS NULL OR level = sqlc.narg('level')::text)
  AND (sqlc.narg('host_mode')::text         IS NULL OR host_mode = sqlc.narg('host_mode')::text)
  AND (sqlc.narg('organizer_dept_id')::bigint IS NULL OR organizer_dept_id = sqlc.narg('organizer_dept_id')::bigint)
  AND (sqlc.narg('from_at')::timestamptz    IS NULL OR start_at >= sqlc.narg('from_at')::timestamptz)
  AND (sqlc.narg('to_at')::timestamptz      IS NULL OR start_at <= sqlc.narg('to_at')::timestamptz)
  AND (sqlc.narg('keyword')::text           IS NULL OR title ILIKE sqlc.narg('keyword')::text OR theme ILIKE sqlc.narg('keyword')::text);

-- name: GetActivity :one
SELECT id, code, tenant_id, status, security_level, activity_type, level, host_mode,
       title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
       invited_experts, est_attendees, project_id, budget_subject_code,
       budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
       sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
       cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted
FROM v_activity
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: CreateActivity :one
INSERT INTO v_activity (
  tenant_id, status, security_level, creator_id, code, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code, budget_amount,
  agenda, attachment_ids, remark
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
  COALESCE($17::jsonb, '[]'::jsonb), $18, $19, $20, $21::numeric,
  COALESCE($22::jsonb, '[]'::jsonb), COALESCE($23::jsonb, '[]'::jsonb), $24
)
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: UpdateActivity :one
UPDATE v_activity SET
  activity_type = $3, level = $4, host_mode = $5, title = $6, theme = $7,
  start_at = $8, end_at = $9, venue = $10, online_url = $11, host_unit = $12,
  organizer_dept_id = $13, invited_experts = COALESCE($14::jsonb, '[]'::jsonb),
  est_attendees = $15, project_id = $16, budget_subject_code = $17,
  budget_amount = $18::numeric, agenda = COALESCE($19::jsonb, '[]'::jsonb),
  attachment_ids = COALESCE($20::jsonb, '[]'::jsonb), security_level = $21, remark = $22,
  modifier_id = $23, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status IN ('DRAFT','RETURNED')
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: TransitionStatus :one
-- 通用状态迁移：由 handler 校验 from→to 合法后调用；set 对应时间戳列（按 to 选）用 CASE 落。
UPDATE v_activity SET
  status = $4,
  submit_at  = CASE WHEN $4 = 'SUBMITTED'  THEN now() ELSE submit_at  END,
  approve_at = CASE WHEN $4 IN ('APPROVED') THEN now() ELSE approve_at END,
  archive_at = CASE WHEN $4 = 'ARCHIVED'   THEN now() ELSE archive_at END,
  cancel_at  = CASE WHEN $4 = 'CANCELLED'  THEN now() ELSE cancel_at  END,
  modifier_id = $5,
  updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = $3
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkHold :one
UPDATE v_activity SET
  status = 'HELD', sign_in_count = $3,
  hold_proof_ids = COALESCE($4::jsonb, hold_proof_ids),
  approve_at = CASE WHEN approve_at IS NULL THEN now() ELSE approve_at END,
  modifier_id = $5, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'APPROVED'
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkArchive :one
UPDATE v_activity SET
  status = 'ARCHIVED', minutes_rich = $3, archive_at = now(), modifier_id = $4, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'HELD'
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkCancel :one
UPDATE v_activity SET
  status = 'CANCELLED', cancel_at = now(), cancel_reason = $3, modifier_id = $4, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
  AND status NOT IN ('ARCHIVED','CANCELLED')
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: SoftDeleteActivity :execrows
UPDATE v_activity SET deleted = 1, status = 'CANCELLED', updated_at = now(), modifier_id = $3
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: ListCalendar :many
SELECT id, code, tenant_id, status, security_level, activity_type, level, host_mode,
       title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
       invited_experts, est_attendees, project_id, budget_subject_code,
       budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
       sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
       cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted
FROM v_activity
WHERE deleted = 0 AND tenant_id = $1
  AND start_at >= $2 AND start_at < $3
ORDER BY start_at;

-- name: StatsByType :many
SELECT activity_type AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1
GROUP BY activity_type ORDER BY count DESC;

-- name: StatsByLevel :many
SELECT level AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1 AND level IS NOT NULL
GROUP BY level ORDER BY count DESC;

-- name: StatsByDept :many
SELECT organizer_dept_id::text AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1 AND organizer_dept_id IS NOT NULL
GROUP BY organizer_dept_id ORDER BY count DESC;

-- name: StatsByMonth :many
SELECT to_char(date_trunc('month', start_at), 'YYYY-MM') AS key, count(*)::int AS count
FROM v_activity WHERE deleted = 0 AND tenant_id = $1 AND start_at IS NOT NULL
GROUP BY 1 ORDER BY 1;
