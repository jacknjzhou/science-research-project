-- 000002_seed_auth.up.sql · 手写种子（不参与 go generate）。依赖 000001 已建 sys_role/sys_user/sys_user_role。
-- 演示口令（均为实测 bcrypt cost=10 哈希）：
--   admin/Admin@123456  manager/Manager@123456  staff/Staff@123456  finance/Finance@123456
-- 注意：内置 dev 账号 ark/ark 仅在 pool==nil 的开发回退路径生效（任务7），不在此入库。

-- 1) 8 基础角色（PRD 2.1，租户 1）
INSERT INTO sys_role (code, name, is_builtin, tenant_id) VALUES
  ('R-STAFF',   '科研人员',     TRUE, 1),
  ('R-MANAGER', '科研管理岗',   TRUE, 1),
  ('R-LEADER',  '单位领导',     TRUE, 1),
  ('R-FINANCE', '财务',         TRUE, 1),
  ('R-AUDITOR', '审计',         TRUE, 1),
  ('R-EXPERT',  '评审专家',     TRUE, 1),
  ('R-ETHICS',  '伦理委员会',   TRUE, 1),
  ('R-ADMIN',   '系统管理员',   TRUE, 1);

-- 2) 4 演示用户（租户 1，creator_id=1 自指；sys_role/sys_user 建表后 identity 首值即 1）
INSERT INTO sys_user (username, real_name, email, staff_no, employment_status, security_level, status, password_hash, tenant_id, creator_id) VALUES
  ('admin',   '系统管理员', 'admin@eplugger.com',   'A0001', 'ONBOARD', 'TOP_SECRET', 'ACTIVE', '$2a$10$a1Cu2YSk60mLMlTC7Mq5t.DzD7Suj.jUkigRj1YNdKFRLPb61XTR2', 1, 1),
  ('manager', '科研管理岗', 'manager@eplugger.com', 'A0002', 'ONBOARD', 'SECRET',     'ACTIVE', '$2a$10$kbJo5wGylj7x4r.kb60cM.Ndxu87QO3zu763TZz8aI1nb2SVen5C2', 1, 1),
  ('staff',   '一线研究员', 'staff@eplugger.com',   'A0003', 'ONBOARD', 'INTERNAL',   'ACTIVE', '$2a$10$CsWOrEdaLYnaq5.YV6/Lu.8HMpDv3XJMyd5vPHvtEbD5fpfuZDPiC', 1, 1),
  ('finance', '财务专员',   'finance@eplugger.com', 'A0004', 'ONBOARD', 'SECRET',     'ACTIVE', '$2a$10$bSMrXkIOn.GH5aCTUG8ceeucmaNH2zz6wiTbqQLjdqkdp9VMWdIqm', 1, 1);

-- 3) 用户—角色绑定（用 code/username 子查询定位，避免依赖 identity 具体值）
INSERT INTO sys_user_role (user_id, role_id, tenant_id)
SELECT u.id, r.id, 1 FROM sys_user u, sys_role r
WHERE u.tenant_id=1 AND r.tenant_id=1 AND (
     (u.username='admin'   AND r.code='R-ADMIN')
  OR (u.username='manager' AND r.code IN ('R-MANAGER','R-LEADER'))
  OR (u.username='staff'   AND r.code='R-STAFF')
  OR (u.username='finance' AND r.code='R-FINANCE')
);
