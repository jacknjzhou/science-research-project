-- F-01 科目字典（只读主数据，seed 维护）

-- name: ListSubjects :many
SELECT * FROM F_SUBJECT
WHERE deleted = 0 AND status = 'ACTIVE' AND tenant_id = $1
ORDER BY sort_no, id;

-- name: GetSubject :one
SELECT * FROM F_SUBJECT WHERE id = $1 AND deleted = 0;
