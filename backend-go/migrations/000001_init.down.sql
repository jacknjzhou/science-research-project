-- 回滚：清空 public schema 中由本次迁移创建的表。
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
