-- =============================================================================
-- 06-科研诚信与伦理-C.ddl.sql · 科研诚信与伦理（C）模块建表脚本
-- 版本 v1.0 · 2026-10-13
-- 上游：../PRD/06-科研诚信与伦理.md（表 C_ETHICS_CASE 等 12 表 + C-01..C-19）、
--       ../README.md（全局约定 §2/§3/§4/§5）、./00-common.sql（横切表，通用审计 sys_audit_log 已存在，本模块不重复建）
-- 方言：PostgreSQL 15
--
-- 【信创达梦差异声明（对齐 design/README.md §2.4，达梦部署时按此替换）】
--   1) 自增主键：GENERATED ALWAYS AS IDENTITY  →  IDENTITY(1,1)
--   2) 时间戳：  TIMESTAMPTZ                    →  TIMESTAMP WITH TIME ZONE
--   3) 布尔：    BOOLEAN                        →  SMALLINT（0/1）
--   4) 半结构：  JSONB（materials/risk/objection/investigation/vote_result 等）
--                →  CLOB/VARCHAR 存 JSON 文本 + 应用层解析
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
--
-- 【单号前缀（PRD 2.11 / ./README.md §2.3）】
--   · C_ETHICS_CASE.code 使用已登记前缀 ETH（00-common.sql seq_prefix_registry 'ETH 伦理审查 C v1.0 per_entity=TRUE'），
--     pattern={prefix}-{yyyy}-{seq6}，即 ETH-年-序。
--   · C_DECISION_LETTER.letter_no 为批件编号（对外可验证），取 ETH 号段派生或独立批件号，公开可查编号、不可查内容。
--   · C_HGR_FILING.national_approval_no 为【国家人遗系统回传的外部号】，非本系统编号中心产物，不强约束唯一前缀。
--   · C_INTEGRITY_RECORD.case_no 走通用编号（失信案号），前缀待 2.11 登记后方可下发（详见 detail.md §10），本脚本仅建列不强约束。
--
-- 【涉密边界（C-19 / PRD 2.13）】本模块不存涉密正文，仅记录 security_level 与移交 X 模块的引用（x_ref）。
--   涉及数据出境（DATA_EXPORT）、人类遗传资源（HGR）等敏感事项标注 security_level，涉密正文由 X 模块管理。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) C_ETHICS_CASE · 伦理审查案卷（聚合根；1:N 挂各从表，1:1 挂 C_DECISION_LETTER / C_HGR_FILING）
--    project_id 逻辑引用 E_PROJECT（02 模块，跨微服务库不建物理外键）
-- -----------------------------------------------------------------------------
CREATE TABLE C_ETHICS_CASE (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),                                 -- ETH-年-序（统一编号中心，已登记前缀 ETH）
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL
                       CHECK (status IN (
                         'DRAFT','SUBMITTED','FORMAL_CHECK','UNDER_REVIEW','NEEDS_REVISION',
                         'APPROVED','REJECTED','MONITORING','EXPIRED')),  -- PRD §6.2 案卷状态机
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  review_type          VARCHAR(32)  NOT NULL
                       CHECK (review_type IN ('HUMAN','ANIMAL','BIO_SAFETY','HGR','DATA_EXPORT')),  -- C-01 审查类型
  project_id           BIGINT,                                      -- 逻辑引用 E_PROJECT.id（可空：预申报阶段先于立项）
  applicant_user_id    BIGINT       NOT NULL,                       -- PI/申请人 sys_user.id（逻辑引用）
  department_id        BIGINT,                                      -- 申请所属部门 sys_org.id（回避判定用，逻辑引用）
  protocol_title       VARCHAR(512) NOT NULL,
  protocol_summary     TEXT,                                        -- 研究方案摘要（涉受试者信息，读接口权限隔离）
  methodology          TEXT,                                        -- 方法学描述
  risk_level           VARCHAR(16)  NOT NULL DEFAULT 'MED'
                       CHECK (risk_level IN ('HIGH','MED','LOW')),  -- 高→会议审查，低→紧急/简化审查（PRD §6.1）
  materials            JSONB        NOT NULL DEFAULT '[]',          -- [{name,url,type,uploaded_at}] 方案/招募材料等附件
  informed_consent_url VARCHAR(512),                                -- 知情同意书对象存储地址（可追溯，PRD §12）
  risk_assessment      JSONB        NOT NULL DEFAULT '{}',          -- AI 伦理风险预判结果 {risk_points:[],need_supplement:[],confidence}
  ai_prescreen         JSONB        NOT NULL DEFAULT '{}',          -- 关键要素完整性预审 {missing_fields:[],passed:boolean}
  submitted_at         TIMESTAMPTZ,                                 -- 正式提交时间（进入 FORMAL_CHECK 前置）
  decision_date        DATE,                                        -- 审查决定日期
  valid_until          DATE,                                        -- 批件有效期截止（到期→EXPIRED，联动 F 冻结支付）
  next_review_at       DATE,                                        -- 下次年度复审日期（复审提醒主键，30 天提前）
  is_emergency         BOOLEAN      NOT NULL DEFAULT FALSE,         -- 紧急/快速通道标记（C-05）
  -- 治理三字段（§2.1 v1.1；涉密/法人隔离，C-19）
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密正文由 X 管理
  x_ref                VARCHAR(64),                                 -- 移交 X 模块涉密外传审计的引用（EXF-年-序），本模块不存涉密正文
  policy_pack_id       BIGINT                                       -- 命中的伦理审查制度包快照（PRD 2.10，可复算）
);

