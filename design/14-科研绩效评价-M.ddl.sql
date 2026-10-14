-- =============================================================================
-- 14 科研绩效评价 · M（模块前缀 PERF/PAY）
-- 版本 v1.0 · 2026-10-14
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4）
-- 约定：金额/权重 NUMERIC；时间 TIMESTAMPTZ；枚举 VARCHAR+CHECK；字典走 sys_dict；
--       计分 metric_value NUMERIC(18,4)；score NUMERIC(10,2)；payout/amount NUMERIC(18,2)。
--       跨模块只存 *_id 逻辑外键；同模块内 factor→scheme、item→record、payout→record 建物理 FK。
-- 编号：m_scheme/m_record code 前缀 PERF、m_payout code 前缀 PAY（svc-numbering 分配，见 00-common seq_prefix_registry）。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- M_SCHEME · 绩效方案（考核规则容器；同 tenant+period_type+effective_period+scope 唯一 active）
-- -----------------------------------------------------------------------------
CREATE TABLE m_scheme (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  legal_entity_id    BIGINT,
  policy_pack_id     BIGINT,                          -- 逻辑外键 → sys_policy_pack(id)
  -- 业务列 ─────────────────────────────────────────────
  name               VARCHAR(128) NOT NULL,
  period_type        VARCHAR(16) NOT NULL
                     CHECK (period_type IN ('YEAR','QUARTER','MONTH')),
  scope_dept_id      BIGINT,                          -- 逻辑外键 → sys_org(id)；空=全院
  scope_staff_type   VARCHAR(32),                     -- 逻辑引用 sys_dict(staff_type)；空=全部
  effective_period   VARCHAR(32) NOT NULL,            -- 生效周期串，如 2026 / 2026Q1 / 2026-03
  version            INT NOT NULL DEFAULT 1,
  active             BOOLEAN NOT NULL DEFAULT FALSE   -- 同维度仅一个 true
);
CREATE UNIQUE INDEX uk_m_scheme_active
  ON m_scheme(tenant_id, period_type, effective_period, COALESCE(scope_dept_id,0), COALESCE(scope_staff_type,''))
  WHERE active = TRUE AND deleted = 0;                -- 部分唯一：同维度仅一个生效
