-- N 域专家库查询。可选过滤铁律：sqlc.narg('x')::type IS NULL OR col = sqlc.narg('x')::type（生成可空 ColumnN）。
-- 列名/枚举以 design/15-专家与评审管理-N.ddl.sql → migrations n_expert 段为准（小写）。

-- name: ListExperts :many
SELECT * FROM n_expert WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source')::text IS NULL OR source = sqlc.narg('source')::text)
  AND (sqlc.narg('kw')::text IS NULL OR name ILIKE ('%'||sqlc.narg('kw')::text||'%'))
ORDER BY updated_at DESC LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountExperts :one
SELECT count(*) FROM n_expert WHERE deleted = 0
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('source')::text IS NULL OR source = sqlc.narg('source')::text)
  AND (sqlc.narg('kw')::text IS NULL OR name ILIKE ('%'||sqlc.narg('kw')::text||'%'));

-- name: GetExpert :one
SELECT * FROM n_expert WHERE id = $1 AND deleted = 0;

-- name: ActiveExpertsForDraw :many
SELECT * FROM n_expert WHERE deleted = 0 AND status = 'ACTIVE';

-- name: CreateExpert :one
INSERT INTO n_expert
  (code, tenant_id, status, creator_id, security_level, name, gender, title, education,
   org_name, dept, phone, email, user_id, source, field_tags, expertise_level, avoid_orgs, avoid_person_ids)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, sqlc.arg('status')::text, sqlc.arg('creator_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.arg('name')::text, sqlc.narg('gender')::text,
   sqlc.narg('title')::text, sqlc.narg('education')::text, sqlc.narg('org_name')::text, sqlc.narg('dept')::text,
   sqlc.narg('phone')::text, sqlc.narg('email')::text, sqlc.narg('user_id')::bigint,
   COALESCE(sqlc.narg('source')::text,'EXTERNAL'), COALESCE(sqlc.narg('field_tags')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('expertise_level')::text,'EXPERT'), COALESCE(sqlc.narg('avoid_orgs')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('avoid_person_ids')::jsonb,'[]'::jsonb))
RETURNING *;

-- name: UpdateExpert :execrows
UPDATE n_expert SET name=sqlc.arg('name')::text, title=sqlc.narg('title')::text,
  org_name=sqlc.narg('org_name')::text, field_tags=sqlc.arg('field_tags')::jsonb,
  avoid_orgs=sqlc.arg('avoid_orgs')::jsonb, avoid_person_ids=sqlc.arg('avoid_person_ids')::jsonb,
  modifier_id=sqlc.arg('modifier_id')::bigint, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: SetExpertStatus :execrows
UPDATE n_expert SET status=sqlc.arg('status')::text, updated_at=now()
WHERE id=sqlc.arg('id')::bigint AND deleted=0;

-- name: SoftDeleteExpert :execrows
UPDATE n_expert SET deleted=1, updated_at=now() WHERE id=$1 AND deleted=0;
