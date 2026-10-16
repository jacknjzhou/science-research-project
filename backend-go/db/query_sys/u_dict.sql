-- U 域 · 数据字典仓储（PRD 2.8：R-ADMIN 维护，业务下拉统一数据源）。
-- sys_dict 软删（deleted=0 过滤）；sys_dict_item 硬删（叶子才可删）。
-- uk_dict_item 为 (dict_id, item_code, COALESCE(effective_from, DATE '1970-01-01'))
-- 部分唯一索引——upsert 的 ON CONFLICT 目标必须逐字一致。

-- name: ListDicts :many
SELECT id, code, name, tenant_id, remark, creator_id, modifier_id, created_at, updated_at
FROM sys_dict
WHERE deleted = 0 AND tenant_id = @tenant_id
  AND (sqlc.narg('keyword')::text IS NULL
       OR code ILIKE '%' || sqlc.narg('keyword')::text || '%'
       OR name ILIKE '%' || sqlc.narg('keyword')::text || '%')
ORDER BY id
LIMIT sqlc.arg('limit_')::bigint OFFSET sqlc.arg('offset_')::bigint;

-- name: CountDicts :one
SELECT count(*) FROM sys_dict
WHERE deleted = 0 AND tenant_id = @tenant_id
  AND (sqlc.narg('keyword')::text IS NULL
       OR code ILIKE '%' || sqlc.narg('keyword')::text || '%'
       OR name ILIKE '%' || sqlc.narg('keyword')::text || '%');

-- name: GetDict :one
SELECT id, code, name, tenant_id, remark, creator_id, modifier_id, created_at, updated_at
FROM sys_dict WHERE id = @id AND tenant_id = @tenant_id AND deleted = 0;

-- name: GetDictByCode :one
SELECT id, code, name, tenant_id, remark, creator_id, modifier_id, created_at, updated_at
FROM sys_dict WHERE tenant_id = @tenant_id AND code = @code AND deleted = 0;

-- name: UpsertDict :one
-- 按 (tenant_id, code) upsert（部分唯一索引 deleted=0；软删后同 code 可重建）。
INSERT INTO sys_dict (tenant_id, code, name, remark, creator_id, modifier_id)
VALUES (@tenant_id, @code, @name, sqlc.narg('remark'), sqlc.narg('actor_id'), sqlc.narg('actor_id'))
ON CONFLICT (tenant_id, code) WHERE deleted = 0 DO UPDATE SET
  name        = EXCLUDED.name,
  remark      = EXCLUDED.remark,
  modifier_id = EXCLUDED.modifier_id,
  updated_at  = now()
RETURNING id, code, name, tenant_id, remark, creator_id, modifier_id, created_at, updated_at;

-- name: SoftDeleteDict :execrows
UPDATE sys_dict SET deleted = 1, modifier_id = sqlc.narg('actor_id'), updated_at = now()
WHERE id = @id AND tenant_id = @tenant_id AND deleted = 0;

-- name: ListDictItems :many
-- 管理端：全部条目（含停用、含未生效），sort_no,id 升序。
SELECT id, dict_id, item_code, item_label, parent_id, ext_json, sort_no,
       i18n_json, effective_from, effective_to, active, tenant_id
FROM sys_dict_item
WHERE dict_id = @dict_id AND tenant_id = @tenant_id
ORDER BY sort_no, id;

-- name: ListActiveDictItems :many
-- 全员公开读取：active=1 且在生效期内。
SELECT id, dict_id, item_code, item_label, parent_id, ext_json, sort_no,
       i18n_json, effective_from, effective_to, active, tenant_id
FROM sys_dict_item
WHERE dict_id = @dict_id AND tenant_id = @tenant_id AND active = TRUE
  AND (effective_from IS NULL OR effective_from <= CURRENT_DATE)
  AND (effective_to   IS NULL OR effective_to   >= CURRENT_DATE)
ORDER BY sort_no, id;

-- name: GetDictItem :one
SELECT id, dict_id, item_code, item_label, parent_id, ext_json, sort_no,
       i18n_json, effective_from, effective_to, active, tenant_id
FROM sys_dict_item WHERE id = @id AND dict_id = @dict_id AND tenant_id = @tenant_id;

-- name: UpsertDictItem :one
-- 按 (dict_id, item_code, 生效期) upsert：同码不同生效期 = 历史版本并存（PRD 字典语义）。
INSERT INTO sys_dict_item (dict_id, item_code, item_label, parent_id, ext_json, sort_no,
                           i18n_json, effective_from, effective_to, active, tenant_id)
VALUES (@dict_id, @item_code, @item_label, sqlc.narg('parent_id'), sqlc.narg('ext_json')::jsonb,
        @sort_no, sqlc.narg('i18n_json')::jsonb, sqlc.narg('effective_from')::date,
        sqlc.narg('effective_to')::date, @active, @tenant_id)
ON CONFLICT (dict_id, item_code, COALESCE(effective_from, DATE '1970-01-01')) DO UPDATE SET
  item_label     = EXCLUDED.item_label,
  parent_id      = EXCLUDED.parent_id,
  ext_json       = EXCLUDED.ext_json,
  i18n_json      = EXCLUDED.i18n_json,
  sort_no        = EXCLUDED.sort_no,
  effective_to   = EXCLUDED.effective_to,
  active         = EXCLUDED.active
RETURNING id, dict_id, item_code, item_label, parent_id, ext_json, sort_no,
          i18n_json, effective_from, effective_to, active, tenant_id;

-- name: DeleteDictItem :execrows
DELETE FROM sys_dict_item WHERE id = @id AND dict_id = @dict_id AND tenant_id = @tenant_id;
