-- seed_dash.sql · dataops 大屏聚合测试数据（租户 7 独立 fixture，不与 funding 包的租户 1 互相干扰）。
-- 场景：预算 10 万 EXECUTING；已认领到账 4 万（本年）；无报销 → used=0。

DELETE FROM F_EXPENSE      WHERE tenant_id = 7;
DELETE FROM F_INCOME       WHERE tenant_id = 7;
DELETE FROM F_BUDGET_LINE  WHERE tenant_id = 7;
DELETE FROM F_BUDGET       WHERE tenant_id = 7;
DELETE FROM F_SUBJECT      WHERE tenant_id = 7;

INSERT INTO F_SUBJECT (tenant_id, status, creator_id, code, name, level, category, is_leaf, ratio_limit, sort_no) VALUES
 (7, 'ACTIVE', 1, 'SUB-DASH-EQ', '设备费（大屏）', 1, 'DIRECT', TRUE, NULL, 1);

INSERT INTO F_BUDGET (id, tenant_id, status, creator_id, code, project_id, legal_entity_id, mode, total_approved, total_adjusted, version, approved_at, approved_by)
OVERRIDING SYSTEM VALUE VALUES
 (8901, 7, 'EXECUTING', 1, 'BUD-DASH-1', 9701, 1, '预算制', 100000, 0, 1, now(), 1);

INSERT INTO F_BUDGET_LINE (id, tenant_id, status, creator_id, budget_id, subject_id, amount_planned)
OVERRIDING SYSTEM VALUE VALUES
 (8911, 7, 'ACTIVE', 1, 8901, (SELECT id FROM F_SUBJECT WHERE code='SUB-DASH-EQ' AND tenant_id=7), 100000);

INSERT INTO F_INCOME (id, tenant_id, status, creator_id, code, project_id, legal_entity_id, receipt_no, receipt_date, amount, payer_name, bank_flow_no, claim_status, claimed_by, claimed_at)
OVERRIDING SYSTEM VALUE VALUES
 (8921, 7, 'ACTIVE', 1, 'INC-DASH-1', 9701, 1, 'RCP-DASH-1', CURRENT_DATE - 5, 40000, '测试基金会', 'FLOW-DASH-1', 'CLAIMED', 1, now());
