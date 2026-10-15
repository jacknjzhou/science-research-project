-- T23 执行三维监控：college（按项目承担部门）/ subject（按预算科目）分组聚合
-- 口径与 executionOf 一致：approved=计划+调整、used=实扣、frozen=冻结

-- name: ExecutionByCollege :many
SELECT COALESCE(p.department_id, 0) AS dim_id,
       CAST(SUM(COALESCE(bl.amount_planned, 0) + COALESCE(bl.amount_adjusted, 0)) AS numeric) AS approved,
       CAST(SUM(COALESCE(bl.amount_used, 0))   AS numeric) AS used,
       CAST(SUM(COALESCE(bl.amount_frozen, 0)) AS numeric) AS frozen
FROM f_budget_line bl
JOIN f_budget b ON b.id = bl.budget_id AND b.deleted = 0
JOIN e_project p ON p.id = b.project_id AND p.deleted = 0
WHERE b.tenant_id = $1
GROUP BY 1 ORDER BY 1;

-- name: ExecutionBySubject :many
SELECT bl.subject_id AS dim_id,
       CAST(SUM(COALESCE(bl.amount_planned, 0) + COALESCE(bl.amount_adjusted, 0)) AS numeric) AS approved,
       CAST(SUM(COALESCE(bl.amount_used, 0))   AS numeric) AS used,
       CAST(SUM(COALESCE(bl.amount_frozen, 0)) AS numeric) AS frozen
FROM f_budget_line bl
JOIN f_budget b ON b.id = bl.budget_id AND b.deleted = 0
WHERE b.tenant_id = $1
GROUP BY 1 ORDER BY 1;
