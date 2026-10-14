-- R 域成果—项目关联查询（R-10）。列名以 design/04-科研成果管理-R.ddl.sql R_OUTPUT_PROJECT 段为准。

-- name: LinkProject :exec
-- DDL 校正：R_OUTPUT_PROJECT 含 deleted 列 + 唯一索引 (output_id,project_id) WHERE deleted=0，
-- 故 ON CONFLICT DO NOTHING 命中重复关联静默跳过；relation_type CHECK ∈ (PRIMARY/CONTRIBUTION/CITED) 默认 CONTRIBUTION。
INSERT INTO R_OUTPUT_PROJECT (tenant_id, creator_id, output_id, project_id, relation_type, contribution_pct)
VALUES (sqlc.arg('tenant_id')::bigint, sqlc.arg('creator_id')::bigint,
  sqlc.arg('output_id')::bigint, sqlc.arg('project_id')::bigint,
  COALESCE(sqlc.narg('relation_type')::text,'CONTRIBUTION'), sqlc.narg('contribution_pct')::numeric)
ON CONFLICT DO NOTHING;

-- name: ListOutputProjects :many
SELECT project_id FROM R_OUTPUT_PROJECT WHERE output_id = $1 AND deleted = 0;
