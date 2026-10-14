-- name: MetricsOutputsByStaff :many
-- R_OUTPUT：按完成人（authors 含该 user_id）在周期内、按 output_type 分组的成果数 + 证据。
-- BY_LEVEL 计分在 Go 端用 levelMap 乘各组 cnt；COUNT 法对全部 cnt 求和。
SELECT o.output_type,
       count(*)::int AS cnt,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','R_OUTPUT','objectId',o.id,'code',o.code,'value',1)),'[]'::jsonb) AS evidence
FROM r_output o
WHERE o.tenant_id = $1
  AND o.deleted = 0
  AND (sqlc.narg('from_date')::date IS NULL OR o.publish_date >= sqlc.narg('from_date')::date)
  AND (sqlc.narg('to_date')::date IS NULL OR o.publish_date <= sqlc.narg('to_date')::date)
  AND o.authors @> jsonb_build_array(jsonb_build_object('user_id', $2::bigint))
GROUP BY o.output_type;

-- name: MetricsIncomeByStaff :one
-- F_INCOME：该 staff 作为 PI 的项目（经 e_project 关联）在周期内的到账金额求和 + 证据。
SELECT COALESCE(sum(fi.amount),0)::numeric(18,4)::text AS metric,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','F_INCOME','objectId',fi.id,'value',fi.amount)),'[]'::jsonb) AS evidence
FROM f_income fi
JOIN e_project ep ON ep.id = fi.project_id
WHERE fi.tenant_id = $1
  AND ep.tenant_id = $1
  AND ep.pi_user_id = $2::bigint
  AND fi.status = 'ACTIVE'
  AND (sqlc.narg('from_date')::date IS NULL OR fi.receipt_date >= sqlc.narg('from_date')::date)
  AND (sqlc.narg('to_date')::date IS NULL OR fi.receipt_date <= sqlc.narg('to_date')::date);

-- name: MetricsProjectsByStaff :many
-- E_PROJECT：该 staff 作为 PI 在周期内立项的项目，按 project_type 分组计数 + 预算求和 + 证据。
SELECT ep.project_type,
       count(*)::int AS cnt,
       COALESCE(sum(ep.total_budget),0)::numeric(18,4)::text AS amount,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','E_PROJECT','objectId',ep.id,'value',ep.total_budget)),'[]'::jsonb) AS evidence
FROM e_project ep
WHERE ep.tenant_id = $1
  AND ep.deleted = 0
  AND ep.pi_user_id = $2::bigint
  AND (sqlc.narg('from_date')::date IS NULL OR ep.start_date >= sqlc.narg('from_date')::date)
  AND (sqlc.narg('to_date')::date IS NULL OR ep.start_date <= sqlc.narg('to_date')::date)
GROUP BY ep.project_type;

-- name: MetricsTransferByStaff :one
-- T_DEAL：该 staff 作为成果完成人的转化合同，在周期内签约金额求和 + 证据。
SELECT COALESCE(sum(td.contract_amount),0)::numeric(18,4)::text AS metric,
       COALESCE(jsonb_agg(jsonb_build_object('objectType','T_DEAL','objectId',td.id,'value',td.contract_amount)),'[]'::jsonb) AS evidence
FROM t_deal td
JOIN r_output o ON o.id = td.output_id
WHERE td.tenant_id = $1
  AND o.deleted = 0
  AND o.authors @> jsonb_build_array(jsonb_build_object('user_id', $2::bigint))
  AND (sqlc.narg('from_date')::date IS NULL OR td.signed_at::date >= sqlc.narg('from_date')::date)
  AND (sqlc.narg('to_date')::date IS NULL OR td.signed_at::date <= sqlc.narg('to_date')::date);

-- name: ListCalcStaff :many
-- calculate 取数轴：确定要计算的人员集合。默认取在研项目 PI（distinct）；dept_ids 非空则限定部门范围。
-- staff_ids 由 handler 直接给定（不走此查询），二者互斥。
SELECT DISTINCT ep.pi_user_id AS staff_user_id, ep.department_id AS dept_id
FROM e_project ep
WHERE ep.tenant_id = $1
  AND ep.deleted = 0
  AND (sqlc.narg('dept_ids')::bigint[] IS NULL OR ep.department_id = ANY(sqlc.narg('dept_ids')::bigint[]));
