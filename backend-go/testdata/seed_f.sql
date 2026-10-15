-- seed_f.sql · F 域集成测试数据（幂等：先清本租户再插）
-- 场景：项目 9001 EXECUTING（结题窗口 15 天后）+ 9002 CLOSED 历史；
--       预算 BUD 50 万（3 行）；到款 30 万已认领 + 20 万待认领 + 流水幂等样例；
--       报销 5 万 DRAFT（预算制，设备费行）。

DELETE FROM F_EXPENSE_APPROVAL WHERE tenant_id = 1;
DELETE FROM F_EXPENSE           WHERE tenant_id = 1;
DELETE FROM F_INDIRECT_FEE      WHERE tenant_id = 1;
DELETE FROM F_INCOME            WHERE tenant_id = 1;
DELETE FROM F_BUDGET_LINE       WHERE tenant_id = 1;
DELETE FROM F_BUDGET            WHERE tenant_id = 1;
DELETE FROM F_SUBJECT           WHERE tenant_id = 1;

-- 科目字典（8 类叶子科目）
INSERT INTO F_SUBJECT (tenant_id, status, creator_id, code, name, level, category, is_leaf, ratio_limit, sort_no) VALUES
 (1, 'ACTIVE', 1, 'SUB-EQ',  '设备费',         1, 'DIRECT',     TRUE, 0.30, 1),
 (1, 'ACTIVE', 1, 'SUB-MAT', '材料费',         1, 'DIRECT',     TRUE, NULL, 2),
 (1, 'ACTIVE', 1, 'SUB-TES', '测试化验加工费', 1, 'DIRECT',     TRUE, NULL, 3),
 (1, 'ACTIVE', 1, 'SUB-TRV', '差旅费',         1, 'DIRECT',     TRUE, NULL, 4),
 (1, 'ACTIVE', 1, 'SUB-MEET','会议费',         1, 'DIRECT',     TRUE, NULL, 5),
 (1, 'ACTIVE', 1, 'SUB-LAB', '劳务费',         1, 'DIRECT',     TRUE, NULL, 6),
 (1, 'ACTIVE', 1, 'SUB-EXP', '专家咨询费',     1, 'DIRECT',     TRUE, NULL, 7),
 (1, 'ACTIVE', 1, 'SUB-IND', '间接费用',       1, 'INDIRECT',   TRUE, 0.30, 8);

-- 项目（E_PROJECT 跨模块逻辑引用：9001 执行中且临近结题、9002 已结题）
DELETE FROM E_PROJECT WHERE id IN (9001, 9002);
INSERT INTO E_PROJECT (id, tenant_id, status, creator_id, application_id, title, pi_user_id, legal_entity_id, end_date, total_budget, member_ids)
OVERRIDING SYSTEM VALUE VALUES
 (9001, 1, 'EXECUTING', 1, 9001, '面向高端装备的拓扑优化研究', 100, 1, CURRENT_DATE + 15, 500000, '[]'),
 (9002, 1, 'CLOSED',    1, 9002, '已结题历史项目',             101, 1, CURRENT_DATE - 200, 100000, '[]');

-- 预算（EXECUTING，50 万）+ 3 行
INSERT INTO F_BUDGET (id, tenant_id, status, creator_id, code, project_id, legal_entity_id, mode, total_approved, total_adjusted, version, approved_at, approved_by)
OVERRIDING SYSTEM VALUE VALUES
 (8801, 1, 'EXECUTING', 1, 'BUD-2026-8801', 9001, 1, '预算制', 500000, 0, 1, now(), 1);

INSERT INTO F_BUDGET_LINE (id, tenant_id, status, creator_id, budget_id, subject_id, amount_planned)
OVERRIDING SYSTEM VALUE VALUES
 (8811, 1, 'ACTIVE', 1, 8801, (SELECT id FROM F_SUBJECT WHERE code='SUB-EQ'  AND tenant_id=1), 150000),
 (8812, 1, 'ACTIVE', 1, 8801, (SELECT id FROM F_SUBJECT WHERE code='SUB-MAT' AND tenant_id=1), 100000),
 (8813, 1, 'ACTIVE', 1, 8801, (SELECT id FROM F_SUBJECT WHERE code='SUB-TRV' AND tenant_id=1), 250000);

-- 到款：1 笔已认领（30 万）+ 1 笔待认领（20 万）+ 1 笔流水幂等样例
INSERT INTO F_INCOME (id, tenant_id, status, creator_id, code, project_id, legal_entity_id, receipt_no, receipt_date, amount, payer_name, bank_flow_no, claim_status, claimed_by, claimed_at)
OVERRIDING SYSTEM VALUE VALUES
 (8601, 1, 'ACTIVE', 1, 'INC-2026-8601', 9001, 1, 'RCP-001', CURRENT_DATE - 30, 300000, '国家自然科学基金委员会', 'FLOW-SEED-0', 'CLAIMED', 100, now()),
 (8602, 1, 'ACTIVE', 1, 'INC-2026-8602', NULL, 1, 'RCP-002', CURRENT_DATE - 10, 200000, '省科技厅',               'FLOW-SEED-1', 'UNCLAIMED', NULL, NULL);

-- 报销：DRAFT 一张（预算制，挂设备费行 8811，5 万）
INSERT INTO F_EXPENSE (id, tenant_id, status, creator_id, code, project_id, budget_line_id, legal_entity_id, applicant_user_id, amount, expense_type, description, invoice_ids, attachment_ids, submit_mode, invoice_check_status)
OVERRIDING SYSTEM VALUE VALUES
 (8701, 1, 'DRAFT', 1, 'EXP-2026-8701', 9001, 8811, 1, 100, 50000, 'EQUIPMENT', '购置高性能计算工作站', '[87001]', '[]', '预算制', 'PENDING');
