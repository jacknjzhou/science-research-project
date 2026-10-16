-- 000015_funding_config_page.down.sql
DELETE FROM sys_page_grant WHERE tenant_id = 1 AND page_name = 'funding-config';
