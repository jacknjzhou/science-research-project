-- seed_demo.sql · 演示数据播种（env ARK_SEED_DEMO=1 时由 cmd/server 启动执行；非 migration）
-- 幂等：e_project 已有 DEMO- 前缀项目则整体跳过。租户 1；用户引用按 username 定位（admin=PI 兼岗、manager、staff、finance）。
-- 数据覆盖：法人 ×2 / 项目分类 ×2 / 科目 ×4 / 项目 ×4 / 任务 ×4 / 里程碑 ×3 / 预算+行 / 到账 / 成果 ×5 / 申报计划+申报单 ×2 / 申报指南 ×6。
DO $seed$
DECLARE
  uid_admin   bigint;
  uid_manager bigint;
  uid_staff   bigint;
  uid_finance bigint;
  le1  bigint; le2  bigint;
  cat1 bigint; cat2 bigint;
  s1 bigint; s2 bigint; s3 bigint; s4 bigint;
  p1 bigint; p2 bigint; p3 bigint; p4 bigint;
  b1 bigint; b2 bigint;
  t1 bigint; t2 bigint; t3 bigint;
  ap1 bigint;
BEGIN
  -- 幂等护栏：已播种则跳过
  IF EXISTS (SELECT 1 FROM e_project WHERE code LIKE 'DEMO-%') THEN
    RETURN;
  END IF;

  SELECT id INTO uid_admin   FROM sys_user WHERE username='admin'   AND tenant_id=1;
  SELECT id INTO uid_manager FROM sys_user WHERE username='manager' AND tenant_id=1;
  SELECT id INTO uid_staff   FROM sys_user WHERE username='staff'   AND tenant_id=1;
  SELECT id INTO uid_finance FROM sys_user WHERE username='finance' AND tenant_id=1;

  -- ========== 1) 法人（status 枚举带中文后缀，见 000001；该表无 creator_id 列） ==========
  INSERT INTO sys_legal_entity (code, name, credit_code, entity_type, short_code, consolidated, status, tenant_id)
  VALUES ('DEMO-LE-001', '智能制造研究院（总院）', '91330100DEMO00001A', 'TOTAL_INSTITUTE', 'ZGY', TRUE,  'ACTIVE=正常', 1)
  RETURNING id INTO le1;
  INSERT INTO sys_legal_entity (code, name, credit_code, entity_type, short_code, consolidated, status, tenant_id)
  VALUES ('DEMO-LE-002', '智能制造研究院（杭州分院）', '91330100DEMO00002B', 'BRANCH_INSTITUTE', 'HZF', FALSE, 'ACTIVE=正常', 1)
  RETURNING id INTO le2;

  -- ========== 2) 项目分类（T21：中检/结项窗口 + 管理费率） ==========
  INSERT INTO e_project_category (tenant_id, code, name, level, mgmt_fee_pct, midcheck_from, midcheck_to, closing_from, closing_to)
  VALUES (1, 'DEMO-CAT-01', '纵向面上项目', 'NORMAL', 5.00, CURRENT_DATE - 365, CURRENT_DATE + 60, CURRENT_DATE + 300, CURRENT_DATE + 420)
  RETURNING id INTO cat1;
  INSERT INTO e_project_category (tenant_id, code, name, level, mgmt_fee_pct)
  VALUES (1, 'DEMO-CAT-02', '横向委托课题', 'NORMAL', 8.00)
  RETURNING id INTO cat2;

  -- ========== 3) 经费科目（末级，可挂预算行） ==========
  INSERT INTO f_subject (tenant_id, creator_id, code, name, level, category, is_leaf, sort_no)
  VALUES (1, uid_admin, 'DEMO-S-01', '设备费', 1, 'DIRECT', TRUE, 1) RETURNING id INTO s1;
  INSERT INTO f_subject (tenant_id, creator_id, code, name, level, category, is_leaf, sort_no)
  VALUES (1, uid_admin, 'DEMO-S-02', '材料费', 1, 'DIRECT', TRUE, 2) RETURNING id INTO s2;
  INSERT INTO f_subject (tenant_id, creator_id, code, name, level, category, is_leaf, sort_no)
  VALUES (1, uid_admin, 'DEMO-S-03', '差旅费', 1, 'DIRECT', TRUE, 3) RETURNING id INTO s3;
  INSERT INTO f_subject (tenant_id, creator_id, code, name, level, category, is_leaf, sort_no)
  VALUES (1, uid_admin, 'DEMO-S-04', '绩效支出', 1, 'PERFORMANCE', TRUE, 9) RETURNING id INTO s4;

  -- ========== 4) 项目 ×4（EXECUTING 为主，快照金额与明细自洽） ==========
  INSERT INTO e_project (code, tenant_id, status, creator_id, application_id, title, project_type,
                         pi_user_id, member_ids, legal_entity_id, start_date, end_date,
                         total_budget, received_amount, spent_amount, health_score, risk_level, category_id)
  VALUES ('DEMO-PRJ-001', 1, 'EXECUTING', uid_manager, 900001, '曲面磨抛机器人自适应工艺关键技术研究', 'NSFC',
          uid_staff, jsonb_build_array(uid_staff, uid_manager), le1,
          CURRENT_DATE - 200, CURRENT_DATE + 530,
          800000.00, 480000.00, 296000.00, 86, 'LOW', cat1)
  RETURNING id INTO p1;
  INSERT INTO e_project (code, tenant_id, status, creator_id, application_id, title, project_type,
                         pi_user_id, member_ids, legal_entity_id, start_date, end_date,
                         total_budget, received_amount, spent_amount, health_score, risk_level, category_id)
  VALUES ('DEMO-PRJ-002', 1, 'EXECUTING', uid_manager, 900002, '高精度力位混合控制与在线补偿方法研究', 'KJBP',
          uid_staff, jsonb_build_array(uid_staff), le2,
          CURRENT_DATE - 420, CURRENT_DATE + 60,
          1200000.00, 900000.00, 830000.00, 58, 'HIGH', cat1)
  RETURNING id INTO p2;
  INSERT INTO e_project (code, tenant_id, status, creator_id, application_id, title, project_type,
                         pi_user_id, member_ids, legal_entity_id, start_date, end_date,
                         total_budget, received_amount, spent_amount, health_score, risk_level, category_id)
  VALUES ('DEMO-PRJ-003', 1, 'EXECUTING', uid_manager, 900003, '复杂曲面机器人磨抛产线数字孪生系统', 'HENGXIANG',
          uid_manager, jsonb_build_array(uid_staff), le1,
          CURRENT_DATE - 90, CURRENT_DATE + 640,
          2000000.00, 600000.00, 210000.00, 92, 'LOW', cat2)
  RETURNING id INTO p3;
  INSERT INTO e_project (code, tenant_id, status, creator_id, application_id, title, project_type,
                         pi_user_id, member_ids, legal_entity_id, start_date, end_date, actual_end_date,
                         total_budget, received_amount, spent_amount, health_score, risk_level, category_id)
  VALUES ('DEMO-PRJ-004', 1, 'COMPLETING', uid_manager, 900004, '软体夹持器结构设计与抓取稳定性分析', 'ZIGE',
          uid_staff, jsonb_build_array(uid_staff, uid_manager), le1,
          CURRENT_DATE - 700, CURRENT_DATE + 20, CURRENT_DATE - 10,
          300000.00, 300000.00, 281000.00, 74, 'MED', cat1)
  RETURNING id INTO p4;

  -- ========== 5) 任务（项目 1，含依赖与进度） ==========
  INSERT INTO e_task (code, tenant_id, status, creator_id, project_id, name, owner_user_id, member_ids,
                      planned_start, planned_end, actual_start, progress_percent)
  VALUES ('DEMO-T-101', 1, 'COMPLETED', uid_manager, p1, '工艺参数库建模与数据采集', uid_staff,
          jsonb_build_array(uid_staff), CURRENT_DATE - 200, CURRENT_DATE - 140, CURRENT_DATE - 198, 100)
  RETURNING id INTO t1;
  INSERT INTO e_task (code, tenant_id, status, creator_id, project_id, name, owner_user_id, member_ids,
                      planned_start, planned_end, actual_start, progress_percent, dep_task_ids)
  VALUES ('DEMO-T-102', 1, 'IN_PROGRESS', uid_manager, p1, '自适应磨抛力控算法开发与仿真', uid_staff,
          jsonb_build_array(uid_staff, uid_manager), CURRENT_DATE - 140, CURRENT_DATE - 20, CURRENT_DATE - 138, 72,
          jsonb_build_array(t1))
  RETURNING id INTO t2;
  INSERT INTO e_task (code, tenant_id, status, creator_id, project_id, name, owner_user_id, member_ids,
                      planned_start, planned_end, progress_percent, dep_task_ids)
  VALUES ('DEMO-T-103', 1, 'PENDING', uid_manager, p1, '样机集成与产线验证', uid_staff,
          jsonb_build_array(uid_staff), CURRENT_DATE - 20, CURRENT_DATE + 160, 0,
          jsonb_build_array(t2))
  RETURNING id INTO t3;
  INSERT INTO e_task (code, tenant_id, status, creator_id, project_id, name, owner_user_id, member_ids,
                      planned_start, planned_end, actual_start, progress_percent)
  VALUES ('DEMO-T-104', 1, 'OVERDUE', uid_manager, p2, '力位混合控制器硬件在环测试', uid_staff,
          jsonb_build_array(uid_staff), CURRENT_DATE - 120, CURRENT_DATE - 40, CURRENT_DATE - 118, 65);

  -- ========== 6) 里程碑（项目 1） ==========
  INSERT INTO e_milestone (code, tenant_id, status, creator_id, project_id, name, due_date, actual_date, owner_user_id, deliverable_type)
  VALUES ('DEMO-MS-101', 1, 'ACHIEVED', uid_manager, p1, '开题与实施方案评审', CURRENT_DATE - 180, CURRENT_DATE - 182, uid_staff, 'REVIEW_REPORT');
  INSERT INTO e_milestone (code, tenant_id, status, creator_id, project_id, name, due_date, owner_user_id, deliverable_type)
  VALUES ('DEMO-MS-102', 1, 'PENDING', uid_manager, p1, '中期检查（算法联调通过）', CURRENT_DATE + 30, uid_staff, 'MID_REPORT');
  INSERT INTO e_milestone (code, tenant_id, status, creator_id, project_id, name, due_date, owner_user_id, deliverable_type)
  VALUES ('DEMO-MS-103', 1, 'PENDING', uid_manager, p1, '结题验收', CURRENT_DATE + 500, uid_staff, 'ACCEPT_REPORT');

  -- ========== 7) 预算 + 行（项目 1/2，EXECUTING；模式为中文枚举） ==========
  INSERT INTO f_budget (code, tenant_id, status, creator_id, project_id, legal_entity_id, mode,
                        total_approved, approved_at, approved_by)
  VALUES ('DEMO-BUD-001', 1, 'EXECUTING', uid_finance, p1, le1, '预算制', 800000.00, now() - INTERVAL '190 days', uid_manager)
  RETURNING id INTO b1;
  INSERT INTO f_budget (code, tenant_id, status, creator_id, project_id, legal_entity_id, mode,
                        total_approved, approved_at, approved_by)
  VALUES ('DEMO-BUD-002', 1, 'EXECUTING', uid_finance, p2, le2, '包干制', 1200000.00, now() - INTERVAL '410 days', uid_manager)
  RETURNING id INTO b2;

  INSERT INTO f_budget_line (code, tenant_id, status, creator_id, budget_id, subject_id, amount_planned, amount_used, remaining)
  VALUES ('DEMO-BL-011', 1, 'ACTIVE', uid_finance, b1, s1, 200000.00, 96000.00, 104000.00),
         ('DEMO-BL-012', 1, 'ACTIVE', uid_finance, b1, s2, 300000.00, 150000.00, 150000.00),
         ('DEMO-BL-013', 1, 'ACTIVE', uid_finance, b1, s3, 100000.00, 50000.00, 50000.00),
         ('DEMO-BL-014', 1, 'ACTIVE', uid_finance, b1, s4, 200000.00, 0.00, 200000.00);
  INSERT INTO f_budget_line (code, tenant_id, status, creator_id, budget_id, subject_id, amount_planned, amount_used, remaining)
  VALUES ('DEMO-BL-021', 1, 'ACTIVE', uid_finance, b2, s1, 400000.00, 320000.00, 80000.00),
         ('DEMO-BL-022', 1, 'ACTIVE', uid_finance, b2, s2, 500000.00, 460000.00, 40000.00),
         ('DEMO-BL-023', 1, 'ACTIVE', uid_finance, b2, s4, 300000.00, 50000.00, 250000.00);

  -- ========== 8) 到账（项目 1/2，CLAIMED） ==========
  INSERT INTO f_income (tenant_id, status, creator_id, project_id, legal_entity_id, receipt_no, receipt_date,
                        amount, payer_name, purpose_text, bank_flow_no, claim_status, claimed_by, claimed_at)
  VALUES (1, 'ACTIVE', uid_finance, p1, le1, 'DEMO-RC-0001', CURRENT_DATE - 150, 480000.00,
          '国家自然科学基金委员会', 'DEMO-PRJ-001 首笔拨款', 'DEMO-FL-0001', 'CLAIMED', uid_finance, now() - INTERVAL '148 days');
  INSERT INTO f_income (tenant_id, status, creator_id, project_id, legal_entity_id, receipt_no, receipt_date,
                        amount, payer_name, purpose_text, bank_flow_no, claim_status, claimed_by, claimed_at)
  VALUES (1, 'ACTIVE', uid_finance, p2, le2, 'DEMO-RC-0002', CURRENT_DATE - 400, 900000.00,
          '省重点研发计划专项', 'DEMO-PRJ-002 第二期经费', 'DEMO-FL-0002', 'CLAIMED', uid_finance, now() - INTERVAL '398 days');

  -- ========== 9) 成果 ×5（论文/专利/软著，含挂靠项目） ==========
  INSERT INTO r_output (code, tenant_id, status, creator_id, output_type, title, publish_date,
                        authors, project_ids, source, is_claimed, claim_status, legal_entity_id)
  VALUES ('DEMO-OUT-001', 1, 'ASSIGNED_TO_PROJECT', uid_staff, 'PAPER',
          'Adaptive force control for robotic surface grinding based on reinforcement learning',
          CURRENT_DATE - 100,
          jsonb_build_array(jsonb_build_object('user_id', uid_staff, 'name', '一线研究员', 'order', 1, 'is_corresponding', true)),
          jsonb_build_array(p1), 'WOS', TRUE, 'CLAIMED', le1);
  INSERT INTO r_output (code, tenant_id, status, creator_id, output_type, title, publish_date,
                        authors, project_ids, source, is_claimed, claim_status, legal_entity_id)
  VALUES ('DEMO-OUT-002', 1, 'ASSIGNED_TO_PROJECT', uid_staff, 'PAPER',
          '曲面机器人磨抛过程的材料去除率建模与实验验证',
          CURRENT_DATE - 60,
          jsonb_build_array(jsonb_build_object('user_id', uid_staff, 'name', '一线研究员', 'order', 1, 'is_corresponding', true)),
          jsonb_build_array(p1, p2), 'CNKI', TRUE, 'CLAIMED', le1);
  INSERT INTO r_output (code, tenant_id, status, creator_id, output_type, title, publish_date,
                        authors, project_ids, source, is_claimed, claim_status, legal_entity_id, stage, annual_fee_due)
  VALUES ('DEMO-OUT-003', 1, 'CLAIMED', uid_staff, 'PATENT',
          '一种力位混合控制的机器人末端执行器', CURRENT_DATE - 200,
          jsonb_build_array(jsonb_build_object('user_id', uid_staff, 'name', '一线研究员', 'order', 1)),
          jsonb_build_array(p2), 'CNIPA', TRUE, 'CLAIMED', le2, 'APPLIED', CURRENT_DATE + 45);
  INSERT INTO r_output (code, tenant_id, status, creator_id, output_type, title, publish_date,
                        authors, project_ids, source, is_claimed, claim_status, legal_entity_id)
  VALUES ('DEMO-OUT-004', 1, 'ASSIGNED_TO_PROJECT', uid_manager, 'SOFTWARE',
          '磨抛产线数字孪生监控软件 V1.0', CURRENT_DATE - 30,
          jsonb_build_array(jsonb_build_object('user_id', uid_manager, 'name', '科研管理岗', 'order', 1)),
          jsonb_build_array(p3), 'MANUAL', TRUE, 'CLAIMED', le1);
  INSERT INTO r_output (code, tenant_id, status, creator_id, output_type, title, publish_date,
                        authors, source, is_claimed, claim_status, legal_entity_id, match_confidence)
  VALUES ('DEMO-OUT-005', 1, 'AUTO_FETCHED', uid_admin, 'PAPER',
          'Digital twin-driven process optimization for robotic belt grinding',
          CURRENT_DATE - 5,
          jsonb_build_array(jsonb_build_object('name', 'W. Zhang', 'order', 1)), 'FETCH',
          FALSE, 'UNCLAIMED', le1, 0.62);

  -- ========== 10) 申报计划（T25，OPEN 窗口内）+ 申报单 ×2 ==========
  INSERT INTO e_apply_plan (tenant_id, name, category_id, source, start_at, end_at, need_review, status, created_at)
  VALUES (1, '2026 年度国家自然科学基金申报（院级汇总）', cat1, 'NSFC',
          CURRENT_DATE - 3, CURRENT_DATE + 30, TRUE, 'OPEN', now() - INTERVAL '10 days')
  RETURNING id INTO ap1;
  INSERT INTO e_application (tenant_id, plan_id, project_name, apply_amount, applicant_id, status)
  VALUES (1, ap1, '机器人化桥梁缆索检测与维护装备研制', 900000.00, uid_staff, 'SUBMITTED');
  INSERT INTO e_application (tenant_id, plan_id, project_name, apply_amount, applicant_id, status)
  VALUES (1, ap1, '大型风电叶片磨抛机器人系统关键技术研究', 1200000.00, uid_manager, 'COLLEGE_PASSED');
