-- F-09 报销审批步骤

-- name: CreateApproval :exec
INSERT INTO F_EXPENSE_APPROVAL (tenant_id, status, creator_id, expense_id, step_order, role)
VALUES ($1, 'PENDING', $2, $3, $4, $5);

-- name: ListApprovalsByExpense :many
SELECT * FROM F_EXPENSE_APPROVAL
WHERE expense_id = $1 AND deleted = 0
ORDER BY step_order;

-- name: GetCurrentApproval :one
SELECT * FROM F_EXPENSE_APPROVAL
WHERE expense_id = $1 AND status = 'PENDING' AND deleted = 0
ORDER BY step_order
LIMIT 1;

-- name: ActApproval :one
UPDATE F_EXPENSE_APPROVAL
SET action = $2, comment = $3, approver_user_id = $4, acted_at = now(), status = 'DONE', updated_at = now()
WHERE id = $1 AND status = 'PENDING' AND deleted = 0
RETURNING *;
