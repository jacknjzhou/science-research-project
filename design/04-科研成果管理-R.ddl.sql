-- =============================================================================
-- 04-科研成果管理-R.ddl.sql · 科研成果管理（R）模块建表脚本
-- 版本 v1.0 · 2026-08-14
-- 上游：../PRD/04-科研成果管理.md（表 R_OUTPUT + 各 *_EXT、R-01..R-21）、../README.md（全局约定 §2/§3/§4/§5）
-- 方言：PostgreSQL 15
--
-- 【信创达梦差异声明（对齐 design/README.md §2.4，达梦部署时按此替换）】
--   1) 自增主键：GENERATED ALWAYS AS IDENTITY  →  IDENTITY(1,1)
--   2) 时间戳：  TIMESTAMPTZ                    →  TIMESTAMP WITH TIME ZONE
--   3) 布尔：    BOOLEAN                        →  SMALLINT（0/1）
--   4) 半结构：  JSONB                          →  CLOB/VARCHAR 存 JSON 文本 + 应用层解析
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0  →  普通唯一索引 + deleted 复合键
--   6) 全文检索 GIN/trigram (pg_trgm/tsvector)   →  应用层 ES / 达梦全文索引
--   7) 表达式唯一索引中的 COALESCE 等函数         →  应用层生成哈希列后建普通唯一索引
--
-- 【通用列（§2.1，所有业务表内联，列名列型完全一致，DDL 不再逐表注释）】
--   id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--   code VARCHAR(64), tenant_id BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
--   deleted SMALLINT NOT NULL DEFAULT 0, creator_id BIGINT NOT NULL, modifier_id BIGINT,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--   remark TEXT
-- 【成果单号前缀】PRD 2.11 尚未为成果登记单号前缀（详见 detail.md §10）。code 先留通用值，
--   正式前缀（建议 OUT/RSLT）须在 seq_prefix_registry 登记后方可下发，本脚本仅建列不建强约束。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1) R_OUTPUT · 成果主表（全类型统一主存，1:1 挂各类型扩展表）
-- -----------------------------------------------------------------------------
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
  -- 治理三字段（§2.1 v1.1；成果涉密/法人隔离，见 detail §7）
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id       BIGINT                                       -- 绩效计入命中的制度包快照（R-11）
);

