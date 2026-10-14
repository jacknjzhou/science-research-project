-- R 域成果主表查询。列名/枚举以 design/04-科研成果管理-R.ddl.sql → migrations R_OUTPUT 段为准。
-- 可选过滤铁律：一律 sqlc.narg('x')::type IS NULL OR col = sqlc.narg('x')::type（生成可空 ColumnN）。

-- name: ListOutputs :many
-- DDL 校正：契约 listOutputs 支持 output_type/year/project_id/source/claim_status/keyword 过滤；
-- project_id 走兼容 JSONB 视图 R_OUTPUT.project_ids（规范化主存见 R_OUTPUT_PROJECT，本轮读用镜像列，
-- 成本最低且不引入跨表 JOIN）；year 用 publish_date 年份；kw 映射到 title ILIKE（对齐 DDL GIN trigram 索引）。
SELECT * FROM R_OUTPUT
WHERE deleted = 0
  AND (sqlc.narg('output_type')::text IS NULL OR output_type = sqlc.narg('output_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('claim_status')::text IS NULL OR claim_status = sqlc.narg('claim_status')::text)
  AND (sqlc.narg('source')::text IS NULL OR source = sqlc.narg('source')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'))
  AND (sqlc.narg('year')::int IS NULL OR EXTRACT(YEAR FROM publish_date)::int = sqlc.narg('year')::int)
  AND (sqlc.narg('department_id')::bigint IS NULL OR department_id = sqlc.narg('department_id')::bigint)
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_ids @> jsonb_build_array(sqlc.narg('project_id')::bigint))
ORDER BY updated_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountOutputs :one
SELECT count(*) FROM R_OUTPUT
WHERE deleted = 0
  AND (sqlc.narg('output_type')::text IS NULL OR output_type = sqlc.narg('output_type')::text)
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('claim_status')::text IS NULL OR claim_status = sqlc.narg('claim_status')::text)
  AND (sqlc.narg('source')::text IS NULL OR source = sqlc.narg('source')::text)
  AND (sqlc.narg('kw')::text IS NULL OR title ILIKE ('%'||sqlc.narg('kw')::text||'%'))
  AND (sqlc.narg('year')::int IS NULL OR EXTRACT(YEAR FROM publish_date)::int = sqlc.narg('year')::int)
  AND (sqlc.narg('department_id')::bigint IS NULL OR department_id = sqlc.narg('department_id')::bigint)
  AND (sqlc.narg('project_id')::bigint IS NULL OR project_ids @> jsonb_build_array(sqlc.narg('project_id')::bigint));

-- name: GetOutput :one
SELECT * FROM R_OUTPUT WHERE id = $1 AND deleted = 0;

-- name: ListMyOutputs :many
-- 我的成果：命中 authors.user_id = 本人（GIN 索引 authors jsonb_path_ops 支持 @>）。
SELECT * FROM R_OUTPUT
WHERE deleted = 0
  AND authors @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('user_id')::bigint))
  AND (sqlc.narg('output_type')::text IS NULL OR output_type = sqlc.narg('output_type')::text)
  AND (sqlc.narg('year')::int IS NULL OR EXTRACT(YEAR FROM publish_date)::int = sqlc.narg('year')::int)
ORDER BY updated_at DESC
LIMIT sqlc.arg('limit_')::int OFFSET sqlc.arg('offset_')::int;

-- name: CountMyOutputs :one
SELECT count(*) FROM R_OUTPUT
WHERE deleted = 0
  AND authors @> jsonb_build_array(jsonb_build_object('user_id', sqlc.arg('user_id')::bigint))
  AND (sqlc.narg('output_type')::text IS NULL OR output_type = sqlc.narg('output_type')::text)
  AND (sqlc.narg('year')::int IS NULL OR EXTRACT(YEAR FROM publish_date)::int = sqlc.narg('year')::int);

-- name: CreateOutput :one
-- DDL 校正：计划正文 CreateOutput 未写 legal_entity_id（NOT NULL 无默认，必须显式供值，来自 auth Domain）。
-- 初值：计划写 status/claim_status='CLAIMED'，但契约 createOutput 描述「落 MANUAL_DRAFT，经审核后进入 CLAIMED」，
-- 故生命周期 status 取 DDL 枚举 MANUAL_DRAFT，认领维度 claim_status 取 CLAIMED + is_claimed=TRUE（手工录入即作者本人认领）。
-- title_hash 为去重键（规范化标题哈希），由 handler 侧计算后传入（SQL 内不做哈希函数）。
INSERT INTO R_OUTPUT
  (code, tenant_id, status, claim_status, creator_id, output_type, title, title_en, abstract,
   publish_date, authors, external_author_names, affiliations, language, source, is_claimed,
   title_hash, department_id, legal_entity_id, security_level, remark)
VALUES
  (sqlc.arg('code')::text, sqlc.arg('tenant_id')::bigint, 'MANUAL_DRAFT', 'CLAIMED',
   sqlc.arg('creator_id')::bigint, sqlc.arg('output_type')::text, sqlc.arg('title')::text,
   sqlc.narg('title_en')::text, sqlc.narg('abstract')::text, sqlc.narg('publish_date')::date,
   COALESCE(sqlc.narg('authors')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('external_author_names')::jsonb,'[]'::jsonb),
   COALESCE(sqlc.narg('affiliations')::jsonb,'[]'::jsonb),
   sqlc.narg('language')::text, sqlc.arg('source')::text, TRUE,
   sqlc.narg('title_hash')::text, sqlc.narg('department_id')::bigint,
   sqlc.arg('legal_entity_id')::bigint,
   COALESCE(sqlc.narg('security_level')::text,'INTERNAL'), sqlc.narg('remark')::text)
RETURNING *;

-- name: SetOutputStatus :execrows
-- linkProjects 用：CLAIMED → ASSIGNED_TO_PROJECT 的通用状态位推进（幂等，仅未删记录）。
UPDATE R_OUTPUT SET status = sqlc.arg('status')::text, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;

-- name: ConcludeOutputEval :execrows
-- 供 N 域成果评价回写（单一写者：R 拥有 R_OUTPUT.status 写权）。目标 status token 由 Go 侧按 pass 选枚举合法值。
UPDATE R_OUTPUT SET status = sqlc.arg('status')::text, is_claimed = sqlc.arg('is_claimed')::bool, updated_at = now()
WHERE id = sqlc.arg('id')::bigint AND deleted = 0;
