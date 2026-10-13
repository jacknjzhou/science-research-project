-- =============================================================================
-- 03-科研经费管理-F.ddl.sql · 模块 F（Funding）建表脚本
-- 版本 v1.1 · 2026-10-13
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4，达梦部署时按此替换）
-- 上游：design/README.md §2 数据库约定 / §4 状态 token；PRD/03-科研经费管理.md
-- 覆盖表：F_SUBJECT · F_BUDGET · F_BUDGET_LINE · F_INCOME · F_EXPENSE ·
--         F_EXPENSE_APPROVAL · F_INVOICE · F_VOUCHER_SYNC · F_INDIRECT_FEE ·
--         F_SETTLEMENT · F_ANOMALY · F_BUDGET_FORECAST · F_COST_POOL ·
--         F_ACCOUNTING_ENTRY · F_DISBURSEMENT
--
-- 【信创达梦差异注记（本模块专用，顶部统一声明）】
--   1) 自增主键  PG: BIGINT GENERATED ALWAYS AS IDENTITY  →  达梦: BIGINT IDENTITY(1,1)
--   2) 时间戳    PG: TIMESTAMPTZ                          →  达梦: TIMESTAMP WITH TIME ZONE
--   3) 布尔      PG: BOOLEAN                              →  达梦: SMALLINT（0/1）
--   4) JSONB     PG: JSONB（invoice_ids/calc_detail/indirect_alloc_json/
--                fin_entry_json/bud_entry_json/score_detail 等）
--                →  达梦: CLOB/VARCHAR 存 JSON 文本 + 应用层解析；表达式索引改应用层维护
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0
--                →  达梦: 以普通唯一索引 + (tenant_id,code,deleted) 复合键替代
--   6) CHECK(col IN(...)) 枚举  PG/达梦一致，保持 VARCHAR+CHECK（便于灰度扩值，不建原生 ENUM）
--   7) 全文/向量检索  PG: pg_trgm/tsvector/pgvector  →  达梦: 应用层 ES / Milvus 独立服务
--
-- 【金额/时间/半结构化】金额一律 NUMERIC(18,2)（元）；比例/置信度 NUMERIC(6,4)；
--   时间 TIMESTAMPTZ（落库 UTC，展示 Asia/Shanghai）；纯日期 DATE；半结构化 JSONB。
-- 【跨模块引用】E_PROJECT(project_id) / S_STAFF / G_CONTRACT(contract_id) /
--   G_SUPPLIER(outsource_unit_id) / sys_policy_pack(policy_pack_id) 只存对方主键 id，
--   不建物理外键（微服务库隔离）；同模块内允许物理外键（见下）。
-- 【单号前缀】预算 BUD、报销 EXP、外拨 DISB（PRD 2.11 注册表，取自统一编号中心 svc-numbering）。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- F-01 · F_SUBJECT 经费科目字典（树形，PRD 5.1；对齐 sys_dict 主数据但独立业务语义）
-- -----------------------------------------------------------------------------
CREATE TABLE F_SUBJECT (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64),
  tenant_id       BIGINT       NOT NULL,
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                  CHECK (status IN ('ACTIVE','INACTIVE','SUPERSEDED')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT,
  -- 业务列
  name            VARCHAR(128) NOT NULL,
  parent_id       BIGINT       REFERENCES F_SUBJECT(id),      -- 树形上级（同模块物理外键）
  level           SMALLINT     NOT NULL DEFAULT 1,            -- 层级，根为 1
  category        VARCHAR(16)  NOT NULL
                  CHECK (category IN ('DIRECT','INDIRECT','PERFORMANCE')),  -- 直接/间接/绩效
  is_leaf         BOOLEAN      NOT NULL DEFAULT TRUE,         -- 是否末级（仅末级可挂预算行）
  ratio_limit     NUMERIC(6,4),                               -- 比例上限（如设备费 0.30），规则引擎读取
  applies_to      JSONB,                                      -- 适用项目类型集合 ["NSFC","KJBP",...]
  sort_no         INT          NOT NULL DEFAULT 0,
  effective_from  DATE,
  effective_to    DATE
);
CREATE UNIQUE INDEX uk_subject_code ON F_SUBJECT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_subject_tenant_status ON F_SUBJECT(tenant_id, status);
CREATE INDEX idx_subject_parent ON F_SUBJECT(parent_id);
COMMENT ON TABLE  F_SUBJECT IS '经费科目字典（F-01）：树形科目，携带比例上限，供规则引擎判定预算比例';
COMMENT ON COLUMN F_SUBJECT.category      IS '科目大类：DIRECT=直接费用/INDIRECT=间接费用/PERFORMANCE=绩效支出';
COMMENT ON COLUMN F_SUBJECT.ratio_limit   IS '科目占比上限（0-1），预算编制/调整时由 svc-policy 校验超限';
COMMENT ON COLUMN F_SUBJECT.is_leaf       IS '仅末级科目允许挂 F_BUDGET_LINE';
COMMENT ON COLUMN F_SUBJECT.applies_to    IS '适用项目类型（JSONB 数组），与 sys_dict project_type 对齐';