END
$seed$;

-- 第二块：申报指南（独立幂等护栏——已有 DEMO 项目时第一块整体 RETURN，
-- 指南增量补种仍可执行；用户按 username 重新定位，不依赖第一块变量）。
DO $seedgl$
DECLARE
  uid_manager bigint;
BEGIN
  IF EXISTS (SELECT 1 FROM p_guideline WHERE code LIKE 'DEMO-GL-%') THEN
    RETURN;
  END IF;
  SELECT id INTO uid_manager FROM sys_user WHERE username='manager' AND tenant_id=1;

  -- 申报指南 ×6：PUBLISHED 窗口内 ×4 / 未开始 ×1 / 已截止 CLOSED ×1
  INSERT INTO p_guideline (tenant_id, code, status, creator_id, title, project_type, funding_source,
                           target_disciplines, apply_start_at, apply_end_at, total_envelope, content_rich, remark, publish_at)
  VALUES (1, 'DEMO-GL-001', 'PUBLISHED', uid_manager,
          '2026 年度国家自然科学基金 · 面上项目 / 青年科学基金', 'NSFC', '国家自然科学基金委员会',
          jsonb_build_array(jsonb_build_object('code','ME','label','机械工程'), jsonb_build_object('code','ROBOT','label','机器人学')),
          CURRENT_DATE - 45, CURRENT_DATE + 12, 500000.00,
          '## 支持方向' || chr(10) ||
          '面向机械工程与机器人学前沿，优先支持：磨抛/装配等作业机器人的力位混合控制、复杂曲面自适应加工工艺、机器人化智能装备研制。' || chr(10) || chr(10) ||
          '## 资助强度' || chr(10) ||
          '面上项目 ≤ 50 万元/项，青年科学基金 ≤ 30 万元/项，研究期限 3 年。' || chr(10) || chr(10) ||
          '## 申报条件' || chr(10) ||
          '1. 具有高级专业技术职务或博士学位；' || chr(10) ||
          '2. 在研+申请国家级项目总数 ≤ 2 项（限项要求）；' || chr(10) ||
          '3. 涉及生命/医学内容的须完成伦理前置审查。' || chr(10) || chr(10) ||
          '## 材料要求' || chr(10) ||
          '申请书通过院级申报计划（2026 年度国家自然科学基金申报）提交，经形式审查 → 学院推荐 → 校级汇总三级流程报送基金委。',
          '在研+申请 ≤ 2；需伦理前置', now() - INTERVAL '45 days'),
         (1, 'DEMO-GL-002', 'PUBLISHED', uid_manager,
          '「智能机器人」重点专项 2026 年度第三批公开申报（揭榜挂帅）', 'KJBP', '科学技术部',
          jsonb_build_array(jsonb_build_object('code','ROBOT','label','机器人学')),
          CURRENT_DATE - 30, CURRENT_DATE + 24, 240000000.00,
          '## 榜单任务' || chr(10) ||
          '本批次围绕工业机器人核心部件、特种机器人整机与应用示范方向发布 8 项榜单任务，专项总盘子 2.4 亿元。' || chr(10) || chr(10) ||
          '## 组织形式' || chr(10) ||
          '揭榜挂帅：须由企业牵头组建产学研联合体，研究院可作为联合单位承担关键技术攻关任务。' || chr(10) || chr(10) ||
          '## 预算要求' || chr(10) ||
          '预算制管理，间接费用比例不超过直接费用扣除设备购置费后的 20%。',
          '需牵头单位资质 · 间接费用 20%', now() - INTERVAL '30 days'),
         (1, 'DEMO-GL-003', 'PUBLISHED', uid_manager,
          '启元研究院 2026 年度「探索者计划」自立项目（第三批）', 'ZIGE', '院科研管理部',
          jsonb_build_array(jsonb_build_object('code','AI','label','人工智能')),
          CURRENT_DATE - 25, CURRENT_DATE + 2, 800000.00,
          '## 定位' || chr(10) ||
          '面向 35 岁以下青年研究人员设立的自由探索类项目，鼓励原创性、非共识选题。' || chr(10) || chr(10) ||
          '## 资助强度' || chr(10) ||
          '单项 ≤ 80 万元，经费包干制（免编明细预算），研究期限 2 年。' || chr(10) || chr(10) ||
          '## 申报方式' || chr(10) ||
          '通过院级申报计划提交一页纸建议书 + 3 页技术路线；AI 起草的申报内容须按 PRD 8.1 标注 AI 起草水印。',
          '包干制 · 面向 35 岁以下', now() - INTERVAL '25 days'),
         (1, 'DEMO-GL-004', 'PUBLISHED', uid_manager,
          '企业横向委托 · 复杂曲面智能磨抛产线联合攻关', 'HENGXIANG', '某高端装备集团',
          jsonb_build_array(jsonb_build_object('code','ME','label','机械工程')),
          CURRENT_DATE - 15, CURRENT_DATE + 16, 3600000.00,
          '## 委托背景' || chr(10) ||
          '委托方产线存在曲面磨抛一致性差、人工打磨占比高两大痛点，拟联合攻关自适应磨抛工艺与产线集成。' || chr(10) || chr(10) ||
          '## 合同要点' || chr(10) ||
          '合同金额 360 万元，分三期到账；需签署技术协议与保密条款，知识产权按贡献比例共享。' || chr(10) || chr(10) ||
          '## 走向提示' || chr(10) ||
          '横向课题走合同审批流（P-18），立项后自动生成合同台账与经费到账计划。',
          '横向 · 走合同审批', now() - INTERVAL '15 days'),
         (1, 'DEMO-GL-005', 'PUBLISHED', uid_manager,
          '省重点研发（产业政策引导）2026 年度 · 高端装备专项', 'PROV', '省工业和信息化厅',
          jsonb_build_array(jsonb_build_object('code','ME','label','机械工程')),
          CURRENT_DATE + 5, CURRENT_DATE + 40, 1500000.00,
          '## 支持方向' || chr(10) ||
          '高端装备专项聚焦智能成套装备、关键基础件两类方向，单项 ≤ 150 万元，省市配套 1:1。' || chr(10) || chr(10) ||
          '## 申报条件' || chr(10) ||
          '需产学研联合体（企业牵头或参与），自筹经费比例不低于 50%。',
          '配套 1:1 · 需产学研联合体', now() - INTERVAL '5 days'),
         (1, 'DEMO-GL-006', 'CLOSED', uid_manager,
          '省自然科学基金 2027 年度集中接收（创新研究群体 / 重点项目）', 'PROV', '省科技厅',
          jsonb_build_array(jsonb_build_object('code','AI','label','人工智能')),
          CURRENT_DATE - 120, CURRENT_DATE - 20, 3000000.00,
          '## 说明' || chr(10) ||
          '本批次已截止。重点 ≤ 100 万元/项，创新研究群体 300 万元/项。形式审查由科研办统一办理，下一批次预计 2027 年 3 月开放。',
          '已截止 · 下一批次 2027-03', now() - INTERVAL '120 days');
END
$seedgl$;