CREATE UNIQUE INDEX uk_m_scheme_code ON m_scheme(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_m_scheme_tenant_st  ON m_scheme(tenant_id, status);

COMMENT ON TABLE  m_scheme IS '绩效方案：周期/范围/版本，因子集合的容器（模块 M）';
COMMENT ON COLUMN m_scheme.active          IS '当前生效标记；与 status=ACTIVE 同步维护';
COMMENT ON COLUMN m_scheme.effective_period IS '生效周期串，决定 calculate 的时间窗';


-- -----------------------------------------------------------------------------
-- M_SCHEME_FACTOR · 考核因子（计分规则；uk scheme_id+factor_code）
-- -----------------------------------------------------------------------------
CREATE TABLE m_scheme_factor (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scheme_id    BIGINT NOT NULL REFERENCES m_scheme(id),
  tenant_id    BIGINT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  creator_id   BIGINT NOT NULL,
  -- 业务列 ─────────────────────────────────────────────
  factor_code  VARCHAR(64) NOT NULL,                  -- PAPER/PATENT/PROJECT/INCOME/AWARD/TRANSFER/BOOK/SOFTWARE/…（sys_dict）
  factor_name  VARCHAR(128),
  weight       NUMERIC(6,2) NOT NULL DEFAULT 0,       -- 占比
  scoring_rule JSONB        NOT NULL DEFAULT '{}'::jsonb, -- {method:COUNT|BY_LEVEL|BY_AMOUNT|LADDER,unit,ladder:[{min,max,score}],levelMap:{...}}
  max_score    NUMERIC(10,2),
  data_source  VARCHAR(32) NOT NULL
               CHECK (data_source IN ('R_OUTPUT','F_INCOME','E_PROJECT','T_DEAL','MANUAL')),
  clause_ref   VARCHAR(256),                          -- 制度出处（可解释）
  sort_no      INT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uk_m_factor ON m_scheme_factor(scheme_id, factor_code);
CREATE INDEX idx_m_factor_scheme ON m_scheme_factor(scheme_id);

COMMENT ON TABLE m_scheme_factor IS '方案因子：权重/计分方式/取数来源/制度出处（模块 M）';
COMMENT ON COLUMN m_scheme_factor.scoring_rule IS '计分规则 JSON：method + 各方式参数';


-- -----------------------------------------------------------------------------
-- M_RECORD · 绩效记录（某人×某方案×某周期；uk scheme+staff+period WHERE deleted=0 幂等 upsert）
--   CALCULATED→CONFIRMED→APPROVED→PAID；分支 APPEAL、VOID
-- -----------------------------------------------------------------------------
CREATE TABLE m_record (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'CALCULATED'
                     CHECK (status IN ('CALCULATED','CONFIRMED','APPROVED','PAID','APPEAL','VOID')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  legal_entity_id    BIGINT,
  -- 业务列 ─────────────────────────────────────────────
  scheme_id          BIGINT NOT NULL REFERENCES m_scheme(id),
  staff_user_id      BIGINT NOT NULL,                 -- 逻辑外键 → sys_user(id)
  period             VARCHAR(32) NOT NULL,            -- 记录所属周期（继承方案 effective_period）
  dept_id            BIGINT,                          -- 逻辑外键 → sys_org(id)
  total_score        NUMERIC(10,2) NOT NULL DEFAULT 0,
  rank               INT,                             -- 名次（排行计算回填）
  calc_detail        JSONB NOT NULL DEFAULT '{}'::jsonb, -- 计分明细快照/算法参数留痕
  calc_batch         VARCHAR(64),                     -- 批次号（幂等重算）
  calc_at            TIMESTAMPTZ,
  confirmed_by       BIGINT,
  confirmed_at       TIMESTAMPTZ,
  approve_by         BIGINT,
  approve_at         TIMESTAMPTZ,
  appeal_reason      VARCHAR(512),                    -- 申诉理由（APPEAL 时填）
  void_reason        VARCHAR(512)                     -- 作废理由（VOID 时填）
);
CREATE UNIQUE INDEX uk_m_record ON m_record(scheme_id, staff_user_id, period) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_m_record_code ON m_record(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_m_record_scheme_period ON m_record(scheme_id, period);
CREATE INDEX idx_m_record_staff        ON m_record(staff_user_id, period);
CREATE INDEX idx_m_record_dept         ON m_record(dept_id);

COMMENT ON TABLE  m_record IS '绩效记录：自动计分产出的人员×方案×周期得分与状态（模块 M）';
COMMENT ON COLUMN m_record.status IS '状态机 token：CALCULATED/CONFIRMED/APPROVED/PAID/APPEAL/VOID';
COMMENT ON COLUMN m_record.calc_batch IS '计算批次号，同 batch 重算幂等（upsert 覆盖）';


-- -----------------------------------------------------------------------------
-- M_RECORD_ITEM · 因子明细得分（uk record_id+factor_code；evidence 命中单据可反查）
-- -----------------------------------------------------------------------------
CREATE TABLE m_record_item (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  record_id      BIGINT NOT NULL REFERENCES m_record(id),
  tenant_id      BIGINT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- 业务列 ─────────────────────────────────────────────
  factor_code    VARCHAR(64) NOT NULL,
  metric_value   NUMERIC(18,4) NOT NULL DEFAULT 0,    -- 原始度量：篇数/金额/项数
  raw_score      NUMERIC(10,2) NOT NULL DEFAULT 0,    -- 规则映射后未加权分
  weighted_score NUMERIC(10,2) NOT NULL DEFAULT 0,    -- raw×weight（或按权重占比）
  evidence       JSONB NOT NULL DEFAULT '[]'::jsonb   -- [{objectType,objectId,code,value}]
);
CREATE UNIQUE INDEX uk_m_item ON m_record_item(record_id, factor_code);
CREATE INDEX idx_m_item_record ON m_record_item(record_id);

COMMENT ON TABLE m_record_item IS '因子明细得分：每项 metric/raw/weighted + 证据单据（模块 M）';


-- -----------------------------------------------------------------------------
-- M_PAYOUT · 绩效发放在线审批（uk record_id WHERE deleted=0 AND status<>'REJECTED'）
--   DRAFT→APPROVING→APPROVED→PAID；分支 REJECTED
-- -----------------------------------------------------------------------------
CREATE TABLE m_payout (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','APPROVING','APPROVED','PAID','REJECTED')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  legal_entity_id    BIGINT,
  -- 业务列 ─────────────────────────────────────────────
  record_id          BIGINT NOT NULL REFERENCES m_record(id),
  payee_user_id      BIGINT NOT NULL,                 -- 逻辑外键 → sys_user(id)
  amount             NUMERIC(18,2) NOT NULL,          -- 发放金额（元）
  period             VARCHAR(32),
  pay_channel        VARCHAR(32),                     -- 工资/专项，逻辑引用 sys_dict
  approver_ids       JSONB NOT NULL DEFAULT '[]'::jsonb, -- 审批链快照 [{userId,at,action}]
  approved_at        TIMESTAMPTZ,
  paid_at            TIMESTAMPTZ,
  voucher_code       VARCHAR(64),                     -- 联动 F 凭证（逻辑外键）
  reject_reason      VARCHAR(512)
);
CREATE UNIQUE INDEX uk_m_payout_record ON m_payout(record_id) WHERE deleted = 0 AND status <> 'REJECTED';
CREATE UNIQUE INDEX uk_m_payout_code  ON m_payout(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_m_payout_tenant_st   ON m_payout(tenant_id, status);

COMMENT ON TABLE  m_payout IS '绩效发放单：从 APPROVED 记录发起的在线审批付款（模块 M）';
COMMENT ON COLUMN m_payout.status IS '状态机 token：DRAFT/APPROVING/APPROVED/PAID/REJECTED';
