-- 裁剪 schema：M 仓储所需 5 张自有表 + 被 calculate 跨读的 R/F/E/T 最小列（仅 sqlc 编译期解析用）。
-- 自有表语句原样摘自 000001_init.up.sql；跨表仅保留 metrics.sql 引用到的列，运行时打真库全量表。
-- 原因：sqlc v1.27 wazero 解析器无法吃 ~394KB 全量迁移。

-- ===== M 自有表（去 COMMENT/索引，保留列与类型）=====
CREATE TABLE m_scheme (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code VARCHAR(64), tenant_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT', deleted SMALLINT NOT NULL DEFAULT 0,
  creator_id BIGINT NOT NULL, modifier_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark TEXT, security_level VARCHAR(16) NOT NULL DEFAULT 'INTERNAL',
  legal_entity_id BIGINT, policy_pack_id BIGINT,
  name VARCHAR(128) NOT NULL, period_type VARCHAR(16) NOT NULL,
  scope_dept_id BIGINT, scope_staff_type VARCHAR(32), effective_period VARCHAR(32) NOT NULL,
  version INT NOT NULL DEFAULT 1, active BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE m_scheme_factor (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scheme_id BIGINT NOT NULL, tenant_id BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  creator_id BIGINT NOT NULL,
  factor_code VARCHAR(64) NOT NULL, factor_name VARCHAR(128), weight NUMERIC(6,2) NOT NULL DEFAULT 0,
  scoring_rule JSONB NOT NULL DEFAULT '{}'::jsonb, max_score NUMERIC(10,2),
  data_source VARCHAR(32) NOT NULL, clause_ref VARCHAR(256), sort_no INT NOT NULL DEFAULT 0
);
CREATE TABLE m_record (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code VARCHAR(64), tenant_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'CALCULATED', deleted SMALLINT NOT NULL DEFAULT 0,
  creator_id BIGINT NOT NULL, modifier_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark TEXT, security_level VARCHAR(16) NOT NULL DEFAULT 'INTERNAL', legal_entity_id BIGINT,
  scheme_id BIGINT NOT NULL, staff_user_id BIGINT NOT NULL, period VARCHAR(32) NOT NULL, dept_id BIGINT,
  total_score NUMERIC(10,2) NOT NULL DEFAULT 0, rank INT, calc_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  calc_batch VARCHAR(64), calc_at TIMESTAMPTZ,
  confirmed_by BIGINT, confirmed_at TIMESTAMPTZ, approve_by BIGINT, approve_at TIMESTAMPTZ,
  appeal_reason VARCHAR(512), void_reason VARCHAR(512)
);
CREATE TABLE m_record_item (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  record_id BIGINT NOT NULL, tenant_id BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  factor_code VARCHAR(64) NOT NULL, metric_value NUMERIC(18,4) NOT NULL DEFAULT 0,
  raw_score NUMERIC(10,2) NOT NULL DEFAULT 0, weighted_score NUMERIC(10,2) NOT NULL DEFAULT 0,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE m_payout (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code VARCHAR(64), tenant_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT', deleted SMALLINT NOT NULL DEFAULT 0,
  creator_id BIGINT NOT NULL, modifier_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark TEXT, security_level VARCHAR(16) NOT NULL DEFAULT 'INTERNAL', legal_entity_id BIGINT,
  record_id BIGINT NOT NULL, payee_user_id BIGINT NOT NULL, amount NUMERIC(18,2) NOT NULL,
  period VARCHAR(32), pay_channel VARCHAR(32), approver_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  approved_at TIMESTAMPTZ, paid_at TIMESTAMPTZ, voucher_code VARCHAR(64), reject_reason VARCHAR(512)
);

-- ===== 被读跨模块表：仅 metrics.sql 引用的列（运行时打真库全量表）=====
CREATE TABLE r_output (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, code VARCHAR(64), deleted SMALLINT NOT NULL DEFAULT 0,
  output_type VARCHAR(32) NOT NULL, publish_date DATE, authors JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE e_project (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, deleted SMALLINT NOT NULL DEFAULT 0,
  pi_user_id BIGINT NOT NULL, department_id BIGINT, project_type VARCHAR(64),
  member_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  start_date DATE, total_budget NUMERIC(18,2) NOT NULL DEFAULT 0
);
CREATE TABLE f_income (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, project_id BIGINT,
  status VARCHAR(32) NOT NULL, receipt_date DATE, amount NUMERIC(18,2) NOT NULL
);
CREATE TABLE t_deal (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, output_id BIGINT NOT NULL,
  contract_amount NUMERIC(18,2) NOT NULL DEFAULT 0, signed_at TIMESTAMPTZ
);

-- T24 画像 used 聚合跨读（最小列，运行时打真库）
CREATE TABLE f_budget (
  id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, project_id BIGINT NOT NULL,
  deleted SMALLINT NOT NULL DEFAULT 0
);
CREATE TABLE f_budget_line (
  id BIGINT PRIMARY KEY, budget_id BIGINT NOT NULL,
  amount_planned NUMERIC(18,2) NOT NULL DEFAULT 0, amount_adjusted NUMERIC(18,2),
  amount_used NUMERIC(18,2) NOT NULL DEFAULT 0, amount_frozen NUMERIC(18,2) NOT NULL DEFAULT 0,
  deleted SMALLINT NOT NULL DEFAULT 0
);