CREATE UNIQUE INDEX uk_output_code        ON R_OUTPUT(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_output_titlehash   ON R_OUTPUT(tenant_id, title_hash) WHERE deleted = 0 AND title_hash IS NOT NULL;  -- 去重
CREATE INDEX idx_output_simhash           ON R_OUTPUT(tenant_id, simhash);
CREATE INDEX idx_output_main              ON R_OUTPUT(tenant_id, legal_entity_id, status);
CREATE INDEX idx_output_type_date         ON R_OUTPUT(tenant_id, output_type, publish_date);
CREATE INDEX idx_output_source            ON R_OUTPUT(tenant_id, source);
CREATE INDEX idx_output_claim             ON R_OUTPUT(tenant_id, is_claimed, claim_status);   -- 待认领中心主路径
CREATE INDEX idx_output_dept              ON R_OUTPUT(tenant_id, department_id);
CREATE INDEX idx_output_master            ON R_OUTPUT(tenant_id, master_output_id);
CREATE INDEX idx_output_authors           ON R_OUTPUT USING GIN (authors jsonb_path_ops);     -- 作者检索（pg_trgm 达梦见 §2.4）
CREATE INDEX idx_output_title_trgm        ON R_OUTPUT USING GIN (title gin_trgm_ops);         -- 模糊搜索（需 CREATE EXTENSION pg_trgm）

COMMENT ON TABLE  R_OUTPUT IS '科研成果主表：全类型统一主存，扩展信息按 output_type 挂对应 *_EXT 表';
COMMENT ON COLUMN R_OUTPUT.status IS '成果状态机 token（§4）：AUTO_FETCHED/PENDING_CLAIM/CLAIMED/ASSIGNED_TO_PROJECT/COUNTED_FOR_PERFORMANCE/MANUAL_DRAFT/PENDING_REVIEW/REJECTED';
COMMENT ON COLUMN R_OUTPUT.output_type IS '成果类型：PAPER/PATENT/SOFTWARE/STANDARD/AWARD/BOOK/DATASET/CONFERENCE；NEW_VARIETY/LAYOUT/APPRAISAL/HONOR 为 R-20 扩充（可配字典）';
COMMENT ON COLUMN R_OUTPUT.authors IS '作者数组 JSONB：[{user_id,name,order,is_corresponding,share_pct,orcid}]，含作者顺序/共同通讯多值/份额';
COMMENT ON COLUMN R_OUTPUT.source IS '数据来源：CNKI/WoS/Scopus/万方/专利局/Crossref/Altmetric/手动/抓取';
COMMENT ON COLUMN R_OUTPUT.match_confidence IS 'R-04 智能匹配置信度：>0.95 入待认领，0.7~0.95 可疑，<0.7 入外部池';
COMMENT ON COLUMN R_OUTPUT.master_output_id IS 'SimHash 命中重复后合并仲裁保留的主记录 id；NULL 表示自身即主记录';

-- -----------------------------------------------------------------------------
-- 2) R_PAPER_EXT · 论文扩展（1:1 R_OUTPUT）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_paper_doi      ON R_PAPER_EXT(tenant_id, doi);
CREATE INDEX idx_paper_wos      ON R_PAPER_EXT(wos_record_id);
CREATE INDEX idx_paper_scopus   ON R_PAPER_EXT(scopus_id);
CREATE INDEX idx_paper_cnki     ON R_PAPER_EXT(cnki_id);
CREATE INDEX idx_paper_if       ON R_PAPER_EXT(tenant_id, impact_factor DESC);
COMMENT ON TABLE  R_PAPER_EXT IS '论文扩展表：与 R_OUTPUT 1:1，output_id 为唯一外键';
COMMENT ON COLUMN R_PAPER_EXT.impact_factor IS '影响因子 NUMERIC(8,4)，由 R-12 数据管道年度刷新';

-- -----------------------------------------------------------------------------
-- 3) R_PATENT_EXT · 专利扩展（1:1 R_OUTPUT，全生命周期 R-06）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_patent_appno    ON R_PATENT_EXT(tenant_id, application_no);
CREATE INDEX idx_patent_legal    ON R_PATENT_EXT(tenant_id, legal_status);
CREATE INDEX idx_patent_annuity  ON R_PATENT_EXT(tenant_id, annuity_due_date);   -- 年费到期扫描
CREATE INDEX idx_patent_grantno  ON R_PATENT_EXT(grant_no);
COMMENT ON TABLE  R_PATENT_EXT IS '专利扩展表：与 R_OUTPUT 1:1，承载申请/授权/年费/法律状态全生命周期';
COMMENT ON COLUMN R_PATENT_EXT.legal_status IS '法律状态 token：申请中PENDING/审中EXAMINING/实审SUBSTANTIVE/授权GRANTED/年费应缴ANNUTY_DUE/无效INVALID/放弃ABANDONED；字典可配走 sys_dict';
COMMENT ON COLUMN R_PATENT_EXT.annuity_due_date IS '年费应缴日期，管道每日扫描生成 patent.annuity.due，提前 60/30/7 天通知';

-- -----------------------------------------------------------------------------
-- 4) R_SOFTWARE_EXT · 软著扩展（1:1 R_OUTPUT，R-07）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_soft_regno ON R_SOFTWARE_EXT(tenant_id, register_no);
COMMENT ON TABLE R_SOFTWARE_EXT IS '软件著作权扩展表：与 R_OUTPUT 1:1';

-- -----------------------------------------------------------------------------
-- 5) R_STANDARD_EXT · 标准扩展（1:1 R_OUTPUT，R-07）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_std_no ON R_STANDARD_EXT(tenant_id, standard_no);
COMMENT ON TABLE R_STANDARD_EXT IS '标准（国际/国家/行业/团体/企业）扩展表：与 R_OUTPUT 1:1';