-- -----------------------------------------------------------------------------
-- F-02/F-03/F-04 · F_BUDGET 项目预算主表（预算制/包干制）
-- -----------------------------------------------------------------------------
CREATE TABLE F_BUDGET (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64),                                -- BUD-年-序（统一编号中心分配）
  tenant_id       BIGINT       NOT NULL,
  status          VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                  CHECK (status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','APPROVED',
                                    'EXECUTING','ADJUSTING','RE_APPROVED','CLOSED')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT,
  -- 业务列
  project_id      BIGINT       NOT NULL,                      -- 逻辑引用 E_PROJECT(id)
  legal_entity_id BIGINT       NOT NULL,                      -- 主责法人（PRD 2.12，成本并表口径）
  mode            VARCHAR(8)   NOT NULL DEFAULT '预算制'
                  CHECK (mode IN ('预算制','包干制')),         -- 经费管理模式（字典可配，PRD 2.8）
  total_approved  NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 批复总额
  total_adjusted  NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 调整后总额
  version         INT          NOT NULL DEFAULT 1,            -- 预算版本号（调整递增）
  approved_at     TIMESTAMPTZ,
  approved_by     BIGINT,                                     -- 批复人 user_id
  policy_pack_id  BIGINT                                     -- 命中制度包快照（比例/限额复算，PRD 2.10）
);
CREATE UNIQUE INDEX uk_budget_code ON F_BUDGET(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_budget_project_ver ON F_BUDGET(tenant_id, project_id, version) WHERE deleted = 0;
CREATE INDEX idx_budget_tenant_status ON F_BUDGET(tenant_id, status);
CREATE INDEX idx_budget_project ON F_BUDGET(project_id);
COMMENT ON TABLE  F_BUDGET IS '项目预算主表（F-02/F-03/F-04）：支持预算制/包干制双模式，版本化';
COMMENT ON COLUMN F_BUDGET.mode            IS '预算制需拆科目行；包干制仅填总额与简要依据（科目字段可空）';
COMMENT ON COLUMN F_BUDGET.policy_pack_id  IS '预算比例/限额判定所依据的制度包快照，供事后复算';
COMMENT ON COLUMN F_BUDGET.version         IS '每次预算调整生成新版本，历史版本保留（可复算执行率）';


-- -----------------------------------------------------------------------------
-- F-02/F-10 · F_BUDGET_LINE 预算明细行（含余额计算列注释）
-- -----------------------------------------------------------------------------
CREATE TABLE F_BUDGET_LINE (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','FROZEN','CLOSED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列
  budget_id        BIGINT       NOT NULL REFERENCES F_BUDGET(id),   -- 同模块物理外键
  subject_id       BIGINT       NOT NULL REFERENCES F_SUBJECT(id),  -- 同模块物理外键
  policy_pack_id   BIGINT,                                          -- 比例上限判定制度包快照
  -- 金额平衡：amount_planned + amount_adjusted_delta = 调整后计划；
  -- 余额 remaining = (amount_planned + amount_adjusted) - amount_frozen - amount_used - amount_released
  amount_planned   NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 计划额（编制）
  amount_adjusted  NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 调整增减额（可为负）
  amount_frozen    NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 冻结额（报销提交即冻结，F-10）
  amount_used      NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 已扣减额（付款实扣，F-10）
  amount_released  NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 已释放额（驳回/退回解冻，F-10）
  remaining        NUMERIC(18,2)                                  -- 可支余额；建议生成列
                   -- PG: GENERATED ALWAYS AS (amount_planned + amount_adjusted
                   --        - amount_frozen - amount_used - amount_released) STORED
                   -- 达梦: 应用层维护 + 触发器/视图计算
);
CREATE UNIQUE INDEX uk_budget_line ON F_BUDGET_LINE(tenant_id, budget_id, subject_id) WHERE deleted = 0;
CREATE INDEX idx_budget_line_tenant_status ON F_BUDGET_LINE(tenant_id, status);
CREATE INDEX idx_budget_line_budget ON F_BUDGET_LINE(budget_id);
CREATE INDEX idx_budget_line_subject ON F_BUDGET_LINE(subject_id);
COMMENT ON TABLE  F_BUDGET_LINE IS '预算明细行（F-02/F-10）：冻结/扣减/释放/余额，预算余额一致性核心表';
COMMENT ON COLUMN F_BUDGET_LINE.amount_frozen   IS '报销 SUBMITTED 后、付款前的预占额度，防超支（F-10）';
COMMENT ON COLUMN F_BUDGET_LINE.amount_used     IS '付款完成实扣额度，冻结转实扣须原子迁移（F-10）';
COMMENT ON COLUMN F_BUDGET_LINE.amount_released IS '审批驳回/退回释放的冻结额度';
COMMENT ON COLUMN F_BUDGET_LINE.remaining       IS '可支余额=计划+调整-冻结-已用-已释放；建议 PG 生成列 STORED，达梦改视图/触发器';


-- -----------------------------------------------------------------------------
-- F-05/F-06 · F_INCOME 到账记录（含银行流水匹配 / 认领状态机）
-- -----------------------------------------------------------------------------
CREATE TABLE F_INCOME (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64),
  tenant_id       BIGINT       NOT NULL,
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                  CHECK (status IN ('ACTIVE','REVERSED','CLOSED')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT,
  -- 业务列
  project_id      BIGINT,                                        -- 认领后回填 E_PROJECT(id)，未认领可空
  legal_entity_id BIGINT       NOT NULL,                         -- 入账法人
  receipt_no      VARCHAR(64),                                   -- 到账票据号
  receipt_date    DATE,                                          -- 到账日期
  amount          NUMERIC(18,2) NOT NULL,                        -- 到账金额
  payer_name      VARCHAR(256),                                  -- 付款方名称
  payer_bank      VARCHAR(128),                                  -- 付款方开户行
  purpose_text    TEXT,                                          -- 汇款用途/备注（匹配依据）
  bank_flow_no    VARCHAR(64),                                   -- 银行流水号（幂等入账键）
  claim_status    VARCHAR(16)  NOT NULL DEFAULT 'UNCLAIMED'
                  CHECK (claim_status IN ('UNCLAIMED','AUTO_MATCHED','CLAIMED','DOUBTFUL')),
  match_confidence NUMERIC(6,4),                                 -- 自动匹配置信度（F-06）
  claimed_by      BIGINT,                                        -- 认领人 user_id
  claimed_at      TIMESTAMPTZ,
  voucher_url     VARCHAR(512)                                   -- 到账凭证附件（对象存储）
);
CREATE UNIQUE INDEX uk_income_bankflow ON F_INCOME(tenant_id, bank_flow_no) WHERE deleted = 0 AND bank_flow_no IS NOT NULL;
CREATE INDEX idx_income_tenant_status ON F_INCOME(tenant_id, status);
CREATE INDEX idx_income_claim_status ON F_INCOME(tenant_id, claim_status);
CREATE INDEX idx_income_project ON F_INCOME(project_id);
COMMENT ON TABLE  F_INCOME IS '到账记录（F-05/F-06）：银行流水导入 + 自动匹配 + 认领状态机';
COMMENT ON COLUMN F_INCOME.claim_status   IS '到账认领：UNCLAIMED=未认领/AUTO_MATCHED=自动匹配/CLAIMED=人工认领/DOUBTFUL=存疑';
COMMENT ON COLUMN F_INCOME.match_confidence IS '自动匹配置信度（付款方+金额+备注），高置信自动入账，低置信转人工';
COMMENT ON COLUMN F_INCOME.bank_flow_no   IS '银行流水号，作幂等入账唯一键，防重复登记';


-- -----------------------------------------------------------------------------
-- F-07/F-10/F-15 · F_EXPENSE 报销主表（含发票三重指纹查重列，携带 policy_pack_id）
-- -----------------------------------------------------------------------------
CREATE TABLE F_EXPENSE (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),                                -- EXP-年-序
  tenant_id          BIGINT       NOT NULL,
  status             VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','SUBMITTED','AI_REVIEW','HUMAN_REVIEW',
                                       'APPROVED','REJECTED','RETURNED','PAID','VOUCHER_SYNCED')),
  deleted            SMALLINT     NOT NULL DEFAULT 0,
  creator_id         BIGINT       NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark             TEXT,
  -- 业务列
  project_id         BIGINT       NOT NULL,                      -- 逻辑引用 E_PROJECT(id)
  budget_line_id     BIGINT,                                     -- 逻辑引用 F_BUDGET_LINE(id)（预算制必填，包干制可空）
  legal_entity_id    BIGINT       NOT NULL,
  applicant_user_id  BIGINT       NOT NULL,                      -- 报销人 user_id
  amount             NUMERIC(18,2) NOT NULL,                     -- 报销金额
  expense_category   VARCHAR(32),                                -- 费用类别（对齐 F_SUBJECT.category 语义）
  expense_type       VARCHAR(16)  NOT NULL DEFAULT 'OTHER'
                     CHECK (expense_type IN ('EQUIPMENT','MATERIAL','TRAVEL','MEETING',
                                             'LABOR','EXPERT','OTHER')),  -- 设备/材料/差旅/会议/劳务/专家咨询/其他
  description        TEXT,                                       -- 报销事由（富文本）
  invoice_ids        JSONB,                                      -- 关联 F_INVOICE id 数组
  attachment_ids     JSONB,                                      -- 附件对象存储 id 数组
  -- 发票三重指纹（发票号 + 金额 + 开票日期）用于查重，命中直接拒绝（PRD 11）
  fingerprint_invoice_no   VARCHAR(64),                          -- 归一化主发票号
  fingerprint_amount       NUMERIC(18,2),                        -- 指纹金额
  fingerprint_invoice_date DATE,                                 -- 指纹开票日期
  fingerprint_hash         VARCHAR(64),                          -- 三重指纹哈希（查重唯一键）
  submit_mode        VARCHAR(8)   NOT NULL DEFAULT '预算制'
                     CHECK (submit_mode IN ('预算制','包干制')),
  ai_verdict         VARCHAR(8)   CHECK (ai_verdict IN ('PASS','REVIEW','REJECT')),  -- AI 初审结论（仅建议）
  ai_confidence      NUMERIC(6,4),                               -- AI 置信度，低于阈值回落人工
  invoice_check_status VARCHAR(16) NOT NULL DEFAULT 'PENDING'
                     CHECK (invoice_check_status IN ('PENDING','PASSED','FAILED','MANUAL')),  -- 税总查验状态
  submitted_at       TIMESTAMPTZ,
  paid_at            TIMESTAMPTZ,
  frozen_at          TIMESTAMPTZ,                                -- 预算冻结时间（F-10）
  policy_pack_id     BIGINT                                     -- 限额/科目合规判定制度包快照
);
CREATE UNIQUE INDEX uk_expense_code ON F_EXPENSE(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_expense_fingerprint ON F_EXPENSE(tenant_id, fingerprint_hash) WHERE deleted = 0;
CREATE INDEX idx_expense_tenant_status ON F_EXPENSE(tenant_id, status);
CREATE INDEX idx_expense_project ON F_EXPENSE(project_id);
CREATE INDEX idx_expense_budget_line ON F_EXPENSE(budget_line_id);
CREATE INDEX idx_expense_applicant ON F_EXPENSE(tenant_id, applicant_user_id, status);
CREATE INDEX idx_expense_fp ON F_EXPENSE(fingerprint_invoice_no, fingerprint_amount, fingerprint_invoice_date);
COMMENT ON TABLE  F_EXPENSE IS '报销主表（F-07/F-10/F-15）：状态机、发票三重指纹查重、AI 初审建议、制度包快照';
COMMENT ON COLUMN F_EXPENSE.fingerprint_hash IS '发票号+金额+开票日期归一化后哈希，唯一索引拦截重复报销';
COMMENT ON COLUMN F_EXPENSE.ai_verdict       IS 'AI 初审结论仅生成建议，不作为唯一审批依据（PRD 2.4/2.10）';
COMMENT ON COLUMN F_EXPENSE.invoice_check_status IS '税总查验状态：PENDING=待查验/PASSED/FAILED/MANUAL=转人工';


-- -----------------------------------------------------------------------------
-- F-09 · F_EXPENSE_APPROVAL 审批流水（多级审批与规则路由，who/when/where/what/why）
-- -----------------------------------------------------------------------------
CREATE TABLE F_EXPENSE_APPROVAL (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','DONE','SKIPPED','DELEGATED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列
  expense_id        BIGINT       NOT NULL REFERENCES F_EXPENSE(id),   -- 同模块物理外键
  step_order        INT          NOT NULL,                             -- 审批步骤序号
  approver_user_id  BIGINT,                                            -- 审批人 user_id
  role              VARCHAR(32),                                       -- R-MANAGER/R-FINANCE/R-LEADER/PI
  action            VARCHAR(16)  CHECK (action IN ('APPROVE','REJECT','RETURN','DELEGATE')),
  comment           TEXT,                                              -- 审批意见
  acted_at          TIMESTAMPTZ,
  ai_suggestion     JSONB                                              -- 该步骤展示的 AI 建议（可解释）
);
CREATE INDEX idx_approval_tenant_status ON F_EXPENSE_APPROVAL(tenant_id, status);
CREATE INDEX idx_approval_expense ON F_EXPENSE_APPROVAL(expense_id, step_order);
CREATE INDEX idx_approval_approver ON F_EXPENSE_APPROVAL(tenant_id, approver_user_id, status);
COMMENT ON TABLE  F_EXPENSE_APPROVAL IS '报销审批流水（F-09）：多级/串行/并行/加签/转办全量留痕';
COMMENT ON COLUMN F_EXPENSE_APPROVAL.action IS 'APPROVE=同意/REJECT=拒绝/RETURN=退回补充/DELEGATE=转办';


-- -----------------------------------------------------------------------------
-- F-08 · F_INVOICE 发票（OCR 结构化 + 查验 + 查重标记）
-- -----------------------------------------------------------------------------
CREATE TABLE F_INVOICE (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','OCR_DONE','CHECKED','BOUND','VOID')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列
  number            VARCHAR(64),                                    -- 发票号码
  invoice_code      VARCHAR(64),                                    -- 发票代码（避免与通用 code 混淆）
  invoice_type      VARCHAR(16)  NOT NULL DEFAULT 'GENERAL'
                    CHECK (invoice_type IN ('GENERAL','SPECIAL','ELECTRONIC','ITINERARY')),  -- 普票/专票/电子票/行程单
  seller_name       VARCHAR(256),
  seller_tax_id     VARCHAR(64),
  buyer_name        VARCHAR(256),
  buyer_tax_id      VARCHAR(64),
  amount_excl_tax   NUMERIC(18,2),
  tax_amount        NUMERIC(18,2),
  total_amount      NUMERIC(18,2),
  issue_date        DATE,
  ocr_confidence    NUMERIC(6,4),                                   -- OCR 识别置信度
  ocr_raw_json      JSONB,                                          -- OCR 原始结构化结果
  check_result      VARCHAR(16) CHECK (check_result IN ('PASS','FAIL','PENDING')),  -- 税总查验结果
  is_duplicated     BOOLEAN      NOT NULL DEFAULT FALSE,            -- 三重指纹命中查重标记
  expense_id        BIGINT                                          -- 绑定报销单 id（可空，未提交前）
);
CREATE UNIQUE INDEX uk_invoice_code_tenant ON F_INVOICE(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_invoice_tenant_status ON F_INVOICE(tenant_id, status);
CREATE INDEX idx_invoice_number ON F_INVOICE(tenant_id, number, issue_date);
CREATE INDEX idx_invoice_expense ON F_INVOICE(expense_id);
COMMENT ON TABLE  F_INVOICE IS '发票（F-08）：OCR 结构化、税总查验、重复标记，回连报销单';
COMMENT ON COLUMN F_INVOICE.invoice_type   IS 'GENERAL=普票/SPECIAL=专票/ELECTRONIC=电子票/ITINERARY=行程单';
COMMENT ON COLUMN F_INVOICE.is_duplicated  IS '发票号+金额+日期三重指纹命中历史即置真，报销直接拒绝';


-- -----------------------------------------------------------------------------
-- F-11 · F_VOUCHER_SYNC 凭证同步（与财务系统，失败重试 3 次）
-- -----------------------------------------------------------------------------
CREATE TABLE F_VOUCHER_SYNC (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64),
  tenant_id       BIGINT       NOT NULL,
  status          VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING','SYNCING','SUCCESS','FAILED','MANUAL')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT,
  -- 业务列
  expense_id      BIGINT       NOT NULL REFERENCES F_EXPENSE(id),   -- 同模块物理外键（1:1）
  finance_system  VARCHAR(16)  NOT NULL
                  CHECK (finance_system IN ('YONYOU','KINGDEE','INSPIRE')),  -- 用友/金蝶/浪潮
  voucher_no      VARCHAR(64),                                      -- 财务系统凭证号（回调回填）
  sync_status     VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                  CHECK (sync_status IN ('PENDING','SUCCESS','FAILED')),
  retry_count     SMALLINT     NOT NULL DEFAULT 0,                 -- 重试计数（>3 转人工，PRD 11）
  payload_json    JSONB,                                           -- 下发凭证报文
  callback_json   JSONB,                                           -- 财务回调回执
  sync_at         TIMESTAMPTZ,
  error_msg       TEXT
);
CREATE UNIQUE INDEX uk_voucher_expense ON F_VOUCHER_SYNC(tenant_id, expense_id) WHERE deleted = 0;
CREATE INDEX idx_voucher_tenant_status ON F_VOUCHER_SYNC(tenant_id, status);
CREATE INDEX idx_voucher_voucher_no ON F_VOUCHER_SYNC(voucher_no);
COMMENT ON TABLE  F_VOUCHER_SYNC IS '凭证同步（F-11）：expense.approved 事件驱动下发，回调对账，重试 3 次转人工';
COMMENT ON COLUMN F_VOUCHER_SYNC.finance_system IS 'YONYOU=用友/KINGDEE=金蝶/INSPIRE=浪潮';
COMMENT ON COLUMN F_VOUCHER_SYNC.retry_count    IS '同步失败累计重试次数，超过 3 次 status 转 MANUAL';


-- -----------------------------------------------------------------------------
-- F-12 · F_INDIRECT_FEE 间接费用与绩效支出计提（按到账比例计提并限额）
-- -----------------------------------------------------------------------------
CREATE TABLE F_INDIRECT_FEE (
  id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                VARCHAR(64),
  tenant_id           BIGINT       NOT NULL,
  status              VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                      CHECK (status IN ('DRAFT','CALCULATED','POSTED','REVERSED')),
  deleted             SMALLINT     NOT NULL DEFAULT 0,
  creator_id          BIGINT       NOT NULL,
  modifier_id         BIGINT,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark              TEXT,
  -- 业务列
  project_id          BIGINT       NOT NULL,                       -- 逻辑引用 E_PROJECT(id)
  legal_entity_id     BIGINT       NOT NULL,
  period              VARCHAR(8)   NOT NULL,                       -- 计提期间 YYYYMM
  total_budget        NUMERIC(18,2) NOT NULL DEFAULT 0,            -- 预算间接费上限
  actual_income       NUMERIC(18,2) NOT NULL DEFAULT 0,            -- 实际到账额（计提基数）
  actual_expense      NUMERIC(18,2) NOT NULL DEFAULT 0,            -- 实际支出额
  indirect_rate       NUMERIC(6,4),                                -- 间接费用比例（阶梯，制度包给定）
  indirect_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,            -- 间接费用计提额
  performance_rate    NUMERIC(6,4),                                -- 绩效支出比例上限
  performance_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,            -- 绩效支出计提额（按到账比例，超限拦截）
  calc_detail         JSONB,                                       -- 计提明细（阶梯计算过程，可复算）
  policy_pack_id      BIGINT                                      -- 计提比例/限额制度包快照
);
CREATE UNIQUE INDEX uk_indirect_code ON F_INDIRECT_FEE(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_indirect_period ON F_INDIRECT_FEE(tenant_id, project_id, period) WHERE deleted = 0;
CREATE INDEX idx_indirect_tenant_status ON F_INDIRECT_FEE(tenant_id, status);
CREATE INDEX idx_indirect_project ON F_INDIRECT_FEE(project_id);
COMMENT ON TABLE  F_INDIRECT_FEE IS '间接费用与绩效支出计提（F-12）：按实际到账比例计提并限额';
COMMENT ON COLUMN F_INDIRECT_FEE.actual_income      IS '绩效支出按项目实际到账额的百分比计提（F-12 基数）';
COMMENT ON COLUMN F_INDIRECT_FEE.calc_detail        IS '阶梯比例计算明细（JSONB），配合 policy_pack_id 复算';
COMMENT ON COLUMN F_INDIRECT_FEE.policy_pack_id     IS '间接费率/绩效限额所依据制度包快照';


-- -----------------------------------------------------------------------------
-- F-13 · F_SETTLEMENT 项目决算与结转结余
-- -----------------------------------------------------------------------------
CREATE TABLE F_SETTLEMENT (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','SUBMITTED','AUDITING','APPROVED','REJECTED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列
  project_id        BIGINT       NOT NULL,                          -- 逻辑引用 E_PROJECT(id)
  legal_entity_id   BIGINT       NOT NULL,
  closing_date      DATE,                                           -- 决算基准日
  income_total      NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 到账合计
  expense_total     NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 支出合计
  remaining         NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 结余
  treatment         VARCHAR(8)   NOT NULL DEFAULT '结转'
                    CHECK (treatment IN ('结转','收回','留用')),      -- 结余处理方式
  audit_report_url  VARCHAR(512),                                   -- 决算审计包（PDF）
  approved_by       BIGINT,
  approved_at       TIMESTAMPTZ,
  score_detail      JSONB                                          -- 决算各科目执行明细/审计评分
);
CREATE UNIQUE INDEX uk_settle_code ON F_SETTLEMENT(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_settle_project ON F_SETTLEMENT(tenant_id, project_id) WHERE deleted = 0;
CREATE INDEX idx_settle_tenant_status ON F_SETTLEMENT(tenant_id, status);
CREATE INDEX idx_settle_project ON F_SETTLEMENT(project_id);
COMMENT ON TABLE  F_SETTLEMENT IS '项目决算与结转结余（F-13）：一键生成审计包，E_PROJECT 1:1';
COMMENT ON COLUMN F_SETTLEMENT.treatment   IS '结余处理：结转/收回/留用（按项目类型与政策）';
COMMENT ON COLUMN F_SETTLEMENT.score_detail IS '决算各科目执行率明细与审计评分（JSONB）';


-- -----------------------------------------------------------------------------
-- F-16 · F_ANOMALY AI 违规模式识别 + 预警（严重级别 HIGH/MED/LOW）
-- -----------------------------------------------------------------------------
CREATE TABLE F_ANOMALY (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64),
  tenant_id       BIGINT       NOT NULL,
  status          VARCHAR(32)  NOT NULL DEFAULT 'OPEN'
                  CHECK (status IN ('OPEN','PROCESSING','RESOLVED','FALSE_POSITIVE','CLOSED')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT,
  -- 业务列
  expense_id      BIGINT,                                           -- 关联报销单（可空：非报销类异常）
  project_id      BIGINT,                                           -- 关联项目（突击花钱等）
  anomaly_type    VARCHAR(32)  NOT NULL
                  CHECK (anomaly_type IN ('SPLIT','RUSH_SPEND','ABNORMAL_SUBJECT','CIRCULAR','SENSITIVE_CATEGORY','BUDGET_OVER','OTHER')),
  rule_code       VARCHAR(64),                                      -- 命中规则号（Drools/制度包）
  severity        VARCHAR(8)   NOT NULL DEFAULT 'LOW'
                  CHECK (severity IN ('HIGH','MED','LOW')),         -- 异常级别
  reason_text     TEXT,                                             -- 异常说明
  evidence        JSONB,                                            -- 证据链（发票/金额/时间对比）
  ai_confidence   NUMERIC(6,4),                                     -- AI 判定置信度
  false_positive  BOOLEAN      NOT NULL DEFAULT FALSE,              -- 人工标记 AI 误判（回流训练，PRD 11）
  resolved_by     BIGINT,
  resolved_at     TIMESTAMPTZ,
  resolution      TEXT
);
CREATE UNIQUE INDEX uk_anomaly_code ON F_ANOMALY(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_anomaly_tenant_status ON F_ANOMALY(tenant_id, status);
CREATE INDEX idx_anomaly_severity ON F_ANOMALY(tenant_id, severity, status);
CREATE INDEX idx_anomaly_expense ON F_ANOMALY(expense_id);
CREATE INDEX idx_anomaly_project ON F_ANOMALY(project_id);
COMMENT ON TABLE  F_ANOMALY IS 'AI 违规模式识别与预警（F-16）：拆分/突击花钱/异常科目/循环/敏感类目';
COMMENT ON COLUMN F_ANOMALY.anomaly_type  IS 'SPLIT=拆分报销/RUSH_SPEND=突击花钱/ABNORMAL_SUBJECT=异常科目/CIRCULAR=循环报销/SENSITIVE_CATEGORY=敏感类别/BUDGET_OVER=超支';
COMMENT ON COLUMN F_ANOMALY.severity      IS '异常级别 HIGH/MED/LOW（PRD §4 状态登记表）';
COMMENT ON COLUMN F_ANOMALY.false_positive IS '审批人/PI 标记 AI 误判，数据回流训练集';


-- -----------------------------------------------------------------------------
-- F-17 · F_BUDGET_FORECAST AI 执行率预测快照（日切）
-- -----------------------------------------------------------------------------
CREATE TABLE F_BUDGET_FORECAST (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                      VARCHAR(64),
  tenant_id                 BIGINT       NOT NULL,
  status                    VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                            CHECK (status IN ('ACTIVE','EXPIRED')),
  deleted                   SMALLINT     NOT NULL DEFAULT 0,
  creator_id                BIGINT       NOT NULL,
  modifier_id               BIGINT,
  created_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark                    TEXT,
  -- 业务列
  project_id                BIGINT       NOT NULL,                  -- 逻辑引用 E_PROJECT(id)
  snapshot_date             DATE         NOT NULL,                  -- 日切快照日期
  current_execution_rate    NUMERIC(6,4),                           -- 当前执行率
  expected_execution_rate   NUMERIC(6,4),                           -- 预测结题执行率（Prophet/LSTM）
  deviation                 NUMERIC(6,4),                           -- 与目标/均值偏离度
  deviation_alert           BOOLEAN      NOT NULL DEFAULT FALSE,    -- 偏离>15% 触发提醒
  suggestion                TEXT,                                   -- 建议动作（自然语言，不进入硬约束）
  model_version             VARCHAR(32)                            -- 预测模型版本
);
CREATE UNIQUE INDEX uk_forecast_code ON F_BUDGET_FORECAST(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_forecast_snapshot ON F_BUDGET_FORECAST(tenant_id, project_id, snapshot_date) WHERE deleted = 0;
CREATE INDEX idx_forecast_tenant_status ON F_BUDGET_FORECAST(tenant_id, status);
CREATE INDEX idx_forecast_project ON F_BUDGET_FORECAST(project_id, snapshot_date);
COMMENT ON TABLE  F_BUDGET_FORECAST IS 'AI 执行率预测快照（F-17）：每日凌晨刷新，误差>15% 推送提醒';
COMMENT ON COLUMN F_BUDGET_FORECAST.expected_execution_rate IS '结题执行率预测值（0-1），AI 仅给建议不作硬约束';


-- -----------------------------------------------------------------------------
-- F-20 · F_COST_POOL 项目全成本核算与分摊（直接费用 + Σ间接分摊，携带 policy_pack_id）
-- -----------------------------------------------------------------------------
CREATE TABLE F_COST_POOL (
  id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                VARCHAR(64),
  tenant_id           BIGINT       NOT NULL,
  status              VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                      CHECK (status IN ('DRAFT','CALCULATED','LOCKED','REVERSED')),
  deleted             SMALLINT     NOT NULL DEFAULT 0,
  creator_id          BIGINT       NOT NULL,
  modifier_id         BIGINT,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark              TEXT,
  -- 业务列
  project_id          BIGINT       NOT NULL,                        -- 逻辑引用 E_PROJECT(id)
  legal_entity_id     BIGINT       NOT NULL,
  period              VARCHAR(8)   NOT NULL,                        -- 核算期间 YYYYMM
  direct_cost         NUMERIC(18,2) NOT NULL DEFAULT 0,             -- 直接费用合计（报销/外拨/采购）
  indirect_alloc_json JSONB,                                        -- 间接分摊明细 [{type,basis,amount}]
  full_cost           NUMERIC(18,2) NOT NULL DEFAULT 0,             -- 全成本 = direct_cost + Σ间接分摊
  basis_rule_id       BIGINT,                                       -- 命中的分摊制度规则（可解释/复算）
  policy_pack_id      BIGINT                                       -- 分摊依据制度包快照
);
CREATE UNIQUE INDEX uk_costpool_code ON F_COST_POOL(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_costpool_period ON F_COST_POOL(tenant_id, project_id, period) WHERE deleted = 0;
CREATE INDEX idx_costpool_tenant_status ON F_COST_POOL(tenant_id, status);
CREATE INDEX idx_costpool_project ON F_COST_POOL(project_id);
COMMENT ON TABLE  F_COST_POOL IS '项目全成本核算与分摊（F-20）：全成本=直接费用+Σ间接分摊，联动 A-12 折旧';
COMMENT ON COLUMN F_COST_POOL.indirect_alloc_json IS '间接分摊明细：管理费/房屋/水电气/设备折旧/共用平台，每项 basis+amount';
COMMENT ON COLUMN F_COST_POOL.basis_rule_id       IS '命中分摊规则号，配合 policy_pack_id 使分摊可复算';


-- -----------------------------------------------------------------------------
-- F-21 · F_ACCOUNTING_ENTRY 政府会计制度平行记账（财务会计 + 预算会计双分录）
-- -----------------------------------------------------------------------------
CREATE TABLE F_ACCOUNTING_ENTRY (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','POSTED','SUSPENSE','REVERSED')),  -- SUSPENSE=挂账
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列
  source_txn_id     BIGINT       NOT NULL,                          -- 源交易 id（报销/收付/折旧，多态）
  source_txn_type   VARCHAR(16)  NOT NULL
                    CHECK (source_txn_type IN ('EXPENSE','INCOME','DISBURSEMENT','DEPRECIATION','INDIRECT')),
  project_id        BIGINT,                                         -- 逻辑引用 E_PROJECT(id)
  legal_entity_id   BIGINT       NOT NULL,
  period            VARCHAR(8)   NOT NULL,                          -- 会计期间 YYYYMM
  fin_entry_json    JSONB,                                          -- 财务会计分录（权责发生制 借/贷科目、金额）
  bud_entry_json    JSONB,                                          -- 预算会计分录（收付实现制 预算支出/资金结存）
  posted_finance    BOOLEAN      NOT NULL DEFAULT FALSE,            -- 财务会计过账状态
  posted_budget     BOOLEAN      NOT NULL DEFAULT FALSE,            -- 预算会计过账状态
  reconcile_status  VARCHAR(16)  NOT NULL DEFAULT 'UNRECONCILED'
                    CHECK (reconcile_status IN ('BALANCED','UNRECONCILED','SUSPENSE')),  -- 两账勾稽结果
  voucher_sync_id   BIGINT,                                        -- 关联 F_VOUCHER_SYNC（凭证同步 F-11）
  policy_pack_id    BIGINT
);
CREATE UNIQUE INDEX uk_entry_code ON F_ACCOUNTING_ENTRY(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_entry_source ON F_ACCOUNTING_ENTRY(tenant_id, source_txn_type, source_txn_id, period) WHERE deleted = 0;
CREATE INDEX idx_entry_tenant_status ON F_ACCOUNTING_ENTRY(tenant_id, status);
CREATE INDEX idx_entry_reconcile ON F_ACCOUNTING_ENTRY(tenant_id, reconcile_status);
CREATE INDEX idx_entry_project ON F_ACCOUNTING_ENTRY(project_id);
COMMENT ON TABLE  F_ACCOUNTING_ENTRY IS '平行记账双分录（F-21，《政府会计制度》）：财务会计权责发生制 + 预算会计收付实现制';
COMMENT ON COLUMN F_ACCOUNTING_ENTRY.fin_entry_json   IS '财务会计分录（权责发生制），借贷平衡校验';
COMMENT ON COLUMN F_ACCOUNTING_ENTRY.bud_entry_json   IS '预算会计分录（收付实现制），预算支出/资金结存';
COMMENT ON COLUMN F_ACCOUNTING_ENTRY.reconcile_status IS '两账勾稽：BALANCED=平/UNRECONCILED=未勾稽/SUSPENSE=不平挂账并告警';


-- -----------------------------------------------------------------------------
-- F-22 · F_DISBURSEMENT 外拨经费（联动 G 合同金额上限拦截，涉密可选 security_level）
-- -----------------------------------------------------------------------------
CREATE TABLE F_DISBURSEMENT (
  id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                    VARCHAR(64),                              -- DISB-年-序（PRD 2.11 注册表 v1.1）
  tenant_id               BIGINT       NOT NULL,
  status                  VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                          CHECK (status IN ('DRAFT','SUBMITTED','APPROVED','PAID','VOUCHER_SYNCED','REJECTED','RETURNED')),
  deleted                 SMALLINT     NOT NULL DEFAULT 0,
  creator_id              BIGINT       NOT NULL,
  modifier_id             BIGINT,
  created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark                  TEXT,
  -- 业务列
  contract_id             BIGINT       NOT NULL,                    -- 逻辑引用 G_CONTRACT(id)→G
  outsource_unit_id       BIGINT       NOT NULL,                    -- 逻辑引用 G_SUPPLIER(id)→G
  project_id              BIGINT       NOT NULL,                    -- 逻辑引用 E_PROJECT(id)
  legal_entity_id         BIGINT       NOT NULL,
  security_level          VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                          CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 横向/涉密可选（PRD 2.13）
  amount                  NUMERIC(18,2) NOT NULL,                   -- 外拨金额
  phase                   VARCHAR(8)   NOT NULL DEFAULT '进度'
                          CHECK (phase IN ('预付','进度','尾款')),     -- 拨付阶段
  approval_chain          JSONB,                                    -- 审批链快照
  invoice_url             VARCHAR(512),                             -- 对方发票/收据附件
  voucher_status          VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                          CHECK (voucher_status IN ('PENDING','SUCCESS','FAILED','MANUAL')),  -- →F-11 凭证同步
  contract_amount         NUMERIC(18,2),                            -- 合同总额快照（来自 G，判定上限）
  disbursed_before        NUMERIC(18,2) NOT NULL DEFAULT 0,         -- 本次前已拨累计
  remain_contract_amount  NUMERIC(18,2),                            -- 合同剩余可拨额（超合同额拦截，F-22）
  compliance_flags        JSONB,                                    -- 命中合规规则：整体转包/单一来源未说明/关联外协单位
  policy_pack_id          BIGINT                                   -- 外拨限额/合规判定制度包快照
);
CREATE UNIQUE INDEX uk_disb_code ON F_DISBURSEMENT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_disb_tenant_status ON F_DISBURSEMENT(tenant_id, status);
CREATE INDEX idx_disb_contract ON F_DISBURSEMENT(contract_id);
CREATE INDEX idx_disb_project ON F_DISBURSEMENT(project_id);
CREATE INDEX idx_disb_unit ON F_DISBURSEMENT(outsource_unit_id);
COMMENT ON TABLE  F_DISBURSEMENT IS '外拨经费（F-22）：联动 G-09 外协合同，超合同金额上限拦截，审计重点';
COMMENT ON COLUMN F_DISBURSEMENT.contract_id            IS '逻辑引用 G_CONTRACT(id)，跨模块只存 id，一致性走事件（外拨↔合同）';
COMMENT ON COLUMN F_DISBURSEMENT.remain_contract_amount IS '合同剩余可拨额，本次外拨 > 剩余额则硬拦截（F-22）';
COMMENT ON COLUMN F_DISBURSEMENT.compliance_flags       IS '禁止整体转包/单一来源未说明/关联外协单位等规则命中结果';
COMMENT ON COLUMN F_DISBURSEMENT.security_level         IS '横向/涉密外拨密级，参与读写双重过滤（PRD 2.13）';


-- =============================================================================
-- 备注：
--   1) 单号前缀 BUD/EXP/DISB 已在 00-common.sql `seq_prefix_registry` 登记（owner=F），
--      业务取号一律走 svc-numbering，作废不回收、重试幂等（PRD 2.11）。
--   2) 跨模块引用（project_id / contract_id / outsource_unit_id / policy_pack_id）
--      不建物理外键，仅存对方主键 id；一致性走 Kafka 事件 + Saga（TECH_ARCH §八）。
--   3) 涉及成本归属的 F 表携带 legal_entity_id（PRD 2.12 法人并表口径）；
--      关键成本/制度表携带 policy_pack_id（PRD 2.10，供复算）。
--   4) 达梦部署：JSONB→CLOB + 应用解析；BOOLEAN→SMALLINT(0/1)；部分唯一索引
--      以 (tenant_id,code,deleted) 普通唯一索引替代；TIMESTAMPTZ→TIMESTAMP WITH TIME ZONE。
-- =============================================================================
