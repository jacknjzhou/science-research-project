-- =============================================================================
-- 05-科技成果转化-T.ddl.sql · 科技成果转化（T）模块建表脚本
-- 版本 v1.0 · 2026-10-13
-- 上游：../PRD/05-科技成果转化.md（表清单 + 功能 T-01..T-19 + 状态机 §6.2 + 异常 §11）、
--       ./README.md（全局约定 §2 数据库 / §3 API / §4 状态 token / §5 共享实体登记表）
-- 方言：PostgreSQL 15
--
-- 【信创达梦差异声明（对齐 design/README.md §2.4，达梦部署时按此替换）】
--   1) 自增主键：GENERATED ALWAYS AS IDENTITY  →  IDENTITY(1,1)
--   2) 时间戳：  TIMESTAMPTZ                    →  TIMESTAMP WITH TIME ZONE
--   3) 布尔：    BOOLEAN                        →  SMALLINT（0/1）
--   4) 半结构：  JSONB                          →  CLOB/VARCHAR 存 JSON 文本 + 应用层解析
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0  →  普通唯一索引 + deleted 复合键
--   6) 全文检索 GIN/trigram (pg_trgm/tsvector)   →  应用层 ES / 达梦全文索引
--   7) 表达式唯一索引中的函数（如 COALESCE）      →  应用层生成哈希列后建普通唯一索引
--
-- 【通用列（§2.1，所有业务表内联，列名列型完全一致，DDL 不再逐表注释）】
--   id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--   code VARCHAR(64), tenant_id BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
--   deleted SMALLINT NOT NULL DEFAULT 0, creator_id BIGINT NOT NULL, modifier_id BIGINT,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--   remark TEXT
--
-- 【单号前缀（§2.3 / PRD 2.11，以 00-common.sql seq_prefix_registry 为唯一来源）】
--   T_DEAL.code 已登记前缀 `DEAL`（pattern=DEAL-年-序，per_entity 分号段），由统一编号中心下发。
--   其余 T 表 code 暂留通用值（PRD 2.11 尚未为披露/合同/分配等登记独立前缀，见 detail §10）；
--   正式前缀登记后方可下发，本脚本仅建列 + 部分唯一索引，不建强 CHECK。
--
-- 【跨模块引用（§5 共享实体登记表）】
--   output_id  → R_OUTPUT.id（04 成果管理，逻辑外键，跨微服务库不建物理 FK）
--   project_id → E_PROJECT.id（02 项目过程，逻辑外键）
--   finance_receipt_id → 03 经费到账/认领（received 入账关联 F，逻辑外键）
--   *_user_id  → sys_user.id（07 人员/横切，逻辑外键）；department_id → sys_org.id
-- 【同模块物理外键（§2.3 允许）】T_DISCLOSURE/T_VALUATION/T_DEAL/T_CONTRACT/T_APPROVAL_CHAIN/
--   T_INCOME/T_DISTRIBUTION_RULE/T_DISTRIBUTION_RECORD/T_PUBLICITY/T_ENTERPARTNER 之间用 REFERENCES。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1) T_DISCLOSURE · 成果披露（拟转化清单，T-01）—— 聚合根
-- -----------------------------------------------------------------------------
CREATE TABLE T_DISCLOSURE (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','SUBMITTED','UNDER_EVAL','DEALING','COMPLETED','REJECTED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  output_id            BIGINT       NOT NULL,                        -- 逻辑引用 R_OUTPUT.id（04）
  project_id           BIGINT,                                       -- 逻辑引用 E_PROJECT.id（02，可空）
  disclosed_by         BIGINT       NOT NULL,                        -- 发明人 sys_user.id（逻辑引用）
  department_id        BIGINT,                                       -- sys_org.id（逻辑引用）
  disclosure_date      DATE         NOT NULL,
  tech_summary         TEXT,
  application_scenarios JSONB       NOT NULL DEFAULT '[]',           -- 应用场景 [{scene,desc,value}]
  maturity_level       SMALLINT     CHECK (maturity_level BETWEEN 1 AND 9), -- 技术成熟度 TRL 1-9
  is_core_tech         BOOLEAN      NOT NULL DEFAULT FALSE,          -- 是否核心/涉密技术
  target_partners      JSONB        NOT NULL DEFAULT '[]',           -- 目标客户 [{name,industry,reason}]
  expected_value       NUMERIC(18,2),                                -- 发明人预期价值（意向价，参考）
  submitted_at         TIMESTAMPTZ,                                  -- 提交时间（触发 disclosure.submitted）
  -- 治理字段（法人隔离 + 涉密通道，见 detail §7）
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_disclosure_code ON T_DISCLOSURE(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_disclosure_main       ON T_DISCLOSURE(tenant_id, status);
CREATE INDEX idx_disclosure_output     ON T_DISCLOSURE(output_id);
CREATE INDEX idx_disclosure_by         ON T_DISCLOSURE(tenant_id, disclosed_by);        -- 我的披露清单
CREATE INDEX idx_disclosure_scenarios  ON T_DISCLOSURE USING GIN (application_scenarios jsonb_path_ops);
COMMENT ON TABLE  T_DISCLOSURE IS '成果披露（拟转化清单，T-01）：发明人一键把成果标记为拟转化并发起披露';
COMMENT ON COLUMN T_DISCLOSURE.status IS '披露状态机 token：DRAFT/SUBMITTED/UNDER_EVAL/DEALING/COMPLETED/REJECTED（对齐 PRD §5.1）';
COMMENT ON COLUMN T_DISCLOSURE.output_id IS '逻辑引用 R_OUTPUT.id（04 成果），跨微服务库不建物理外键';
COMMENT ON COLUMN T_DISCLOSURE.maturity_level IS '技术成熟度 TRL 1-9（PRD §5.1）';

-- -----------------------------------------------------------------------------
-- 2) T_VALUATION · 资产评估（内评/外评，T-03/T-04）
-- -----------------------------------------------------------------------------
CREATE TABLE T_VALUATION (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','ASSIGNED','REPORT_UPLOADED','CONFIRMED','INVALID')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  disclosure_id        BIGINT       NOT NULL REFERENCES T_DISCLOSURE(id),   -- 同模块物理外键
  valuator_type        VARCHAR(16)  NOT NULL CHECK (valuator_type IN ('INTERNAL','EXTERNAL')), -- 内评/外评
  valuator_name        VARCHAR(128),                               -- 评估人/评估机构经办人
  valuator_org         VARCHAR(256),                               -- 第三方评估机构名称（外评）
  method               VARCHAR(16)  CHECK (method IN ('收益法','成本法','市场法')), -- 评估方法（sys_dict 可配）
  valuation_amount     NUMERIC(18,2),                              -- 评估金额
  currency             VARCHAR(8)   NOT NULL DEFAULT 'CNY',
  report_url           VARCHAR(512),                               -- 评估报告（外评上传对象存储）
  valuation_date       DATE,
  valid_until          DATE,                                       -- 评估结论有效期
  ai_pricing_ref       JSONB                                       -- T-19 AI 定价参考快照（区间/依据/案例，仅供参考）
);
CREATE UNIQUE INDEX uk_valuation_code   ON T_VALUATION(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_valuation_disclosure   ON T_VALUATION(disclosure_id);
CREATE INDEX idx_valuation_main         ON T_VALUATION(tenant_id, status);
CREATE INDEX idx_valuation_type         ON T_VALUATION(tenant_id, valuator_type);
COMMENT ON TABLE  T_VALUATION IS '资产评估（T-03 内评 / T-04 第三方外评）：1:N 挂披露，支持内部小组与外部机构两种路径';
COMMENT ON COLUMN T_VALUATION.valuator_type IS '评估类型：INTERNAL 内部评估小组 / EXTERNAL 第三方机构';
COMMENT ON COLUMN T_VALUATION.method IS '评估方法：收益法/成本法/市场法（可配 sys_dict，PRD 2.8）';
COMMENT ON COLUMN T_VALUATION.ai_pricing_ref IS 'T-19 AI 定价参考输出快照（定价区间+依据+可比案例），仅供参考不硬约束';

-- -----------------------------------------------------------------------------
-- 3) T_ENTERPARTNER · 合作企业库（意向企业登记 + 工商真实性，T-06 / PRD §11）
-- -----------------------------------------------------------------------------
CREATE TABLE T_ENTERPARTNER (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('PENDING','ACTIVE','BLACKLIST','EXPIRED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  company_name         VARCHAR(256) NOT NULL,                      -- PRD §5.1 name（企业名）
  credit_code          VARCHAR(64),                                -- 统一社会信用代码
  industry             VARCHAR(64),                                -- 所属行业
  register_status      VARCHAR(32),                                -- 工商登记状态（存续/注销/吊销）
  business_check_json  JSONB,                                      -- 天眼查/企查查返回快照（真实性校验）
  check_abnormal       BOOLEAN      NOT NULL DEFAULT FALSE,        -- 工商 API 异常/风险 → 签约前标红
  last_checked_at      TIMESTAMPTZ,                                -- 最近一次工商核验时间
  tech_needs           JSONB        NOT NULL DEFAULT '[]',         -- 企业公开技术需求 [{need,source,url}]
  contact              JSONB,                                      -- 联系人 {name,title,phone,email}
  past_deals           JSONB        NOT NULL DEFAULT '[]',         -- 历史合作交易 [{deal_id,deal_type,amount,year}]
  evaluation_score     NUMERIC(6,4)                                -- 合作评价分（0-1，供 AI 匹配参考）
);
CREATE UNIQUE INDEX uk_enterpartner_code  ON T_ENTERPARTNER(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_enterpartner_credit ON T_ENTERPARTNER(tenant_id, credit_code) WHERE deleted = 0 AND credit_code IS NOT NULL;
CREATE INDEX idx_enterpartner_main        ON T_ENTERPARTNER(tenant_id, status);
CREATE INDEX idx_enterpartner_name        ON T_ENTERPARTNER USING GIN (company_name gin_trgm_ops); -- 模糊检索（需 pg_trgm）
CREATE INDEX idx_enterpartner_needs       ON T_ENTERPARTNER USING GIN (tech_needs jsonb_path_ops);  -- AI 机会识别匹配
COMMENT ON TABLE  T_ENTERPARTNER IS '合作企业库（T-06）：意向企业登记 + 工商真实性核验 + 技术需求，供 AI 转化机会识别';
COMMENT ON COLUMN T_ENTERPARTNER.check_abnormal IS 'PRD §11 交易对手风险：签约前调工商 API 校验，异常/注销/失信置 TRUE 前端标红';
COMMENT ON COLUMN T_ENTERPARTNER.tech_needs IS '企业公开技术需求 JSONB，供 T-17 向量化匹配（专利族 ↔ 需求）';

-- -----------------------------------------------------------------------------
-- 4) T_DEAL · 转化交易（状态机主体，T-02/T-07/T-08/T-09）
--     code 前缀已登记：DEAL-年-序（00-common.sql seq_prefix_registry，per_entity）
-- -----------------------------------------------------------------------------
CREATE TABLE T_DEAL (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),                                -- DEAL-年-序（统一编号中心下发）
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN (
                         'DRAFT','VALUATED','NEGOTIATING','DRAFT_CONTRACT','UNDER_APPROVAL','APPROVED',
                         'PUBLICIZED','SIGNED','EXECUTING','INCOME_RECEIVED','DISTRIBUTED','CLOSED','TERMINATED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  disclosure_id        BIGINT       NOT NULL REFERENCES T_DISCLOSURE(id),   -- 同模块物理外键
  output_id            BIGINT       NOT NULL,                        -- 逻辑引用 R_OUTPUT.id（04）
  project_id           BIGINT,                                       -- 逻辑引用 E_PROJECT.id（02）
  enterpartner_id      BIGINT REFERENCES T_ENTERPARTNER(id),         -- N:1 合作企业库（PRD §5.2）
  deal_type            VARCHAR(16)  NOT NULL
                       CHECK (deal_type IN ('转让','独占许可','排他许可','普通许可','作价投资','合作实施')), -- T-02
  partner_name         VARCHAR(256),                                 -- 交易对手方名称（快照）
  partner_credit_code  VARCHAR(64),                                  -- 对手方信用代码（快照）
  contract_amount      NUMERIC(18,2) NOT NULL DEFAULT 0,             -- 成交/合同金额
  payment_method       VARCHAR(24)  NOT NULL DEFAULT '一次性'
                       CHECK (payment_method IN ('一次性','分期','入门费+销售提成')),                       -- T-02/§11
  initial_fee          NUMERIC(18,2),                                -- 入门费（入门费+销售提成模式）
  royalty_rate         NUMERIC(6,4),                                 -- 销售提成比例（royalty）
  term_start           DATE,
  term_end             DATE,
  partner_check_abnormal BOOLEAN    NOT NULL DEFAULT FALSE,          -- 工商核验异常标红（签约前阻断）
  partner_checked_at   TIMESTAMPTZ,
  -- 作价入股额外管理（PRD §11）
  equity_ratio         NUMERIC(6,4),                                 -- 入股股权比例（deal_type=作价投资）
  equity_value         NUMERIC(18,2),                                -- 作价入股金额
  exit_arrangement     JSONB,                                        -- 退出机制/收益安排 {exit_type,trigger,terms}
  -- 审批门槛快照（T-08：命中制度包复算）
  policy_pack_id       BIGINT,                                       -- 审批权限门槛命中的 sys_policy_pack.id
  approval_required_level VARCHAR(32)
                       CHECK (approval_required_level IN
                         ('LEGAL','FINANCE','INSTITUTE','COMPETENT_DEPT','BOARD')), -- 需达到的最高审批层级
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  signed_at            TIMESTAMPTZ,                                  -- 电子签完成时间（触发 deal.signed）
  terminated_reason    VARCHAR(32)  CHECK (terminated_reason IN
                       ('NEGOTIATION_BREAK','OBJECTION_SUSTAINED','PARTNER_RISK','BREACH','OTHER')) -- TERMINATED 触发因
);
CREATE UNIQUE INDEX uk_deal_code      ON T_DEAL(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_deal_main            ON T_DEAL(tenant_id, legal_entity_id, status);   -- 交易列表主路径 <500ms
CREATE INDEX idx_deal_disclosure      ON T_DEAL(disclosure_id);
CREATE INDEX idx_deal_output          ON T_DEAL(output_id);
CREATE INDEX idx_deal_partner         ON T_DEAL(enterpartner_id);
CREATE INDEX idx_deal_project         ON T_DEAL(project_id);
CREATE INDEX idx_deal_type            ON T_DEAL(tenant_id, deal_type, payment_method);
COMMENT ON TABLE  T_DEAL IS '转化交易（状态机主体，T-02/T-07/T-08/T-09）：承载定价、谈判、审批、签约、执行、到账、分配全链';
COMMENT ON COLUMN T_DEAL.status IS '交易状态机 token（PRD §6.2）：DRAFT/VALUATED/NEGOTIATING/DRAFT_CONTRACT/UNDER_APPROVAL/APPROVED/PUBLICIZED/SIGNED/EXECUTING/INCOME_RECEIVED/DISTRIBUTED/CLOSED + 异常 TERMINATED';
COMMENT ON COLUMN T_DEAL.deal_type IS '转化方式（T-02）：转让/独占许可/排他许可/普通许可/作价投资/合作实施';
COMMENT ON COLUMN T_DEAL.payment_method IS '支付方式：一次性/分期/入门费+销售提成（分期与提成各自触发分配，见 detail §4）';
COMMENT ON COLUMN T_DEAL.approval_required_level IS 'T-08 规则引擎判定需达到的最高审批层级（金额阈值→院所/理事会 BOARD）';

-- -----------------------------------------------------------------------------
-- 5) T_CONTRACT · 转化合同（起草/签审/电子签/归档，T-08/T-10；交易记录不可篡改）
-- -----------------------------------------------------------------------------
CREATE TABLE T_CONTRACT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','UNDER_APPROVAL','TO_SIGN','SIGNED','AMENDING','ARCHIVED','TERMINATED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  deal_id              BIGINT       NOT NULL REFERENCES T_DEAL(id),   -- 1:1（PRD §5.2），同模块物理外键
  contract_no          VARCHAR(64),                                   -- 合同编号（对外）
  template_code        VARCHAR(64),                                   -- 合同模板 sys_print_template.code
  contract_file_url    VARCHAR(512),                                  -- 合同正文（永久保留，对象存储）
  redline_file_url     VARCHAR(512),                                  -- 红线版留存（PRD 7.4）
  signed_at            TIMESTAMPTZ,
  seal_records         JSONB        NOT NULL DEFAULT '[]',            -- 电子签记录 [{provider,seal_id,party,signed_at,sig_hash}]
  legal_opinion        TEXT,                                          -- 法务意见
  finance_opinion      TEXT,                                          -- 财务意见
  leader_opinion       TEXT,                                          -- 院所领导意见
  ai_risk_report       JSONB,                                         -- T-18 AI 条款风险审查结果 [{clause,severity,issue,suggestion,ref_article}]
  version              INT          NOT NULL DEFAULT 1,               -- 变更版本（重大变更走重新审批链）
  immutable_hash       VARCHAR(128),                                  -- 本版本内容哈希（哈希链，防篡改）
  prev_hash            VARCHAR(128)                                   -- 上一版本哈希（链式）
);
CREATE UNIQUE INDEX uk_contract_code ON T_CONTRACT(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_contract_deal ON T_CONTRACT(deal_id) WHERE deleted = 0;   -- 一交易一有效合同
CREATE INDEX idx_contract_main       ON T_CONTRACT(tenant_id, status);
CREATE INDEX idx_contract_no         ON T_CONTRACT(tenant_id, contract_no);
COMMENT ON TABLE  T_CONTRACT IS '转化合同（T-08/T-10）：与交易 1:1，承载模板起草、多级意见、电子签章、红线留存、哈希链防篡改';
COMMENT ON COLUMN T_CONTRACT.deal_id IS '逻辑上 1:1（PRD §5.2 T_DEAL 1──1 T_CONTRACT），有效合同唯一索引 WHERE deleted=0';
COMMENT ON COLUMN T_CONTRACT.immutable_hash IS '合同内容哈希，配合 prev_hash 构成哈希链；交易记录不可篡改（PRD §12 合规）';
COMMENT ON COLUMN T_CONTRACT.seal_records IS '电子签章记录 JSONB（e签宝/法大大/CFCA），含各方签名哈希与时间戳';

-- -----------------------------------------------------------------------------
-- 6) T_APPROVAL_CHAIN · 多级审批链（法务/财务/院所/主管/理事会，T-09）
-- -----------------------------------------------------------------------------
CREATE TABLE T_APPROVAL_CHAIN (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','APPROVED','REJECTED','RETURNED','SKIPPED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  deal_id              BIGINT       NOT NULL REFERENCES T_DEAL(id),   -- 同模块物理外键
  step_order           INT          NOT NULL,                         -- 审批步序（顺序或并行分组）
  parallel_group       VARCHAR(32),                                   -- 并行组标识（同组并行审批）
  approver_role        VARCHAR(32)  NOT NULL
                       CHECK (approver_role IN ('LEGAL','FINANCE','INSTITUTE','COMPETENT_DEPT','BOARD')), -- 法务/财务/院所/主管/理事会
  approver_id          BIGINT,                                        -- sys_user.id（逻辑引用）
  action               VARCHAR(16)  CHECK (action IN ('APPROVE','REJECT','RETURN','SKIP')),
  comment              TEXT,                                          -- 审批意见（完整留痕）
  amount_threshold     NUMERIC(18,2),                                 -- 触发该层审批的金额阈值快照（T-08）
  policy_pack_id       BIGINT,                                        -- 命中制度包快照（可复算）
  acted_at             TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_approval_code ON T_APPROVAL_CHAIN(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_approval_step ON T_APPROVAL_CHAIN(deal_id, step_order) WHERE deleted = 0;
CREATE INDEX idx_approval_deal       ON T_APPROVAL_CHAIN(deal_id);
CREATE INDEX idx_approval_main       ON T_APPROVAL_CHAIN(tenant_id, status);
CREATE INDEX idx_approval_approver   ON T_APPROVAL_CHAIN(tenant_id, approver_id, acted_at);
COMMENT ON TABLE  T_APPROVAL_CHAIN IS '多级审批链（T-09）：1:N 挂交易，每级审批留痕（谁在何时说了什么），支持顺序/并行';
COMMENT ON COLUMN T_APPROVAL_CHAIN.approver_role IS '审批层级：LEGAL 法务/FINANCE 财务/INSTITUTE 院所/COMPETENT_DEPT 主管部门/BOARD 理事会（>500 万门槛）';
COMMENT ON COLUMN T_APPROVAL_CHAIN.policy_pack_id IS 'T-08 审批权限门槛命中的制度包快照，配合 sys_rule_hit 可解释可复算';

-- -----------------------------------------------------------------------------
-- 7) T_INCOME · 转化到账登记与匹配（T-11；分期/提成按期入账）
-- -----------------------------------------------------------------------------
CREATE TABLE T_INCOME (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','MATCHED','ALLOCATED','REVERSED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  deal_id              BIGINT       NOT NULL REFERENCES T_DEAL(id),   -- 1:N（PRD §5.2）
  finance_receipt_id   BIGINT,                                       -- 逻辑引用 03 经费到账/认领（received 入账关联 F）
  received_date        DATE         NOT NULL,
  amount               NUMERIC(18,2) NOT NULL,                        -- 到账金额
  currency             VARCHAR(8)   NOT NULL DEFAULT 'CNY',
  receipt_no           VARCHAR(64),                                   -- 收据编号
  bank_flow_no         VARCHAR(64),                                   -- 银行流水号（匹配键）
  payment_phase        VARCHAR(32),                                   -- 期次描述（一次性/第 N 期/提成期）
  sales_amount         NUMERIC(18,2),                                 -- 企业上报销售额（提成模式）
  royalty_calc_amount  NUMERIC(18,2),                                 -- 按 sales_amount×royalty_rate 计算提成
  voucher_url          VARCHAR(512),                                  -- 到账凭证
  allocated            BOOLEAN      NOT NULL DEFAULT FALSE            -- 是否已分配（触发 income.received→分配计算）
);
CREATE UNIQUE INDEX uk_income_code     ON T_INCOME(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_income_bankflow ON T_INCOME(tenant_id, bank_flow_no) WHERE deleted = 0 AND bank_flow_no IS NOT NULL; -- 防重复登记
CREATE INDEX idx_income_deal           ON T_INCOME(deal_id);
CREATE INDEX idx_income_main           ON T_INCOME(tenant_id, status);
CREATE INDEX idx_income_received       ON T_INCOME(tenant_id, received_date);
CREATE INDEX idx_income_allocated      ON T_INCOME(tenant_id, allocated);   -- 待分配扫描
COMMENT ON TABLE  T_INCOME IS '转化到账登记与匹配（T-11）：1:N 挂交易，支持一次性/分期/销售提成按期入账，触发分配计算';
COMMENT ON COLUMN T_INCOME.finance_receipt_id IS '逻辑引用 03 经费模块到账/认领记录（跨微服务库不建物理 FK，一致性走事件）';
COMMENT ON COLUMN T_INCOME.allocated IS 'FALSE 时进入待分配队列；到账登记生成 income.received 事件驱动分配明细生成';

-- -----------------------------------------------------------------------------
-- 8) T_DISTRIBUTION_RULE · 收益分配规则字典（T-12；历史留档、可配置）
-- -----------------------------------------------------------------------------
CREATE TABLE T_DISTRIBUTION_RULE (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  rule_name            VARCHAR(128) NOT NULL,
  applies_to           VARCHAR(16)  NOT NULL
                       CHECK (applies_to IN ('转让','许可','作价')),             -- 适用转化方式（T-12）
  team_pct             NUMERIC(6,4) NOT NULL,                          -- 团队比例
  institute_pct        NUMERIC(6,4) NOT NULL,                          -- 院所比例
  individual_pct       NUMERIC(6,4) NOT NULL,                          -- 个人比例
  min_team_pct         NUMERIC(6,4) NOT NULL,                          -- 团队最低限（低于则拦截，PRD 7.5）
  policy_ref           VARCHAR(256),                                   -- 政策依据条款
  policy_pack_id       BIGINT,                                         -- 命中/关联制度包
  effective_from       DATE         NOT NULL,
  effective_to         DATE,
  active               BOOLEAN      NOT NULL DEFAULT TRUE,
  CONSTRAINT ck_dist_rule_sum CHECK (ABS(team_pct + institute_pct + individual_pct - 1) < 0.0001)
);
CREATE UNIQUE INDEX uk_distrule_code    ON T_DISTRIBUTION_RULE(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_distrule_lookup        ON T_DISTRIBUTION_RULE(tenant_id, applies_to, active);
CREATE INDEX idx_distrule_effective     ON T_DISTRIBUTION_RULE(applies_to, effective_from, effective_to);
COMMENT ON TABLE  T_DISTRIBUTION_RULE IS '收益分配规则字典（T-12）：团队/院所/个人比例与团队最低限，历史版本留档可复算';
COMMENT ON COLUMN T_DISTRIBUTION_RULE.min_team_pct IS 'T-12 确定性拦截线：team_pct < min_team_pct 直接拒绝保存（规则引擎判定，非 LLM）';
COMMENT ON COLUMN T_DISTRIBUTION_RULE.applies_to IS '适用方式：转让/许可/作价（作价入股另关联股权/退出管理）';

-- -----------------------------------------------------------------------------
-- 9) T_DISTRIBUTION_RECORD · 收益分配明细（T-12/T-13；发放到人，争议可暂缓）
-- -----------------------------------------------------------------------------
CREATE TABLE T_DISTRIBUTION_RECORD (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','GENERATED','PUBLISHED','CONFIRMED','DISPUTED','HELD','ISSUED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  income_id            BIGINT       NOT NULL REFERENCES T_INCOME(id),   -- 1:1（PRD §5.2）
  deal_id              BIGINT       NOT NULL REFERENCES T_DEAL(id),     -- 同模块物理外键
  rule_id              BIGINT REFERENCES T_DISTRIBUTION_RULE(id),       -- N:1
  total_amount         NUMERIC(18,2) NOT NULL DEFAULT 0,                -- 本次分配总额（到账净额）
  team_amount          NUMERIC(18,2) NOT NULL DEFAULT 0,
  institute_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
  individual_amount    NUMERIC(18,2) NOT NULL DEFAULT 0,
  breakdown            JSONB        NOT NULL DEFAULT '[]',              -- [{user_id,pct,amount,basis}] 明细到人
  policy_pack_id       BIGINT,                                          -- 分配规则命中快照（可复算）
  dispute_note         TEXT,                                            -- 发明人异议/仲裁说明（暂缓发放）
  held_reason          VARCHAR(32)  CHECK (held_reason IN ('DISPUTE','ARBITRATION','OBJECTION','OTHER')),
  issued_at            TIMESTAMPTZ                                      -- 发放到人时间（触发 distribution.issued）
);
CREATE UNIQUE INDEX uk_distrec_code   ON T_DISTRIBUTION_RECORD(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_distrec_income ON T_DISTRIBUTION_RECORD(income_id) WHERE deleted = 0;  -- 一期到账一分配明细
CREATE INDEX idx_distrec_deal         ON T_DISTRIBUTION_RECORD(deal_id);
CREATE INDEX idx_distrec_main         ON T_DISTRIBUTION_RECORD(tenant_id, status);
CREATE INDEX idx_distrec_breakdown    ON T_DISTRIBUTION_RECORD USING GIN (breakdown jsonb_path_ops); -- 按 user_id 查"与我相关"
COMMENT ON TABLE  T_DISTRIBUTION_RECORD IS '收益分配明细（T-12/T-13）：1:1 挂到账，团队/院所/个人三拆 + breakdown 到人，争议可 HELD 暂缓';
COMMENT ON COLUMN T_DISTRIBUTION_RECORD.status IS 'DISPUTED 争议中/HELD 仲裁暂缓发放；员工仅见 breakdown 中与自己相关条目（detail §7）';

-- -----------------------------------------------------------------------------
-- 10) T_PUBLICITY · 公示记录（T-14；公示倒计时 + 异议独立状态机，记录保留 10 年）
-- -----------------------------------------------------------------------------
CREATE TABLE T_PUBLICITY (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'PUBLISHED'
                       CHECK (status IN ('DRAFT','PUBLISHED','IN_PROGRESS','OBJECTION_PENDING','OBJECTION_RESOLVED','COMPLETED','TERMINATED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  deal_id              BIGINT       NOT NULL REFERENCES T_DEAL(id),   -- 1:N（PRD §5.2）
  publish_start_at     TIMESTAMPTZ  NOT NULL,                          -- 公示开始（deal.signed 触发倒计时）
  publish_end_at       TIMESTAMPTZ  NOT NULL,                          -- 公示截止（倒计时到期→无异议进执行）
  duration_days        INT          NOT NULL DEFAULT 15,               -- 公示天数
  url                  VARCHAR(512),                                   -- 公开 URL（不登录可看，走 CDN）
  summary_json         JSONB        NOT NULL DEFAULT '{}',             -- 对外摘要 {subject,output_summary,valuation,deal_amount,distribution}
  objections           JSONB        NOT NULL DEFAULT '[]',             -- [{objection_id,submitter,contact,content,submitted_at,handle_status,handle_result,handled_at}]
  objection_open       BOOLEAN      NOT NULL DEFAULT FALSE,            -- 存在未结异议 → 阻断进入 EXECUTING（PRD §11）
  public_snapshot_hash VARCHAR(128)                                    -- 公示内容快照哈希（防篡改，留档 10 年）
);
CREATE UNIQUE INDEX uk_publicity_code ON T_PUBLICITY(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_publicity_deal       ON T_PUBLICITY(deal_id);
CREATE INDEX idx_publicity_main       ON T_PUBLICITY(tenant_id, status);
CREATE INDEX idx_publicity_countdown  ON T_PUBLICITY(publish_end_at, objection_open);  -- 倒计时/异议未结扫描
COMMENT ON TABLE  T_PUBLICITY IS '公示记录（T-14）：1:N 挂交易，公开门户展示 + 异议提交通道；公示记录保留 10 年';
COMMENT ON COLUMN T_PUBLICITY.objection_open IS 'PRD §11：异议未处理前不得进入执行阶段；由独立异议状态机驱动收敛';
COMMENT ON COLUMN T_PUBLICITY.summary_json IS '对外公开摘要（交易主体/成果摘要/评估价/成交价/分配情况），脱敏后仅摘要可见';

-- -----------------------------------------------------------------------------
-- 11) T_ANNUAL_REPORT · 年度转化报告（T-15/T-14；一键生成 PDF，满足法定披露）
-- -----------------------------------------------------------------------------
CREATE TABLE T_ANNUAL_REPORT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','GENERATED','PUBLISHED','EXPORTED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  report_year          INT          NOT NULL,                          -- 报告年度（PRD §5.1 year，规避关键字）
  total_deals          INT          NOT NULL DEFAULT 0,                -- 全年成交笔数
  total_contract_amount NUMERIC(18,2) NOT NULL DEFAULT 0,              -- 全年合同总额
  total_income         NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 全年到账总额
  total_distributed    NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 全年已分配总额
  top_deals            JSONB        NOT NULL DEFAULT '[]',             -- 标杆交易 [{deal_id,code,title,amount,type}]
  distribution_summary JSONB,                                          -- 分配汇总（团队/院所/个人）
  report_file_url      VARCHAR(512),                                   -- 生成的 PDF（套打模板）
  generated_at         TIMESTAMPTZ,
  published_at         TIMESTAMPTZ,
  legal_entity_id      BIGINT                                          -- 法人维度可分组上报
);
CREATE UNIQUE INDEX uk_annual_code ON T_ANNUAL_REPORT(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_annual_year ON T_ANNUAL_REPORT(tenant_id, report_year, COALESCE(legal_entity_id, 0)) WHERE deleted = 0;
CREATE INDEX idx_annual_main       ON T_ANNUAL_REPORT(tenant_id, status);
COMMENT ON TABLE  T_ANNUAL_REPORT IS '年度转化报告（T-15/T-14）：一键生成满足《促进科技成果转化法》年度披露，可导出主管部门';
COMMENT ON COLUMN T_ANNUAL_REPORT.report_year IS '报告年度（PRD §5.1 的 year，规避保留字命名）；(tenant_id,report_year,legal_entity_id) 唯一';

-- =============================================================================
-- 建表完毕：T 模块共 11 张表
--   T_DISCLOSURE · T_VALUATION · T_ENTERPARTNER · T_DEAL · T_CONTRACT ·
--   T_APPROVAL_CHAIN · T_INCOME · T_DISTRIBUTION_RULE · T_DISTRIBUTION_RECORD ·
--   T_PUBLICITY · T_ANNUAL_REPORT
-- =============================================================================