-- -----------------------------------------------------------------------------
-- 6) R_AWARD_EXT · 科技奖励扩展（1:1 R_OUTPUT，R-08）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_award_date ON R_AWARD_EXT(tenant_id, award_date);
COMMENT ON TABLE R_AWARD_EXT IS '科技奖励（申报+获奖）扩展表：与 R_OUTPUT 1:1';

-- -----------------------------------------------------------------------------
-- 7) R_BOOK_EXT · 专著/编著扩展（1:1 R_OUTPUT，R-09）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_book_isbn ON R_BOOK_EXT(tenant_id, isbn);
COMMENT ON TABLE R_BOOK_EXT IS '专著/编著/教材/译著扩展表：与 R_OUTPUT 1:1';

-- -----------------------------------------------------------------------------
-- 8) R_CLAIM_RECORD · 认领记录（1:N R_OUTPUT，R-05）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_claim_output ON R_CLAIM_RECORD(output_id, user_id);   -- 认领去重主路径
CREATE INDEX idx_claim_user   ON R_CLAIM_RECORD(tenant_id, user_id, action_at);
CREATE INDEX idx_claim_batch  ON R_CLAIM_RECORD(batch_id);
COMMENT ON TABLE  R_CLAIM_RECORD IS '成果认领流水：CLAIM/REJECT/MARK_NOT_MINE/EDIT，支持批量与字段订正';
COMMENT ON COLUMN R_CLAIM_RECORD.batch_id IS '批量认领批次号；一次批量操作共享同一 batch_id';

-- -----------------------------------------------------------------------------
-- 9) R_METRIC_SNAPSHOT · 指标快照（日切，1:N R_OUTPUT，R-12/R-17）
-- -----------------------------------------------------------------------------
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
CREATE UNIQUE INDEX uk_metric_day ON R_METRIC_SNAPSHOT(output_id, snapshot_date);
CREATE INDEX idx_metric_output    ON R_METRIC_SNAPSHOT(tenant_id, output_id, snapshot_date);
COMMENT ON TABLE R_METRIC_SNAPSHOT IS '成果影响力度量日切快照：被引/关注度/下载，供趋势与画像（联动 S 模块）';

-- -----------------------------------------------------------------------------
-- 10) R_DATASET · 数据集/软件资源（1:1 可选 R_OUTPUT，R-13）
-- -----------------------------------------------------------------------------
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
CREATE INDEX idx_dataset_output ON R_DATASET(tenant_id, output_id);
COMMENT ON TABLE R_DATASET IS '数据集/软件资源表：与 R_OUTPUT 可选 1:1，承载存储地址、许可与下载/引用统计';

-- -----------------------------------------------------------------------------
-- 11) R_OUTPUT_PROJECT · 成果—项目关联表（N:N 规范化主存，R-10）
--     project_id 逻辑引用 E_PROJECT（跨模块不建物理外键，一致性走事件，见 §5）
-- -----------------------------------------------------------------------------
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
CREATE UNIQUE INDEX uk_output_project ON R_OUTPUT_PROJECT(output_id, project_id) WHERE deleted = 0;
CREATE INDEX idx_op_project           ON R_OUTPUT_PROJECT(tenant_id, project_id);   -- 项目结题选成果
CREATE INDEX idx_op_output            ON R_OUTPUT_PROJECT(tenant_id, output_id);
COMMENT ON TABLE  R_OUTPUT_PROJECT IS '成果—项目关联表（N:N 规范化主存）：替代 R_OUTPUT.project_ids JSON，二者可并存，本表为准';
COMMENT ON COLUMN R_OUTPUT_PROJECT.project_id IS '逻辑引用 E_PROJECT.id（02 模块），跨微服务库不建物理外键';

-- =============================================================================
-- 建表完毕：R 模块共 11 张表（1 主表 + 6 类型扩展 + 认领流水 + 指标快照 + 数据集 + 关联表）
-- =============================================================================
