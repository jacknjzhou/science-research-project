-- 2 行 tenant=1 正常，1 行 tenant=2，1 行 tenant=1 且 deleted=1
INSERT INTO p_application (tenant_id, status, creator_id, title, project_type, pi_user_id, member_ids, total_budget, is_horizontal)
VALUES
 (1,'DRAFT',1001,'A 项目','NAT',2001,'[]'::jsonb,'1000.00',FALSE),
 (1,'SUBMITTED',1001,'B 项目','NAT',2001,'[]'::jsonb,'2000.00',FALSE),
 (2,'DRAFT',1002,'C 项目','NAT',2002,'[]'::jsonb,'500.00',FALSE),
 (1,'DRAFT',1001,'D 已删','NAT',2001,'[]'::jsonb,'0.00',FALSE);
UPDATE p_application SET deleted=1 WHERE title='D 已删';
