-- ============================================================
-- 15 · 专家与评审管理（模块 N）
-- PG15；达梦差异：IDENTITY/JSONB/TIMESTAMPTZ 需适配（见 00-common 注记）
-- 跨模块仅存 *_id 逻辑外键，不建物理 FK（同模块内可建）
-- ============================================================

CREATE TABLE n_expert (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'CANDIDATE'
                    CHECK (status IN ('CANDIDATE','ACTIVE','SUSPENDED','BLACKLIST')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  name              VARCHAR(64)  NOT NULL,
  gender            VARCHAR(8),
  title             VARCHAR(64),
  education         VARCHAR(32),
  org_name          VARCHAR(128),
  dept              VARCHAR(128),
  phone             VARCHAR(32),
  email             VARCHAR(128),
  user_id           BIGINT,                                   -- 逻辑→sys_user（本院专家），可空=纯外部
  source            VARCHAR(16)  NOT NULL DEFAULT 'EXTERNAL'
                    CHECK (source IN ('INTERNAL','EXTERNAL')),
  field_tags        JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 研究领域标签数组
  expertise_level   VARCHAR(16)  NOT NULL DEFAULT 'EXPERT'
                    CHECK (expertise_level IN ('JUNIOR','SENIOR','EXPERT')),
  avoid_orgs        JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 回避单位名列表
  avoid_person_ids  JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 回避人员 user_id 列表
  bank_account      JSONB,                                     -- 评审费收款信息（走 X 加密治理）
  cv_doc_ids        JSONB        NOT NULL DEFAULT '[]'::jsonb, -- O 域 document id
  last_review_at    TIMESTAMPTZ,
  review_count      INT          NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uk_n_expert_code ON n_expert(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_n_expert_tenant_status ON n_expert(tenant_id, status);
CREATE INDEX idx_n_expert_field ON n_expert USING GIN (field_tags);
CREATE INDEX idx_n_expert_user ON n_expert(user_id);

CREATE TABLE n_expert_group (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  name              VARCHAR(128) NOT NULL,
  criteria          JSONB        NOT NULL DEFAULT '{}'::jsonb,
  expert_ids        JSONB        NOT NULL DEFAULT '[]'::jsonb
);
CREATE UNIQUE INDEX uk_n_group_name ON n_expert_group(tenant_id, name) WHERE deleted = 0;

CREATE TABLE n_review_task (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','DRAWN','INVITING','QUORUM','IN_REVIEW','COLLECTING','CONCLUDED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  biz_type          VARCHAR(24)  NOT NULL
                    CHECK (biz_type IN ('MID_CHECK','FINAL_ACCEPT','OUTPUT_EVAL','PROJECT_APPLY','OTHER')),
  target_type       VARCHAR(32),
  target_id         BIGINT,                                    -- 逻辑→E_MID_CHECK/E_FINAL_ACCEPT/R_OUTPUT id
  project_id        BIGINT,                                    -- 逻辑→E_PROJECT（回避判定用）
  title             VARCHAR(256) NOT NULL,
  review_method     VARCHAR(16)  NOT NULL DEFAULT 'RANDOM'
                    CHECK (review_method IN ('RANDOM','COMBINATION','MANUAL')),
  plan_count        INT          NOT NULL DEFAULT 3,
  draw_rule         JSONB        NOT NULL DEFAULT '{}'::jsonb, -- {field_tags,min_title,org_diversity,exclude_user_ids,exclude_orgs}
  conclusion        VARCHAR(16),
  score_summary     JSONB,
  drawn_at          TIMESTAMPTZ,
  started_at        TIMESTAMPTZ,
  concluded_at      TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_n_task_code ON n_review_task(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_n_task_project ON n_review_task(project_id, biz_type);
CREATE INDEX idx_n_task_target ON n_review_task(target_type, target_id);
CREATE INDEX idx_n_task_tenant_status ON n_review_task(tenant_id, status);

CREATE TABLE n_review_invitation (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  task_id           BIGINT       NOT NULL REFERENCES n_review_task(id),
  expert_id         BIGINT       NOT NULL REFERENCES n_expert(id),
  seat_no           INT          NOT NULL DEFAULT 0,
  avoid_hit         BOOLEAN      NOT NULL DEFAULT FALSE,
  response          VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (response IN ('PENDING','ACCEPT','DECLINE','EXPIRED')),
  invited_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  responded_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_n_invite ON n_review_invitation(task_id, expert_id);
CREATE INDEX idx_n_invite_task ON n_review_invitation(task_id, response);

CREATE TABLE n_review_score (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  task_id           BIGINT       NOT NULL REFERENCES n_review_task(id),
  expert_id         BIGINT       NOT NULL REFERENCES n_expert(id),
  target_type       VARCHAR(32),
  target_id         BIGINT,
  dimension_scores  JSONB        NOT NULL DEFAULT '[]'::jsonb,
  total_score       NUMERIC(10,2) NOT NULL DEFAULT 0,
  comment           TEXT,
  status            VARCHAR(16)  NOT NULL DEFAULT 'SUBMITTED' CHECK (status IN ('SUBMITTED','ABSTAIN')),
  submitted_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_n_score ON n_review_score(task_id, expert_id);

CREATE TABLE n_review_fee (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'UNPAID' CHECK (status IN ('UNPAID','PAID')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  task_id           BIGINT       NOT NULL REFERENCES n_review_task(id),
  expert_id         BIGINT       NOT NULL REFERENCES n_expert(id),
  amount            NUMERIC(18,2) NOT NULL,
  pay_channel       VARCHAR(32),
  paid_at           TIMESTAMPTZ,
  voucher_code      VARCHAR(64)                                  -- 逻辑→F 凭证
);
CREATE UNIQUE INDEX uk_n_fee ON n_review_fee(task_id, expert_id) WHERE deleted = 0;
