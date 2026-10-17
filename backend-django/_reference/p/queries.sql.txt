-- P-02 申报指南仓储。deleted=0 软删过滤 + tenant 隔离；keyword 走 title/code ILIKE。
-- total_envelope 保持原生 pgtype.Numeric 出参（::text cast 会被 sqlc 视为非空 string，
-- NULL 行扫描炸裂；列级 override 又不作用于 row 字段），mapper 层格式化为契约 string。

-- name: ListGuidelines :many
SELECT id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, title, project_type, funding_source,
       target_disciplines, apply_start_at, apply_end_at,
       total_envelope, content_rich, attachment_ids, publish_at
FROM p_guideline
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text)
  AND (sqlc.narg('keyword')::text IS NULL
       OR title ILIKE '%' || sqlc.narg('keyword')::text || '%'
       OR COALESCE(code, '') ILIKE '%' || sqlc.narg('keyword')::text || '%')
ORDER BY (apply_end_at IS NULL), apply_end_at ASC NULLS LAST, id DESC
LIMIT @limit_ OFFSET @offset_;

-- name: CountGuidelines :one
SELECT count(*)::int AS n
FROM p_guideline
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('project_type')::text IS NULL OR project_type = sqlc.narg('project_type')::text)
  AND (sqlc.narg('keyword')::text IS NULL
       OR title ILIKE '%' || sqlc.narg('keyword')::text || '%'
       OR COALESCE(code, '') ILIKE '%' || sqlc.narg('keyword')::text || '%');

-- name: GetGuideline :one
SELECT id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, title, project_type, funding_source,
       target_disciplines, apply_start_at, apply_end_at,
       total_envelope, content_rich, attachment_ids, publish_at
FROM p_guideline
WHERE id = $1 AND deleted = 0
LIMIT 1;

-- name: UpsertGuideline :one
-- 按 (tenant_id, code) upsert（uk_p_guideline_code 为 deleted=0 部分唯一索引，
-- ON CONFLICT 必须带同款 WHERE 谓词）。publish_at 由 Go 侧传参（首次置 PUBLISHED 时 now()），
-- 避免 $status 在 VALUES/CASE 双处使用导致 PG 参数类型推断冲突（SQLSTATE 42P08）。
INSERT INTO p_guideline (
  tenant_id, code, status, creator_id, modifier_id, remark, title, project_type,
  funding_source, target_disciplines, apply_start_at, apply_end_at,
  total_envelope, content_rich, attachment_ids, publish_at
) VALUES (
  @tenant_id, @code, @status, @creator_id, @modifier_id, @remark, @title, @project_type,
  @funding_source, sqlc.arg('target_disciplines')::jsonb, sqlc.narg('apply_start_at')::timestamptz,
  sqlc.narg('apply_end_at')::timestamptz, sqlc.narg('total_envelope')::numeric, @content_rich,
  sqlc.arg('attachment_ids')::jsonb, sqlc.narg('publish_at')::timestamptz
)
ON CONFLICT (tenant_id, code) WHERE deleted = 0 DO UPDATE SET
  status            = EXCLUDED.status,
  modifier_id       = EXCLUDED.modifier_id,
  remark            = EXCLUDED.remark,
  title             = EXCLUDED.title,
  project_type      = EXCLUDED.project_type,
  funding_source    = EXCLUDED.funding_source,
  target_disciplines = EXCLUDED.target_disciplines,
  apply_start_at    = EXCLUDED.apply_start_at,
  apply_end_at      = EXCLUDED.apply_end_at,
  total_envelope    = EXCLUDED.total_envelope,
  content_rich      = EXCLUDED.content_rich,
  attachment_ids    = EXCLUDED.attachment_ids,
  publish_at        = CASE WHEN EXCLUDED.status = 'PUBLISHED' AND p_guideline.publish_at IS NULL
                           THEN now() ELSE p_guideline.publish_at END,
  updated_at        = now()
RETURNING id, code, tenant_id, status, deleted, creator_id, modifier_id,
       created_at, updated_at, remark, title, project_type, funding_source,
       target_disciplines, apply_start_at, apply_end_at,
       total_envelope, content_rich, attachment_ids, publish_at;
