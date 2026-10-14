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
  AND ($2::text   IS NULL OR status = $2::text)
  AND ($3::text   IS NULL OR activity_type = $3::text)
  AND ($4::text   IS NULL OR level = $4::text)
  AND ($5::text   IS NULL OR host_mode = $5::text)
  AND ($6::bigint IS NULL OR organizer_dept_id = $6::bigint)
  AND ($7::timestamptz IS NULL OR start_at >= $7::timestamptz)
  AND ($8::timestamptz IS NULL OR start_at <= $8::timestamptz)
  AND ($9::text   IS NULL OR title ILIKE $9::text OR theme ILIKE $9::text)
ORDER BY id DESC
LIMIT $11 OFFSET $10;

-- name: CountActivities :one
SELECT count(*)::int AS n
FROM v_activity
WHERE deleted = 0
  AND tenant_id = $1
  AND ($2::text   IS NULL OR status = $2::text)
  AND ($3::text   IS NULL OR activity_type = $3::text)
  AND ($4::text   IS NULL OR level = $4::text)
  AND ($5::text   IS NULL OR host_mode = $5::text)
  AND ($6::bigint IS NULL OR organizer_dept_id = $6::bigint)
  AND ($7::timestamptz IS NULL OR start_at >= $7::timestamptz)
  AND ($8::timestamptz IS NULL OR start_at <= $8::timestamptz)
  AND ($9::text   IS NULL OR title ILIKE $9::text OR theme ILIKE $9::text);

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
  activity_type = $4, level = $5, host_mode = $6, title = $7, theme = $8,
  start_at = $9, end_at = $10, venue = $11, online_url = $12, host_unit = $13,
  organizer_dept_id = $14, invited_experts = COALESCE($15::jsonb, '[]'::jsonb),
  est_attendees = $16, project_id = $17, budget_subject_code = $18,
  budget_amount = $19::numeric, agenda = COALESCE($20::jsonb, '[]'::jsonb),
  attachment_ids = COALESCE($21::jsonb, '[]'::jsonb), security_level = $22, remark = $23,
  modifier_id = $24, updated_at = now()
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
  status = 'HELD', sign_in_count = $4,
  hold_proof_ids = COALESCE($5::jsonb, hold_proof_ids),
  approve_at = CASE WHEN approve_at IS NULL THEN now() ELSE approve_at END,
  modifier_id = $6, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'APPROVED'
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkArchive :one
UPDATE v_activity SET
  status = 'ARCHIVED', minutes_rich = $4, archive_at = now(), modifier_id = $5, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0 AND status = 'HELD'
RETURNING id, code, tenant_id, status, security_level, activity_type, level, host_mode,
  title, theme, start_at, end_at, venue, online_url, host_unit, organizer_dept_id,
  invited_experts, est_attendees, project_id, budget_subject_code,
  budget_amount::text AS budget_amount, agenda, attachment_ids, minutes_rich,
  sign_in_count, hold_proof_ids, submit_at, approve_at, archive_at, cancel_at,
  cancel_reason, creator_id, modifier_id, created_at, updated_at, remark, deleted;

-- name: MarkCancel :one
UPDATE v_activity SET
  status = 'CANCELLED', cancel_at = now(), cancel_reason = $4, modifier_id = $5, updated_at = now()
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
