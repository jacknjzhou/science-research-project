-- name: ListParticipants :many
SELECT id, activity_id, user_id, guest_name, role, report_title, tenant_id, created_at
FROM v_activity_participant
WHERE activity_id = $1 AND tenant_id = $2
ORDER BY id;

-- name: AddParticipant :one
INSERT INTO v_activity_participant (activity_id, user_id, guest_name, role, report_title, tenant_id)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, activity_id, user_id, guest_name, role, report_title, tenant_id, created_at;

-- name: DeleteParticipant :execrows
DELETE FROM v_activity_participant
WHERE id = $1 AND activity_id = $2 AND tenant_id = $3;
