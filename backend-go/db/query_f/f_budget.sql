-- F-02/03/04 预算编制 / 批复 / 调整

-- name: CreateBudget :one
INSERT INTO F_BUDGET (tenant_id, status, creator_id, project_id, legal_entity_id, mode, total_approved, total_adjusted)
VALUES ($1, 'DRAFT', $2, $3, $4, $5, $6, 0)
RETURNING *;

-- name: SetBudgetCode :exec
UPDATE F_BUDGET SET code = $2, updated_at = now() WHERE id = $1;

-- name: GetBudget :one
SELECT * FROM F_BUDGET WHERE id = $1 AND deleted = 0;

-- name: ListBudgets :many
SELECT * FROM F_BUDGET
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_id = sqlc.narg('project_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
ORDER BY id DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountBudgets :one
SELECT count(*) FROM F_BUDGET
WHERE deleted = 0 AND tenant_id = sqlc.arg('tenant_id')::bigint
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_id = sqlc.narg('project_id')::bigint)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text);

-- name: SubmitBudget :one
UPDATE F_BUDGET SET status = 'SUBMITTED', updated_at = now()
WHERE id = $1 AND status = 'DRAFT' AND deleted = 0
RETURNING *;

-- name: ApproveBudget :one
UPDATE F_BUDGET SET status = 'EXECUTING', approved_at = now(), approved_by = $2, updated_at = now()
WHERE id = $1 AND status = 'SUBMITTED' AND deleted = 0
RETURNING *;

-- name: AdjustBudget :one
UPDATE F_BUDGET
SET total_adjusted = total_adjusted + $2, version = version + 1, updated_at = now()
WHERE id = $1 AND status = 'EXECUTING' AND deleted = 0
RETURNING *;

-- 预算行
-- name: CreateBudgetLine :one
INSERT INTO F_BUDGET_LINE (tenant_id, status, creator_id, budget_id, subject_id, amount_planned)
VALUES ($1, 'ACTIVE', $2, $3, $4, $5)
RETURNING *;

-- name: ListLinesByBudget :many
SELECT * FROM F_BUDGET_LINE
WHERE budget_id = $1 AND deleted = 0
ORDER BY id;

-- name: GetLine :one
SELECT * FROM F_BUDGET_LINE WHERE id = $1 AND deleted = 0;

-- name: GetLineForUpdate :one
SELECT * FROM F_BUDGET_LINE WHERE id = $1 AND deleted = 0 FOR UPDATE;

-- name: AdjustLine :exec
UPDATE F_BUDGET_LINE SET amount_adjusted = amount_adjusted + $2, updated_at = now()
WHERE id = $1 AND deleted = 0;

-- F-10 冻结 / 实扣 / 解冻（调用方必须在同一事务内先 GetLineForUpdate 校验余额）
-- name: FreezeLine :exec
UPDATE F_BUDGET_LINE SET amount_frozen = amount_frozen + $2, updated_at = now()
WHERE id = $1 AND deleted = 0;

-- name: CommitSpend :exec
UPDATE F_BUDGET_LINE
SET amount_frozen = amount_frozen - $2, amount_used = amount_used + $2, updated_at = now()
WHERE id = $1 AND deleted = 0;

-- name: ReleaseLine :exec
UPDATE F_BUDGET_LINE
SET amount_frozen = amount_frozen - $2, amount_released = amount_released + $2, updated_at = now()
WHERE id = $1 AND deleted = 0;

-- T14 预算追加（F-23）：提交追加申请（pending_delta 累计，行级同步累计）
-- name: AppendBudgetPending :execrows
UPDATE F_BUDGET
SET pending_delta = pending_delta + $2, status = 'ADJUSTING', updated_at = now()
WHERE id = $1 AND deleted = 0 AND status = 'EXECUTING';

-- name: AppendLinePending :execrows
UPDATE F_BUDGET_LINE
SET pending_delta = pending_delta + $2, updated_at = now()
WHERE id = $1 AND deleted = 0;

-- 追加批复：预算/行 pending_delta 并入正式口径，版本 +1
-- name: ApproveBudgetAppend :one
UPDATE F_BUDGET
SET total_approved = total_approved + pending_delta, pending_delta = 0,
    version = version + 1, status = 'EXECUTING', updated_at = now()
WHERE id = $1 AND deleted = 0 AND status = 'ADJUSTING'
RETURNING *;

-- name: ApproveLinesAppend :execrows
UPDATE F_BUDGET_LINE
SET amount_adjusted = amount_adjusted + pending_delta, pending_delta = 0, updated_at = now()
WHERE budget_id = $1 AND pending_delta <> 0 AND deleted = 0;
