-- =============================================================================
-- 01-项目申报与立项-P.ddl.sql · M1 核心模块 P（Project Application）建表脚本
-- 版本 v1.0 · 2026-10-13
-- 方言：PostgreSQL 15
-- 归属微服务：svc-project（P 域）；逻辑库隔离，跨模块只存对方主键 id 作逻辑外键
--
-- ── 信创达梦差异（参见 design/README.md §2.4，达梦部署时按此替换）───────────────
--   1) 自增主键   GENERATED ALWAYS AS IDENTITY  →  IDENTITY(1,1)
--   2) 时间戳     TIMESTAMPTZ                    →  TIMESTAMP WITH TIME ZONE
--   3) 布尔       BOOLEAN                        →  SMALLINT（0/1）
--   4) JSON       JSONB                          →  CLOB / VARCHAR 存 JSON 文本 + 应用层解析
--   5) 数组       VARCHAR(16)[]                  →  CLOB 存序列化 + 应用层解析（或关联子表）
--   6) CHECK(IN)  同                             →  同
--   7) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE →  用普通唯一索引 + deleted 复合键替代
--   8) 全文检索   tsvector / pg_trgm             →  应用层 ES / 达梦全文索引
--
-- ── 通用列（design/README.md §2.1）已在每张业务表内联，列名与类型完全一致 ────────
--   id / code / tenant_id / status / deleted / creator_id / modifier_id
--   created_at / updated_at / remark
--   说明：P 模块不携带 legal_entity_id / security_level / policy_pack_id 治理三列。
--         · 立项/申报的法人归属经 pi_user_id → sys_user.legal_entity_id / sys_org 派生，
--           避免跨模块冗余存储（PRD 2.15 单一事实来源）；跨法人联合攻关在主责法人登记，
--           由 svc-project 读取时关联 sys_org，不在 P 表落 legal_entity_id。
--         · 涉密项目密级由 X 模块（sys_user.security_level / x_flow_audit）治理，
--           P 表 security_level 暂不落地；若后续涉密申报需在办公/涉密分域部署，
--           届时以增补脚本追加三列（见 detail.md §10 待细化）。
--         · 制度包快照 policy_pack_id 落在下游 03 经费预算（F_BUDGET），P 侧预算草稿
--           仅作合规预检提示（ai_compliance_*），不作确定性复算依据。
--
-- ── 标量约定（design/README.md §2.2）：金额 NUMERIC(18,2)；时间 TIMESTAMPTZ；
--     半结构化 JSONB；枚举 VARCHAR + CHECK(IN)；字典可配项走 sys_dict 禁止硬编码。
--
-- ── 编号（design/README.md §2.3 / PRD 2.11）：code 值由统一编号中心 svc-numbering 分配。
--     P_APPLICATION.code 与 P_TASK_BOOK.code 复用已登记前缀 PRJ（项目/立项，P/E 拥有）；
--     P_GUIDELINE / P_TEMPLATE.code 为管理员可读配置码（非全局唯一单号），
--     仅做 (tenant_id, code) 唯一。未自造新的单号前缀。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- P_GUIDELINE · 申报指南（P-02 指南发布与浏览）
-- -----------------------------------------------------------------------------
CREATE TABLE p_guideline (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','PUBLISHED','CLOSED')),
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  title             VARCHAR(256) NOT NULL,
  project_type      VARCHAR(64)  NOT NULL,          -- 字典 sys_dict(project_type) 的 item_code
  funding_source    VARCHAR(128),                   -- 资助来源/发起单位（文本，来自字典或手填）
  target_disciplines JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- 目标学科方向数组 [{code,label}]
  apply_start_at    TIMESTAMPTZ,                    -- 申报窗口开始
  apply_end_at      TIMESTAMPTZ,                    -- 申报截止（超期拦截判定基准，PRD §11）
  total_envelope    NUMERIC(18,2),                  -- 指南总盘子（资助总额，单位元）
  content_rich      TEXT,                           -- 指南正文（富文本/Markdown 原文）
  attachment_ids    JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- 附件对象存储 id 数组
  publish_at        TIMESTAMPTZ                     -- 实际发布时间
);
CREATE UNIQUE INDEX uk_p_guideline_code ON p_guideline(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_p_guideline_type       ON p_guideline(tenant_id, project_type);
CREATE INDEX idx_p_guideline_end        ON p_guideline(apply_end_at);
CREATE INDEX idx_p_guideline_tenant_st  ON p_guideline(tenant_id, status);

COMMENT ON TABLE  p_guideline IS '申报指南：管理员发布，科研人员浏览/订阅（P-02）';
COMMENT ON COLUMN p_guideline.status            IS '发布态：DRAFT=草稿/PUBLISHED=已发布/CLOSED=已截止';
COMMENT ON COLUMN p_guideline.project_type      IS '项目类型，取 sys_dict(project_type).item_code，禁止硬编码';
COMMENT ON COLUMN p_guideline.target_disciplines IS '目标学科方向 JSON 数组，如 [{"code":"CS","label":"计算机科学"}]';
COMMENT ON COLUMN p_guideline.apply_end_at      IS '申报截止时间，用于超期不允许提交拦截（PRD §11）';
COMMENT ON COLUMN p_guideline.total_envelope    IS '指南资助总盘子，NUMERIC(18,2) 单位元';
COMMENT ON COLUMN p_guideline.attachment_ids    IS '附件对象存储 id 的 JSON 数组，如 ["obj-1","obj-2"]';


-- -----------------------------------------------------------------------------
-- P_TEMPLATE · 申报模板（P-01 可视化配置，无需开发介入）
-- -----------------------------------------------------------------------------
CREATE TABLE p_template (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  name              VARCHAR(128) NOT NULL,
  project_type      VARCHAR(64)  NOT NULL,          -- 字典 sys_dict(project_type)
  form_schema       JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- 结构化表单字段定义
  sections          JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- 章节树 [{code,title,order,required,maxWords}]
  budget_schema     JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- 预算科目/年份矩阵定义（引用 F 科目字典）
  review_card       JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- 评分卡维度 [{dim,weight,maxScore}]
  approval_chain    JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- 审批链（对接 svc-workflow）节点定义
  version           INT          NOT NULL DEFAULT 1,
  active            BOOLEAN      NOT NULL DEFAULT FALSE         -- 当前生效版本（同 project_type 仅一个 true）
);
CREATE UNIQUE INDEX uk_p_template_code     ON p_template(tenant_id, code, version) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_p_template_active   ON p_template(tenant_id, project_type) WHERE active = TRUE AND deleted = 0;
CREATE INDEX idx_p_template_type           ON p_template(tenant_id, project_type);
CREATE INDEX idx_p_template_tenant_st      ON p_template(tenant_id, status);

COMMENT ON TABLE  p_template IS '申报模板：字段/章节/预算/评分卡/审批链可视化配置（P-01）';
COMMENT ON COLUMN p_template.status        IS 'DRAFT=草稿/ACTIVE=生效/SUPERSEDED=被新版本取代';
COMMENT ON COLUMN p_template.form_schema   IS '申报书结构化表单字段 schema（JSON）';
COMMENT ON COLUMN p_template.sections      IS '章节定义 JSON 数组，驱动撰写页左栏导航与完整性检查';
COMMENT ON COLUMN p_template.budget_schema IS '预算编制矩阵定义，科目取自 03 F 科目字典（逻辑引用 F_SUBJECT）';
COMMENT ON COLUMN p_template.review_card   IS '评审评分卡维度与权重，驱动 P_REVIEW_TASK.score_detail';
COMMENT ON COLUMN p_template.approval_chain IS '多级审批与推荐链（部门→院所→主管），交由 svc-workflow 执行';
COMMENT ON COLUMN p_template.active        IS '是否当前生效版本；同租户同项目类型仅允许一个 active';


-- -----------------------------------------------------------------------------
-- P_APPLICATION · 申报主表（P-03/P-04/P-05/P-06/P-17/P-18）
-- 状态机权威序列（design/README.md §4）：
--   DRAFT→SUBMITTED→FORMAL_CHECK→RECOMMENDED→UNDER_REVIEW→INTERVIEWING→
--   DECIDED→PUBLISHED→SIGNED→EXECUTING；分支 REJECTED / WITHDRAWN
-- -----------------------------------------------------------------------------
CREATE TABLE p_application (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                    -- 申报/立项编号，svc-numbering 分配（复用前缀 PRJ）
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','SUBMITTED','FORMAL_CHECK','RECOMMENDED','UNDER_REVIEW',
                                      'INTERVIEWING','DECIDED','PUBLISHED','SIGNED','EXECUTING',
                                      'REJECTED','WITHDRAWN')),
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  guideline_id      BIGINT REFERENCES p_guideline(id),        -- 同模块物理外键
  template_id       BIGINT REFERENCES p_template(id),         -- 同模块物理外键（记录所用模板版本）
  title             VARCHAR(256) NOT NULL,
  project_type      VARCHAR(64)  NOT NULL,          -- 字典 sys_dict(project_type)
  pi_user_id        BIGINT       NOT NULL,          -- 逻辑外键 → sys_user(id)（项目负责人 PI，07 S 关联）
  member_ids        JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 团队成员 user_id 数组 [{userId,role,deptId}]
  department_id     BIGINT,                         -- 逻辑外键 → sys_org(id)（申报部门）
  abstract          TEXT,                           -- 摘要
  research_target   TEXT,                           -- 研究目标
  technical_route   TEXT,                           -- 技术路线
  expected_output   TEXT,                           -- 预期成果
  duration_months   INT,                            -- 研究周期（月）
  total_budget      NUMERIC(18,2),                  -- 申报总预算（单位元）
  is_horizontal     BOOLEAN      NOT NULL DEFAULT FALSE,      -- 是否横向/委托课题（P-18）
  funding_channel   VARCHAR(64),                    -- 经费来源渠道（横向委托，字典 item_code）
  ai_draft_marked   BOOLEAN      NOT NULL DEFAULT FALSE,      -- 是否含 AI 起草水印段落（PRD 8.1 合规标记）
  submit_at         TIMESTAMPTZ,                    -- 提交时间
  withdraw_at       TIMESTAMPTZ,                    -- 撤回/终止时间
  withdraw_reason   VARCHAR(512)                    -- 撤回/终止理由（进入评审后必填，PRD §11）
);
CREATE UNIQUE INDEX uk_p_application_code     ON p_application(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_p_application_once     ON p_application(tenant_id, guideline_id, pi_user_id)
                   WHERE deleted = 0 AND status NOT IN ('WITHDRAWN','REJECTED');  -- 同指南同 PI 仅一份有效申报
CREATE INDEX idx_p_application_pi             ON p_application(pi_user_id);
CREATE INDEX idx_p_application_guideline      ON p_application(guideline_id);
CREATE INDEX idx_p_application_dept           ON p_application(department_id);
CREATE INDEX idx_p_application_type           ON p_application(tenant_id, project_type);
CREATE INDEX idx_p_application_tenant_st      ON p_application(tenant_id, status);

COMMENT ON TABLE  p_application IS '申报主表：申报全生命周期载体，状态机见 §4 登记表（P-03~P-06/P-17/P-18）';
COMMENT ON COLUMN p_application.code           IS '申报/立项编号，统一编号中心分配，复用前缀 PRJ-年-序';
COMMENT ON COLUMN p_application.status         IS '申报状态机持久态 token（DRAFT..EXECUTING / REJECTED / WITHDRAWN）';
COMMENT ON COLUMN p_application.guideline_id   IS '所属申报指南，同模块物理外键 → p_guideline(id)';
COMMENT ON COLUMN p_application.pi_user_id     IS '项目负责人，逻辑外键 → sys_user(id)；PI 不在职一律拦截（PRD §11）';
COMMENT ON COLUMN p_application.member_ids     IS '团队成员 JSON：[{"userId":1,"role":"参与","deptId":9}]';
COMMENT ON COLUMN p_application.department_id  IS '申报部门，逻辑外键 → sys_org(id)';
COMMENT ON COLUMN p_application.total_budget   IS '申报总预算，NUMERIC(18,2) 单位元，受指南上限约束';
COMMENT ON COLUMN p_application.is_horizontal  IS '横向/委托课题标记（P-18），合同链移交 09 G 的 G-10';
COMMENT ON COLUMN p_application.ai_draft_marked IS '是否包含 AI 起草内容（需 PI 显式确认并打水印，PRD 8.1）';
COMMENT ON COLUMN p_application.withdraw_reason IS '撤回/终止理由；进入评审后禁止撤回只能终止且理由必填（PRD §11）';


-- -----------------------------------------------------------------------------
-- P_APPLICATION_DOC · 申报书章节（P-03 在线撰写，富文本 + 版本 + 批注）
-- -----------------------------------------------------------------------------
CREATE TABLE p_application_doc (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','FINAL')),
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  application_id    BIGINT NOT NULL REFERENCES p_application(id),  -- 同模块物理外键
  section_code      VARCHAR(64) NOT NULL,          -- 章节编码（对应 p_template.sections.code）
  content_rich      TEXT,                          -- 章节正文（富文本/Markdown）
  word_count        INT NOT NULL DEFAULT 0,        -- 字数（形式审查校验项，P-05）
  table_count       INT NOT NULL DEFAULT 0,        -- 图/表数量（形式审查校验项）
  doc_version       INT NOT NULL DEFAULT 1,        -- 版本号，历史保留
  is_current        BOOLEAN NOT NULL DEFAULT TRUE, -- 是否当前版本
  annotations       JSONB NOT NULL DEFAULT '[]'::jsonb  -- 协同批注 [{author,at,text}]
);
CREATE UNIQUE INDEX uk_p_doc_current ON p_application_doc(application_id, section_code) WHERE is_current = TRUE AND deleted = 0;
CREATE INDEX idx_p_doc_application   ON p_application_doc(application_id, section_code);
CREATE INDEX idx_p_doc_tenant_st     ON p_application_doc(tenant_id, status);

COMMENT ON TABLE  p_application_doc IS '申报书章节内容，含版本与协同批注（P-03）';
COMMENT ON COLUMN p_application_doc.section_code IS '章节编码，与 p_template.sections 中的 code 对齐';
COMMENT ON COLUMN p_application_doc.word_count   IS '当前章节字数，驱动形式审查字数校验（P-05）';
COMMENT ON COLUMN p_application_doc.doc_version  IS '章节版本号，每次保存递增，历史版本 is_current=false';
COMMENT ON COLUMN p_application_doc.annotations  IS '协同批注 JSON 数组 [{"authorId":1,"at":"...","text":"..."}]';


-- -----------------------------------------------------------------------------
-- P_BUDGET_DRAFT · 预算草稿（P-04 在线编制，与 03 经费科目字典联动；P-14 AI 合规预检）
-- -----------------------------------------------------------------------------
CREATE TABLE p_budget_draft (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','CHECKED','APPROVED')),
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  application_id    BIGINT NOT NULL REFERENCES p_application(id),  -- 同模块物理外键
  subject_code      VARCHAR(64) NOT NULL,          -- 预算科目编码（逻辑引用 03 F_SUBJECT.subject_code / sys_dict）
  subject_name      VARCHAR(128),                   -- 科目名称快照
  fiscal_year       SMALLINT,                       -- 预算年度（纯年份，达梦 SMALLINT）
  amount            NUMERIC(18,2) NOT NULL DEFAULT 0, -- 科目/年度金额（单位元）
  calc_detail       JSONB NOT NULL DEFAULT '{}'::jsonb, -- 计算明细 JSON（测算依据/单价×数量等）
  ai_compliance_flag   VARCHAR(16) CHECK (ai_compliance_flag IN ('OK','WARN','VIOLATION','UNKNOWN')),
  ai_compliance_reason TEXT                          -- AI 合规预检理由+条款出处（P-14）
);
CREATE INDEX idx_p_budget_application ON p_budget_draft(application_id);
CREATE INDEX idx_p_budget_subject     ON p_budget_draft(tenant_id, subject_code);
CREATE INDEX idx_p_budget_tenant_st   ON p_budget_draft(tenant_id, status);

COMMENT ON TABLE  p_budget_draft IS '预算草稿行：科目×年度矩阵单元格，立项前草稿（P-04/P-14）';
COMMENT ON COLUMN p_budget_draft.subject_code   IS '预算科目编码，逻辑引用 03 F 科目字典（F_SUBJECT），跨模块不建物理外键';
COMMENT ON COLUMN p_budget_draft.fiscal_year    IS '预算年度，如 2026；配合 P_TEMPLATE.budget_schema 形成年度列';
COMMENT ON COLUMN p_budget_draft.amount         IS '该科目该年度金额，NUMERIC(18,2) 单位元';
COMMENT ON COLUMN p_budget_draft.calc_detail    IS '测算明细 JSON，例如 {"unitPrice":1000,"qty":10,"note":"..."}';
COMMENT ON COLUMN p_budget_draft.ai_compliance_flag IS 'AI 合规预检标记（概率判断，非硬约束）：OK/WARN/VIOLATION/UNKNOWN';


-- -----------------------------------------------------------------------------
-- P_REVIEW_TASK · 评审任务（P-08 智能分派 + P-09 在线评审打分 + P-10 会评）
-- -----------------------------------------------------------------------------
CREATE TABLE p_review_task (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'ASSIGNED'
                    CHECK (status IN ('ASSIGNED','ACCEPTED','SCORING','SUBMITTED','RETURNED','EXPIRED')),
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  application_id    BIGINT NOT NULL REFERENCES p_application(id),  -- 同模块物理外键
  expert_user_id    BIGINT NOT NULL,               -- 逻辑外键 → sys_user(id)（评审专家 R-EXPERT）
  review_round      SMALLINT NOT NULL DEFAULT 1,   -- 评审轮次：1=通讯评审 2=会评/合议
  dispatch_mode     VARCHAR(16) NOT NULL DEFAULT 'MANUAL'
                    CHECK (dispatch_mode IN ('MANUAL','AI')),        -- 分派方式（P-08）
  anonymous_view    BOOLEAN NOT NULL DEFAULT TRUE, -- 评审期匿名化（隐藏 PI 与单位，PRD §9）
  conflict_flag     BOOLEAN NOT NULL DEFAULT FALSE,-- 回避关系命中（同单位/3 年合作/师生，PRD §11）
  score_total       NUMERIC(10,2),                 -- 总分（按评分卡加权汇总）
  score_detail      JSONB NOT NULL DEFAULT '{}'::jsonb, -- 分维度打分明细 [{dim,score,maxScore,comment}]
  comment_text      TEXT,                          -- 评审意见正文
  ai_opinion_draft  TEXT,                          -- AI 评审意见草稿（P-16，不自动写入正式意见）
  deadline_at       TIMESTAMPTZ,                   -- 评审截止时间
  submitted_at      TIMESTAMPTZ                    -- 提交打分时间（撤回窗口 24h 起点）
);
CREATE UNIQUE INDEX uk_p_review_task_once ON p_review_task(application_id, expert_user_id, review_round) WHERE deleted = 0;
CREATE INDEX idx_p_review_application    ON p_review_task(application_id);
CREATE INDEX idx_p_review_expert         ON p_review_task(expert_user_id, status);
CREATE INDEX idx_p_review_tenant_st      ON p_review_task(tenant_id, status);

COMMENT ON TABLE  p_review_task IS '评审任务：专家×申报×轮次，独立打分与合议载体（P-08/P-09/P-10）';
COMMENT ON COLUMN p_review_task.status      IS 'ASSIGNED=已分派/ACCEPTED=已接收/SCORING=打分中/SUBMITTED=已提交/RETURNED=退回/EXPIRED=超期';
COMMENT ON COLUMN p_review_task.review_round IS '轮次：1=通讯评审，2=会评/答辩合议';
COMMENT ON COLUMN p_review_task.anonymous_view IS '是否匿名评审视图（通讯评审默认隐藏 PI/单位）';
COMMENT ON COLUMN p_review_task.conflict_flag IS '回避关系命中位；分派时应自动排除命中专家';
COMMENT ON COLUMN p_review_task.score_total IS '评分卡加权总分，NUMERIC(10,2)';
COMMENT ON COLUMN p_review_task.score_detail IS '分维度得分明细 JSON，结构对齐 p_template.review_card';
COMMENT ON COLUMN p_review_task.ai_opinion_draft IS 'AI 评审意见草稿，仅在专家点击生成参考时产出，需专家编辑后提交（PRD 8.4）';


-- -----------------------------------------------------------------------------
-- P_REVIEW_RESULT · 评审结果与立项决议（P-11 决议 + 公示；decision 用决议 token）
-- -----------------------------------------------------------------------------
CREATE TABLE p_review_result (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('PENDING','PUBLICIZING','PUBLISHED','FINAL')),  -- 公示态
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  application_id    BIGINT NOT NULL REFERENCES p_application(id),  -- 同模块物理外键（1:1）
  final_score       NUMERIC(10,2),                 -- 合议最终分
  rank              INT,                           -- 排名（并列触发复议，PRD §11）
  decision          VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (decision IN ('DRAFT','APPROVED','REJECTED','PENDING_INTERVIEW')), -- 决议 token
  decided_by        BIGINT,                        -- 决议人（R-LEADER）user_id，逻辑外键 → sys_user
  decided_at        TIMESTAMPTZ,
  publicity_start_at TIMESTAMPTZ,                  -- 公示开始
  publicity_end_at   TIMESTAMPTZ,                  -- 公示结束
  objections        JSONB NOT NULL DEFAULT '[]'::jsonb, -- 公示异议清单 [{who,at,content,handleStatus}]
  publish_status    VARCHAR(32) CHECK (publish_status IN ('UNPUBLISHED','PUBLISHED'))
);
CREATE UNIQUE INDEX uk_p_review_result_app ON p_review_result(application_id) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_p_review_result_code ON p_review_result(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_p_review_result_decision  ON p_review_result(tenant_id, decision);
CREATE INDEX idx_p_review_result_tenant_st ON p_review_result(tenant_id, status);

COMMENT ON TABLE  p_review_result IS '评审结果与立项决议：汇总分/排名/决议/公示（P-11），与 p_application 1:1';
COMMENT ON COLUMN p_review_result.status     IS '公示流转态：PENDING=待公示/PUBLICIZING=公示中/PUBLISHED=已公示/FINAL=定档';
COMMENT ON COLUMN p_review_result.decision   IS '立项决议 token：DRAFT/APPROVED/REJECTED/PENDING_INTERVIEW（§4 决议序列）';
COMMENT ON COLUMN p_review_result.final_score IS '合议最终得分，NUMERIC(10,2)；决议前对申请人不可见（PRD §12 安全）';
COMMENT ON COLUMN p_review_result.rank        IS '排名；并列触发复议流程（PRD §11）';
COMMENT ON COLUMN p_review_result.objections  IS '公示期异议 JSON 数组，异议处理走独立状态机';


-- -----------------------------------------------------------------------------
-- P_TASK_BOOK · 任务书（P-12 生成与签订，PDF 套打 + 电子签章；与 p_application 1:1）
-- -----------------------------------------------------------------------------
CREATE TABLE p_task_book (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                    -- 任务书编号，复用前缀 PRJ（与立项一致，svc-numbering 分配）
  tenant_id         BIGINT NOT NULL,
  status            VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','SIGNED','EXECUTING')),
  deleted           SMALLINT NOT NULL DEFAULT 0,
  creator_id        BIGINT NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列 ─────────────────────────────────────────────
  application_id    BIGINT NOT NULL REFERENCES p_application(id),  -- 同模块物理外键（1:1）
  content_snapshot  JSONB NOT NULL DEFAULT '{}'::jsonb, -- 生成时快照（目标/考核指标/预算/进度，防篡改）
  print_template_code VARCHAR(64),                  -- 套打模板编码（逻辑引用 sys_print_template.code=TASK_BOOK）
  signed_pdf_url    VARCHAR(512),                   -- 签订后 PDF 对象存储地址（归档件）
  sign_records      JSONB NOT NULL DEFAULT '[]'::jsonb, -- 电子签章记录 [{signer,role,signedAt,sigResult}]
  effective_date    DATE,                           -- 任务书生效日期
  project_id        BIGINT                          -- 立项后回填：逻辑外键 → 02 E_PROJECT(id)（跨模块，不建物理外键）
);
CREATE UNIQUE INDEX uk_p_task_book_app  ON p_task_book(application_id) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_p_task_book_code ON p_task_book(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_p_task_book_project    ON p_task_book(project_id);
CREATE INDEX idx_p_task_book_tenant_st  ON p_task_book(tenant_id, status);

COMMENT ON TABLE  p_task_book IS '任务书：立项通过后自动生成，核对+电子签章签订（P-12），与申报 1:1';
COMMENT ON COLUMN p_task_book.code        IS '任务书编号，复用前缀 PRJ（项目/立项），svc-numbering 幂等分配';
COMMENT ON COLUMN p_task_book.status      IS 'DRAFT=待核对/SIGNED=已签订/EXECUTING=已进入执行（联动 02）';
COMMENT ON COLUMN p_task_book.content_snapshot IS '任务书内容快照 JSON，生成时冻结，保证归档一致性（PRD 2.14）';
COMMENT ON COLUMN p_task_book.sign_records IS '电子签章记录 JSON：[{"signerId":1,"role":"PI","signedAt":"...","result":"OK"}]';
COMMENT ON COLUMN p_task_book.project_id  IS '立项建项后回填，逻辑外键 → E_PROJECT(id)（02 模块，仅存 id 不建物理外键）';
