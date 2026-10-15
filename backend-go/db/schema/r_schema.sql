CREATE TABLE R_OUTPUT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL
                       CHECK (status IN (
                         'AUTO_FETCHED','PENDING_CLAIM','CLAIMED','ASSIGNED_TO_PROJECT',
                         'COUNTED_FOR_PERFORMANCE','MANUAL_DRAFT','PENDING_REVIEW','REJECTED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  output_type          VARCHAR(32)  NOT NULL
                       CHECK (output_type IN (
                         'PAPER','PATENT','SOFTWARE','STANDARD','AWARD','BOOK','DATASET','CONFERENCE',
                         'NEW_VARIETY','LAYOUT','APPRAISAL','HONOR')),  -- R-20 扩充类型
  title                VARCHAR(512) NOT NULL,
  title_en             VARCHAR(512),
  abstract             TEXT,
  publish_date         DATE,
  authors              JSONB        NOT NULL DEFAULT '[]',            -- [{user_id,name,order,is_corresponding,share_pct,orcid}]
  external_author_names JSONB       NOT NULL DEFAULT '[]',            -- 非本院署名作者 [{name,inst}]
  affiliations         JSONB        NOT NULL DEFAULT '[]',            -- [{user_id,inst_id,is_primary}]
  project_ids          JSONB        NOT NULL DEFAULT '[]',            -- 兼容视图：规范化主存见 R_OUTPUT_PROJECT
  language             VARCHAR(16),
  source               VARCHAR(32)  NOT NULL
                       CHECK (source IN (
                         'CNKI','WOS','SCOPUS','WANFANG','CNIPA','CROSSREF','ALTMETRIC','MANUAL','FETCH')),
  is_claimed           BOOLEAN      NOT NULL DEFAULT FALSE,
  claim_status         VARCHAR(32)  NOT NULL DEFAULT 'UNCLAIMED'
                       CHECK (claim_status IN ('UNCLAIMED','PENDING','CLAIMED','REJECTED','NOT_MINE','DOUBTFUL')),
  match_confidence     NUMERIC(6,4),                                  -- 智能匹配置信度（R-04）
  simhash              VARCHAR(64),                                  -- 标题/摘要 SimHash 指纹（去重）
  title_hash           VARCHAR(64),                                  -- 规范化标题哈希（去重主键候选）
  master_output_id     BIGINT,                                       -- 合并仲裁：指向保留的主记录（NULL=本身为主）
  department_id        BIGINT,                                       -- 第一完成人所属部门（sys_org.id 逻辑引用）
  stage                VARCHAR(16) NOT NULL DEFAULT 'PRE_APPLY',     -- T18 专利阶段（仅 PATENT 有效）
  annual_fee_due       DATE,                                         -- T18 年费到期日
  agency_id            BIGINT,                                       -- T18 代理机构 R_AGENCY(id)
  -- 治理三字段（§2.1 v1.1；成果涉密/法人隔离，见 detail §7）
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id       BIGINT                                       -- 绩效计入命中的制度包快照（R-11）
);
CREATE TABLE R_PAPER_EXT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL UNIQUE REFERENCES R_OUTPUT(id),
  journal_name         VARCHAR(256),
  journal_issn         VARCHAR(32),
  level_code           VARCHAR(32),  -- 刊物级别冗余快照（T16 resolve）
  volume               VARCHAR(32),
  issue                VARCHAR(32),
  page_range           VARCHAR(64),
  doi                  VARCHAR(128),
  keywords             JSONB        NOT NULL DEFAULT '[]',
  category             VARCHAR(32)  CHECK (category IN ('SCI','EI','PKU_CORE','CSCD','GENERAL')),
  jcr_partition        VARCHAR(16),                                  -- JCR Q1..Q4（R-12 自动更新）
  cas_partition        VARCHAR(16),                                  -- 中科院分区
  impact_factor        NUMERIC(8,4),                                 -- 影响因子
  cited_times          INT          NOT NULL DEFAULT 0,              -- 被引次数（当前值，历史见 R_METRIC_SNAPSHOT）
  is_highly_cited      BOOLEAN      NOT NULL DEFAULT FALSE,          -- 高被引（R-17）
  esi_top1             BOOLEAN      NOT NULL DEFAULT FALSE,          -- ESI 前 1%
  wos_record_id        VARCHAR(64),
  scopus_id            VARCHAR(64),
  cnki_id              VARCHAR(64)
);
CREATE TABLE R_PATENT_EXT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL UNIQUE REFERENCES R_OUTPUT(id),
  patent_type          VARCHAR(32)  CHECK (patent_type IN ('INVENTION','UTILITY','DESIGN')),
  application_no       VARCHAR(64),
  application_date     DATE,
  grant_no             VARCHAR(64),
  grant_date           DATE,
  expiry_date          DATE,
  legal_status         VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                       CHECK (legal_status IN ('PENDING','EXAMINING','SUBSTANTIVE','GRANTED','ANNUTY_DUE','INVALID','ABANDONED')),
  inventors            JSONB        NOT NULL DEFAULT '[]',           -- [{user_id,name,rank}]
  applicants           JSONB        NOT NULL DEFAULT '[]',           -- 申请人（法人/单位）
  agency_name          VARCHAR(128),                                 -- 代理机构
  annuity_due_date     DATE,                                         -- 下次年费应缴日（触发 patent.annuity.due）
  annuity_paid_year    INT,                                          -- 已缴至年度
  maintain_years       INT,                                          -- 维持年限
  license_status       VARCHAR(32)  CHECK (license_status IN ('UNLICENSED','NON_EXCLUSIVE','EXCLUSIVE','TRANSFERRED')),
  is_transferable      BOOLEAN      NOT NULL DEFAULT FALSE           -- 可转化标记（R-USR-15）
);
CREATE TABLE R_SOFTWARE_EXT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL UNIQUE REFERENCES R_OUTPUT(id),
  register_no          VARCHAR(64),                                 -- 登记号
  register_date        DATE,
  copyright_owners     JSONB        NOT NULL DEFAULT '[]',          -- 著作权人
  first_release_date   DATE,
  source_code_lines    INT
);
CREATE TABLE R_STANDARD_EXT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL UNIQUE REFERENCES R_OUTPUT(id),
  standard_type        VARCHAR(32)  CHECK (standard_type IN ('INTERNATIONAL','NATIONAL','INDUSTRY','GROUP','ENTERPRISE')),
  standard_no          VARCHAR(64),
  publish_date         DATE,
  drafting_unit_rank   VARCHAR(32),                                 -- 起草单位排名
  main_drafters        JSONB        NOT NULL DEFAULT '[]'           -- 主要起草人
);
CREATE TABLE R_AWARD_EXT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL UNIQUE REFERENCES R_OUTPUT(id),
  award_name           VARCHAR(256),
  award_level          VARCHAR(32)  CHECK (award_level IN ('NATIONAL','MINISTRY','PROVINCE','SOCIETY')),
  award_grade          VARCHAR(16)  CHECK (award_grade IN ('FIRST','SECOND','THIRD')),
  award_date           DATE,
  awarding_body        VARCHAR(256),
  winner_rank          JSONB        NOT NULL DEFAULT '[]'           -- [{user_id,name,rank}]
);
CREATE TABLE R_BOOK_EXT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL UNIQUE REFERENCES R_OUTPUT(id),
  publisher            VARCHAR(256),
  isbn                 VARCHAR(32),
  book_date            DATE,
  book_type            VARCHAR(32)  CHECK (book_type IN ('MONOGRAPH','EDITED','TEXTBOOK','TRANSLATION')),
  word_count           INT,
  role                 VARCHAR(32)  CHECK (role IN ('CHIEF_EDITOR','DEPUTY_EDITOR','CONTRIBUTOR'))
);
CREATE TABLE R_CLAIM_RECORD (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DONE' CHECK (status IN ('DONE','REVOKED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL REFERENCES R_OUTPUT(id),
  user_id              BIGINT       NOT NULL,                     -- sys_user.id（逻辑引用）
  action               VARCHAR(32)  NOT NULL CHECK (action IN ('CLAIM','REJECT','MARK_NOT_MINE','EDIT')),
  edited_fields        JSONB,                                     -- {field:{from,to}} 认领时的字段订正
  reason               TEXT,                                       -- 拒绝/挂名说明（入诚信记录）
  confidence           NUMERIC(6,4),                             -- 认领时的匹配置信度快照
  action_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  batch_id             VARCHAR(64)                               -- 批量认领批次号（100 条 < 3s）
);
CREATE TABLE R_METRIC_SNAPSHOT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ARCHIVED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL REFERENCES R_OUTPUT(id),
  snapshot_date        DATE         NOT NULL,
  cited_times          INT          NOT NULL DEFAULT 0,
  altmetric            INT          NOT NULL DEFAULT 0,          -- 关注度分值
  downloads            INT          NOT NULL DEFAULT 0,
  impact_factor        NUMERIC(8,4)                              -- 当期影响因子快照
);
CREATE TABLE R_DATASET (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL UNIQUE REFERENCES R_OUTPUT(id),
  storage_url          VARCHAR(512),
  size_bytes           BIGINT,
  format               VARCHAR(64),
  license              VARCHAR(64),                              -- 数据许可协议（合规）
  doi                  VARCHAR(128),
  download_count       INT          NOT NULL DEFAULT 0,
  citation_count       INT          NOT NULL DEFAULT 0
);
CREATE TABLE R_OUTPUT_PROJECT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REVOKED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  output_id            BIGINT       NOT NULL REFERENCES R_OUTPUT(id),
  project_id           BIGINT       NOT NULL,                    -- 逻辑引用 E_PROJECT.id
  relation_type        VARCHAR(32)  NOT NULL DEFAULT 'CONTRIBUTION'
                       CHECK (relation_type IN ('PRIMARY','CONTRIBUTION','CITED')),
  contribution_pct     NUMERIC(6,4)                             -- 成果对该项目的贡献占比
);

