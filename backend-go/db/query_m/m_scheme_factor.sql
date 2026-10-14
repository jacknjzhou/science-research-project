-- name: ListFactors :many
SELECT * FROM m_scheme_factor
WHERE scheme_id = $1
ORDER BY sort_no ASC, id ASC;

-- name: UpsertFactor :one
INSERT INTO m_scheme_factor (scheme_id, tenant_id, creator_id, factor_code, factor_name,
                             weight, scoring_rule, max_score, data_source, clause_ref, sort_no)
VALUES ($1, $2, $3, $4, $5, COALESCE($6::numeric,0), COALESCE($7::jsonb,'{}'::jsonb),
        $8, $9, $10, COALESCE($11::int,0))
ON CONFLICT (scheme_id, factor_code) DO UPDATE SET
  factor_name  = EXCLUDED.factor_name,
  weight       = EXCLUDED.weight,
  scoring_rule = EXCLUDED.scoring_rule,
  max_score    = EXCLUDED.max_score,
  data_source  = EXCLUDED.data_source,
  clause_ref   = EXCLUDED.clause_ref,
  sort_no      = EXCLUDED.sort_no,
  updated_at   = now()
RETURNING *;

-- name: UpdateFactor :one
UPDATE m_scheme_factor SET
  factor_name  = COALESCE($4::text, factor_name),
  weight       = COALESCE($5::numeric, weight),
  scoring_rule = COALESCE($6::jsonb, scoring_rule),
  max_score    = COALESCE($7::numeric, max_score),
  data_source  = COALESCE($8::text, data_source),
  clause_ref   = COALESCE($9::text, clause_ref),
  sort_no      = COALESCE($10::int, sort_no),
  updated_at   = now()
WHERE id = $1 AND scheme_id = $2 AND tenant_id = $3
RETURNING *;

-- name: DeleteFactor :execrows
DELETE FROM m_scheme_factor WHERE id = $1 AND scheme_id = $2 AND tenant_id = $3;

-- name: ListFactorsBySchemeForCalc :many
-- calculate 用：取某方案全部因子（含 scoring_rule）。SELECT * → []SchemeFactor（weight/max_score 为 pgtype.Numeric）。
SELECT * FROM m_scheme_factor
WHERE scheme_id = $1 AND tenant_id = $2
ORDER BY sort_no ASC, id ASC;
