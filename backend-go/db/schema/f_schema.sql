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
  pending_delta   NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 追加审批中金额（T14）
  version         INT          NOT NULL DEFAULT 1,            -- 预算版本号（调整递增）
  approved_at     TIMESTAMPTZ,
  approved_by     BIGINT,                                     -- 批复人 user_id
  policy_pack_id  BIGINT                                     -- 命中制度包快照（比例/限额复算，PRD 2.10）
);

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
  pending_delta    NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 追加审批中金额（T14）
  amount_frozen    NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 冻结额（报销提交即冻结，F-10）
  amount_used      NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 已扣减额（付款实扣，F-10）
  amount_released  NUMERIC(18,2) NOT NULL DEFAULT 0,               -- 已释放额（驳回/退回解冻，F-10）
  remaining        NUMERIC(18,2)                                  -- 可支余额；建议生成列
                   -- PG: GENERATED ALWAYS AS (amount_planned + amount_adjusted
                   --        - amount_frozen - amount_used - amount_released) STORED
                   -- 达梦: 应用层维护 + 触发器/视图计算
);

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

CREATE TABLE E_PROJECT (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),                              -- 项目编号 PRJ-年-序（统一编号中心分配）
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL
                   CHECK (status IN ('EXECUTING','MID_CHECK','CHANGING','CORRECTING','DELAYED','COMPLETING','CLOSED','TERMINATED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列（PRD §5.1）
  application_id   BIGINT       NOT NULL,                    -- 逻辑外键 -> 01 P_APPLICATION.id（1:1 继承，跨模块不建物理 FK）
  title            VARCHAR(512) NOT NULL,
  project_type     VARCHAR(64),                              -- 项目类型，取自 sys_dict('project_type')，禁止硬编码（PRD 2.8）
  pi_user_id       BIGINT       NOT NULL,                    -- 逻辑外键 -> common sys_user.id（项目负责人）
  member_ids       JSONB        NOT NULL DEFAULT '[]'::jsonb,-- 项目成员 user_id 数组（半结构化）
  department_id    BIGINT,                                   -- 逻辑外键 -> common sys_org.id（承担部门）
  legal_entity_id  BIGINT       NOT NULL,                    -- 法人细分（PRD 2.12 成本归属与并表；E_PROJECT 携带）
  start_date       DATE,
  end_date         DATE,
  actual_end_date  DATE,
  total_budget     NUMERIC(18,2) NOT NULL DEFAULT 0,         -- 立项总预算（快照，明细权威在 03 F_BUDGET）
  received_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,         -- 累计到账（快照，来源 03 F 到账认领）
  spent_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,         -- 累计支出（快照，来源 03 F 报销；只读引用不重算）
  health_score     INT          NOT NULL DEFAULT 100         -- 健康度 0-100（E-10，红黄绿：<60 红 / 60-79 黄 / >=80 绿）
                   CHECK (health_score BETWEEN 0 AND 100),
  risk_level       VARCHAR(16)  NOT NULL DEFAULT 'LOW'
                   CHECK (risk_level IN ('HIGH','MED','LOW')),-- 风险等级（与 F 异常级别 token 一致）
  ethics_case_id   BIGINT,                                   -- 逻辑外键 -> 05/06 C 模块伦理审查案件（单号前缀 ETH）
  policy_pack_id   BIGINT,                                   -- 命中制度包快照 -> common sys_policy_pack.id（复算依据，PRD 2.10）
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')) -- 涉密等级（PRD 2.13）
);

-- T14 外拨（F-24）：经费拨付外单位，两级审批后从预算行实扣
CREATE TABLE F_OUTWARD (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code               VARCHAR(64),
    tenant_id          BIGINT NOT NULL,
    status             VARCHAR(16) NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    deleted            SMALLINT NOT NULL DEFAULT 0,
    creator_id         BIGINT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    remark             TEXT,
    project_id         BIGINT NOT NULL,
    budget_id          BIGINT,
    budget_line_id     BIGINT,
    amount             NUMERIC(18,2) NOT NULL,
    to_unit            VARCHAR(256) NOT NULL,
    reason             TEXT,
    first_approved_by  BIGINT,
    first_approved_at  TIMESTAMPTZ,
    approved_by        BIGINT,
    approved_at        TIMESTAMPTZ
);

-- T14 结转（F-25）：结题项目余额结转下年度，批复后生成 F_INCOME 行
CREATE TABLE F_CARRYOVER (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         VARCHAR(64),
    tenant_id    BIGINT NOT NULL,
    status       VARCHAR(16) NOT NULL DEFAULT 'PENDING'
                 CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    deleted      SMALLINT NOT NULL DEFAULT 0,
    creator_id   BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    remark       TEXT,
    project_id   BIGINT NOT NULL,
    fiscal_year  INT NOT NULL,
    target_year  INT NOT NULL,
    amount       NUMERIC(18,2) NOT NULL,
    income_id    BIGINT
);