CREATE UNIQUE INDEX uk_ethics_code        ON C_ETHICS_CASE(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX        idx_ethics_main       ON C_ETHICS_CASE(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_ethics_project    ON C_ETHICS_CASE(tenant_id, project_id);
CREATE INDEX        idx_ethics_applicant  ON C_ETHICS_CASE(tenant_id, applicant_user_id);
CREATE INDEX        idx_ethics_type_risk  ON C_ETHICS_CASE(tenant_id, review_type, risk_level);
CREATE INDEX        idx_ethics_validuntil ON C_ETHICS_CASE(tenant_id, valid_until);     -- 到期扫描→EXPIRED/冻结
CREATE INDEX        idx_ethics_nextreview ON C_ETHICS_CASE(tenant_id, next_review_at);  -- 年度复审 30 天提醒扫描
CREATE INDEX        idx_ethics_dept       ON C_ETHICS_CASE(tenant_id, department_id);   -- 回避判定
CREATE INDEX        idx_ethics_materials  ON C_ETHICS_CASE USING GIN (materials jsonb_path_ops);

COMMENT ON TABLE  C_ETHICS_CASE IS '伦理审查案卷（聚合根）：5 类审查（人体/动物/生安/人遗/数据出境），1:N 分派/意见/会议/修正/不良/年度复审，1:1 批件';
COMMENT ON COLUMN C_ETHICS_CASE.code IS '伦理案卷编号 ETH-年-序（前缀 ETH 已在 seq_prefix_registry 登记，owner_module=C，per_entity 分号段）';
COMMENT ON COLUMN C_ETHICS_CASE.status IS '案卷状态机（§4/PRD §6.2）：DRAFT/SUBMITTED/FORMAL_CHECK/UNDER_REVIEW/NEEDS_REVISION/APPROVED/REJECTED/MONITORING/EXPIRED';
COMMENT ON COLUMN C_ETHICS_CASE.review_type IS '审查类型：HUMAN 人体/ANIMAL 动物/BIO_SAFETY 生物安全/HGR 人类遗传资源/DATA_EXPORT 数据出境（C-01）';
COMMENT ON COLUMN C_ETHICS_CASE.risk_level IS '风险等级 HIGH/MED/LOW：HIGH 走会议审查，LOW 可紧急/简化审查（PRD §6.1）';
COMMENT ON COLUMN C_ETHICS_CASE.protocol_summary IS '研究方案摘要——涉受试者信息，属敏感数据，读接口严格权限隔离（PI/分派委员/主审/管理员）';
COMMENT ON COLUMN C_ETHICS_CASE.informed_consent_url IS '知情同意书地址，可追溯（PRD §12 合规要求）';
COMMENT ON COLUMN C_ETHICS_CASE.valid_until IS '批件有效期截止；到期未复审→status=EXPIRED，并联动 F 模块冻结该项目支付（见 detail §4）';
COMMENT ON COLUMN C_ETHICS_CASE.security_level IS '涉密等级；涉及数据出境/涉密事项标 SECRET/TOP_SECRET，涉密正文由 X 模块管理';
COMMENT ON COLUMN C_ETHICS_CASE.x_ref IS '移交模块 X 的涉密外传审计引用（EXF 号），本模块不存涉密正文，只留引用（C-19）';

-- -----------------------------------------------------------------------------
-- 2) C_REVIEWER_ASSIGN · 分派主审 + 委员（1:N C_ETHICS_CASE；同模块物理外键 case_id）
-- -----------------------------------------------------------------------------
CREATE TABLE C_REVIEWER_ASSIGN (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ASSIGNED'
                       CHECK (status IN ('ASSIGNED','ACCEPTED','RECUSED','COMPLETED','TIMEOUT','REASSIGNED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       NOT NULL REFERENCES C_ETHICS_CASE(id),
  reviewer_user_id     BIGINT       NOT NULL,                       -- 委员/主审 sys_user.id（逻辑引用）
  role                 VARCHAR(16)  NOT NULL CHECK (role IN ('CHIEF','BOARD')),  -- CHIEF 主审 / BOARD 委员
  assigned_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  deadline             TIMESTAMPTZ,                                 -- 审阅时限（超期→TIMEOUT 自动升级催办）
  conflict_of_interest BOOLEAN      NOT NULL DEFAULT FALSE,         -- 利益冲突回避命中标记（同部门/师生强制回避）
  coi_reason           VARCHAR(256)                                 -- 回避事由（同部门/师生关系等）
);
CREATE UNIQUE INDEX uk_assign_case_reviewer ON C_REVIEWER_ASSIGN(case_id, reviewer_user_id) WHERE deleted = 0;
CREATE INDEX        idx_assign_reviewer     ON C_REVIEWER_ASSIGN(tenant_id, reviewer_user_id, status);  -- 委员工作台待审列表
CREATE INDEX        idx_assign_case         ON C_REVIEWER_ASSIGN(case_id);
CREATE INDEX        idx_assign_deadline     ON C_REVIEWER_ASSIGN(tenant_id, deadline);   -- 超期扫描→催办升级
COMMENT ON TABLE  C_REVIEWER_ASSIGN IS '审查分派：为案卷指派主审(CHIEF)与委员(BOARD)；(case_id,reviewer) 唯一';
COMMENT ON COLUMN C_REVIEWER_ASSIGN.role IS '角色：CHIEF 主审（签发批件）/ BOARD 委员（打分与意见）';
COMMENT ON COLUMN C_REVIEWER_ASSIGN.deadline IS '审阅时限，超期由调度扫描置 TIMEOUT 并升级通知管理员催办（PRD §11 审查超期）';
COMMENT ON COLUMN C_REVIEWER_ASSIGN.conflict_of_interest IS '利益冲突回避：与 PI 同部门或有师生关系时强制回避（true 不得参与本案卷评审）';

-- -----------------------------------------------------------------------------
-- 3) C_REVIEW_OPINION · 委员审阅意见与打分（1:N C_ETHICS_CASE）
-- -----------------------------------------------------------------------------
CREATE TABLE C_REVIEW_OPINION (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'SUBMITTED'
                       CHECK (status IN ('DRAFT','SUBMITTED','SUPERSEDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       NOT NULL REFERENCES C_ETHICS_CASE(id),
  reviewer_user_id     BIGINT       NOT NULL,                       -- sys_user.id（逻辑引用）；对 PI 匿名展示
  score                NUMERIC(6,4),                                -- 打分（比例/置信度精度 §2.2）
  comments             TEXT,                                        -- 意见正文（PI 视角匿名，PRD §7.2）
  objection            JSONB        NOT NULL DEFAULT '{}',          -- 异议/质询 {points:[], requested_docs:[]}
  risks_identified     JSONB        NOT NULL DEFAULT '[]',          -- 识别风险点 [{item,severity,note}]
  recommendation       VARCHAR(32)  NOT NULL
                       CHECK (recommendation IN ('APPROVE','APPROVE_WITH_CHANGES','REJECT'))  -- 建议结论
);
CREATE UNIQUE INDEX uk_opinion_case_reviewer ON C_REVIEW_OPINION(case_id, reviewer_user_id) WHERE deleted = 0 AND status <> 'SUPERSEDED';
CREATE INDEX        idx_opinion_case         ON C_REVIEW_OPINION(case_id);
CREATE INDEX        idx_opinion_reviewer     ON C_REVIEW_OPINION(tenant_id, reviewer_user_id);
COMMENT ON TABLE  C_REVIEW_OPINION IS '委员独立审阅意见：打分 + 意见 + 异议 + 风险点 + 建议（APPROVE/APPROVE_WITH_CHANGES/REJECT）';
COMMENT ON COLUMN C_REVIEW_OPINION.score IS '打分 NUMERIC(6,4)；用于会议审查参考与决议汇聚';
COMMENT ON COLUMN C_REVIEW_OPINION.recommendation IS '委员建议：APPROVE 批准/APPROVE_WITH_CHANGES 修改后批准/REJECT 不批准（主审汇聚，C-04/C-06）';

-- -----------------------------------------------------------------------------
-- 4) C_MEETING_RECORD · 会议审查纪要（1:N C_ETHICS_CASE；在线签到/表决/自动生成纪要，C-04）
-- -----------------------------------------------------------------------------
CREATE TABLE C_MEETING_RECORD (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'SCHEDULED'
                       CHECK (status IN ('SCHEDULED','IN_PROGRESS','MINUTED','FINALIZED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       NOT NULL REFERENCES C_ETHICS_CASE(id),
  meeting_date         TIMESTAMPTZ  NOT NULL,
  attendees            JSONB        NOT NULL DEFAULT '[]',          -- 签到 [{user_id,name,role,signed_in,signed_at}]
  quorum_met           BOOLEAN      NOT NULL DEFAULT FALSE,         -- 是否达到法定到会人数
  discussion_text      TEXT,                                        -- 讨论记录（自动生成纪要）
  decision             VARCHAR(32)  CHECK (decision IN ('APPROVE','APPROVE_WITH_CHANGES','REJECT','CONTINUE')),
  vote_result          JSONB        NOT NULL DEFAULT '{}'           -- 表决 {approve:n,reject:n,abstain:n,total:n,pass:bool}
);
CREATE INDEX idx_meeting_case ON C_MEETING_RECORD(case_id);
CREATE INDEX idx_meeting_date ON C_MEETING_RECORD(tenant_id, meeting_date);
COMMENT ON TABLE  C_MEETING_RECORD IS '会议审查纪要：出席签到 + 法定人数 + 讨论 + 表决结果 + 决议';
COMMENT ON COLUMN C_MEETING_RECORD.attendees IS '签到 JSONB：[{user_id,name,role,signed_in,signed_at}]，回避委员不计入表决';
COMMENT ON COLUMN C_MEETING_RECORD.vote_result IS '表决结果 JSONB，达法定人数通过（PRD §11 利益冲突回避在此汇聚剔除）';

-- -----------------------------------------------------------------------------
-- 5) C_DECISION_LETTER · 伦理批件（1:1 C_ETHICS_CASE；签发 + 对外公开验证 + 二维码，C-06）
-- -----------------------------------------------------------------------------
CREATE TABLE C_DECISION_LETTER (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','ISSUED','PUBLISHED','REVOKED','EXPIRED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,                       -- 主审 CHIEF 签发
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       NOT NULL UNIQUE REFERENCES C_ETHICS_CASE(id),  -- 1:1
  decision_type        VARCHAR(32)  NOT NULL
                       CHECK (decision_type IN ('APPROVE','APPROVE_WITH_CHANGES','REJECT')),
  letter_no            VARCHAR(64)  NOT NULL,                       -- 批件编号（对外可验证，编号可查内容不可查）
  letter_url           VARCHAR(512),                                -- 批件 PDF 地址
  verify_url           VARCHAR(512),                                -- 公开验证页（GET /ethics/letter/{letterNo}）
  qr_code_url          VARCHAR(512),                                -- 验证二维码图片地址
  signature_url        VARCHAR(512),                                -- 电子签名存证（svc-integration 电子签名服务）
  issued_at            TIMESTAMPTZ,                                 -- 签发时间
  expires_at           TIMESTAMPTZ                                  -- 批件到期（→EXPIRED 联动 F 冻结）
);
CREATE UNIQUE INDEX uk_letter_no        ON C_DECISION_LETTER(tenant_id, letter_no) WHERE deleted = 0;
CREATE INDEX        idx_letter_case     ON C_DECISION_LETTER(case_id);
CREATE INDEX        idx_letter_expires  ON C_DECISION_LETTER(tenant_id, expires_at);
COMMENT ON TABLE  C_DECISION_LETTER IS '伦理批件：主审签发，1:1 案卷；对外公开验证（编号可查、内容不可查）+ 二维码';
COMMENT ON COLUMN C_DECISION_LETTER.letter_no IS '批件编号，对外唯一可验证标识；GET /ethics/letter/{letterNo} 仅返回真伪与该案卷存在性，不泄露受试者内容';
COMMENT ON COLUMN C_DECISION_LETTER.verify_url IS '公开验证页地址（PRD §12 批件编号可外部验证：公开 URL + 二维码）';
COMMENT ON COLUMN C_DECISION_LETTER.expires_at IS '批件到期时点；到期扫描→status=EXPIRED 且案卷 EXPIRED，联动 F 冻结该项目经费支付（detail §4）';

-- -----------------------------------------------------------------------------
-- 6) C_AMENDMENT · 修正案审查（方案变更，1:N C_ETHICS_CASE，C-08）
-- -----------------------------------------------------------------------------
CREATE TABLE C_AMENDMENT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','APPROVED','REJECTED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       NOT NULL REFERENCES C_ETHICS_CASE(id),
  change_summary       TEXT         NOT NULL,                       -- 变更摘要
  materials            JSONB        NOT NULL DEFAULT '[]',          -- 变更材料附件
  submitted_at         TIMESTAMPTZ,
  decided_at           TIMESTAMPTZ,
  decision_note        TEXT                                         -- 修正案决定说明
);
CREATE INDEX idx_amendment_case ON C_AMENDMENT(case_id);
CREATE INDEX idx_amendment_status ON C_AMENDMENT(tenant_id, status);
COMMENT ON TABLE C_AMENDMENT IS '修正案审查：批件有效期内研究方案变更的再审查（C-08）';

-- -----------------------------------------------------------------------------
-- 7) C_AE_REPORT · 不良事件报告（1:N C_ETHICS_CASE，C-09）
-- -----------------------------------------------------------------------------
CREATE TABLE C_AE_REPORT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'REPORTED'
                       CHECK (status IN ('REPORTED','ASSESSING','ACTIONED','CLOSED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       NOT NULL REFERENCES C_ETHICS_CASE(id),
  event_date           TIMESTAMPTZ  NOT NULL,
  severity             VARCHAR(16)  NOT NULL CHECK (severity IN ('SERIOUS','NON_SERIOUS','SUSAR')),  -- 严重/非严重/可疑非预期严重
  description          TEXT         NOT NULL,                       -- 涉受试者信息，敏感，权限隔离
  action_taken         TEXT,                                        -- 已采取措施
  reported_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  assessed_by          BIGINT                                       -- 主审评估人 sys_user.id
);
CREATE INDEX idx_ae_case     ON C_AE_REPORT(case_id);
CREATE INDEX idx_ae_severity ON C_AE_REPORT(tenant_id, severity, event_date);  -- 严重不良事件升级扫描
COMMENT ON TABLE  C_AE_REPORT IS '不良事件报告：严重/非严重/可疑非预期严重事件（C-09）；SERIOUS/SUSAR 触发主审快速评估';
COMMENT ON COLUMN C_AE_REPORT.description IS '不良事件描述——涉受试者信息，敏感，读接口严格权限隔离';

-- -----------------------------------------------------------------------------
-- 8) C_ANNUAL_REVIEW · 年度复审与跟踪（1:N C_ETHICS_CASE，C-07）
-- -----------------------------------------------------------------------------
CREATE TABLE C_ANNUAL_REVIEW (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','SUBMITTED','UNDER_REVIEW','APPROVED','OVERDUE')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       NOT NULL REFERENCES C_ETHICS_CASE(id),
  review_year          SMALLINT     NOT NULL,                       -- 复审年度
  progress_summary     TEXT,                                        -- 研究进展报告
  incidents            JSONB        NOT NULL DEFAULT '[]',          -- 本年事件汇总（含不良事件引用）
  next_plan            TEXT,                                        -- 下一年度计划
  submitted_at         TIMESTAMPTZ,
  approved_at          TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_annual_case_year ON C_ANNUAL_REVIEW(case_id, review_year) WHERE deleted = 0;
CREATE INDEX        idx_annual_case     ON C_ANNUAL_REVIEW(case_id);
CREATE INDEX        idx_annual_status   ON C_ANNUAL_REVIEW(tenant_id, status);
COMMENT ON TABLE C_ANNUAL_REVIEW IS '年度复审与跟踪：批件有效期内按年复审，进度/事件/计划；逾期→OVERDUE（联动案卷 EXPIRED 判断）';

-- -----------------------------------------------------------------------------
-- 9) C_INTEGRITY_PLEDGE · 诚信承诺签署（USER 1:N，C-15；电子签名 + 阅读倒计时存证）
-- -----------------------------------------------------------------------------
CREATE TABLE C_INTEGRITY_PLEDGE (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'SIGNED'
                       CHECK (status IN ('PENDING','SIGNED','REVOKED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id              BIGINT       NOT NULL,                       -- sys_user.id（逻辑引用）
  pledge_type          VARCHAR(32)  NOT NULL,                        -- 承诺类型：入职/申报/评奖/年度（走 sys_dict c_pledge_type，禁止硬编码 PRD 2.8）
  content_version      VARCHAR(32)  NOT NULL,                        -- 承诺文本版本（可追溯）
  read_seconds         INT          NOT NULL DEFAULT 0,              -- 阅读倒计时秒数（前端强制阅读时长存证）
  signed_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  signature_url        VARCHAR(512),                                 -- 电子签名板存证（svc-integration 电子签名）
  ip                   VARCHAR(64),
  ua                   VARCHAR(256),
  biz_ref_type         VARCHAR(32),                                  -- 关联业务对象：APPLICATION/AWARD/ANNUAL/ONBOARD（可空）
  biz_ref_id           BIGINT                                        -- 关联业务对象 id（如某次申报，逻辑引用）
);
CREATE UNIQUE INDEX uk_pledge_code   ON C_INTEGRITY_PLEDGE(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX        idx_pledge_user  ON C_INTEGRITY_PLEDGE(tenant_id, user_id, pledge_type, signed_at);
COMMENT ON TABLE  C_INTEGRITY_PLEDGE IS '科研诚信承诺签署记录：入职/申报/评奖/年度，电子签名 + 阅读倒计时 + IP/UA 存证（C-15）';
COMMENT ON COLUMN C_INTEGRITY_PLEDGE.pledge_type IS '承诺类型走字典 sys_dict（建议字典码 c_pledge_type：ONBOARD/APPLY/AWARD/ANNUAL），不落 CHECK 硬编码，便于扩值与多语言';
COMMENT ON COLUMN C_INTEGRITY_PLEDGE.content_version IS '承诺文本版本号，文本更新后需按新版本重签（合规可追溯）';

-- -----------------------------------------------------------------------------
-- 10) C_INTEGRITY_RECORD · 失信档案（USER 1:N，C-16；独立调查/申诉流程，非伦理案卷状态机）
-- -----------------------------------------------------------------------------
CREATE TABLE C_INTEGRITY_RECORD (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'CREATED'
                       CHECK (status IN ('CREATED','APPEALING','CLOSED')),        -- 对外可见性/申诉主状态
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id              BIGINT       NOT NULL,                       -- 被记录人 sys_user.id（逻辑引用）
  event_type           VARCHAR(32)  NOT NULL,                        -- 事件类型：抄袭/数据造假/一稿多投/违规报销/利益冲突未申报/其他（走 sys_dict c_event_type）
  event_type_code      VARCHAR(32)  NOT NULL,                        -- 字典项码 PLAGIARISM/DATA_FABRICATION/DUAL_SUBMISSION/EXPENSE_VIOLATION/COI_UNDISCLOSED/OTHER
  discovered_date      DATE,
  evidence             JSONB        NOT NULL DEFAULT '[]',          -- 证据 [{name,url,source}]
  investigation        JSONB        NOT NULL DEFAULT '{}',          -- 调查过程 {steps:[],conclusion_ref,interview:[]}
  case_no              VARCHAR(64),                                 -- 失信案号（通用编号，前缀待 2.11 登记，见 detail §10）
  investigation_status VARCHAR(32)  NOT NULL DEFAULT 'INVESTIGATING'
                       CHECK (investigation_status IN ('INVESTIGATING','SUSTAINED','UNSUSTAINED','CLOSED')),  -- 独立调查状态机
  decision             TEXT,                                        -- 处理决定
  sanction             VARCHAR(64),                                 -- 处分（字典 c_sanction）
  sanction_effective_until DATE,                                    -- 处分影响期截止
  is_public            BOOLEAN      NOT NULL DEFAULT FALSE,         -- 是否对外公开（默认仅纪检与本人可见部分对外）
  -- 申诉（独立流程，PRD §11 异议/申诉）
  appeal_status        VARCHAR(32)  NOT NULL DEFAULT 'NONE'
                       CHECK (appeal_status IN ('NONE','FILED','REVIEWING','UPHELD','OVERTURNED')),
  appeal_deadline      DATE,                                        -- 申诉截止（收到通知起可申诉期）
  appeal_reason        TEXT,
  appealed_at          TIMESTAMPTZ,
  appeal_resolved_at   TIMESTAMPTZ,
  -- 治理三字段（法人隔离；纪检内部可见性）
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_integrity_code ON C_INTEGRITY_RECORD(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX        idx_integrity_user ON C_INTEGRITY_RECORD(tenant_id, user_id, investigation_status);  -- 个人诚信标签页
CREATE INDEX        idx_integrity_type ON C_INTEGRITY_RECORD(tenant_id, event_type_code);
CREATE INDEX        idx_integrity_pub  ON C_INTEGRITY_RECORD(tenant_id, is_public);
CREATE INDEX        idx_integrity_appeal ON C_INTEGRITY_RECORD(appeal_status);
COMMENT ON TABLE  C_INTEGRITY_RECORD IS '失信档案：违规事实 + 证据 + 调查 + 处理决定 + 处分影响期 + 本人申诉（独立于伦理案卷状态机）';
COMMENT ON COLUMN C_INTEGRITY_RECORD.investigation_status IS '独立调查状态机：INVESTIGATING 调查中/SUSTAINED 事实成立/UNSUSTAINED 不成立/CLOSED 结案（不套用 §6.2 案卷状态）';
COMMENT ON COLUMN C_INTEGRITY_RECORD.event_type_code IS '事件类型走字典 sys_dict（建议字典码 c_event_type：抄袭/数据造假/一稿多投/违规报销/利益冲突未申报/其他），禁止硬编码';
COMMENT ON COLUMN C_INTEGRITY_RECORD.is_public IS '对外公开标记；默认 FALSE，仅纪检与本人可见（PRD §9），公开范围经审批后置 TRUE';
COMMENT ON COLUMN C_INTEGRITY_RECORD.appeal_status IS '申诉独立流程：NONE/FILED/REVIEWING/UPHELD 维持/OVERTURNED 撤销；申诉期内冻结处分生效';

-- -----------------------------------------------------------------------------
-- 11) C_MISCONDUCT_SCAN · 学术不端检测记录（多态 target，C-14/C-18）
--     target_type PAPER(→04 R_OUTPUT)/DEAL(→05 T)/OUTPUT(→04 R)；跨模块仅存 id 逻辑引用
-- -----------------------------------------------------------------------------
CREATE TABLE C_MISCONDUCT_SCAN (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','RUNNING','DONE','FAILED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  target_type          VARCHAR(32)  NOT NULL CHECK (target_type IN ('PAPER','DEAL','OUTPUT')),  -- 检测对象类型（逻辑引用）
  target_id            BIGINT       NOT NULL,                       -- 检测对象主键（R_OUTPUT.id / DEAL.id 等，跨模块逻辑外键）
  scan_type            VARCHAR(32)  NOT NULL
                       CHECK (scan_type IN ('TEXT_DUP','IMAGE_DUP','DATA_ANOMALY')),  -- 文字查重/图片查重/数据异常（C-14）
  score                NUMERIC(6,4),                                -- 相似度/异常度（0..1）
  confidence           NUMERIC(6,4),                                -- AI 判定置信度（进阶 C-18 多模态）
  report_url           VARCHAR(512),                                -- 查重/检测报告地址
  verdict              VARCHAR(32)  CHECK (verdict IN ('CLEAN','SUSPECTED','CONFIRMED')),  -- 结论
  engine               VARCHAR(32)  CHECK (engine IN ('CNKI','TURNITIN','PHASH_CNN','BENFORD','MULTIMODAL_LLM')),  -- 检测引擎（svc-integration/svc-ai-gateway）
  triggered_by         VARCHAR(32)  NOT NULL DEFAULT 'MANUAL'
                       CHECK (triggered_by IN ('MANUAL','ON_REGISTER','PRE_FUNDING','SCHEDULED')),  -- 触发方式
  scanned_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  investigation_id     BIGINT                                       -- 升级为失信调查时回指 C_INTEGRITY_RECORD.id（可选，同模块逻辑）
);
CREATE INDEX idx_scan_target   ON C_MISCONDUCT_SCAN(tenant_id, target_type, target_id);
CREATE INDEX idx_scan_verdict  ON C_MISCONDUCT_SCAN(tenant_id, verdict, scan_type);
CREATE INDEX idx_scan_score    ON C_MISCONDUCT_SCAN(tenant_id, score DESC);
COMMENT ON TABLE  C_MISCONDUCT_SCAN IS '学术不端检测记录：对 PAPER/DEAL/OUTPUT 多态目标做文字查重/图片查重/数据异常扫描（C-14/C-18）';
COMMENT ON COLUMN C_MISCONDUCT_SCAN.target_type IS '检测对象：PAPER(论文→R_OUTPUT)/DEAL(转化→T)/OUTPUT(成果→R)，跨模块仅存 id 逻辑外键';
COMMENT ON COLUMN C_MISCONDUCT_SCAN.scan_type IS '扫描类型：TEXT_DUP 文字查重(CNKI/Turnitin)/IMAGE_DUP 图片查重(pHash+CNN)/DATA_ANOMALY 数据异常(Benford/方差/重复值)';
COMMENT ON COLUMN C_MISCONDUCT_SCAN.confidence IS 'AI 判定置信度 NUMERIC(6,4)；低置信需人工兜底复核（detail §4 规则引擎 vs LLM 分工）';

-- -----------------------------------------------------------------------------
-- 12) C_HGR_FILING · 人类遗传资源备案（对接国家系统，1:1 可选挂 E_PROJECT / 案卷，C-10）
--     national_approval_no 为【国家人遗系统回传外部号】，非本系统编号中心产物
-- -----------------------------------------------------------------------------
CREATE TABLE C_HGR_FILING (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','SUBMITTED','NATIONAL_RECEIVED','APPROVED','REJECTED','EXPIRED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  case_id              BIGINT       REFERENCES C_ETHICS_CASE(id),   -- 关联伦理案卷（HGR 类，同模块物理外键，可空）
  project_id           BIGINT,                                      -- 逻辑引用 E_PROJECT.id（跨模块）
  filing_type          VARCHAR(32)  NOT NULL,                        -- 备案类型：采集/保藏/国际合作/开发利用（走 sys_dict c_hgr_filing_type）
  filing_type_code     VARCHAR(32)  NOT NULL CHECK (filing_type_code IN ('COLLECT','PRESERVE','INTL_COOP','DEVELOP')),
  filing_no            VARCHAR(64),                                 -- 本系统备案流水号
  national_approval_no VARCHAR(64),                                 -- 国家人遗管理服务系统批准号（外部回传号，非编号中心）
  submission_date      DATE,
  approval_status      VARCHAR(32)  CHECK (approval_status IN ('PENDING','APPROVED','REJECTED')),  -- 国家侧审批状态镜像
  approval_date        DATE,
  expiry_date          DATE,
  sync_batch_id        VARCHAR(64),                                 -- 对接国家系统同步批次（svc-integration 回执追溯）
  -- 治理：人遗资源涉国家安全，默认 INTERNAL，涉外/涉密升 SEC 域（正文由 X 管理）
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  x_ref                VARCHAR(64)                                  -- 涉外/涉密移交 X 的引用
);
CREATE UNIQUE INDEX uk_hgr_code      ON C_HGR_FILING(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE UNIQUE INDEX uk_hgr_national  ON C_HGR_FILING(tenant_id, national_approval_no) WHERE deleted = 0 AND national_approval_no IS NOT NULL;
CREATE INDEX        idx_hgr_project  ON C_HGR_FILING(tenant_id, project_id);
CREATE INDEX        idx_hgr_case     ON C_HGR_FILING(case_id);
CREATE INDEX        idx_hgr_expiry   ON C_HGR_FILING(tenant_id, expiry_date);
COMMENT ON TABLE  C_HGR_FILING IS '人类遗传资源备案：采集/保藏/国际合作/开发利用，对接国家人遗管理服务系统（C-10）';
COMMENT ON COLUMN C_HGR_FILING.filing_type IS '备案类型走字典 sys_dict（c_hgr_filing_type：采集/保藏/国际合作/开发利用）；filing_type_code 为规范化 token';
COMMENT ON COLUMN C_HGR_FILING.national_approval_no IS '国家人遗系统批准号，为外部系统回传号，非统一编号中心产物，故仅做 (tenant) 唯一去重不套前缀规范';
COMMENT ON COLUMN C_HGR_FILING.security_level IS '人遗资源涉国家安全，涉外/涉密事项升 SECRET，涉密正文与出境材料由 X 模块管理';

-- =============================================================================
-- 建表完毕：C 模块共 12 张表
--   案卷中心：C_ETHICS_CASE（聚合根）
--   审查从表：C_REVIEWER_ASSIGN / C_REVIEW_OPINION / C_MEETING_RECORD / C_DECISION_LETTER(1:1)
--             / C_AMENDMENT / C_AE_REPORT / C_ANNUAL_REVIEW
--   诚信相关：C_INTEGRITY_PLEDGE / C_INTEGRITY_RECORD（独立调查/申诉状态机）
--   检测/备案：C_MISCONDUCT_SCAN（多态目标） / C_HGR_FILING（对接国家系统）
-- 通用审计复用 00-common.sys_audit_log，本模块不重复建表。
-- =============================================================================
