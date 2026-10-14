-- name: ListRecords :many
SELECT * FROM m_record
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('scheme_id')::bigint     IS NULL OR scheme_id = sqlc.narg('scheme_id')::bigint)
  AND (sqlc.narg('period')::text          IS NULL OR period = sqlc.narg('period')::text)
  AND (sqlc.narg('dept_id')::bigint       IS NULL OR dept_id = sqlc.narg('dept_id')::bigint)
  AND (sqlc.narg('staff_user_id')::bigint IS NULL OR staff_user_id = sqlc.narg('staff_user_id')::bigint)
  AND (sqlc.narg('status')::text          IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('code')::text            IS NULL OR code ILIKE sqlc.narg('code')::text)
ORDER BY total_score DESC NULLS LAST, id DESC
LIMIT $3 OFFSET $2;

-- name: CountRecords :one
SELECT count(*)::int AS n
FROM m_record
WHERE deleted = 0
  AND tenant_id = $1
  AND (sqlc.narg('scheme_id')::bigint     IS NULL OR scheme_id = sqlc.narg('scheme_id')::bigint)
  AND (sqlc.narg('period')::text          IS NULL OR period = sqlc.narg('period')::text)
  AND (sqlc.narg('dept_id')::bigint       IS NULL OR dept_id = sqlc.narg('dept_id')::bigint)
  AND (sqlc.narg('staff_user_id')::bigint IS NULL OR staff_user_id = sqlc.narg('staff_user_id')::bigint)
  AND (sqlc.narg('status')::text          IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('code')::text            IS NULL OR code ILIKE sqlc.narg('code')::text);

-- name: GetRecord :one
SELECT * FROM m_record
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: UpsertRecord :one
-- calculate 幂等：同 (scheme,staff,period WHERE deleted=0) 覆盖重算（M0 直接覆盖，含已确认态；生产可加 status 谓词）。
INSERT INTO m_record (tenant_id, creator_id, status, scheme_id, staff_user_id, period, dept_id,
                      total_score, calc_detail, calc_batch, calc_at, security_level)
VALUES ($1, $2, 'CALCULATED', $3, $4, $5, $6, $7::numeric, $8::jsonb, $9, now(), COALESCE($10::text,'INTERNAL'))
ON CONFLICT (scheme_id, staff_user_id, period) WHERE deleted = 0 DO UPDATE SET
  total_score = EXCLUDED.total_score,
  calc_detail = EXCLUDED.calc_detail,
  calc_batch  = EXCLUDED.calc_batch,
  calc_at     = now(),
  dept_id     = EXCLUDED.dept_id,
  status      = 'CALCULATED',
  modifier_id = EXCLUDED.creator_id,
  updated_at  = now()
RETURNING *;

-- name: DeleteItemsByRecord :exec
DELETE FROM m_record_item WHERE record_id = $1;

-- name: InsertItem :one
INSERT INTO m_record_item (record_id, tenant_id, factor_code, metric_value, raw_score, weighted_score, evidence)
VALUES ($1, $2, $3, $4::numeric, $5::numeric, $6::numeric, COALESCE($7::jsonb,'[]'::jsonb))
ON CONFLICT (record_id, factor_code) DO UPDATE SET
  metric_value = EXCLUDED.metric_value,
  raw_score    = EXCLUDED.raw_score,
  weighted_score = EXCLUDED.weighted_score,
  evidence     = EXCLUDED.evidence
RETURNING *;

-- name: ListItems :many
SELECT * FROM m_record_item
WHERE record_id = $1
ORDER BY id ASC;

-- name: ConfirmRecord :one
UPDATE m_record SET status='CONFIRMED', confirmed_by=$3, confirmed_at=now(), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='CALCULATED'
RETURNING *;

-- name: AppealRecord :one
UPDATE m_record SET status='APPEAL', appeal_reason=$4, modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status IN ('CALCULATED','CONFIRMED')
RETURNING *;

-- name: ApproveRecord :one
UPDATE m_record SET status='APPROVED', approve_by=$3, approve_at=now(), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='CONFIRMED'
RETURNING *;

-- name: VoidRecord :one
UPDATE m_record SET status='VOID', void_reason=COALESCE($4, void_reason), modifier_id=$3, updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status <> 'PAID'
RETURNING *;

-- name: MarkRecordPaid :one
UPDATE m_record SET status='PAID', updated_at=now()
WHERE id=$1 AND tenant_id=$2 AND deleted=0 AND status='APPROVED'
RETURNING *;

-- name: ListMyRecords :many
-- /perf/me：ABAC 强制 staff_user_id=本人。返回记录，明细由 handler 逐个 ListItems 组装。
SELECT * FROM m_record
WHERE deleted = 0 AND tenant_id = $1 AND staff_user_id = $2
  AND (sqlc.narg('period')::text IS NULL OR period = sqlc.narg('period')::text)
ORDER BY period DESC, id DESC;

-- name: RankedRecords :many
-- /perf/ranking：某方案某周期按总分降序取名次（window row_number）。子查询 SELECT * 保 model 列 + 追加 rn。
SELECT * FROM (
  SELECT *, row_number() OVER (ORDER BY total_score DESC, id ASC) AS rn
  FROM m_record
  WHERE deleted = 0 AND tenant_id = $1 AND scheme_id = $2 AND period = $3
    AND status IN ('CALCULATED','CONFIRMED','APPROVED','PAID')
) r
ORDER BY rn ASC
LIMIT $4;