-- T16 期刊源库 / 刊物级别 / 转载（P5）
CREATE TABLE R_JOURNAL_SOURCE (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    name VARCHAR(256) NOT NULL,
    issn VARCHAR(32),
    year_from INT,
    year_to INT,
    deleted SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE R_JOURNAL_LEVEL (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    paper_type VARCHAR(32),
    indexed BOOLEAN NOT NULL DEFAULT TRUE,
    deleted SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE R_JOURNAL_LEVEL_SOURCE (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    level_id BIGINT NOT NULL REFERENCES R_JOURNAL_LEVEL(id),
    source_id BIGINT NOT NULL REFERENCES R_JOURNAL_SOURCE(id),
    year_from INT,
    year_to INT
);
CREATE TABLE R_PAPER_REPRINT (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    output_id BIGINT NOT NULL REFERENCES R_OUTPUT(id),
    name VARCHAR(256) NOT NULL,
    type VARCHAR(32),
    reprint_date DATE,
    remark TEXT,
    deleted SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- T17 网推成果推送池
CREATE TABLE R_PUSH_ITEM (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    type VARCHAR(16) NOT NULL,
    source_db VARCHAR(32) NOT NULL,
    title VARCHAR(512) NOT NULL,
    authors JSONB NOT NULL DEFAULT '[]'::jsonb,
    year INT,
    raw_doi VARCHAR(128),
    status VARCHAR(16) NOT NULL DEFAULT 'PUSHED',
    pushed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dedup_key VARCHAR(64) NOT NULL,
    output_id BIGINT,
    deleted SMALLINT NOT NULL DEFAULT 0
);

-- T18 专利扩展（挂在 R_OUTPUT 上）
CREATE TABLE R_PATENT_FEE (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    patent_id BIGINT NOT NULL REFERENCES R_OUTPUT(id),
    year INT NOT NULL,
    amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    paid_at DATE,
    status VARCHAR(16) NOT NULL DEFAULT 'UNPAID',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE R_AGENCY (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    name VARCHAR(256) NOT NULL,
    contact VARCHAR(256),
    deleted SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
