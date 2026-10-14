-- E 域种子：3 条 tenant=1（pi_user_id=1001，覆盖 EXECUTING/PLANNING/COMPLETED 三态），
-- 1 条 tenant=2 演示跨租户隔离，1 条 tenant=1 且 deleted=1。application_id 是逻辑外键
-- （无物理约束），此处填占位值 0，不依赖 seed_p.sql。
--
-- 子资源（task/milestone/mid_check）挂在标题为 'A 项目-执行中' 的项目上，便于集成用例
-- 用 LIKE 反查 project_id 后校验 tasks/milestones/mid-check 计数与状态。

INSERT INTO E_PROJECT
  (tenant_id, status, creator_id, application_id, title, project_type, pi_user_id,
   member_ids, legal_entity_id, start_date, end_date, total_budget, health_score,
   risk_level, security_level)
VALUES
  (1,'EXECUTING',1001,0,'A 项目-执行中','NSFC',1001,'[1002,1003]'::jsonb,1,
     CURRENT_DATE - INTERVAL '60 day', CURRENT_DATE + INTERVAL '120 day','1000000.00',82,'LOW','INTERNAL'),
  (1,'PLANNING', 1001,0,'B 项目-筹备中','NSFC',1001,'[]'::jsonb,1,
     CURRENT_DATE + INTERVAL '30 day', CURRENT_DATE + INTERVAL '300 day','500000.00',70,'MEDIUM','INTERNAL'),
  (1,'COMPLETED',1001,0,'C 项目-已结题','PROVINCIAL',1001,'[]'::jsonb,1,
     CURRENT_DATE - INTERVAL '400 day', CURRENT_DATE - INTERVAL '30 day','200000.00',95,'LOW','PUBLIC'),
  (2,'EXECUTING',1002,0,'D 项目-别租户','NSFC',1002,'[]'::jsonb,2,
     CURRENT_DATE - INTERVAL '10 day', CURRENT_DATE + INTERVAL '90 day','800000.00',75,'LOW','INTERNAL'),
  (1,'EXECUTING',1001,0,'E 项目-软删','NSFC',1001,'[]'::jsonb,1,
     CURRENT_DATE, CURRENT_DATE,'100.00',50,'HIGH','INTERNAL');
UPDATE E_PROJECT SET deleted=1 WHERE title='E 项目-软删';

-- 给 A 项目挂 2 条任务 + 2 个里程碑（甘特视图 + ListTasks 集成用）
INSERT INTO E_TASK
  (tenant_id, status, creator_id, project_id, parent_task_id, name, owner_user_id,
   planned_start, planned_end, actual_start, actual_end, progress_percent, weight)
SELECT 1,'IN_PROGRESS',1001, id, NULL, 'T1 需求分析', 1001,
       CURRENT_DATE - INTERVAL '50 day', CURRENT_DATE + INTERVAL '10 day',
       CURRENT_DATE - INTERVAL '50 day', NULL, 60, '0.40'
  FROM E_PROJECT WHERE title='A 项目-执行中'
UNION ALL
SELECT 1,'PENDING',    1001, id, NULL, 'T2 系统设计', 1002,
       CURRENT_DATE, CURRENT_DATE + INTERVAL '40 day',
       NULL, NULL, 0, '0.60'
  FROM E_PROJECT WHERE title='A 项目-执行中';

INSERT INTO E_MILESTONE
  (tenant_id, status, creator_id, project_id, name, due_date, owner_user_id, weight)
SELECT 1,'PENDING',1001, id, 'M1 需求评审通过', CURRENT_DATE + INTERVAL '15 day', 1001, '0.30'
  FROM E_PROJECT WHERE title='A 项目-执行中'
UNION ALL
SELECT 1,'PENDING',1001, id, 'M2 系统交付',     CURRENT_DATE + INTERVAL '60 day', 1002, '0.70'
  FROM E_PROJECT WHERE title='A 项目-执行中';

-- 给 A 项目挂 1 条 PENDING 中检（供 N 集成测试的 writeback 起点）
INSERT INTO E_MID_CHECK
  (tenant_id, status, creator_id, project_id, check_round, check_date)
SELECT 1,'PENDING',1001, id, 1, CURRENT_DATE
  FROM E_PROJECT WHERE title='A 项目-执行中';
