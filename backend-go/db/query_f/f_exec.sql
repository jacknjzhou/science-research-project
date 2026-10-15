-- 执行率聚合与预警（F 闭环度量）

-- name: SumClaimedIncome :one
SELECT COALESCE(SUM(amount), 0)::text AS total FROM F_INCOME
WHERE tenant_id = $1 AND project_id = $2 AND claim_status = 'CLAIMED' AND deleted = 0;

-- name: SumExpenseUsed :one
SELECT COALESCE(SUM(amount), 0)::text AS total FROM F_EXPENSE
WHERE tenant_id = $1 AND project_id = $2 AND deleted = 0
  AND status IN ('APPROVED','PAID','VOUCHER_SYNCED');

-- name: SumExpenseFrozen :one
SELECT COALESCE(SUM(amount), 0)::text AS total FROM F_EXPENSE
WHERE tenant_id = $1 AND project_id = $2 AND deleted = 0
  AND status IN ('SUBMITTED','AI_REVIEW','HUMAN_REVIEW');

-- name: SumBudgetApproved :one
SELECT COALESCE(SUM(total_approved), 0)::text AS total FROM F_BUDGET
WHERE tenant_id = $1 AND project_id = $2 AND deleted = 0
  AND status IN ('EXECUTING','ADJUSTING','RE_APPROVED','CLOSED');

-- name: ListExecutingProjects :many
SELECT id, code, title, end_date, actual_end_date FROM E_PROJECT
WHERE tenant_id = $1 AND deleted = 0
  AND status IN ('EXECUTING','MID_CHECK','CHANGING','CORRECTING','COMPLETING','DELAYED')
ORDER BY id;

-- name: GetProjectBrief :one
SELECT id, code, title, end_date, actual_end_date, pi_user_id FROM E_PROJECT
WHERE id = $1 AND deleted = 0;
