-- T16 期刊源库 / 刊物级别 / 转载

-- name: CreateJournalSource :one
INSERT INTO R_JOURNAL_SOURCE (tenant_id, name, issn, year_from, year_to)
VALUES ($1, $2, $3, $4, $5)
RETURNING *;

-- name: ListJournalSources :many
SELECT * FROM R_JOURNAL_SOURCE
WHERE deleted = 0 AND tenant_id = $1
  AND ($2::int IS NULL OR year_from <= $2)
  AND ($3::int IS NULL OR COALESCE(year_to, 9999) >= $3)
ORDER BY name;

-- name: GetJournalSourceByID :one
SELECT * FROM R_JOURNAL_SOURCE WHERE id = $1 AND deleted = 0;

-- name: CreateJournalLevel :one
INSERT INTO R_JOURNAL_LEVEL (tenant_id, code, name, paper_type, indexed)
VALUES ($1, $2, $3, $4, $5)
RETURNING *;

-- name: ListJournalLevels :many
SELECT * FROM R_JOURNAL_LEVEL WHERE deleted = 0 AND tenant_id = $1 ORDER BY code;

-- name: AttachLevelSource :one
INSERT INTO R_JOURNAL_LEVEL_SOURCE (tenant_id, level_id, source_id, year_from, year_to)
VALUES ($1, $2, $3, $4, $5)
RETURNING *;

-- 按期刊名+年度解析级别：源名精确命中 → 年度窗口过滤 → 级别码
-- name: ResolveJournalLevel :many
SELECT jl.code, jl.name
FROM R_JOURNAL_SOURCE js
JOIN R_JOURNAL_LEVEL_SOURCE jls ON jls.source_id = js.id
JOIN R_JOURNAL_LEVEL jl ON jl.id = jls.level_id AND jl.deleted = 0
WHERE js.deleted = 0 AND js.tenant_id = $1 AND js.name = $2
  AND ($3::int IS NULL OR (COALESCE(jls.year_from, 0) <= $3 AND COALESCE(jls.year_to, 9999) >= $3))
ORDER BY jl.id LIMIT 1;

-- name: CreatePaperReprint :one
INSERT INTO R_PAPER_REPRINT (tenant_id, output_id, name, type, reprint_date, remark)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: ListPaperReprints :many
SELECT * FROM R_PAPER_REPRINT
WHERE deleted = 0 AND tenant_id = $1 AND output_id = $2
ORDER BY reprint_date DESC NULLS LAST;

-- name: SetPaperLevelCode :exec
UPDATE R_PAPER_EXT SET level_code = $2 WHERE output_id = $1;
