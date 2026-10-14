-- 2 行 tenant=1 正常（A 为 DRAFT 供状态机流转测试），1 行 tenant=2，1 行 tenant=1 且 deleted=1
INSERT INTO v_activity
  (tenant_id, status, creator_id, title, activity_type, level, host_mode,
   organizer_dept_id, start_at, end_at, venue, budget_amount)
VALUES
  (1,'DRAFT',    1001,'A 量子计算专题报告','LECTURE','NATIONAL',   'HOST',  5001, now()+interval '7 day', now()+interval '7 day' + interval '2 hour','主楼报告厅','5000.00'),
  (1,'SUBMITTED',1001,'B 交叉学科研讨会',  'SEMINAR','PROVINCIAL', 'HOST',  5001, now()+interval '14 day',now()+interval '14 day'+ interval '6 hour','国际会议中心','20000.00'),
  (2,'DRAFT',    1002,'C 院内学术讲座',    'LECTURE','CAMPUS',     'ATTEND',5002, now()+interval '3 day', now()+interval '3 day' + interval '1 hour','三楼会议室','0.00'),
  (1,'DRAFT',    1001,'D 已撤销活动',      'OTHER',  'CAMPUS',     'HOST',  5001, now()+interval '1 day', now()+interval '1 day',              '临时','0.00');
UPDATE v_activity SET deleted=1 WHERE title='D 已撤销活动';

-- 给 A 活动挂 2 名参与人（演示 participants 子资源；user_id 逻辑外键）
INSERT INTO v_activity_participant (tenant_id, activity_id, user_id, role)
SELECT 1, id, 2001, 'SPEAKER' FROM v_activity WHERE title='A 量子计算专题报告'
UNION ALL
SELECT 1, id, 2002, 'MEMBER'  FROM v_activity WHERE title='A 量子计算专题报告';
