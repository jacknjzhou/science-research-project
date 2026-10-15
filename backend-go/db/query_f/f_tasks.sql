-- T20 任务中心：跨域待办读模型（我名下 PENDING 审批单）
-- 说明：NF 块 schema 无 F 表，故此查询放 F 块生成，notify handler 经 fstore 调用。

-- name: ListPendingExpenseApprovals :many
SELECT e.id, e.code, e.amount, e.status, e.expense_type, e.created_at, a.step_order, a.role
FROM f_expense_approval a
JOIN f_expense e ON e.id = a.expense_id
WHERE a.status = 'PENDING' AND a.deleted = 0
  AND a.role = ANY(sqlc.arg('roles')::text[])
  AND e.status IN ('SUBMITTED','AI_REVIEW','HUMAN_REVIEW')
ORDER BY e.created_at DESC, e.id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountPendingExpenseApprovals :one
SELECT count(*)
FROM f_expense_approval a
JOIN f_expense e ON e.id = a.expense_id
WHERE a.status = 'PENDING' AND a.deleted = 0
  AND a.role = ANY(sqlc.arg('roles')::text[])
  AND e.status IN ('SUBMITTED','AI_REVIEW','HUMAN_REVIEW');
