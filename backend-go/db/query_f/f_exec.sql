-- 执行率聚合与预警（F 闭环度量）

-- name: SumClaimedIncome :one
SELECT COALESCE(SUM(amount), 0)::numeric(18,2)::text AS total FROM F_INCOME
WHERE tenant_id = $1 AND project_id = $2 AND claim_status = 'CLAIMED' AND deleted = 0;

-- name: SumExpenseUsed :one
SELECT COALESCE(SUM(amount), 0)::numeric(18,2)::text AS total FROM F_EXPENSE
WHERE tenant_id = $1 AND project_id = $2 AND deleted = 0
  AND status IN ('APPROVED','PAID','VOUCHER_SYNCED');

-- name: SumExpenseFrozen :one
SELECT COALESCE(SUM(amount), 0)::numeric(18,2)::text AS total FROM F_EXPENSE
WHERE tenant_id = $1 AND project_id = $2 AND deleted = 0
  AND status IN ('SUBMITTED','AI_REVIEW','HUMAN_REVIEW');

-- name: SumBudgetApproved :one
SELECT COALESCE(SUM(total_approved), 0)::numeric(18,2)::text AS total FROM F_BUDGET
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

-- —— 大屏聚合（F-18 一图一舱三预警，T10）——
-- 语义：
--   totalBudget  = 有效批复预算合计
--   yearIncome   = 本年度已认领到账
--   yearUsed     = 本年度已核销支出（APPROVED/PAID/VOUCHER_SYNCED）
--   violation    = 事后违规近似：本年度 REJECTED/RETURNED 报销单数
--   deptHeatmap  = 按法人实体分组（契约 departmentId 以 legal_entity_id 承载）
--   trend12      = 近 12 个月逐月支出（相对 totalBudget 归一执行率）

-- name: DashTotalBudget :one
SELECT COALESCE(SUM(total_approved), 0)::numeric(18,2)::text AS total FROM F_BUDGET
WHERE tenant_id = $1 AND deleted = 0
  AND (sqlc.narg('legal_entity_id')::bigint IS NULL OR legal_entity_id = sqlc.narg('legal_entity_id')::bigint)
  AND status IN ('EXECUTING','ADJUSTING','RE_APPROVED','CLOSED');

-- name: DashYearIncome :one
SELECT COALESCE(SUM(amount), 0)::numeric(18,2)::text AS total FROM F_INCOME
WHERE tenant_id = $1 AND deleted = 0 AND claim_status = 'CLAIMED'
  AND (sqlc.narg('legal_entity_id')::bigint IS NULL OR legal_entity_id = sqlc.narg('legal_entity_id')::bigint)
  AND claimed_at >= date_trunc('year', now());

-- name: DashYearUsed :one
SELECT COALESCE(SUM(amount), 0)::numeric(18,2)::text AS total FROM F_EXPENSE
WHERE tenant_id = $1 AND deleted = 0
  AND (sqlc.narg('legal_entity_id')::bigint IS NULL OR legal_entity_id = sqlc.narg('legal_entity_id')::bigint)
  AND status IN ('APPROVED','PAID','VOUCHER_SYNCED')
  AND COALESCE(submitted_at, created_at) >= date_trunc('year', now());

-- name: DashViolationCount :one
SELECT count(*) FROM F_EXPENSE
WHERE tenant_id = $1 AND deleted = 0
  AND (sqlc.narg('legal_entity_id')::bigint IS NULL OR legal_entity_id = sqlc.narg('legal_entity_id')::bigint)
  AND status IN ('REJECTED','RETURNED')
  AND COALESCE(submitted_at, created_at) >= date_trunc('year', now());

-- name: DashDeptHeatmap :many
SELECT b.legal_entity_id AS department_id,
       COALESCE(SUM(b.total_approved), 0)::numeric(18,2)::text AS budget,
       COALESCE((SELECT SUM(e.amount) FROM F_EXPENSE e
                 WHERE e.tenant_id = $1 AND e.deleted = 0
                   AND e.legal_entity_id = b.legal_entity_id
                   AND e.status IN ('APPROVED','PAID','VOUCHER_SYNCED')), 0)::numeric(18,2)::text AS used
FROM F_BUDGET b
WHERE b.tenant_id = $1 AND b.deleted = 0
  AND (sqlc.narg('legal_entity_id')::bigint IS NULL OR b.legal_entity_id = sqlc.narg('legal_entity_id')::bigint)
  AND b.status IN ('EXECUTING','ADJUSTING','RE_APPROVED','CLOSED')
GROUP BY b.legal_entity_id;

-- name: DashTrend12 :many
SELECT to_char(date_trunc('month', COALESCE(submitted_at, created_at)), 'YYYY-MM') AS month,
       COALESCE(SUM(amount), 0)::numeric(18,2)::text AS total
FROM F_EXPENSE
WHERE tenant_id = $1 AND deleted = 0
  AND (sqlc.narg('legal_entity_id')::bigint IS NULL OR legal_entity_id = sqlc.narg('legal_entity_id')::bigint)
  AND status IN ('APPROVED','PAID','VOUCHER_SYNCED')
  AND COALESCE(submitted_at, created_at) >= date_trunc('month', now()) - interval '11 months'
GROUP BY 1 ORDER BY 1;

-- name: DashCountsByState :many
SELECT CASE
         WHEN status = 'DRAFT' THEN 'pre'
         WHEN status IN ('SUBMITTED','AI_REVIEW','HUMAN_REVIEW') THEN 'during'
         ELSE 'post'
       END AS bucket, count(*) AS cnt
FROM F_EXPENSE
WHERE tenant_id = $1 AND deleted = 0
  AND (sqlc.narg('legal_entity_id')::bigint IS NULL OR legal_entity_id = sqlc.narg('legal_entity_id')::bigint)
  AND COALESCE(submitted_at, created_at) >= date_trunc('year', now())
GROUP BY 1;
