-- 000002_seed_auth.down.sql · 撤销种子（逆 FK 依赖顺序）。000001.down 的 DROP SCHEMA CASCADE 亦会整体清空，此处仅做局部可回退。
DELETE FROM sys_user_role WHERE tenant_id = 1;
DELETE FROM sys_user      WHERE tenant_id = 1 AND username IN ('admin','manager','staff','finance');
DELETE FROM sys_role      WHERE tenant_id = 1 AND code IN
  ('R-STAFF','R-MANAGER','R-LEADER','R-FINANCE','R-AUDITOR','R-EXPERT','R-ETHICS','R-ADMIN');
