-- T21 认领管理费：入账时按项目分类费率计算

-- name: GetMgmtFeePctByProject :one
SELECT COALESCE(c.mgmt_fee_pct, 0) AS mgmt_fee_pct
FROM e_project p
LEFT JOIN e_project_category c ON c.id = p.category_id AND c.deleted = 0
WHERE p.id = $1 AND p.deleted = 0;

-- name: UpdateIncomeMgmtFee :execrows
UPDATE f_income SET mgmt_fee = $2, updated_at = now() WHERE id = $1;
