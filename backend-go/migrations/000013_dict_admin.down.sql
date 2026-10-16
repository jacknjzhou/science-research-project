-- 000013_dict_admin.down.sql · 回滚字典管理改造
DELETE FROM sys_dict_item WHERE dict_id IN (
  SELECT id FROM sys_dict WHERE code IN ('project_type','output_source','activity_type','activity_level','pay_method')
);
DELETE FROM sys_dict WHERE code IN ('project_type','output_source','activity_type','activity_level','pay_method');
DROP INDEX IF EXISTS uk_dict_code;
CREATE UNIQUE INDEX IF NOT EXISTS uk_dict_code ON sys_dict(tenant_id, code);
ALTER TABLE sys_dict
  DROP COLUMN IF EXISTS deleted,
  DROP COLUMN IF EXISTS creator_id,
  DROP COLUMN IF EXISTS modifier_id;
