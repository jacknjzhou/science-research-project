-- 000015_funding_config_page.up.sql · 经费配置页矩阵种子（plan 2026-10-16-funding-config）
-- 新页 funding-config（支出科目树管理 + 预算编制与审批）。
-- 矩阵白名单制：不种即不可见（R-ADMIN 前端硬编码兜底除外），故必须随迁移灌种子。
-- 权限口径：R-MANAGER 写（科目 CRUD / 预算编制提交批复，Casbin 已备）；R-FINANCE 只读（页面可见，写按钮由 auth.can 隐藏）。

INSERT INTO sys_page_grant (tenant_id, page_name, role_code) VALUES
  (1, 'funding-config', 'R-MANAGER'),
  (1, 'funding-config', 'R-FINANCE')
ON CONFLICT (tenant_id, page_name, role_code) DO NOTHING;
