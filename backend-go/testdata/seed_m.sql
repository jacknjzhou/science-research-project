-- 方案（YEAR 粒度便于跨表 publish_date/receipt_date 覆盖全年；此处用 2026Q3 计）
INSERT INTO m_scheme (id, code, tenant_id, creator_id, status, security_level,
                      name, period_type, effective_period, version, active)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'PERF-2026-000001', 1, 1, 'ACTIVE', 'INTERNAL',
   '2026 科研绩效方案', 'QUARTER', '2026Q3', 1, TRUE);

-- 因子（4 个数据源 + 4 计分法）
INSERT INTO m_scheme_factor (id, scheme_id, tenant_id, creator_id, factor_code, factor_name,
                             weight, scoring_rule, max_score, data_source, sort_no) OVERRIDING SYSTEM VALUE VALUES
  (1, 1, 1, 1, 'F_OUTPUT', '论文数×2',       40.00, '{"method":"COUNT","unit":2}',        100.00, 'R_OUTPUT',  1),
  (2, 1, 1, 1, 'F_LEVEL',  '项目分类型',      30.00, '{"method":"BY_LEVEL","levelMap":{"NATIONAL":60,"PROVINCIAL":30}}', 100.00, 'E_PROJECT', 2),
  (3, 1, 1, 1, 'F_INCOME', '到账经费',         20.00, '{"method":"BY_AMOUNT","unit":0.001}', 50.00,  'F_INCOME',  3),
  (4, 1, 1, 1, 'F_DEAL',   '转化分档',         10.00, '{"method":"LADDER","ladder":[{"min":0,"max":100000,"score":5},{"min":100000,"max":999999999,"score":10}]}', 10.00, 'T_DEAL', 4);

-- R_OUTPUT：1 篇（publish_date 落 2026Q3，作者含 user_id=100）
INSERT INTO r_output (id, code, tenant_id, creator_id, status, deleted, security_level,
                      output_type, publish_date, authors)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'OUT-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL', 'PAPER', DATE '2026-08-01',
   '[{"user_id":100,"role":"FIRST_AUTHOR"}]'::jsonb);

-- E_PROJECT：1 个省级项目（PI=100, start_date 落 2026Q3, 预算 500000）
INSERT INTO e_project (id, code, tenant_id, creator_id, status, deleted, security_level,
                       project_type, pi_user_id, department_id, start_date, total_budget)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'EPRJ-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL', 'PROVINCIAL', 100, 10,
   DATE '2026-07-15', 500000.00);

-- F_INCOME：到账 200000（挂上面项目，receipt_date 落 2026Q3）
INSERT INTO f_income (id, code, tenant_id, creator_id, status, deleted, security_level,
                      project_id, amount, receipt_date)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'INC-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL',
   1, 200000.00, DATE '2026-09-01');

-- T_DEAL：转化合同 150000（signed_at 落 2026Q3，output_id=1）
INSERT INTO t_deal (id, code, tenant_id, creator_id, status, deleted, security_level,
                    output_id, contract_amount, signed_at)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'DEAL-2026-000001', 1, 100, 'ACTIVE', 0, 'INTERNAL',
   1, 150000.00, TIMESTAMPTZ '2026-08-15T00:00:00Z');

-- 序列对齐（IDENTITY/BIGSERIAL 手工插 id 后须 setval，否则 handler 再插会撞主键）
SELECT setval(pg_get_serial_sequence('r_output','id'),  (SELECT COALESCE(MAX(id),1) FROM r_output));
SELECT setval(pg_get_serial_sequence('e_project','id'), (SELECT COALESCE(MAX(id),1) FROM e_project));
SELECT setval(pg_get_serial_sequence('f_income','id'),  (SELECT COALESCE(MAX(id),1) FROM f_income));
SELECT setval(pg_get_serial_sequence('t_deal','id'),    (SELECT COALESCE(MAX(id),1) FROM t_deal));
SELECT setval(pg_get_serial_sequence('m_scheme','id'),  (SELECT COALESCE(MAX(id),1) FROM m_scheme));
SELECT setval(pg_get_serial_sequence('m_scheme_factor','id'), (SELECT COALESCE(MAX(id),1) FROM m_scheme_factor));
