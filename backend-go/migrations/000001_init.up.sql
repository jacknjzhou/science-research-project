-- 由 design/*.sql 自动生成，勿手改。来源：
-- 非 PostgreSQL 段（ClickHouse OLAP / Doris 等）已由 gen.go::stripNonPostgres 剔除，ADR-003。

-- ===== 00-common.sql =====
-- =============================================================================
-- 00-common.sql · 横切平台表（多模块共用底座）
-- 版本 v1.0 · 2026-10-13
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4）
-- 约定：金额 NUMERIC(18,2)；时间 TIMESTAMPTZ；枚举 VARCHAR+CHECK；字典禁止硬编码（PRD 2.8）
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0) 依赖扩展（供后续模块建 trigram/GIN 索引；pg_trgm 属 postgresql-contrib，
--    postgres:15 官方镜像已内置。IF NOT EXISTS 使 compose 反复重跑幂等。）
--    使用点：04 R_OUTPUT.idx_output_title_trgm / 05 T_ENTERPARTNER.idx_enterpartner_name
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- 1) 统一身份与组织（PRD 2.1 角色 / 2.12 法人 / 2.13 三员）
-- -----------------------------------------------------------------------------

-- 用户主体（登录态，业务表以 *_user_id 引用）
CREATE TABLE sys_user (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username        VARCHAR(64)  NOT NULL,
  real_name       VARCHAR(64)  NOT NULL,
  email           VARCHAR(128),
  phone           VARCHAR(32),
  staff_no        VARCHAR(64),                 -- 工号（与 ORCID 共同去重同名，见 PRD 07 异常）
  employment_status VARCHAR(16) NOT NULL DEFAULT 'ONBOARD'
                  CHECK (employment_status IN ('ONBOARD','RESIGNED','RETIRED','VISITING','GUEST','REHIRE')),
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                  CHECK (status IN ('ACTIVE','LOCKED','DISABLED')),
  password_hash   VARCHAR(100),                -- bcrypt($2a$10$…) 定长60留裕度；NULL=无口令账号(dev/外联身份)，一律拒登
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT,
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_user_username ON sys_user(tenant_id, username) WHERE deleted = 0;

-- 角色字典（PRD 2.1 八基础角色）
CREATE TABLE sys_role (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code         VARCHAR(32) NOT NULL,           -- R-STAFF/R-MANAGER/R-LEADER/R-FINANCE/R-AUDITOR/R-EXPERT/R-ETHICS/R-ADMIN
  name         VARCHAR(64) NOT NULL,
  is_builtin   BOOLEAN     NOT NULL DEFAULT TRUE,
  tenant_id    BIGINT      NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_role_code ON sys_role(tenant_id, code);

-- 用户—角色（RBAC）
CREATE TABLE sys_user_role (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES sys_user(id),
  role_id    BIGINT NOT NULL REFERENCES sys_role(id),
  tenant_id  BIGINT NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ                        -- 客座/访问学者短期权限到期自动失效（PRD 07 S-11）
);
CREATE UNIQUE INDEX uk_user_role ON sys_user_role(user_id, role_id);

-- 三员分立账号类型（PRD 2.13：系统/安全/审计管理员，禁止兼任）
CREATE TABLE sys_admin_duty (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES sys_user(id),
  duty_type   VARCHAR(16) NOT NULL CHECK (duty_type IN ('SYS_ADMIN','SEC_ADMIN','AUDIT_ADMIN')),
  tenant_id   BIGINT NOT NULL,
  legal_entity_id BIGINT,
  effective_from TIMESTAMPTZ NOT NULL,
  effective_to   TIMESTAMPTZ
);
-- 一人只可担任一类三员职责（三权分立，物理隔离账号）
CREATE UNIQUE INDEX uk_admin_duty_user ON sys_admin_duty(user_id);
CREATE UNIQUE INDEX uk_admin_duty_type  ON sys_admin_duty(tenant_id, duty_type) WHERE effective_to IS NULL;

-- 组织树（部门，支持法人层级）
CREATE TABLE sys_org (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,
  name            VARCHAR(128) NOT NULL,
  parent_id       BIGINT       REFERENCES sys_org(id),
  org_type        VARCHAR(16)  NOT NULL DEFAULT 'DEPT'
                  CHECK (org_type IN ('TOTAL_INSTITUTE','BRANCH_INSTITUTE','DEPT','LAB','PLATFORM')),
  legal_entity_id BIGINT,
  sort_no         INT          NOT NULL DEFAULT 0,
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','MERGED','DISSOLVED')),
  tenant_id       BIGINT       NOT NULL,
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_org_code ON sys_org(tenant_id, code) WHERE deleted = 0;

-- 法人主体（PRD 2.12 多法人治理；单号前缀 LE）
CREATE TABLE sys_legal_entity (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,        -- LE-年-序（统一编号中心分配）
  name            VARCHAR(128) NOT NULL,
  credit_code     VARCHAR(64),                  -- 统一社会信用代码
  entity_type     VARCHAR(16)  NOT NULL CHECK (entity_type IN ('TOTAL_INSTITUTE','BRANCH_INSTITUTE')),
  short_code      VARCHAR(16),                  -- 法人短码（号段前缀，避免跨院所串号，PRD 2.11）
  consolidated    BOOLEAN      NOT NULL DEFAULT FALSE,  -- 是否并表主体
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE=正常','DEREGISTERED=注销')),
  tenant_id       BIGINT       NOT NULL,
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_legal_entity_code ON sys_legal_entity(tenant_id, code) WHERE deleted = 0;

-- -----------------------------------------------------------------------------
-- 2) 数据字典（PRD 2.8）
-- -----------------------------------------------------------------------------
CREATE TABLE sys_dict (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        VARCHAR(64) NOT NULL,             -- 字典编码：project_type/expense_type/asset_category ...
  name        VARCHAR(128) NOT NULL,
  tenant_id   BIGINT NOT NULL,
  remark      TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_dict_code ON sys_dict(tenant_id, code);

CREATE TABLE sys_dict_item (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dict_id      BIGINT NOT NULL REFERENCES sys_dict(id) ON DELETE CASCADE,
  item_code    VARCHAR(64) NOT NULL,
  item_label   VARCHAR(128) NOT NULL,
  parent_id    BIGINT REFERENCES sys_dict_item(id),   -- 支持树形（经费科目/资产分类）
  ext_json     JSONB,                                  -- 附加属性：ratio_limit/applies_to 等
  sort_no      INT NOT NULL DEFAULT 0,
  i18n_json    JSONB,                                  -- 多语言
  effective_from DATE,
  effective_to   DATE,
  active       BOOLEAN NOT NULL DEFAULT TRUE,
  tenant_id    BIGINT NOT NULL
);
CREATE UNIQUE INDEX uk_dict_item ON sys_dict_item(dict_id, item_code, COALESCE(effective_from, DATE '1970-01-01'));

-- -----------------------------------------------------------------------------
-- 3) 制度规则引擎·制度包（PRD 2.10）
-- -----------------------------------------------------------------------------
CREATE TABLE sys_policy_pack (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,        -- 制度包编码
  name            VARCHAR(128) NOT NULL,
  effective_from  DATE NOT NULL,
  effective_to    DATE,
  applied_modules VARCHAR(128)[] NOT NULL,      -- {F,G,P,...} 生效模块集合
  dsl_yaml        TEXT NOT NULL,                -- 规则 DSL（采购限额/科目比例/审批权限矩阵）
  version         INT NOT NULL DEFAULT 1,
  status          VARCHAR(32) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),
  tenant_id       BIGINT NOT NULL,
  legal_entity_id BIGINT,
  deleted         SMALLINT NOT NULL DEFAULT 0,
  creator_id      BIGINT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_policy_pack ON sys_policy_pack(tenant_id, code, version) WHERE deleted = 0;
-- 同租户同模块集合仅一套 ACTIVE
CREATE UNIQUE INDEX uk_policy_pack_active ON sys_policy_pack(tenant_id, applied_modules) WHERE status = 'ACTIVE' AND deleted = 0;

-- 规则命中审计（可解释、可复算：业务单据记录命中规则号 + 出处）
CREATE TABLE sys_rule_hit (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  policy_pack_id  BIGINT NOT NULL REFERENCES sys_policy_pack(id),
  rule_code       VARCHAR(64) NOT NULL,         -- 命中规则号
  clause_ref      VARCHAR(256),                 -- 出处条款
  biz_object      VARCHAR(32) NOT NULL,         -- 单据类型：REQ/EXP/CON ...
  biz_id          BIGINT NOT NULL,              -- 单据主键
  verdict         VARCHAR(16) NOT NULL CHECK (verdict IN ('PASS','REJECT','WARN')),
  detail_json     JSONB,
  tenant_id       BIGINT NOT NULL,
  hit_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rule_hit_biz ON sys_rule_hit(biz_object, biz_id);

-- -----------------------------------------------------------------------------
-- 4) 统一编号中心（PRD 2.11）—— 号段注册表 + 分配流水
-- -----------------------------------------------------------------------------
-- 前缀注册表为唯一事实来源（与 PRD README 2.11 对齐，新增前缀先登记）
CREATE TABLE seq_prefix_registry (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  prefix        VARCHAR(16) NOT NULL,           -- PRJ/BUD/EXP/DISB/REQ/ORD/SUP/SOSC/CON/OSC/AST/DSP/LE/EXF
  biz_object    VARCHAR(64) NOT NULL,
  owner_module  VARCHAR(8)  NOT NULL,
  introduced_ver VARCHAR(8) NOT NULL DEFAULT 'v1.0',
  pattern       VARCHAR(64) NOT NULL DEFAULT '{prefix}-{yyyy}-{seq6}',
  per_entity    BOOLEAN NOT NULL DEFAULT FALSE, -- 是否按法人分号段
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (prefix)
);

-- 号段水位（Redis 为热路径，DB 双写落此；重启/灾备回灌）
CREATE TABLE seq_allocation (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  prefix        VARCHAR(16) NOT NULL,
  tenant_id     BIGINT NOT NULL,
  legal_entity_id BIGINT NOT NULL DEFAULT 0,    -- 0 表示总院统一号段
  year          SMALLINT NOT NULL,
  current_no    BIGINT NOT NULL DEFAULT 0,      -- 已分配最大序号
  step          INT NOT NULL DEFAULT 100,       -- 号段步长（批量取号降低 DB 压力）
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (prefix, tenant_id, legal_entity_id, year)
);

-- -----------------------------------------------------------------------------
-- 5) 套打模板（PRD 2.14）
-- -----------------------------------------------------------------------------
CREATE TABLE sys_print_template (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code          VARCHAR(64) NOT NULL,           -- 模板编码：TASK_BOOK/CONTRACT/EXPENSE_VOUCHER/ASSET_LABEL ...
  name          VARCHAR(128) NOT NULL,
  biz_object    VARCHAR(32) NOT NULL,           -- 适用单据类型
  file_url      VARCHAR(512) NOT NULL,          -- 红头/表格模板（对象存储）
  mapping_json  JSONB NOT NULL,                 -- 结构化字段 -> 模板占位符映射
  with_comment  BOOLEAN NOT NULL DEFAULT FALSE, -- 含批注版本
  version       INT NOT NULL DEFAULT 1,
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  tenant_id     BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_print_tpl ON sys_print_template(tenant_id, code, version);

-- -----------------------------------------------------------------------------
-- 6) 审计日志（PRD 2.3 / 2.9 / 2.13）—— 字段级 diff + 数字签名 + 不可篡改
-- -----------------------------------------------------------------------------
CREATE TABLE sys_audit_log (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     BIGINT NOT NULL,
  legal_entity_id BIGINT,
  actor_id      BIGINT NOT NULL,                -- who
  actor_role    VARCHAR(32),
  action        VARCHAR(32) NOT NULL,           -- CREATE/UPDATE/DELETE/APPROVE/EXPORT/PRINT/SEC_OUTPUT ...
  object_type   VARCHAR(32) NOT NULL,           -- 表名或单据类型
  object_id     BIGINT NOT NULL,
  biz_code      VARCHAR(64),                    -- 单据业务编号
  diff_json     JSONB,                          -- 字段级前后值 what/why
  channel       VARCHAR(16),                    -- WEB/MOBILE/API
  ip            VARCHAR(64),
  where_json    JSONB,                          -- 位置/设备上下文 where
  occurred_at   TIMESTAMPTZ NOT NULL,           -- when
  prev_sig      VARCHAR(128),                   -- 前一条签名（哈希链，防篡改）
  sig           VARCHAR(128) NOT NULL           -- 本条数字签名
);
CREATE INDEX idx_audit_obj ON sys_audit_log(object_type, object_id);
CREATE INDEX idx_audit_actor ON sys_audit_log(tenant_id, actor_id, occurred_at);

-- -----------------------------------------------------------------------------
-- 7) 涉密输出审批流（PRD 2.13 / X 模块；单号前缀 EXF）
--    业务表跨域下行/上行一律留痕；M1 建表，流程能力 M2 完善
-- -----------------------------------------------------------------------------
CREATE TABLE x_flow_audit (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code          VARCHAR(64) NOT NULL,           -- EXF-年-序
  direction     VARCHAR(8) NOT NULL CHECK (direction IN ('DOWN','UP')), -- 涉密→内网 / 互联网→涉密
  object_type   VARCHAR(32) NOT NULL,
  object_id     BIGINT NOT NULL,
  from_domain   VARCHAR(16) NOT NULL,
  to_domain     VARCHAR(16) NOT NULL,
  applicant_id  BIGINT NOT NULL,
  reason        TEXT,
  second_verifier_id BIGINT,                    -- 二次核验人
  status        VARCHAR(32) NOT NULL DEFAULT 'APPLIED'
                CHECK (status IN ('APPLIED','PRE_REVIEW','SEC_REVIEW','RELEASED','REJECTED','RECORDED')),
  tenant_id     BIGINT NOT NULL,
  legal_entity_id BIGINT,
  security_level VARCHAR(16) NOT NULL DEFAULT 'SECRET',
  deleted       SMALLINT NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_exf_code ON x_flow_audit(tenant_id, code) WHERE deleted = 0;

-- -----------------------------------------------------------------------------
-- 8) 追溯节点（PRD 2.14 / E-17）—— 贯穿申报→合同→采购→经费→成果→资产→归档
-- -----------------------------------------------------------------------------
CREATE TABLE e_trace_node (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  trace_id      VARCHAR(64) NOT NULL,           -- 一条端到端链标识
  node_seq      INT NOT NULL,
  prev_node_id  BIGINT REFERENCES e_trace_node(id),
  object_type   VARCHAR(32) NOT NULL,           -- APPLICATION/CONTRACT/ORDER/EXPENSE/ASSET/...
  object_id     BIGINT NOT NULL,
  biz_code      VARCHAR(64),
  actor_id      BIGINT,
  action        VARCHAR(32),
  occurred_at   TIMESTAMPTZ NOT NULL,
  tenant_id     BIGINT NOT NULL,
  legal_entity_id BIGINT
);
CREATE INDEX idx_trace_obj ON e_trace_node(object_type, object_id);
CREATE INDEX idx_trace_chain ON e_trace_node(trace_id, node_seq);

-- =============================================================================
-- 初始化：编号前缀注册表（与 PRD README 2.11 保持一致）
-- =============================================================================
INSERT INTO seq_prefix_registry (prefix, biz_object, owner_module, introduced_ver, per_entity) VALUES
  ('PRJ','项目/立项','P/E','v1.0',TRUE),
  ('BUD','预算','F','v1.0',TRUE),
  ('EXP','报销单','F','v1.0',TRUE),
  ('DISB','外拨经费','F','v1.1',TRUE),
  ('DEAL','转化交易','T','v1.0',TRUE),
  ('ETH','伦理审查','C','v1.0',TRUE),
  ('REQ','采购申请','G','v1.1',TRUE),
  ('ORD','采购订单','G','v1.1',TRUE),
  ('SUP','供应商','G','v1.1',TRUE),
  ('SOSC','外协单位','G','v1.1',TRUE),
  ('CON','合同','G','v1.1',TRUE),
  ('OSC','外协/分包合同','G','v1.1',TRUE),
  ('AST','资产卡','A','v1.1',TRUE),
  ('DSP','资产处置单','A','v1.1',TRUE),
  ('LE','法人主体','X','v1.1',FALSE),
  ('EXF','涉密外传/输出审计','X','v1.1',TRUE),
  ('ACT','学术活动','V','v1.0',TRUE),
  ('PERF','绩效记录','M','v1.0',TRUE),
  ('PAY','绩效发放','M','v1.0',TRUE);


-- ===== 01-项目申报与立项-P.ddl.sql =====
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


-- ===== 02-项目过程管理-E.ddl.sql =====
-- =============================================================================
-- 02-项目过程管理-E.ddl.sql · M1 核心模块 E（Execution）建表脚本
-- 版本 v1.0 · 2026-10-13
-- 方言：PostgreSQL 15
-- 上游：../PRD/02-项目过程管理.md · design/README.md §2 数据库约定 · §4 状态 token · §5 共享实体登记表
-- 说明：本模块为执行域项目主表 E_PROJECT 的拥有方（project_id 被 F/G/A 逻辑引用）。
--       只 CREATE 不 DROP；e_trace_node 追溯节点已在 00-common.sql 定义，本文件不重复建表，只引用。
--
-- -----------------------------------------------------------------------------
-- 信创达梦差异注记（部署达梦时按 design/README.md §2.4 整体替换，逐条对应）：
--   1) 自增主键     GENERATED ALWAYS AS IDENTITY  ->  IDENTITY(1,1)
--   2) 时间戳       TIMESTAMPTZ                    ->  TIMESTAMP WITH TIME ZONE（时区基准 Asia/Shanghai，落库 UTC）
--   3) 布尔         BOOLEAN                        ->  SMALLINT（0/1）
--   4) JSONB        JSONB                          ->  CLOB/VARCHAR 存 JSON 文本 + 应用层解析
--   5) 枚举 CHECK   CHECK(col IN(...))             ->  同（保持 VARCHAR+CHECK，不用原生 ENUM）
--   6) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0
--                  ->  达梦用普通唯一索引 + deleted 复合键替代（本文件每处 uk_ 索引旁注此差异）
--   7) 全文检索     pg_trgm/tsvector               ->  应用层 ES / 达梦全文索引
--   8) 数组         本模块未使用数组列（制度包 applied_modules 在 common）
--   9) 向量         本模块无 pgvector 列（健康度/风险的向量归 AI 中台 Milvus）
--
-- 通用列（design/README.md §2.1）：每张业务表均含
--   id / code / tenant_id / status / deleted / creator_id / modifier_id / created_at / updated_at / remark
--   内联定义，类型完全一致，不再逐表在注释中重复语义。
-- 标量（§2.2）：金额 NUMERIC(18,2)；比例/置信度/权重 NUMERIC(6,4)；时间 TIMESTAMPTZ；纯日期 DATE；半结构化 JSONB。
-- 命名（§2.3）：表前缀 E_；单号前缀 PRJ（登记于 seq_prefix_registry，属 E/P 共有）；跨模块仅 *_id 逻辑外键，同模块物理外键。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) E_PROJECT 执行态项目主表（与 01 P_APPLICATION 1:1 继承，project_id 拥有方）
--    被 03 F / 09 G / 10 A 以 project_id 逻辑引用（见 README §5 共享实体登记表）。
-- -----------------------------------------------------------------------------
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
COMMENT ON TABLE  E_PROJECT IS '执行态项目主表；与 01 P_APPLICATION 1:1 继承，project_id 全局拥有方';
COMMENT ON COLUMN E_PROJECT.application_id IS '逻辑外键 01 P_APPLICATION.id，立项来源';
COMMENT ON COLUMN E_PROJECT.member_ids IS '项目成员 user_id JSON 数组，跨模块只读引用 sys_user';
COMMENT ON COLUMN E_PROJECT.health_score IS 'E-10 健康度总分 0-100，事件与 ETL 双通道刷新';
COMMENT ON COLUMN E_PROJECT.spent_amount IS '经费支出快照，权威值在 03 F，事件同步（PRD 2.15 单一事实来源）';

CREATE UNIQUE INDEX uk_e_project_code ON E_PROJECT(tenant_id, code) WHERE deleted = 0;  -- 达梦：改普通唯一索引 + (tenant_id,code,deleted)
CREATE UNIQUE INDEX uk_e_project_app  ON E_PROJECT(application_id) WHERE deleted = 0;   -- 保证与申报 1:1
CREATE INDEX idx_e_project_tenant_status ON E_PROJECT(tenant_id, legal_entity_id, status);
CREATE INDEX idx_e_project_pi   ON E_PROJECT(pi_user_id, status);
CREATE INDEX idx_e_project_dept ON E_PROJECT(department_id);
CREATE INDEX idx_e_project_risk ON E_PROJECT(tenant_id, risk_level, status);
CREATE INDEX idx_e_project_member ON E_PROJECT USING gin (member_ids jsonb_path_ops);


-- -----------------------------------------------------------------------------
-- 2) E_TASK 任务 / WBS 节点（树形自引用 parent_task_id）
-- -----------------------------------------------------------------------------
CREATE TABLE E_TASK (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','IN_PROGRESS','COMPLETED','OVERDUE','CANCELLED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),  -- 同模块物理外键
  parent_task_id   BIGINT       REFERENCES E_TASK(id),              -- 树形自引用
  name             VARCHAR(256) NOT NULL,
  description      TEXT,
  owner_user_id    BIGINT,                                          -- 逻辑外键 -> sys_user.id（任务负责人）
  member_ids       JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- 任务执行人 user_id 数组
  dep_task_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- 前置依赖 task_id 数组（甘特依赖箭头）
  planned_start    DATE,
  planned_end      DATE,
  actual_start     DATE,
  actual_end       DATE,
  progress_percent INT          NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
  weight           NUMERIC(6,4) NOT NULL DEFAULT 1.0                -- WBS 权重（用于里程碑/进度加权）
);
COMMENT ON TABLE  E_TASK IS 'WBS 任务分解与分配（E-02），树形结构';
COMMENT ON COLUMN E_TASK.dep_task_ids IS '甘特依赖关系，前置任务 id 数组';
COMMENT ON COLUMN E_TASK.weight IS '任务权重 0-1，健康度进度分按里程碑/任务加权';

CREATE UNIQUE INDEX uk_e_task_code ON E_TASK(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_e_task_project ON E_TASK(project_id, status);
CREATE INDEX idx_e_task_parent  ON E_TASK(parent_task_id);
CREATE INDEX idx_e_task_owner   ON E_TASK(owner_user_id, status);


-- -----------------------------------------------------------------------------
-- 3) E_MILESTONE 里程碑与关键节点
-- -----------------------------------------------------------------------------
CREATE TABLE E_MILESTONE (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','ACHIEVED','OVERDUE','SKIPPED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),
  name             VARCHAR(256) NOT NULL,
  due_date         DATE,
  actual_date      DATE,
  evidence_docs    JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- 里程碑证据（doc_id/url 数组）
  owner_user_id    BIGINT,                                          -- 逻辑外键 sys_user.id
  deliverable_type VARCHAR(64),                                     -- 交付物类型，取自 sys_dict
  weight           NUMERIC(6,4) NOT NULL DEFAULT 1.0                -- 应完成里程碑加权（健康度进度分）
);
COMMENT ON TABLE E_MILESTONE IS '里程碑与关键节点跟踪（E-03）';
COMMENT ON COLUMN E_MILESTONE.weight IS '进度分 = 已完成里程碑加权 / 应完成里程碑加权';

CREATE UNIQUE INDEX uk_e_milestone_code ON E_MILESTONE(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_e_milestone_project ON E_MILESTONE(project_id, status);
CREATE INDEX idx_e_milestone_due     ON E_MILESTONE(tenant_id, due_date);


-- -----------------------------------------------------------------------------
-- 4) E_PROGRESS_REPORT 进度填报与阶段材料
-- -----------------------------------------------------------------------------
CREATE TABLE E_PROGRESS_REPORT (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','SUBMITTED','REVIEWED','RETURNED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),
  period           VARCHAR(32)  NOT NULL,                           -- 填报周期：QUARTER/HALF_YEAR/YEAR（sys_dict）
  report_type      VARCHAR(32)  NOT NULL DEFAULT 'SELF'
                   CHECK (report_type IN ('SELF','MID_CHECK','ANNUAL')), -- 自报/中检/年度
  content_rich     TEXT,                                            -- 富文本正文
  progress_percent INT          NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
  issues_text      TEXT,
  next_plan        TEXT,
  attachment_ids   JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- E_PROJECT_DOC.id 数组
  submitted_at     TIMESTAMPTZ
);
COMMENT ON TABLE E_PROGRESS_REPORT IS '进度填报与阶段材料（E-04）';
COMMENT ON COLUMN E_PROGRESS_REPORT.period IS '季度/半年/年，取自字典 project_period';

CREATE UNIQUE INDEX uk_e_progress_code ON E_PROGRESS_REPORT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_e_progress_project ON E_PROGRESS_REPORT(project_id, report_type, status);
CREATE INDEX idx_e_progress_submit  ON E_PROGRESS_REPORT(tenant_id, submitted_at);


-- -----------------------------------------------------------------------------
-- 5) E_MID_CHECK 中检主表
-- -----------------------------------------------------------------------------
CREATE TABLE E_MID_CHECK (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'PLANNED'
                   CHECK (status IN ('PLANNED','IN_REVIEW','SCORED','CONCLUDED','CORRECTING')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),
  check_round      INT          NOT NULL DEFAULT 1,                 -- 中检轮次
  check_date       DATE,
  plan_id          BIGINT,                                          -- 逻辑外键：中检计划/模板（sys_dict / policy_pack，E-06/E-USR-07）
  template_id      BIGINT,                                          -- 逻辑外键：评分表模板配置（按 project_type）
  expert_ids       JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- 评审专家 user_id 数组（R-EXPERT，在线打分）
  conclusion       VARCHAR(32)
                   CHECK (conclusion IN ('CONTINUE','CORRECT','TERMINATE')), -- 中检结论（README §4）
  score_detail     JSONB,                                           -- 多维度评分明细（半结构化）
  report_id        BIGINT REFERENCES E_PROGRESS_REPORT(id),         -- 同模块物理外键：关联中检报告
  correct_deadline DATE,                                            -- 整改截止日期（结论=CORRECT 时置入）
  status_overdue   SMALLINT     NOT NULL DEFAULT 0                  -- 是否逾期整改（触发支出冻结，见 §8）
);
COMMENT ON TABLE  E_MID_CHECK IS '中检计划与执行（E-06/E-08 打分）';
COMMENT ON COLUMN E_MID_CHECK.conclusion IS 'CONTINUE=继续/CORRECT=整改/TERMINATE=终止（README §4 中检结论）';
COMMENT ON COLUMN E_MID_CHECK.correct_deadline IS '整改截止；逾期未整改项目置 CORRECTING 并冻结经费支出';

CREATE UNIQUE INDEX uk_e_midcheck_code ON E_MID_CHECK(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_e_midcheck_round ON E_MID_CHECK(project_id, check_round) WHERE deleted = 0;
CREATE INDEX idx_e_midcheck_project ON E_MID_CHECK(project_id, status);
CREATE INDEX idx_e_midcheck_date    ON E_MID_CHECK(tenant_id, check_date);


-- -----------------------------------------------------------------------------
-- 6) E_CHANGE_REQUEST 变更申请（延期/预算/成员/题目/范围）
-- -----------------------------------------------------------------------------
CREATE TABLE E_CHANGE_REQUEST (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','SUBMITTED','APPROVING','APPROVED','REJECTED','RETURNED','ROLLED_BACK','EFFECTIVE')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),
  change_type      VARCHAR(32)  NOT NULL
                   CHECK (change_type IN ('DELAY','BUDGET','MEMBER','TITLE','SCOPE')), -- 变更类型（PRD §5.1）
  old_value        JSONB,                                           -- 变更前值快照
  new_value        JSONB,                                           -- 变更后值
  reason           TEXT,
  effective_from   DATE,
  approval_status  VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                   CHECK (approval_status IN ('PENDING','APPROVING','APPROVED','REJECTED')), -- 逐级审批态
  approved_at      TIMESTAMPTZ,
  impact_analysis  JSONB,                                           -- 影响分析结果（经费/进度/成员对比，E-07）
  conflict_flag    SMALLINT     NOT NULL DEFAULT 0,                 -- 预算变更与实支出冲突标记（1=阻止生效并回退）
  snapshot_ref     VARCHAR(128)                                     -- 生效写入的历史快照引用（PRD 6.2 更新历史快照）
);
COMMENT ON TABLE  E_CHANGE_REQUEST IS '变更管理（E-07）';
COMMENT ON COLUMN E_CHANGE_REQUEST.change_type IS 'DELAY/BUDGET/MEMBER/TITLE/SCOPE（README §4 无独立 token，采用 PRD §5.1）';
COMMENT ON COLUMN E_CHANGE_REQUEST.conflict_flag IS '1=预算变更与经费实际支出冲突，阻止生效并回退（PRD 11 变更冲突）';

CREATE UNIQUE INDEX uk_e_change_code ON E_CHANGE_REQUEST(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_e_change_project ON E_CHANGE_REQUEST(project_id, change_type, approval_status);
CREATE INDEX idx_e_change_tenant  ON E_CHANGE_REQUEST(tenant_id, status);


-- -----------------------------------------------------------------------------
-- 7) E_FINAL_ACCEPT 结题验收（E-08）
-- -----------------------------------------------------------------------------
CREATE TABLE E_FINAL_ACCEPT (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'APPLIED'
                   CHECK (status IN ('APPLIED','TECH_REVIEW','FIN_REVIEW','APPROVED','REJECTED','NEED_SUPPLEMENT')), -- 技术+财务双轨并行
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),
  apply_at         TIMESTAMPTZ,
  accept_at        TIMESTAMPTZ,
  output_summary   JSONB,                                           -- 成果清单汇总（来源 04 R，只读引用）
  finance_report_id BIGINT,                                         -- 逻辑外键 -> 03 F 决算报告.id（跨模块不建物理 FK）
  expert_ids       JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- 评审专家 user_id 数组
  conclusion       VARCHAR(32)
                   CHECK (conclusion IN ('PASS','PASS_WITH_CONDITIONS','FAIL')), -- 结题结论（README §4）
  attachment_ids   JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- E_PROJECT_DOC.id 数组
  archive_checklist_id BIGINT                                       -- 同模块物理外键：归档清单校验实例（E-15）；FK 由文末 ALTER TABLE 后加，避免前向引用
);
COMMENT ON TABLE  E_FINAL_ACCEPT IS '结题申请与验收（E-08），技术验收与财务验收并行';
COMMENT ON COLUMN E_FINAL_ACCEPT.conclusion IS 'PASS/PASS_WITH_CONDITIONS/FAIL（README §4 结题结论）';
COMMENT ON COLUMN E_FINAL_ACCEPT.finance_report_id IS '逻辑外键 03 F 决算；project.completed 事件触发决算';
COMMENT ON COLUMN E_FINAL_ACCEPT.archive_checklist_id IS '归档清单校验通过方可验收（缺项拦截，E-15）';

CREATE UNIQUE INDEX uk_e_final_code ON E_FINAL_ACCEPT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_e_final_project ON E_FINAL_ACCEPT(project_id, status);
CREATE INDEX idx_e_final_tenant  ON E_FINAL_ACCEPT(tenant_id, conclusion);


-- -----------------------------------------------------------------------------
-- 8) E_PROJECT_DOC 项目档案（文档中心 E-05）
-- -----------------------------------------------------------------------------
CREATE TABLE E_PROJECT_DOC (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','SUPERSEDED','ARCHIVED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),
  category         VARCHAR(32)  NOT NULL
                   CHECK (category IN ('APPLICATION','TASK_BOOK','MID_CHECK','CHANGE','FINAL','OTHER')), -- 申报书/任务书/中检/变更/结题/其他
  file_url         VARCHAR(512) NOT NULL,                           -- 对象存储地址
  file_name        VARCHAR(256),
  mime_type        VARCHAR(128),                                    -- 与归档清单 mime 校验项比对
  file_size        BIGINT,                                          -- 字节数
  version          INT          NOT NULL DEFAULT 1,                 -- 同一 category 内单调递增版本
  checksum         VARCHAR(128),                                    -- 文件摘要（完整性/防篡改）
  uploaded_by      BIGINT       NOT NULL,                           -- 逻辑外键 sys_user.id
  uploaded_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')) -- 涉密文档下行需 X 审批（PRD 2.13）
);
COMMENT ON TABLE E_PROJECT_DOC IS '项目档案文档中心（E-05），分类树+全文搜索';
COMMENT ON COLUMN E_PROJECT_DOC.version IS '同 category 版本链，历史可回溯';

CREATE UNIQUE INDEX uk_e_doc_code ON E_PROJECT_DOC(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_e_doc_ver  ON E_PROJECT_DOC(project_id, category, code) WHERE deleted = 0;
CREATE INDEX idx_e_doc_project ON E_PROJECT_DOC(project_id, category);
CREATE INDEX idx_e_doc_upload  ON E_PROJECT_DOC(tenant_id, uploaded_at);


-- -----------------------------------------------------------------------------
-- 9) E_HEALTH_HISTORY 健康度快照（日切，E-10）
-- -----------------------------------------------------------------------------
CREATE TABLE E_HEALTH_HISTORY (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'OK'
                   CHECK (status IN ('OK','DROPPED')),              -- DROPPED=较上期下降（触发 project.health.dropped）
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT       NOT NULL REFERENCES E_PROJECT(id),
  snapshot_date    DATE         NOT NULL,                           -- 日切日期
  progress_score   NUMERIC(6,4) NOT NULL DEFAULT 0,                 -- 进度分（0-1 归一化）
  budget_score     NUMERIC(6,4) NOT NULL DEFAULT 0,                 -- 经费分（0-1 归一化）
  output_score     NUMERIC(6,4) NOT NULL DEFAULT 0,                 -- 成果分（0-1 归一化）
  risk_score       NUMERIC(6,4) NOT NULL DEFAULT 1,                 -- 风险分（0-1 归一化，含扣分）
  risk_penalty     NUMERIC(6,4) NOT NULL DEFAULT 0,                 -- 扣分明细合计（变更×5/逾期×3/未批支出×10）
  total_score      INT          NOT NULL DEFAULT 100                -- 加权总分 0-100（红黄绿阈值 80/60）
                   CHECK (total_score BETWEEN 0 AND 100),
  breakdown        JSONB,                                           -- 各分项原始值/权重/扣分来源明细
  ai_reason        TEXT,                                            -- AI 一句话归因（健康分下降时生成）
  trigger_source   VARCHAR(16)  NOT NULL DEFAULT 'ETL'
                   CHECK (trigger_source IN ('ETL','EVENT')),       -- 每日全量 ETL / 事件实时刷新
  policy_pack_id   BIGINT                                         -- 计算所用权重快照（复算，PRD 2.10）
);
COMMENT ON TABLE  E_HEALTH_HISTORY IS '健康度每日快照与事件刷新留痕（E-10），可回溯任意日期状态';
COMMENT ON COLUMN E_HEALTH_HISTORY.total_score IS '0.3*进度分+0.3*经费分+0.2*成果分+0.2*风险分，分量归一化后×100';
COMMENT ON COLUMN E_HEALTH_HISTORY.breakdown IS '存储权重/分量/扣分明细，支撑 AI 归因与复算';

CREATE UNIQUE INDEX uk_e_health_code ON E_HEALTH_HISTORY(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_e_health_day  ON E_HEALTH_HISTORY(project_id, snapshot_date) WHERE deleted = 0; -- 日切唯一
CREATE INDEX idx_e_health_project ON E_HEALTH_HISTORY(project_id, snapshot_date DESC);
CREATE INDEX idx_e_health_status  ON E_HEALTH_HISTORY(tenant_id, status, snapshot_date);


-- -----------------------------------------------------------------------------
-- 10) E_ARCHIVE_CHECKLIST 归档清单（模板 + 项目实例，E-15；README §5 拥有方）
--     project_id IS NULL => 模板（按 project_type/stage 配置）；project_id NOT NULL => 项目实例（缺项拦截结题）。
-- -----------------------------------------------------------------------------
CREATE TABLE E_ARCHIVE_CHECKLIST (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'TEMPLATE'
                   CHECK (status IN ('TEMPLATE','IN_PROGRESS','PASSED','BLOCKED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  project_id       BIGINT REFERENCES E_PROJECT(id),                 -- 同模块物理外键，NULL=模板
  project_type     VARCHAR(64),                                     -- 模板适用项目类型（sys_dict）
  stage            VARCHAR(32)  NOT NULL
                   CHECK (stage IN ('APPLICATION','MID_CHECK','FINAL')), -- 触发点：申报/中检/结题
  checklist_json   JSONB        NOT NULL DEFAULT '[]'::jsonb,       -- [{item,required,mime,doc_id,uploaded}] 清单项
  required_count   INT          NOT NULL DEFAULT 0,                 -- 必交项总数（生成列/校验维护）
  completed_count  INT          NOT NULL DEFAULT 0,                 -- 已上传必交项数
  completeness     NUMERIC(6,4) NOT NULL DEFAULT 0,                 -- 完成度=已上传必交项/必交项总数
  blocked_items    JSONB        NOT NULL DEFAULT '[]'::jsonb        -- 缺项清单（结题/验收拦截依据）
);
COMMENT ON TABLE  E_ARCHIVE_CHECKLIST IS '归档材料清单校验与缺项拦截（E-15）；被 E_FINAL_ACCEPT 引用';
COMMENT ON COLUMN E_ARCHIVE_CHECKLIST.project_id IS 'NULL=按 project_type+stage 的模板；非空=项目结题实例';
COMMENT ON COLUMN E_ARCHIVE_CHECKLIST.completeness IS '必交项未齐则 status=BLOCKED，拦截结题验收';

CREATE UNIQUE INDEX uk_e_arch_code ON E_ARCHIVE_CHECKLIST(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_e_arch_project ON E_ARCHIVE_CHECKLIST(project_id, stage);
CREATE INDEX idx_e_arch_tpl     ON E_ARCHIVE_CHECKLIST(tenant_id, project_type, stage, status);


-- -----------------------------------------------------------------------------
-- 延迟外键（本模块内前向引用，建表顺序 E_FINAL_ACCEPT 早于 E_ARCHIVE_CHECKLIST）
-- -----------------------------------------------------------------------------
ALTER TABLE E_FINAL_ACCEPT
  ADD CONSTRAINT fk_e_final_archive_checklist
  FOREIGN KEY (archive_checklist_id) REFERENCES E_ARCHIVE_CHECKLIST(id);

-- =============================================================================
-- 引用说明（不在本文件建表）：
--   e_trace_node 追溯节点（E-17）已在 00-common.sql 定义，object_type/object_id 指向 E_* 与 PRJ 编号，
--   GET /project/{id}/trace 通过 e_trace_node(trace_id, node_seq) 组织端到端有向链，本模块仅引用不重复建表。
--   外协台账（E-16）统一在 09 G 的 G_OUTSOURCE/G_CONTRACT，本模块只以 contract_id/outsource_unit_id 逻辑引用与视图展示。
-- =============================================================================


-- ===== 03-科研经费管理-F.ddl.sql =====
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
CREATE UNIQUE INDEX uk_f_income_bankflow ON F_INCOME(tenant_id, bank_flow_no) WHERE deleted = 0 AND bank_flow_no IS NOT NULL;
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
CREATE INDEX idx_f_approval_approver ON F_EXPENSE_APPROVAL(tenant_id, approver_user_id, status);
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


-- ===== 04-科研成果管理-R.ddl.sql =====
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


-- ===== 05-科技成果转化-T.ddl.sql =====
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
CREATE INDEX idx_t_approval_approver   ON T_APPROVAL_CHAIN(tenant_id, approver_id, acted_at);
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
CREATE UNIQUE INDEX uk_t_income_bankflow ON T_INCOME(tenant_id, bank_flow_no) WHERE deleted = 0 AND bank_flow_no IS NOT NULL; -- 防重复登记
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


-- ===== 06-科研诚信与伦理-C.ddl.sql =====
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


-- ===== 07-人员与团队-S.ddl.sql =====
-- =============================================================================
-- 07-人员与团队-S.ddl.sql · 人员与团队（S）模块建表脚本
-- 版本 v1.0 · 2026-10-13
-- 上游：../PRD/07-人员与团队.md（S_STAFF/S_TEAM/... 表 + S-01..S-16 功能）、
--       ./README.md（全局约定 §2/§3/§4/§5）、./00-common.sql（sys_user/sys_org/sys_role 横切底座）
-- 方言：PostgreSQL 15
--
-- 【信创达梦差异声明（对齐 design/README.md §2.4，达梦部署时按此替换）】
--   1) 自增主键：GENERATED ALWAYS AS IDENTITY  →  IDENTITY(1,1)
--   2) 时间戳：  TIMESTAMPTZ                    →  TIMESTAMP WITH TIME ZONE
--   3) 布尔：    BOOLEAN                        →  SMALLINT（0/1）——本脚本 is_pi 为布尔，达梦替换为 SMALLINT
--   4) 半结构：  JSONB                          →  CLOB/VARCHAR 存 JSON 文本 + 应用层解析
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0  →  普通唯一索引 + deleted 复合键
--   6) 全文检索 GIN/trigram (pg_trgm/tsvector)   →  应用层 ES / 达梦全文索引
--   7) CHECK (col IN(...))                      →  达梦同支持，保留
--
-- 【通用列（§2.1，所有业务表内联，列名列型完全一致，DDL 不再逐表注释）】
--   id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--   code VARCHAR(64), tenant_id BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
--   deleted SMALLINT NOT NULL DEFAULT 0, creator_id BIGINT NOT NULL, modifier_id BIGINT,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--   remark TEXT
--
-- 【单号前缀待细化】PRD 2.11 尚未为人员/团队登记专属单号前缀（详见 detail.md §10）。
--   S_STAFF/S_TEAM/S_TALENT_PLAN 的 code 先留通用值、不强建唯一约束（仅建部分唯一索引，
--   待向 seq_prefix_registry 登记前缀——建议 EMP/TM/TP——后回填 code 生成逻辑）。
--
-- 【敏感字段】S_STAFF.id_card_hash / bank_card_hash 为加密/哈希落库列（身份证/银行卡），
--   非管理员在应用层脱敏或不可见（PRD §9），审计走 sys_audit_log。
-- 【S_STAFF ↔ sys_user 1:1】user_id UNIQUE REFERENCES sys_user(id)，身份层与科研画像层分离。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1) S_STAFF · 科研人员主表（HR 同步 + 科研专属扩展；与 sys_user 1:1）
--    status 走通用生命周期 token（ACTIVE/INACTIVE）；雇佣状态落独立列 employment_status
-- -----------------------------------------------------------------------------
CREATE TABLE S_STAFF (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),                                -- 人员档案编号（前缀待 2.11 登记，见 detail §10）
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('ACTIVE','INACTIVE')),    -- 档案生命周期（非雇佣状态；雇佣状态见 employment_status）
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 身份关联（1:1 sys_user，S-USR-01 基本信息从 HR 同步） --------------------------------
  user_id              BIGINT       NOT NULL REFERENCES sys_user(id),  -- 与 sys_user 1:1（下方 uk_staff_user 强制）
  hr_code              VARCHAR(64)  NOT NULL,                       -- 工号（HR 主数据，同名学者双主键之一，与 ORCID 共同去重）
  -- 基本信息（HR 同步列） ---------------------------------------------------------------
  name                 VARCHAR(64)  NOT NULL,
  name_en              VARCHAR(128),
  gender               VARCHAR(8)   CHECK (gender IN ('MALE','FEMALE','OTHER','UNKNOWN')),
  birth_year           INT,
  id_card_hash         VARCHAR(128),                                -- 【敏感·加密/哈希】身份证号，加密落库，非管理员不可见
  bank_card_hash       VARCHAR(128),                                -- 【敏感·加密/哈希】银行卡号，加密落库，非管理员不可见
  email                VARCHAR(128),
  phone                VARCHAR(32),
  department_id        BIGINT       NOT NULL,                       -- 主部门 sys_org.id（双聘唯一主部门）
  secondary_dept_ids   JSONB        NOT NULL DEFAULT '[]',          -- 双聘/兼聘次部门 [{org_id,effort_pct}]，主部门唯一
  -- 岗位与雇佣 ---------------------------------------------------------------------------
  staff_type           VARCHAR(24)  NOT NULL DEFAULT 'FORMAL'       -- S-03 人员分类
                       CHECK (staff_type IN ('FORMAL','POSTDOC','VISITING_SCHOLAR','GUEST','TEMPORARY','STUDENT')),
  position             VARCHAR(32)                                  -- 岗位（研究员/副研/助研/博后/客座/学生…走字典 sys_dict）
                       CHECK (position IN ('RESEARCHER','ASSOCIATE_RESEARCHER','ASSISTANT_RESEARCHER','POSTDOC','GUEST','STUDENT','SUPPORT','OTHER')),
  title                VARCHAR(64),                                 -- 职称（走字典，可配）
  education            VARCHAR(32),                                 -- 学历（走字典，可配）
  hire_date            DATE,
  leave_date           DATE,
  employment_status    VARCHAR(16)  NOT NULL DEFAULT 'ONBOARD'      -- 雇佣状态（§4 S 状态 token）
                       CHECK (employment_status IN ('ONBOARD','RESIGNED','RETIRED','VISITING','GUEST','REHIRE')),
  photo_url            VARCHAR(512),
  -- 学者外部标识（S-04，去重与画像依赖） ------------------------------------------------
  orcid                VARCHAR(32),                                 -- ORCID iD（同名学者双主键之二，唯一）
  wos_researcher_id    VARCHAR(64),                                 -- WoS ResearcherID
  scopus_id            VARCHAR(64),                                 -- Scopus Author ID
  cnki_author_id       VARCHAR(64),                                 -- CNKI 作者号
  -- 科研专属扩展（S-02 / S-05 / S-16） --------------------------------------------------
  bio                  TEXT,                                         -- 个人简介
  research_expertise   JSONB        NOT NULL DEFAULT '[]',           -- 研究方向标签 [{tag,weight,source(AI|MANUAL),updated_at}]（S-05 AI+自建）
  external_appointments JSONB       NOT NULL DEFAULT '[]',           -- 学术任职 [{org,role,from_year,to_year}]（S-16）
  is_pi                BOOLEAN      NOT NULL DEFAULT FALSE,          -- 是否 PI（达梦→SMALLINT 0/1，见 §2.4）
  -- 治理三字段（§2.1 v1.1） ------------------------------------------------------------
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id       BIGINT                                       -- 命中制度包快照（画像/梯队规则复算用，可空）
);

CREATE UNIQUE INDEX uk_staff_user       ON S_STAFF(user_id) WHERE deleted = 0;                 -- 1:1 sys_user
CREATE UNIQUE INDEX uk_staff_hrcode     ON S_STAFF(tenant_id, hr_code) WHERE deleted = 0;        -- 工号唯一（双主键去重）
CREATE UNIQUE INDEX uk_staff_orcid      ON S_STAFF(orcid) WHERE deleted = 0 AND orcid IS NOT NULL; -- ORCID 全局唯一
CREATE INDEX        idx_staff_main      ON S_STAFF(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_staff_dept      ON S_STAFF(tenant_id, department_id);
CREATE INDEX        idx_staff_pi        ON S_STAFF(tenant_id, is_pi, employment_status);         -- PI 视图 / 离职交接扫描
CREATE INDEX        idx_staff_empstat   ON S_STAFF(tenant_id, employment_status);
CREATE INDEX        idx_staff_type      ON S_STAFF(tenant_id, staff_type);
CREATE INDEX        idx_staff_name      ON S_STAFF(tenant_id, name);                              -- 同名检索（pg_trgm 达梦退 ES）
CREATE INDEX        idx_staff_expertise ON S_STAFF USING GIN (research_expertise jsonb_path_ops); -- 方向标签检索

COMMENT ON TABLE  S_STAFF IS '科研人员主表：HR 同步基本信息 + 科研专属扩展字段，与 sys_user 1:1（user_id 关联）';
COMMENT ON COLUMN S_STAFF.status IS '档案生命周期 token：ACTIVE=在用/INACTIVE=停用（离职归档保留可查）；雇佣状态请用 employment_status';
COMMENT ON COLUMN S_STAFF.employment_status IS '雇佣状态 §4：ONBOARD=在职/RESIGNED=离职/RETIRED=退休/VISITING=访问/GUEST=客座/REHIRE=返聘；字典可配走 sys_dict';
COMMENT ON COLUMN S_STAFF.hr_code IS '工号（HR 主数据）：与 orcid 共同构成同名学者去重双主键（PRD §11）';
COMMENT ON COLUMN S_STAFF.id_card_hash IS '【敏感字段】身份证号加密/哈希落库，非管理员响应中脱敏或不可见（PRD §9），访问写 sys_audit_log';
COMMENT ON COLUMN S_STAFF.bank_card_hash IS '【敏感字段】银行卡号加密/哈希落库，非管理员不可见';
COMMENT ON COLUMN S_STAFF.department_id IS '主部门 sys_org.id：一人主部门唯一；双聘/兼聘次部门见 secondary_dept_ids（跨部门贡献可分配）';
COMMENT ON COLUMN S_STAFF.secondary_dept_ids IS '次部门数组 JSONB [{org_id,effort_pct}]：支持一人多部门，主部门唯一（PRD §11 双聘）';
COMMENT ON COLUMN S_STAFF.staff_type IS '人员分类 S-03：FORMAL=正式/POSTDOC=博士后/VISITING_SCHOLAR=访问学者/GUEST=客座/TEMPORARY=临时/STUDENT=学生';
COMMENT ON COLUMN S_STAFF.research_expertise IS '研究方向标签 JSONB：自建+AI 生成（S-05），[{tag,weight,source,updated_at}]，达梦以 CLOB 存 JSON 文本';
COMMENT ON COLUMN S_STAFF.is_pi IS '是否 PI（达梦 SMALLINT 0/1）：离职交接触发 E 项目/F 经费冻结的判据';

-- -----------------------------------------------------------------------------
-- 2) S_TEAM · 团队 / 课题组（创新团队/PI 组/重点实验室；S-06/S-07）
--    status 走团队生命周期 token：组建→运行→评估→变更→解散/换届
-- -----------------------------------------------------------------------------
CREATE TABLE S_TEAM (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),                                -- 团队编号（前缀待 2.11 登记，见 detail §10）
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'FORMING'
                       CHECK (status IN ('FORMING','ACTIVE','EVALUATING','CHANGING','RENEWAL','DISSOLVED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  -- 业务列 -------------------------------------------------------------------
  name                 VARCHAR(128) NOT NULL,
  team_type            VARCHAR(32)  NOT NULL DEFAULT 'PI_GROUP'
                       CHECK (team_type IN ('INNOVATION','PI_GROUP','RESEARCH_GROUP','KEY_LAB','PLATFORM')),
  pi_staff_id          BIGINT       REFERENCES S_STAFF(id),        -- PI（同模块物理外键）；pi_user_id 逻辑引用 sys_user
  pi_user_id           BIGINT,                                     -- PI 登录态 sys_user.id（与 S_STAFF.user_id 一致，冗余便于跨模块引用）
  department_id        BIGINT,                                     -- 挂靠部门 sys_org.id
  member_ids           JSONB        NOT NULL DEFAULT '[]',         -- 成员快照 [{user_id,role,joined_at,left_at}]；规范化主存见 S_MEMBERSHIP
  formed_date          DATE,                                       -- 组建日期
  evaluation_cycle     VARCHAR(32),                                -- 评估周期（走字典：ANNUAL/BIANNUAL/…）
  -- 治理三字段（§2.1 v1.1：团队涉法人隔离与密级） --------------------
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_team_code    ON S_TEAM(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX        idx_team_main   ON S_TEAM(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_team_pi     ON S_TEAM(tenant_id, pi_staff_id);
CREATE INDEX        idx_team_dept   ON S_TEAM(tenant_id, department_id);
CREATE INDEX        idx_team_member ON S_TEAM USING GIN (member_ids jsonb_path_ops);
COMMENT ON TABLE  S_TEAM IS '团队/课题组表：创新团队/PI 组/课题组/重点实验室；member_ids 为快照，权威成员见 S_MEMBERSHIP';
COMMENT ON COLUMN S_TEAM.status IS '团队生命周期 token：FORMING=组建/ACTIVE=运行/EVALUATING=周期评估/CHANGING=变更/RENEWAL=换届/DISSOLVED=解散';
COMMENT ON COLUMN S_TEAM.member_ids IS '成员快照 JSONB（组织树/前端渲染用）；增删成员一律写 S_MEMBERSHIP，本列由事件同步';

-- -----------------------------------------------------------------------------
-- 3) S_MEMBERSHIP · 成员关系（S_STAFF N:1 S_TEAM 规范化主存；S-06）
-- -----------------------------------------------------------------------------
CREATE TABLE S_MEMBERSHIP (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('ACTIVE','LEFT')),        -- 在册 / 已退出
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  team_id              BIGINT       NOT NULL REFERENCES S_TEAM(id),
  staff_id             BIGINT       NOT NULL REFERENCES S_STAFF(id),
  user_id              BIGINT,                                     -- 冗余 sys_user.id（跨模块引用便捷）
  role                 VARCHAR(16)  NOT NULL DEFAULT 'MEMBER'
                       CHECK (role IN ('LEADER','CORE','MEMBER','STUDENT','VISITOR')),
  joined_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  left_at              TIMESTAMPTZ,                                -- 退出时间（NULL=在册）
  contribution_summary TEXT                                         -- 个人贡献记录（S-USR-02）
);
CREATE UNIQUE INDEX uk_membership_active ON S_MEMBERSHIP(team_id, staff_id) WHERE deleted = 0 AND left_at IS NULL; -- 同团队在册唯一
CREATE INDEX        idx_membership_team  ON S_MEMBERSHIP(tenant_id, team_id);
CREATE INDEX        idx_membership_staff ON S_MEMBERSHIP(tenant_id, staff_id);   -- staff_id 常用过滤列
CREATE INDEX        idx_membership_role  ON S_MEMBERSHIP(tenant_id, role);
COMMENT ON TABLE  S_MEMBERSHIP IS '成员关系表（S_STAFF 1—N S_MEMBERSHIP N—1 S_TEAM 规范化主存）';
COMMENT ON COLUMN S_MEMBERSHIP.role IS '成员角色 token：LEADER=负责人/CORE=核心/MEMBER=成员/STUDENT=学生/VISITOR=访客';
COMMENT ON COLUMN S_MEMBERSHIP.left_at IS '退出时间；NULL 表示在册，配合 uk_membership_active 保证同团队在册唯一';

-- -----------------------------------------------------------------------------
-- 4) S_VISITOR · 客座 / 访问学者（S-08；短期权限生命周期 S-11）
--    status 走申请审批流：申请→审批→在用→到期
-- -----------------------------------------------------------------------------
CREATE TABLE S_VISITOR (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'APPLIED'
                       CHECK (status IN ('APPLIED','APPROVED','REJECTED','ACTIVE','EXPIRED','TERMINATED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  staff_id             BIGINT       NOT NULL REFERENCES S_STAFF(id),   -- 已在 S_STAFF 建档（employment_status=VISITING/GUEST）
  host_pi_staff_id     BIGINT       REFERENCES S_STAFF(id),            -- 邀请人 / 接待 PI
  host_team_id         BIGINT       REFERENCES S_TEAM(id),             -- 接待团队
  home_institution     VARCHAR(256),                                   -- 所属外部机构（跨机构学者，不入本院主档语义）
  visit_type           VARCHAR(16)  NOT NULL DEFAULT 'SHORT_TERM'
                       CHECK (visit_type IN ('SHORT_TERM','LONG_TERM','JOINT_RESEARCH')),
  start_date           DATE         NOT NULL,
  end_date             DATE         NOT NULL,                          -- 到期日：到期自动失效（联动 sys_user_role.expires_at）
  funding_source       VARCHAR(128),                                   -- 经费来源
  project_id           BIGINT,                                         -- 关联项目 E_PROJECT.id（逻辑引用，跨模块不建物理外键）
  permissions_scope    JSONB        NOT NULL DEFAULT '{}',             -- 授权范围 {project_ids:[],team_ids:[],modules:[],role_codes:[]} 限本项目/本团队
  reminder_stage       VARCHAR(8)   NOT NULL DEFAULT 'NONE'            -- 到期提醒阶段（30/7 天，幂等）
                       CHECK (reminder_stage IN ('NONE','DUE_30','DUE_7')),
  -- 治理三字段（§2.1 v1.1） ------------------------------------------
  legal_entity_id      BIGINT       NOT NULL,
  security_level       VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                       CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_visitor_code  ON S_VISITOR(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX        idx_visitor_end  ON S_VISITOR(tenant_id, end_date);           -- 到期扫描主路径（调度每日扫）
CREATE INDEX        idx_visitor_staff ON S_VISITOR(tenant_id, staff_id);
CREATE INDEX        idx_visitor_host ON S_VISITOR(tenant_id, host_pi_staff_id, host_team_id);
CREATE INDEX        idx_visitor_status ON S_VISITOR(tenant_id, status);
COMMENT ON TABLE  S_VISITOR IS '客座/访问学者表：短期入驻 + 授权范围 + 到期自动失效；permissions_scope 限本项目/本团队';
COMMENT ON COLUMN S_VISITOR.end_date IS '入驻到期日；到期由调度规则置 EXPIRED 并 revoke sys_user_role（expires_at 协作），100% 自动失效';
COMMENT ON COLUMN S_VISITOR.permissions_scope IS '授权范围 JSONB {project_ids,team_ids,modules,role_codes}：客座学者权限限定，达梦以 CLOB 存 JSON';
COMMENT ON COLUMN S_VISITOR.status IS '入驻状态 token：APPLIED=申请/APPROVED=已批/REJECTED=驳回/ACTIVE=在用/EXPIRED=到期失效/TERMINATED=提前终止';

-- -----------------------------------------------------------------------------
-- 5) S_STUDENT · 学生参与科研登记（S-09）
-- -----------------------------------------------------------------------------
CREATE TABLE S_STUDENT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ENROLLED'
                       CHECK (status IN ('ENROLLED','GRADUATED','WITHDRAWN','SUSPENDED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  staff_id             BIGINT       NOT NULL REFERENCES S_STAFF(id),   -- 学生也建 S_STAFF 档（staff_type=STUDENT）
  student_type         VARCHAR(16)  NOT NULL
                       CHECK (student_type IN ('PHD','MASTER','UNDERGRAD_THESIS','JOINT_TRAINING')),
  supervisor_staff_id  BIGINT       REFERENCES S_STAFF(id),            -- 导师（本院 PI/研究员）
  supervisor_user_id   BIGINT,                                         -- 导师登录态 sys_user.id（逻辑引用）
  enroll_year          INT,
  graduate_year        INT,
  thesis_topic         VARCHAR(512),
  associated_project_ids JSONB      NOT NULL DEFAULT '[]'              -- 参与项目 [E_PROJECT.id,...]（逻辑引用）
);
CREATE UNIQUE INDEX uk_student_staff ON S_STUDENT(staff_id) WHERE deleted = 0;   -- 学生与档案 1:1（若适用）
CREATE INDEX        idx_student_sup  ON S_STUDENT(tenant_id, supervisor_staff_id);
CREATE INDEX        idx_student_type ON S_STUDENT(tenant_id, student_type, status);
COMMENT ON TABLE  S_STUDENT IS '学生参与科研登记表：博/硕/本科毕设/联合培养，关联导师与参与项目';
COMMENT ON COLUMN S_STUDENT.student_type IS '学生类型 token：PHD=博士/MASTER=硕士/UNDERGRAD_THESIS=本科毕设/JOINT_TRAINING=联合培养';
COMMENT ON COLUMN S_STUDENT.associated_project_ids IS '参与项目 id 数组（逻辑引用 E_PROJECT.id），达梦以 CLOB 存 JSON';

-- -----------------------------------------------------------------------------
-- 6) S_PORTRAIT · PI / 学者画像快照（日 / 周切；S-13，派生聚合表）
--    指标列为聚合快照，不承载业务写；每周批量刷新 + 关键事件即时更新
-- -----------------------------------------------------------------------------
CREATE TABLE S_PORTRAIT (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('ACTIVE','ARCHIVED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  staff_id             BIGINT       NOT NULL REFERENCES S_STAFF(id),
  snapshot_date        DATE         NOT NULL,                          -- 快照日（日切/周切）
  -- 项目维（聚合 E_PROJECT） ------------------------------------------
  project_count_total  INT          NOT NULL DEFAULT 0,
  project_count_active INT          NOT NULL DEFAULT 0,
  -- 经费维（聚合 F_*） ------------------------------------------------
  funding_total        NUMERIC(18,2) NOT NULL DEFAULT 0,              -- 累计在研/主持经费（元）
  funding_yearly       NUMERIC(18,2) NOT NULL DEFAULT 0,              -- 近一年到账/立项经费（元）
  -- 成果维（聚合 R_OUTPUT） -------------------------------------------
  output_count_papers  INT          NOT NULL DEFAULT 0,
  output_count_patents INT          NOT NULL DEFAULT 0,
  h_index              INT          NOT NULL DEFAULT 0,               -- h 指数
  total_citations      INT          NOT NULL DEFAULT 0,               -- 总被引
  top_journals         JSONB        NOT NULL DEFAULT '[]',            -- 代表作/顶刊 [{title,journal,year,citations}]
  expertise_tags       JSONB        NOT NULL DEFAULT '[]',            -- AI 生成方向标签 [{tag,weight}]（S-05）
  -- 合作 / 培养 / 阶段 ------------------------------------------------
  collaboration_score  NUMERIC(6,4) NOT NULL DEFAULT 0,               -- 合作活跃度/中心度归一分
  mentoring_count      INT          NOT NULL DEFAULT 0,               -- 培养研究生数
  career_stage         VARCHAR(16)  NOT NULL DEFAULT 'STABLE'
                       CHECK (career_stage IN ('RISING','STABLE','MATURE')),  -- 上升/稳定/成熟
  ai_summary           TEXT,                                          -- LLM 生成自然语言画像摘要（辅助评审/合作决策）
  integrity_flag       BOOLEAN      NOT NULL DEFAULT FALSE            -- 诚信风险标记（联动 06 模块，仅纪检/管理员可见）
);
CREATE UNIQUE INDEX uk_portrait_day  ON S_PORTRAIT(staff_id, snapshot_date);     -- 每人每快照日一条
CREATE INDEX        idx_portrait_staff ON S_PORTRAIT(tenant_id, staff_id, snapshot_date DESC);
CREATE INDEX        idx_portrait_stage ON S_PORTRAIT(tenant_id, career_stage);
CREATE INDEX        idx_portrait_pi    ON S_PORTRAIT(tenant_id, h_index DESC);
COMMENT ON TABLE  S_PORTRAIT IS 'PI/学者画像快照表（日/周切，派生聚合）：项目/经费/成果/引用/合作/培养/诚信六维 + AI 摘要';
COMMENT ON COLUMN S_PORTRAIT.funding_total IS '累计主持/在研经费 NUMERIC(18,2)，聚合 F 模块；口径见 detail §4 S-13';
COMMENT ON COLUMN S_PORTRAIT.career_stage IS '职业阶段 token：RISING=上升/STABLE=稳定/MATURE=成熟（由规则+模型综合判定）';
COMMENT ON COLUMN S_PORTRAIT.expertise_tags IS 'AI 生成研究方向标签 JSONB，与 S_STAFF.research_expertise 对齐（快照冗余）';
COMMENT ON COLUMN S_PORTRAIT.integrity_flag IS '诚信风险标记（达梦 SMALLINT 0/1），仅纪检/管理员可见，普通角色不可见';

-- -----------------------------------------------------------------------------
-- 7) S_COLLAB_GRAPH · 合作关系网络边表（快照切片；S-14，论文/项目/专利共现聚合）
--    无向边规范化 CHECK staff_a_id < staff_b_id；支持按 snapshot_date 时间切片
-- -----------------------------------------------------------------------------
CREATE TABLE S_COLLAB_GRAPH (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('ACTIVE','ARCHIVED')),
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  staff_a_id           BIGINT       NOT NULL REFERENCES S_STAFF(id),   -- 边端点 A（约定 a<b，规范化无向边）
  staff_b_id           BIGINT       NOT NULL REFERENCES S_STAFF(id),   -- 边端点 B
  snapshot_date        DATE         NOT NULL,                          -- 切片日（时间切片渲染）
  weight               INT          NOT NULL DEFAULT 0,                -- 合作次数（共现边权）
  first_year           INT,                                            -- 首次合作年
  last_year            INT,                                            -- 最近合作年
  shared_projects      JSONB        NOT NULL DEFAULT '[]',            -- 共现项目 [project_id,...]（逻辑引用 E_PROJECT）
  shared_papers        JSONB        NOT NULL DEFAULT '[]',            -- 共现论文 [output_id,...]（逻辑引用 R_OUTPUT）
  centrality_score     NUMERIC(6,4),                                  -- 该边/节点中心度（分析产出，可选）
  community_id         INT,                                           -- 社团检测结果簇号（分析产出，可选）
  legal_entity_id      BIGINT       NOT NULL,                         -- 法人隔离（边归属法人）
  CONSTRAINT ck_collab_ordered CHECK (staff_a_id < staff_b_id)         -- 无向边规范化，防重复边
);
CREATE UNIQUE INDEX uk_collab_edge ON S_COLLAB_GRAPH(staff_a_id, staff_b_id, snapshot_date);  -- 同一切片每对学者一条边
CREATE INDEX        idx_collab_a   ON S_COLLAB_GRAPH(tenant_id, staff_a_id, snapshot_date);
CREATE INDEX        idx_collab_b   ON S_COLLAB_GRAPH(tenant_id, staff_b_id, snapshot_date);
CREATE INDEX        idx_collab_date ON S_COLLAB_GRAPH(tenant_id, snapshot_date);
COMMENT ON TABLE  S_COLLAB_GRAPH IS '合作关系网络边表（快照切片）：论文/项目/专利共现聚合而成，支持时间切片与中心度/社团分析';
COMMENT ON COLUMN S_COLLAB_GRAPH.staff_a_id IS '边端点 A，约定 staff_a_id<staff_b_id 规范化无向边；(a,b,snapshot_date) 唯一';
COMMENT ON COLUMN S_COLLAB_GRAPH.weight IS '合作次数（论文+项目+专利共现加权聚合）';

-- -----------------------------------------------------------------------------
-- 8) S_TALENT_PLAN · 人才计划与称号（S-12；杰青/优青/长江/万人/院所自立）
-- -----------------------------------------------------------------------------
CREATE TABLE S_TALENT_PLAN (
  id                   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                 VARCHAR(64),                                -- 人才计划登记编号（前缀待 2.11 登记）
  tenant_id            BIGINT       NOT NULL,
  status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('CANDIDATE','ACTIVE','COMPLETED','EXPIRED','REVOKED')),  -- 候选/在期/已结/到期/撤销
  deleted              SMALLINT     NOT NULL DEFAULT 0,
  creator_id           BIGINT       NOT NULL,
  modifier_id          BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark               TEXT,
  staff_id             BIGINT       NOT NULL REFERENCES S_STAFF(id),
  plan_name            VARCHAR(64)  NOT NULL,                       -- 计划名称（走字典 sys_dict：杰青/优青/长江/万人/院所自立…）
  plan_code            VARCHAR(64),                                 -- 计划编码（字典 item_code）
  level                VARCHAR(16)  CHECK (level IN ('NATIONAL','MINISTRY','PROVINCE','INSTITUTE')),
  awarded_year         INT,
  duration_years       INT,                                         -- 资助周期（年）
  end_year             INT,                                         -- 到期年（awarded_year+duration_years）
  batch                VARCHAR(64)                                  -- 批次（走字典/文本）
);
CREATE UNIQUE INDEX uk_talent_code ON S_TALENT_PLAN(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX        idx_talent_staff ON S_TALENT_PLAN(tenant_id, staff_id);
CREATE INDEX        idx_talent_name  ON S_TALENT_PLAN(tenant_id, plan_name, status);
CREATE INDEX        idx_talent_year  ON S_TALENT_PLAN(tenant_id, awarded_year);
COMMENT ON TABLE  S_TALENT_PLAN IS '人才计划与称号表：杰青/优青/长江/万人/院所自立等，供画像时间轴与梯队分析';
COMMENT ON COLUMN S_TALENT_PLAN.level IS '层级 token：NATIONAL=国家级/MINISTRY=部级/PROVINCE=省级/INSTITUTE=院所自立';
COMMENT ON COLUMN S_TALENT_PLAN.plan_name IS '计划名称，可配项走 sys_dict（禁止硬编码，PRD 2.8）';

-- =============================================================================
-- 建表完毕：S 模块共 8 张表
--   S_STAFF（人员主表，1:1 sys_user）
--   S_TEAM（团队/课题组）· S_MEMBERSHIP（成员关系 N:N 规范化主存）
--   S_VISITOR（客座/访问学者，短期权限生命周期）· S_STUDENT（学生参与科研）
--   S_PORTRAIT（PI/学者画像快照，日/周切，派生聚合）
--   S_COLLAB_GRAPH（合作关系网络边表，时间切片，共现聚合）
--   S_TALENT_PLAN（人才计划与称号）
-- 派生/快照表（S_PORTRAIT/S_COLLAB_GRAPH）由画像引擎批 + 事件即时写入，不承载业务直写。
-- =============================================================================


-- ===== 08-数据分析与决策-D.ddl.sql =====
-- =============================================================================
-- 08-数据分析与决策-D.ddl.sql · 数据分析与决策支持（D）模块建表脚本
-- 版本 v1.0 · 2026-10-13
-- 上游：../PRD/08-数据分析与决策.md（D-01..D-19、数仓分层 §5.1、应用层表 §5.2、
--       ETL §6、AI §8、权限 §9、接口 §10、异常 §11、非功能 §12）、
--       ./README.md（全局约定 §2 数据库 / §3 API / §4 状态 token / §5 共享实体登记表）、
--       ../TECH_ARCHITECTURE.md（§二 技术选型 / §五 数据架构：ClickHouse OLAP、CDC、NL2SQL）
--
-- 【本模块特殊性：双引擎落地（ADR-003 OLTP 与 OLAP 双引擎）】
--   ┌───────────────────────────────────────────────────────────────────────┐
--   │ 第一部分：PostgreSQL 15 —— OLTP 配置 / 应用元数据 / AI 交互留痕         │
--   │   D_METRIC / D_REPORT / D_REPORT_INSTANCE / D_SCREEN / D_SUBSCRIPTION  │
--   │   D_QUERY_LOG / D_BENCHMARK / D_FORECAST / D_POLICY_QA / D_EXPORT      │
--   │   —— 事务型、低频读写、强一致、被 svc-analytics 直接维护                │
--   ├───────────────────────────────────────────────────────────────────────┤
--   │ 第二部分：ClickHouse —— 数仓 ODS/DWD/DWS/ADS 四层                       │
--   │   ods_expense / dwd_* / dim_* / dws_* / ads_*                          │
--   │   —— 列存高吞吐聚合、大屏/画像/趋势、经 CDC→Kafka→Flink T+1 灌入        │
--   │   信创替代（../TECH_ARCHITECTURE.md §二）：ClickHouse → Apache Doris    │
--   └───────────────────────────────────────────────────────────────────────┘
--   指标口径以 D_METRIC.formula_sql 为唯一真源（PRD §11 报送数据不一致以此为准）。
--   多法人合并视图（D-19）联动 X-10 并表口径：跨法人聚合表统一携带 legal_entity_id，
--   总院合并 = 各法人按主责法人口径聚合（避免重复计入），分院下钻 = WHERE legal_entity_id。
--
-- 【信创达梦差异声明（仅针对第一部分 PostgreSQL 15，对齐 design/README.md §2.4，达梦部署时按此替换）】
--   1) 自增主键：GENERATED ALWAYS AS IDENTITY  →  IDENTITY(1,1)
--   2) 时间戳：  TIMESTAMPTZ                    →  TIMESTAMP WITH TIME ZONE
--   3) 布尔：    BOOLEAN                        →  SMALLINT（0/1）
--   4) 半结构：  JSONB                          →  CLOB/VARCHAR 存 JSON 文本 + 应用层解析
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0  →  普通唯一索引 + deleted 复合键
--   6) 全文检索 GIN/trigram (pg_trgm/tsvector)   →  应用层 ES / 达梦全文索引
--   7) 表达式唯一索引中的函数（如 COALESCE）      →  应用层生成哈希列后建普通唯一索引
--   注：第二部分 ClickHouse 不受达梦方言影响，信创分析库替换路径为 Doris（列存语法近似，
--       ENGINE 改为 Distributed/MergeTree 系，COMMENT 语法兼容）。
--
-- 【通用列（§2.1，第一部分所有表内联，列名列型完全一致，DDL 不再逐表注释）】
--   id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--   code VARCHAR(64), tenant_id BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
--   deleted SMALLINT NOT NULL DEFAULT 0, creator_id BIGINT NOT NULL, modifier_id BIGINT,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--   remark TEXT
--   治理三字段（§2.1 v1.1，携带于涉及法人隔离/密级的表）：legal_entity_id BIGINT、
--   security_level VARCHAR(16) DEFAULT 'INTERNAL'、policy_pack_id BIGINT（本模块基本不用）。
--
-- 【单号前缀（§2.3 / PRD 2.11）】D 模块配置类表 code 为业务可读编码（指标编码 / 报表编码 /
--   报送模板编码），非统一编号中心流水号；D 未登记独立单号前缀（见 detail §10 待细化）。
--
-- 【跨模块引用（§5 共享实体登记表，逻辑外键，跨微服务库不建物理 FK）】
--   user_id / *_user_id / generated_by → sys_user.id；report_id 引用 D_REPORT.id（同模块物理 FK）；
--   ClickHouse dim/事实表的 staff_id/department_id/project_id/subject_id 为业务库主键的镜像值。
-- =============================================================================


-- #############################################################################
-- 第一部分 · PostgreSQL 15（OLTP 配置 / 应用元数据 / AI 交互留痕）
-- #############################################################################

-- -----------------------------------------------------------------------------
-- 1) D_METRIC · 指标字典（口径唯一真源，D-01 / D-19）
--    PRD §5.2：id,code,name,category,unit,formula_sql,drill_dims,refresh_freq,owner_role。
--    口径版本化（PRD §11 指标口径变化）：version + effective_from/to + prev_metric_id，
--    历史报表实例引用其生成时的指标版本快照，新报表用最新 ACTIVE 版本。
-- -----------------------------------------------------------------------------
CREATE TABLE D_METRIC (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,                          -- 指标编码（人可读，如 ACTIVE_PRJ_CNT）
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','DEPRECATED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  name             VARCHAR(128) NOT NULL,                          -- 指标中文名
  category         VARCHAR(32)  NOT NULL
                   CHECK (category IN ('PROJECT','FUNDING','OUTPUT','TRANSFER','PEOPLE','RISK','COMPREHENSIVE')), -- 主题域（sys_dict 可配扩展）
  unit             VARCHAR(32),                                    -- 单位：万元/篇/项/%/人 等
  formula_sql      TEXT         NOT NULL,                          -- 口径 SQL（唯一真源，ADS 取数模板 / 下钻起点）
  drill_dims       JSONB        NOT NULL DEFAULT '[]',             -- 下钻维度 [{dim,path}] 如 部门→项目→报销
  refresh_freq     VARCHAR(16)  NOT NULL DEFAULT 'DAILY'
                   CHECK (refresh_freq IN ('REALTIME','HOURLY','DAILY','WEEKLY','MONTHLY')),
  owner_role       VARCHAR(32),                                    -- 归口角色（R-MANAGER/R-FINANCE/…）
  caliber_note     TEXT,                                            -- 口径说明 / 变更理由（评审留痕）
  version          INT          NOT NULL DEFAULT 1,                -- 口径版本（变更评审后递增）
  prev_metric_id   BIGINT       REFERENCES D_METRIC(id),          -- 上一版本（口径变更链，同模块物理 FK）
  effective_from   DATE         NOT NULL DEFAULT CURRENT_DATE,     -- 口径生效起
  effective_to     DATE,                                            -- 口径生效止（NULL=当前有效）
  -- 治理字段（法人归属 + 密级，指标可按法人差异化）
  legal_entity_id  BIGINT,                                          -- NULL=全院统一口径；非空=法人专属口径
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_metric_code_ver ON D_METRIC(tenant_id, code, version) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_metric_active   ON D_METRIC(tenant_id, code) WHERE deleted = 0 AND effective_to IS NULL AND status = 'ACTIVE';
CREATE INDEX idx_metric_category      ON D_METRIC(tenant_id, category, status);
COMMENT ON TABLE  D_METRIC IS '指标字典（D-01）：全院核心指标口径唯一真源，指标命名统一避免口径歧义（PRD §12 数据治理）';
COMMENT ON COLUMN D_METRIC.formula_sql IS '指标口径 SQL，ADS 结果表与下钻取数的唯一真源；报送口径冲突以此为准（PRD §11）';
COMMENT ON COLUMN D_METRIC.drill_dims IS '下钻维度链 JSON：ADS→DWS→DWD→业务表的可下钻路径定义';
COMMENT ON COLUMN D_METRIC.version IS '口径版本；历史 D_REPORT_INSTANCE 冻结其生成时版本，新报表取最新 ACTIVE 版本';
COMMENT ON COLUMN D_METRIC.legal_entity_id IS 'NULL=总院统一口径（合并视图基准）；非空=分法人差异化口径';

-- -----------------------------------------------------------------------------
-- 2) D_REPORT · 报表定义（D-04/05，PRD §5.2）
--    id,code,name,type(DASHBOARD/TABLE/CHART),schema_json,data_source,permission_scope,schedule
-- -----------------------------------------------------------------------------
CREATE TABLE D_REPORT (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','PUBLISHED','OFFLINE')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  name             VARCHAR(128) NOT NULL,
  type             VARCHAR(16)  NOT NULL CHECK (type IN ('DASHBOARD','TABLE','CHART')), -- 报表类型
  schema_json      JSONB        NOT NULL DEFAULT '{}',             -- 设计器 DSL（字段树/透视/图表/参数化）
  data_source      VARCHAR(64)  NOT NULL,                          -- 数据源标识：ADS 表名 / 指标 code / JDBC 逻辑名
  permission_scope VARCHAR(32)  NOT NULL DEFAULT 'DEPT'
                   CHECK (permission_scope IN ('SELF','DEPT','ALL_INSTITUTE','FINANCE','AUDIT')), -- 可见范围（联动 detail §7）
  metric_refs      JSONB        NOT NULL DEFAULT '[]',             -- 引用指标 code 清单（联动 D_METRIC）
  schedule         VARCHAR(64),                                    -- 定时表达式 cron（生成 report.scheduled；空=手动）
  data_freshness   VARCHAR(16)  NOT NULL DEFAULT 'T_PLUS_1'
                   CHECK (data_freshness IN ('REALTIME','T_PLUS_1','T_PLUS_7')), -- 数据新鲜度标注（PRD §11 数据延迟提醒）
  -- 治理字段
  legal_entity_id  BIGINT,                                          -- NULL=全院报表；非空=法人专属报表
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_report_code ON D_REPORT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_report_main      ON D_REPORT(tenant_id, status, type);
CREATE INDEX idx_report_scope     ON D_REPORT(tenant_id, permission_scope);
COMMENT ON TABLE  D_REPORT IS '报表定义（D-04 多维分析 / D-05 自定义报表设计器）：预置 20+ 常用报表 + 用户自定义模板';
COMMENT ON COLUMN D_REPORT.permission_scope IS '可见范围 token，驱动 NL2SQL/取数的行级权限过滤（detail §4 权限过滤）';
COMMENT ON COLUMN D_REPORT.data_freshness IS '数据新鲜度标注，T+1 未刷新时报表/大屏顶部红色提醒（PRD §11）';

-- -----------------------------------------------------------------------------
-- 3) D_REPORT_INSTANCE · 报表实例（含快照，D-05/D-09/D-10，PRD §5.2/§5.3）
--    id,report_id,params,snapshot_url,generated_at,generated_by,expires_at
--    口径冻结：metric_version_snapshot 记录生成时各指标版本，历史报表留旧口径（PRD §11）
-- -----------------------------------------------------------------------------
CREATE TABLE D_REPORT_INSTANCE (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'GENERATED'
                   CHECK (status IN ('GENERATING','GENERATED','EXPIRED','FAILED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  report_id        BIGINT       NOT NULL REFERENCES D_REPORT(id), -- 同模块物理外键
  params           JSONB        NOT NULL DEFAULT '{}',             -- 实例参数（时间/部门/项目类型切片）
  snapshot_url     VARCHAR(512),                                   -- 快照文件（对象存储 MinIO）
  metric_version_snapshot JSONB NOT NULL DEFAULT '{}',             -- 冻结口径版本 {code:version}（历史留旧口径）
  dq_flag          VARCHAR(16)  NOT NULL DEFAULT 'OK'
                   CHECK (dq_flag IN ('OK','PARTIAL_MISSING')),    -- 数据质量标注（PRD §11 质量下降标缺失）
  data_as_of       DATE,                                           -- 数据截至日期（大屏/报表顶部）
  generated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
  generated_by     BIGINT       NOT NULL,                          -- 生成人 sys_user.id（逻辑引用）
  expires_at       TIMESTAMPTZ                                     -- 快照过期（到期回收，PI 导出限时下载）
);
CREATE INDEX idx_inst_report ON D_REPORT_INSTANCE(report_id, generated_at DESC);
CREATE INDEX idx_inst_user   ON D_REPORT_INSTANCE(tenant_id, generated_by);
COMMENT ON TABLE  D_REPORT_INSTANCE IS '报表实例（含快照）：一键生成 / 定时生成 / 个人导出 / 上级报送的落地记录';
COMMENT ON COLUMN D_REPORT_INSTANCE.metric_version_snapshot IS '生成时冻结的指标口径版本，历史报表复算取旧口径，不受新口径影响（PRD §11）';
COMMENT ON COLUMN D_REPORT_INSTANCE.dq_flag IS '数据质量标注：PARTIAL_MISSING 时报表顶部显示"数据存在部分缺失"';

-- -----------------------------------------------------------------------------
-- 4) D_SCREEN · 数据大屏配置（D-06，PRD §5.2/§7.3）
--    id,name,layout_json,widgets([{type,data_metric_id,viz_config}]),rotation_seconds
-- -----------------------------------------------------------------------------
CREATE TABLE D_SCREEN (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','PUBLISHED','OFFLINE')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  name             VARCHAR(128) NOT NULL,
  theme            VARCHAR(32)                                        -- 预置模板：全景/经费监督/转化/人才/学科分布
                   CHECK (theme IS NULL OR theme IN ('OVERVIEW','FUNDING','TRANSFER','TALENT','DISCIPLINE')),
  layout_json      JSONB        NOT NULL DEFAULT '{}',               -- 拼图布局（栅格坐标/断点续播位点）
  widgets          JSONB        NOT NULL DEFAULT '[]',               -- [{widgetId,type,dataMetricId,vizConfig,drillPath}]
  rotation_seconds INT          NOT NULL DEFAULT 30,                 -- 轮播间隔秒（支持 6 组视图自动轮播）
  data_as_of_expr  VARCHAR(128),                                     -- 数据截至日期取值表达式（顶部展示 + T+1 提醒）
  -- 治理字段（大屏可含法人维度）
  legal_entity_id  BIGINT                                             -- NULL=总院合并大屏；非空=法人下钻大屏
);
CREATE UNIQUE INDEX uk_screen_code ON D_SCREEN(tenant_id, code) WHERE deleted = 0;
COMMENT ON TABLE  D_SCREEN IS '数据大屏配置（D-06）：全屏深色多块拼图，自动轮播 6 组视图，适配会议室 4K';
COMMENT ON COLUMN D_SCREEN.widgets IS '组件 JSON：每个 widget 引用 D_METRIC.code 取数，viz_config 存 ECharts 配置';

-- -----------------------------------------------------------------------------
-- 5) D_SUBSCRIPTION · 数据订阅（D-18，PRD §5.2/§12 三通道）
--    id,user_id,report_id,frequency(DAILY/WEEKLY/MONTHLY),channel(EMAIL/WECHAT/INBOX),last_sent_at
-- -----------------------------------------------------------------------------
CREATE TABLE D_SUBSCRIPTION (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','PAUSED','CANCELLED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id          BIGINT       NOT NULL,                            -- sys_user.id（逻辑引用）
  report_id        BIGINT       NOT NULL REFERENCES D_REPORT(id),    -- 同模块物理外键
  frequency        VARCHAR(16)  NOT NULL DEFAULT 'DAILY'
                   CHECK (frequency IN ('DAILY','WEEKLY','MONTHLY')),
  channel          VARCHAR(16)  NOT NULL DEFAULT 'EMAIL'
                   CHECK (channel IN ('EMAIL','WECHAT','INBOX')),    -- 邮件 / 企业微信 / 站内消息
  send_day         SMALLINT,                                         -- 发送日（周几/月几号，配合 frequency）
  last_sent_at     TIMESTAMPTZ,                                      -- 最近推送时间（幂等去重 + 排重）
  params_override  JSONB        NOT NULL DEFAULT '{}'                -- 订阅级参数覆盖（如仅看本部门）
);
CREATE UNIQUE INDEX uk_sub_user_report ON D_SUBSCRIPTION(tenant_id, user_id, report_id, frequency, channel) WHERE deleted = 0;
COMMENT ON TABLE  D_SUBSCRIPTION IS '数据订阅（D-18）：邮件/企业微信/站内消息三通道定时推送报表实例';
COMMENT ON COLUMN D_SUBSCRIPTION.channel IS '推送通道 token（对齐 PRD §12 三通道；实际投递经 svc-notify）';

-- -----------------------------------------------------------------------------
-- 6) D_QUERY_LOG · 自然语言查询日志（D-11，PRD §5.2/§8.1）
--    id,user_id,question_text,generated_sql,executed_at,row_count,feedback
--    权限改写审计：rewritten_sql 存注入 tenant_id/legal_entity/security_level 后的最终 SQL
-- -----------------------------------------------------------------------------
CREATE TABLE D_QUERY_LOG (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'SUCCESS'
                   CHECK (status IN ('SUCCESS','FAILED','TIMEOUT','REJECTED_UNMAPPED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id          BIGINT       NOT NULL,                            -- sys_user.id（逻辑引用）
  question_text    TEXT         NOT NULL,                            -- 原始自然语言问题
  matched_metrics  JSONB        NOT NULL DEFAULT '[]',               -- 命中的指标 code（Schema-aware 匹配）
  semantic_readback TEXT,                                             -- 语义回读文本"你是不是想问…"
  user_confirmed   BOOLEAN      NOT NULL DEFAULT FALSE,             -- 用户是否确认回读语义
  generated_sql    TEXT,                                             -- LLM 生成 SQL（改写前）
  rewritten_sql    TEXT,                                             -- 权限改写层注入过滤后的最终 SQL（审计）
  executed_at      TIMESTAMPTZ,                                      -- 执行时间
  row_count        INT,                                              -- 返回行数
  elapsed_ms       INT,                                              -- 端到端耗时（<5s SLA，超时中断）
  masked           BOOLEAN      NOT NULL DEFAULT FALSE,             -- 结果是否脱敏（掩码手机/身份证）
  feedback         VARCHAR(16)  CHECK (feedback IS NULL OR feedback IN ('THUMBS_UP','THUMBS_DOWN','CORRECTED')) -- 反馈回流评估集
);
CREATE INDEX idx_qlog_user  ON D_QUERY_LOG(tenant_id, user_id, created_at DESC);
CREATE INDEX idx_qlog_status ON D_QUERY_LOG(tenant_id, status);
COMMENT ON TABLE  D_QUERY_LOG IS 'NL2SQL 查询日志（D-11）：问题/生成SQL/改写SQL/语义回读/耗时/反馈，供评估与审计复算';
COMMENT ON COLUMN D_QUERY_LOG.rewritten_sql IS '权限改写层注入 tenant_id+legal_entity_id+security_level 过滤后的最终执行 SQL（detail §4）';
COMMENT ON COLUMN D_QUERY_LOG.status IS 'REJECTED_UNMAPPED=无法映射指标→兜底"未理解请联系管理员"不瞎猜（PRD §11）；TIMEOUT=5s 超时中断';

-- -----------------------------------------------------------------------------
-- 7) D_BENCHMARK · 机构对标（D-14，PRD §5.2/§7.5）
--    id,peer_institute_id,year,metric_code,peer_value,our_value,rank
-- -----------------------------------------------------------------------------
CREATE TABLE D_BENCHMARK (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','ARCHIVED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  peer_institute_id BIGINT      NOT NULL,                            -- 对标院所标识（外部/公开数据主体）
  peer_name        VARCHAR(128) NOT NULL,                            -- 对标院所名称（雷达图标签）
  year             SMALLINT     NOT NULL,                            -- 对标年度
  metric_code      VARCHAR(64)  NOT NULL,                            -- 逻辑引用 D_METRIC.code（口径可比）
  peer_value       NUMERIC(18,2),                                    -- 对方值
  our_value        NUMERIC(18,2),                                    -- 本院值
  rank             INT,                                              -- 本院在该组中的排名
  data_source      VARCHAR(32)  NOT NULL DEFAULT 'PUBLIC'
                   CHECK (data_source IN ('PUBLIC','ANNUAL_REPORT')), -- 公开数据 / 上级单位年报
  legal_entity_id  BIGINT                                             -- NULL=全院对标；非空=法人对标
);
CREATE UNIQUE INDEX uk_benchmark ON D_BENCHMARK(tenant_id, peer_institute_id, year, metric_code) WHERE deleted = 0;
COMMENT ON TABLE  D_BENCHMARK IS '机构间对标（D-14）：本院 vs N 家同类院所关键指标对比，数据源公开 + 上级年报';
COMMENT ON COLUMN D_BENCHMARK.metric_code IS '逻辑引用 D_METRIC.code，保证本院与对方口径可比（同真源）';

-- -----------------------------------------------------------------------------
-- 8) D_FORECAST · 趋势预测快照（D-16，PRD §5.2/§8.4）
--    id,target_metric,model_type,forecast_date,predicted_value,confidence_interval
-- -----------------------------------------------------------------------------
CREATE TABLE D_FORECAST (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  target_metric    VARCHAR(64)  NOT NULL,                            -- 逻辑引用 D_METRIC.code（经费到账/论文产出/立项数）
  model_type       VARCHAR(32)  NOT NULL DEFAULT 'PROPHET'
                   CHECK (model_type IN ('PROPHET','ARIMA','LTSM','LINEAR_REG')), -- Prophet+外部指标为主
  forecast_date    DATE         NOT NULL,                            -- 预测目标日期（如明年到账）
  predicted_value  NUMERIC(18,2) NOT NULL,                           -- 预测值
  confidence_interval JSONB     NOT NULL DEFAULT '{}',               -- 置信区间 {lower,upper,level}
  key_assumptions  JSONB        NOT NULL DEFAULT '[]',               -- 关键假设（GDP/国家政策信号，展示可解释）
  generated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
  legal_entity_id  BIGINT
);
CREATE INDEX idx_forecast_metric ON D_FORECAST(tenant_id, target_metric, forecast_date);
COMMENT ON TABLE  D_FORECAST IS '趋势预测快照（D-16）：经费/成果/立项预测曲线 + 置信区间 + 关键假设';
COMMENT ON COLUMN D_FORECAST.confidence_interval IS '置信区间 JSON {lower,upper,level}，前端画阴影带（PRD §8.4）';

-- -----------------------------------------------------------------------------
-- 9) D_POLICY_QA · 政策问答留痕（D-12，PRD §5.2/§8.2）
--    id,question,answer_text,source_articles,confidence,user_feedback
-- -----------------------------------------------------------------------------
CREATE TABLE D_POLICY_QA (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ANSWERED'
                   CHECK (status IN ('ANSWERED','FALLBACK','FAILED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id          BIGINT       NOT NULL,                            -- 提问人 sys_user.id
  question         TEXT         NOT NULL,                            -- 问题原文
  answer_text      TEXT,                                             -- LLM 组织回答
  source_articles  JSONB        NOT NULL DEFAULT '[]',               -- RAG Top-5 条款 [{pack,article,ref,url}]
  confidence       NUMERIC(6,4),                                     -- 置信度 0-1（低于阈值回落人工）
  amount_related   BOOLEAN      NOT NULL DEFAULT FALSE,             -- 是否涉及金额/审批权限（标注"请与科研办确认"）
  hit_policy_pack_id BIGINT,                                         -- 命中的制度包快照 sys_policy_pack.id
  user_feedback    VARCHAR(16)  CHECK (user_feedback IS NULL OR user_feedback IN ('THUMBS_UP','THUMBS_DOWN','CORRECTED')),
  latency_ms       INT                                                -- 端到端耗时（<5s）
);
CREATE INDEX idx_qa_user ON D_POLICY_QA(tenant_id, user_id, created_at DESC);
COMMENT ON TABLE  D_POLICY_QA IS 'AI 政策问答留痕（D-12）：RAG 检索条款 + LLM 组织回答 + 出处链接 + 反馈回流评估集';
COMMENT ON COLUMN D_POLICY_QA.amount_related IS '涉及具体金额/审批权限时 TRUE，答案强制标注"请与科研办确认"（PRD §8.2 风险控制）';
COMMENT ON COLUMN D_POLICY_QA.status IS 'FALLBACK=置信度低于阈值兜底人工/未理解（PRD 2.4 人工兜底）';

-- -----------------------------------------------------------------------------
-- 10) D_EXPORT · 上级报送模板与导出记录（D-07，PRD §7.6，支撑上级报送）
--     code,name,template_scope,target_org,format(CSV/EXCEL/PDF/XML),schema_json,version
-- -----------------------------------------------------------------------------
CREATE TABLE D_EXPORT (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,                            -- 模板编码（EDU年报/CAST年报/CAS评价/省科技厅）
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列（模板属性）--------------------------------------------------------
  name             VARCHAR(128) NOT NULL,
  template_scope   VARCHAR(32)  NOT NULL
                   CHECK (template_scope IN ('ANNUAL_STAT','DISCIPLINE_EVAL','FUNDING_REPORT','Talent_STAT')), -- 报送范围/用途
  target_org       VARCHAR(128) NOT NULL,                            -- 报送对象（教育部/科技部/中科院/省科技厅）
  format           VARCHAR(16)  NOT NULL DEFAULT 'EXCEL'
                   CHECK (format IN ('CSV','EXCEL','PDF','XML')),     -- 导出/报文格式
  schema_json      JSONB        NOT NULL DEFAULT '{}',                -- 报送表格字段->数据源映射（免表：字段可直抽生成）
  metric_refs      JSONB        NOT NULL DEFAULT '[]',               -- 报送涉及指标 code（口径以 D_METRIC 为准）
  version          INT          NOT NULL DEFAULT 1,                  -- 模板版本（上级口径年度调整）
  prev_export_id   BIGINT       REFERENCES D_EXPORT(id),            -- 上一版本模板（同模块物理 FK）
  -- 业务列（导出记录，最近一次生成快照）------------------------------------
  last_generated_at TIMESTAMPTZ,                                     -- 最近生成时间
  last_generated_by BIGINT,                                          -- 最近生成人 sys_user.id
  last_output_url  VARCHAR(512),                                     -- 最近导出文件（对象存储，报送留痕）
  -- 治理字段
  legal_entity_id  BIGINT                                             -- NULL=总院合并报送；非空=分法人报送
);
CREATE UNIQUE INDEX uk_export_code_ver ON D_EXPORT(tenant_id, code, version) WHERE deleted = 0;
COMMENT ON TABLE  D_EXPORT IS '上级报送模板库与导出记录（D-07）：预置 4+ 报送模板，一键生成→审核→导出→报送留痕';
COMMENT ON COLUMN D_EXPORT.schema_json IS '报送表格字段映射，字段必须可从库直接抽取生成（免表，PRD 2.15 / ../TECH_ARCHITECTURE §四）';
COMMENT ON COLUMN D_EXPORT.format IS '导出格式 token，报送报文支持 CSV/EXCEL/PDF/XML';


-- ↑ 该文件后半段（第二部分 · ClickHouse OLAP）非 PostgreSQL 目标，已剔除


-- ===== 09-采购与合同管理-G.ddl.sql =====
-- =============================================================================
-- 09-采购与合同管理-G.ddl.sql · 模块 G（Procurement & Contract）建表脚本
-- 版本 v1.1 · 2026-10-13
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4，达梦部署时按此替换）
-- 上游：design/README.md §2 数据库约定 / §4 状态 token / §5 共享实体；PRD/09-采购与合同管理.md §5.1
-- 覆盖表：G_REQUISITION · G_SUPPLIER · G_BID · G_CONTRACT · G_CONTRACT_PAYMENT ·
--         G_ORDER · G_OUTSOURCE
--
-- 【信创达梦差异注记（本模块专用，顶部统一声明）】
--   1) 自增主键  PG: BIGINT GENERATED ALWAYS AS IDENTITY  →  达梦: BIGINT IDENTITY(1,1)
--   2) 时间戳    PG: TIMESTAMPTZ                          →  达梦: TIMESTAMP WITH TIME ZONE
--   3) 布尔      PG: BOOLEAN                              →  达梦: SMALLINT（0/1）；本模块 blacklist/outsource_flag
--                直接以 SMALLINT(0/1) 落地，两端一致
--   4) JSONB     PG: JSONB（qualification_json/bids_json/pay_terms_json/deliverables_json/
--                ai_parse_json/ai_risk_json 等）
--                →  达梦: CLOB/VARCHAR 存 JSON 文本 + 应用层解析；表达式索引改应用层维护
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0
--                →  达梦: 以普通唯一索引 + (tenant_id,code,deleted) 复合键替代
--   6) CHECK(col IN(...)) 枚举  PG/达梦一致，保持 VARCHAR+CHECK（便于灰度扩值，不建原生 ENUM）
--   7) 全文/向量检索  PG: pg_trgm/tsvector/pgvector  →  达梦: 应用层 ES / Milvus 独立服务
--
-- 【金额/时间/半结构化】金额一律 NUMERIC(18,2)（元）；比例/进度/置信度 NUMERIC(6,4)；
--   时间 TIMESTAMPTZ（落库 UTC，展示 Asia/Shanghai）；纯日期 DATE；半结构化 JSONB。
-- 【治理三列】G 模块所有表携带 legal_entity_id / security_level / policy_pack_id
--   （design/README.md §2.1 v1.1；PRD 2.12/2.13/2.10）。
-- 【跨模块引用】E_PROJECT(project_id) / F_SUBJECT(budget_subject_code) / F_EXPENSE(expense_id) /
--   E_ARCHIVE_CHECKLIST(archive_checklist_id) / sys_policy_pack(policy_pack_id) / sys_user(*_id 人员)
--   只存对方主键 id，不建物理外键（微服务库隔离，PRD §5 共享实体登记表）。
--   同模块内物理外键：G_BID/G_CONTRACT/G_ORDER→G_REQUISITION；G_CONTRACT/G_ORDER/G_OUTSOURCE→G_SUPPLIER；
--   G_CONTRACT_PAYMENT/G_OUTSOURCE→G_CONTRACT 等（见下 REFERENCES）。
-- 【单号前缀（PRD 2.11 注册表，取自统一编号中心 svc-numbering，作废不回收·重试幂等）】
--   采购申请 REQ · 采购订单 ORD · 供应商 SUP · 外协单位 SOSC · 合同 CON · 外协/分包合同 OSC。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- G-01/G-02/G-03 · G_REQUISITION 采购申请（预算冻结 · 采购方式判定，携带制度包快照）
-- -----------------------------------------------------------------------------
CREATE TABLE G_REQUISITION (
  -- 通用列（design/README.md §2.1）
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- REQ-年-序（统一编号中心分配）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,                      -- 主责法人（PRD 2.12）
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密采购密级（PRD 2.13）
  policy_pack_id    BIGINT,                                     -- 采购方式判定所依据制度包快照（复算，PRD 2.10）
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','SUBMITTED','WAY_DECIDED','BIDDING','ORDERED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  project_id        BIGINT       NOT NULL,                      -- 逻辑引用 E_PROJECT(id)→02 E
  applicant_id      BIGINT       NOT NULL,                      -- 申请人 user_id（逻辑引用 sys_user）
  category          VARCHAR(16)  NOT NULL
                    CHECK (category IN ('设备','材料','试剂耗材','服务','软件','外协')),  -- 采购标的类别
  item_name         VARCHAR(256) NOT NULL,                      -- 采购标的名称
  spec              TEXT,                                       -- 技术参数/规格要求
  est_amount        NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 预算（估算）金额，触发方式判定
  budget_subject_code VARCHAR(64),                              -- 占用经费科目编码（逻辑引用 F_SUBJECT.subject_code→03 F）
  frozen_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 冻结金额（联动 F-10，超预算拦截、不允许负余额）
  purchase_way      VARCHAR(16)
                    CHECK (purchase_way IN ('公开招标','邀请招标','竞争性谈判','单一来源','询价','自行采购')),  -- G-03 判定结果
  way_basis_rule_id BIGINT                                      -- 命中的制度规则号（逻辑引用 sys_rule_hit，可解释）
);
CREATE UNIQUE INDEX uk_req_code ON G_REQUISITION(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_req_tenant_entity_status ON G_REQUISITION(tenant_id, legal_entity_id, status);
CREATE INDEX idx_req_project ON G_REQUISITION(project_id);
CREATE INDEX idx_req_applicant ON G_REQUISITION(tenant_id, applicant_id, status);
CREATE INDEX idx_req_security ON G_REQUISITION(tenant_id, security_level, status);
COMMENT ON TABLE  G_REQUISITION IS '采购申请（G-01/G-02/G-03）：预算冻结 + 采购方式判定结果落库，携带制度包快照供复算';
COMMENT ON COLUMN G_REQUISITION.category           IS '采购标的类别：设备/材料/试剂耗材/服务/软件/外协';
COMMENT ON COLUMN G_REQUISITION.frozen_amount      IS '提交时在对应经费科目冻结的额度，联动 F-10；驳回/废标释放';
COMMENT ON COLUMN G_REQUISITION.purchase_way       IS 'G-03 采购方式判定引擎输出（金额+经费性质+制度包），人不越权';
COMMENT ON COLUMN G_REQUISITION.way_basis_rule_id  IS '命中制度规则号，配合 policy_pack_id 使方式判定可解释、可复算';
COMMENT ON COLUMN G_REQUISITION.project_id         IS '逻辑引用 E_PROJECT(id)，跨模块只存 id，一致性走事件';
COMMENT ON COLUMN G_REQUISITION.budget_subject_code IS '逻辑引用 F_SUBJECT 科目编码，占用/冻结定位到科目';
COMMENT ON COLUMN G_REQUISITION.security_level     IS '涉密采购密级，参与涉密域读写过滤（PRD 2.13）';


-- -----------------------------------------------------------------------------
-- G-04/G-09 · G_SUPPLIER 供应商 / 外协单位库（资质证照、分级、黑名单、入库状态）
-- -----------------------------------------------------------------------------
CREATE TABLE G_SUPPLIER (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- SUP-年-序=供应商 / SOSC-年-序=外协单位（前缀随 type 分流）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,                      -- 入库法人
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密供应商资质密级
  policy_pack_id    BIGINT,                                     -- 资质审查规则制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','IN_LIBRARY','REJECTED','EXPIRED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  name              VARCHAR(256) NOT NULL,                      -- 供应商/外协单位名称
  credit_code       VARCHAR(64),                                -- 统一社会信用代码（唯一去重键）
  type              VARCHAR(16)  NOT NULL DEFAULT '供应商'
                    CHECK (type IN ('供应商','外协单位','服务商')),  -- 主体类型（决定 code 前缀 SUP/SOSC）
  qualification_json JSONB,                                     -- 资质证照 ISO/CNAS/保密资质等 [{cert,no,issue,expire,url}]
  grade             VARCHAR(2)   NOT NULL DEFAULT 'C'
                    CHECK (grade IN ('A','B','C','D')),          -- 分级（A 优 ~ D 差）
  blacklist         SMALLINT     NOT NULL DEFAULT 0
                    CHECK (blacklist IN (0,1)),                 -- 是否黑名单（1=硬拦截，禁止参与任何新合同）
  review_status     VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (review_status IN ('PENDING','IN_LIBRARY','REJECTED','EXPIRED')),  -- 资质入库审查状态（对齐 status）
  expire_date       DATE                                         -- 资质到期日（到期自动置 EXPIRED，禁止新合同引用）
);
CREATE UNIQUE INDEX uk_sup_code ON G_SUPPLIER(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_sup_credit ON G_SUPPLIER(tenant_id, credit_code) WHERE deleted = 0 AND credit_code IS NOT NULL;
CREATE INDEX idx_sup_tenant_entity_status ON G_SUPPLIER(tenant_id, legal_entity_id, status);
CREATE INDEX idx_sup_type_status ON G_SUPPLIER(tenant_id, type, review_status);
CREATE INDEX idx_sup_blacklist ON G_SUPPLIER(tenant_id, blacklist);
CREATE INDEX idx_sup_expire ON G_SUPPLIER(expire_date);
COMMENT ON TABLE  G_SUPPLIER IS '供应商/外协单位库（G-04/G-09）：资质入库、分级、黑名单硬拦截、到期禁止新合同';
COMMENT ON COLUMN G_SUPPLIER.code            IS '单号前缀随 type 分流：供应商 SUP-年-序；外协单位 SOSC-年-序';
COMMENT ON COLUMN G_SUPPLIER.qualification_json IS '资质证照 JSONB：每项含证书号/机关/有效期/附件；供 svc-policy 校验到期与齐全度';
COMMENT ON COLUMN G_SUPPLIER.blacklist       IS '黑名单标记（0/1）；命中即禁止参与新合同/新招标，历史只读';
COMMENT ON COLUMN G_SUPPLIER.review_status   IS '资质入库状态，与 status 同源；到期任务自动置 EXPIRED';
COMMENT ON COLUMN G_SUPPLIER.expire_date     IS '最近一项资质到期日，过期后禁止被新合同引用（PRD 11）';


-- -----------------------------------------------------------------------------
-- G-05 · G_BID 招标/比价/询价记录（报价、评标、定标、公示、节资）
-- -----------------------------------------------------------------------------
CREATE TABLE G_BID (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- 招标编号（沿用 REQ 关联，可扩展独立前缀）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 评标办法/公示规则制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'PUBLICIZING'
                    CHECK (status IN ('PUBLICIZING','AWARDED','CHALLENGE')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  requisition_id    BIGINT       NOT NULL REFERENCES G_REQUISITION(id),  -- 同模块物理外键（1:0..1）
  method            VARCHAR(16)  NOT NULL
                    CHECK (method IN ('公开招标','邀请招标','竞争性谈判','单一来源','询价')),  -- 招标方式（源自申请判定）
  publish_at        TIMESTAMPTZ,                                -- 发标时间
  bid_open_at       TIMESTAMPTZ,                                -- 开标时间
  award_at          TIMESTAMPTZ,                                -- 定标时间
  bids_json         JSONB,                                      -- 报价/评标明细 [{supplier_id,price,score,tech_eval,commercial_eval}]
  winner_supplier_id BIGINT      REFERENCES G_SUPPLIER(id),     -- 中标供应商（同模块物理外键）
  saving_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 节资金额（预算-中标价）
  winner_reason     TEXT,                                       -- 定标理由（审计可复算）
  publicity_status  VARCHAR(16)  NOT NULL DEFAULT 'PUBLICIZING'
                    CHECK (publicity_status IN ('PUBLICIZING','AWARDED','CHALLENGE'))  -- 公示状态（对齐 status）
);
CREATE UNIQUE INDEX uk_bid_code ON G_BID(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_bid_tenant_entity_status ON G_BID(tenant_id, legal_entity_id, status);
CREATE INDEX idx_bid_requisition ON G_BID(requisition_id);
CREATE INDEX idx_bid_winner ON G_BID(winner_supplier_id);
CREATE INDEX idx_bid_security ON G_BID(tenant_id, security_level, status);
COMMENT ON TABLE  G_BID IS '招标/比价/询价记录（G-05）：发标/开标/定标、报价评标明细、公示与质疑、节资统计';
COMMENT ON COLUMN G_BID.bids_json        IS '各家报价与评分明细（JSONB 数组），审计可逐笔复算评标过程';
COMMENT ON COLUMN G_BID.winner_supplier_id IS '中标供应商 id（同模块物理外键→G_SUPPLIER）';
COMMENT ON COLUMN G_BID.saving_amount    IS '节资金额=预算金额-中标价，供 G-16 看板节资率统计';
COMMENT ON COLUMN G_BID.publicity_status IS '公示状态：PUBLICIZING=公示中/AWARDED=已定标/CHALLENGE=质疑处理（对齐 status）';


-- -----------------------------------------------------------------------------
-- G-07/G-10/G-11/G-13/G-14 · G_CONTRACT 合同（统一：采购/外协分包/横向委托/技术服务）
-- -----------------------------------------------------------------------------
CREATE TABLE G_CONTRACT (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- CON-年-序=采购/技术服务/横向 / OSC-年-序=外协分包
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,                      -- 主责法人；参与法人只读（PRD 2.12/§11）
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密合同仅涉密网（PRD 2.13）
  policy_pack_id    BIGINT,                                     -- 合同评审/条款红线判定制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','REVIEW','TO_SIGN','ACTIVE','AMENDING','SETTLING','ARCHIVED','TERMINATED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  requisition_id    BIGINT      REFERENCES G_REQUISITION(id),   -- 关联采购申请（可空·横向委托无前置申请）
  contract_type     VARCHAR(16) NOT NULL
                    CHECK (contract_type IN ('采购','外协分包','横向委托','技术服务','其他')),  -- 合同类型（外协分包→派生 G_OUTSOURCE）
  project_id        BIGINT,                                     -- 逻辑引用 E_PROJECT(id)→02 E
  supplier_id       BIGINT      REFERENCES G_SUPPLIER(id),      -- 相对方供应商/外协单位（同模块物理外键；须 IN_LIBRARY 且非黑名单）
  party_a           VARCHAR(256),                               -- 甲方
  party_b           VARCHAR(256),                               -- 乙方
  amount            NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 合同金额（付款累计上限基准，含变更）
  currency          VARCHAR(8)  NOT NULL DEFAULT 'CNY',         -- 币种
  pay_terms_json    JSONB,                                      -- 付款条款 [{phase:预付/到货/验收/质保,ratio,trigger}]
  deliverables_json JSONB,                                      -- 交付物清单
  sign_date         DATE,                                       -- 签署日期
  start_date        DATE,                                       -- 履行开始
  end_date          DATE,                                       -- 履行结束
  sign_method       VARCHAR(8)  CHECK (sign_method IN ('电子签','异地','纸质')),  -- 签署方式（联动 P-12；CA 不可用降级纸质）
  archive_checklist_id BIGINT,                                   -- 逻辑引用 E_ARCHIVE_CHECKLIST(id)→02 E（归档联动 E-15）
  ai_parse_json     JSONB,                                      -- G-13 AI 解析结果（逐字段来源+置信度，人工确认后落字段）
  ai_risk_json      JSONB                                       -- G-14 AI 风险提示（条款/风险类型/等级/建议/命中规则号）
);
CREATE UNIQUE INDEX uk_con_code ON G_CONTRACT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_con_tenant_entity_status ON G_CONTRACT(tenant_id, legal_entity_id, status);
CREATE INDEX idx_con_project ON G_CONTRACT(project_id);
CREATE INDEX idx_con_supplier ON G_CONTRACT(supplier_id);
CREATE INDEX idx_con_requisition ON G_CONTRACT(requisition_id);
CREATE INDEX idx_con_type_status ON G_CONTRACT(tenant_id, contract_type, status);
CREATE INDEX idx_con_security ON G_CONTRACT(tenant_id, security_level, status);
COMMENT ON TABLE  G_CONTRACT IS '合同主表（G-07/G-10/G-11/G-13/G-14）：统一四类合同全生命周期 + AI 解析/风险';
COMMENT ON COLUMN G_CONTRACT.code             IS '单号前缀：CON=采购/技术服务/横向委托；OSC=外协分包合同';
COMMENT ON COLUMN G_CONTRACT.contract_type    IS '合同类型；外协分包派生 G_OUTSOURCE 台账，横向委托可无 requisition_id';
COMMENT ON COLUMN G_CONTRACT.supplier_id      IS '同模块物理外键→G_SUPPLIER；入库(IN_LIBRARY)且非黑名单方可签约';
COMMENT ON COLUMN G_CONTRACT.amount           IS '合同金额=付款计划累计硬上限（含变更 AMENDING 后调增），超出拦截';
COMMENT ON COLUMN G_CONTRACT.pay_terms_json   IS '付款条款数组，G-08 据此生成付款计划；关键项须人工确认后方生效';
COMMENT ON COLUMN G_CONTRACT.archive_checklist_id IS '逻辑引用 E_ARCHIVE_CHECKLIST(id)，归档联动 E-15';
COMMENT ON COLUMN G_CONTRACT.ai_parse_json    IS 'G-13 LLM 解析结果，附字段级置信度与来源；<0.85 标黄强制人工复核';
COMMENT ON COLUMN G_CONTRACT.ai_risk_json     IS 'G-14 风险卡片列表；高风险必须法务人工签意见，AI 不得单独放行';
COMMENT ON COLUMN G_CONTRACT.security_level   IS '涉密合同密级≥SECRET 仅涉密网可见，非涉密域访问拒绝并审计告警';


-- -----------------------------------------------------------------------------
-- G-08/G-09 · G_CONTRACT_PAYMENT 付款计划与执行（关联 F 报销/凭证、外拨标记）
-- -----------------------------------------------------------------------------
CREATE TABLE G_CONTRACT_PAYMENT (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- 付款计划编号（沿用合同号+阶段序）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 付款条款合规判定制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'PLANNED'
                    CHECK (status IN ('PLANNED','DUE','PAID','VOUCHER_SYNCED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  contract_id       BIGINT       NOT NULL REFERENCES G_CONTRACT(id),  -- 同模块物理外键（1:N）
  phase             VARCHAR(8)   NOT NULL
                    CHECK (phase IN ('预付','到货','验收','质保','进度','尾款')),  -- 付款阶段
  plan_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 计划付款金额
  plan_date         DATE,                                       -- 计划付款日期
  paid_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 实付金额（回调回填）
  pay_date          DATE,                                       -- 实付日期
  expense_id        BIGINT,                                     -- 逻辑引用 F_EXPENSE(id)→03 F（付款/报销单）
  voucher_status    VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (voucher_status IN ('PENDING','SUCCESS','FAILED','MANUAL')),  -- 凭证同步状态（→F-11）
  invoice_url       VARCHAR(512),                               -- 发票/收据附件（对象存储）
  outsource_flag    SMALLINT     NOT NULL DEFAULT 0
                    CHECK (outsource_flag IN (0,1))             -- 是否外拨（1=联动 F-22 外拨经费）
);
CREATE UNIQUE INDEX uk_pay_code ON G_CONTRACT_PAYMENT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_pay_tenant_entity_status ON G_CONTRACT_PAYMENT(tenant_id, legal_entity_id, status);
CREATE INDEX idx_pay_contract ON G_CONTRACT_PAYMENT(contract_id);
CREATE INDEX idx_pay_expense ON G_CONTRACT_PAYMENT(expense_id);
CREATE INDEX idx_pay_outsource ON G_CONTRACT_PAYMENT(tenant_id, outsource_flag, status);
COMMENT ON TABLE  G_CONTRACT_PAYMENT IS '付款计划与执行（G-08/G-09）：条款驱动生成计划、累计≤合同额硬拦截、外拨标记';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.plan_amount   IS '各阶段计划金额之和累计不得超过 G_CONTRACT.amount（含变更）';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.expense_id    IS '逻辑引用 F_EXPENSE(id)，付款执行回调落 F，凭证经 F-11 同步';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.voucher_status IS '凭证同步状态：PENDING/SUCCESS/FAILED/MANUAL（转人工，→F-11）';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.outsource_flag IS '外拨标记，=1 时联动 F-22 外拨经费并受合同剩余额约束';


-- -----------------------------------------------------------------------------
-- G-06/G-17 · G_ORDER 采购订单与到货验收（到货一键转资产/耗材）
-- -----------------------------------------------------------------------------
CREATE TABLE G_ORDER (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- ORD-年-序（统一编号中心分配）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 订单/验收规则制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','CONFIRMED','EXECUTING','COMPLETED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  requisition_id    BIGINT       NOT NULL REFERENCES G_REQUISITION(id),  -- 同模块物理外键
  contract_id       BIGINT      REFERENCES G_CONTRACT(id),      -- 可空·限额内自行采购无合同
  supplier_id       BIGINT       NOT NULL REFERENCES G_SUPPLIER(id),     -- 同模块物理外键
  order_amount      NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 订单金额
  currency          VARCHAR(8)  NOT NULL DEFAULT 'CNY',         -- 币种
  order_date        DATE,                                       -- 下单日期
  expect_delivery_date DATE,                                    -- 预计到货日期
  delivery_status   VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (delivery_status IN ('PENDING','SHIPPED','ARRIVED','ACCEPTED','REJECTED')),  -- 到货/验收状态机
  acceptance_by     BIGINT,                                     -- 验收人 user_id
  acceptance_date   DATE,                                       -- 验收日期
  converted_asset   SMALLINT     NOT NULL DEFAULT 0
                    CHECK (converted_asset IN (0,1))            -- 到货转资产标记（→ G-17 / 模块10 A_ASSET·A_CONSUMABLE）
);
CREATE UNIQUE INDEX uk_ord_code ON G_ORDER(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_ord_tenant_entity_status ON G_ORDER(tenant_id, legal_entity_id, status);
CREATE INDEX idx_ord_requisition ON G_ORDER(requisition_id);
CREATE INDEX idx_ord_contract ON G_ORDER(contract_id);
CREATE INDEX idx_ord_supplier ON G_ORDER(supplier_id);
CREATE INDEX idx_ord_delivery ON G_ORDER(tenant_id, delivery_status);
CREATE INDEX idx_ord_security ON G_ORDER(tenant_id, security_level, status);
COMMENT ON TABLE  G_ORDER IS '采购订单（G-06/G-17）：下单→到货→验收状态机，验收通过一键转资产/耗材';
COMMENT ON COLUMN G_ORDER.contract_id     IS '逻辑可空：限额内自行采购（无合同）直接由 requisition_id 下单';
COMMENT ON COLUMN G_ORDER.delivery_status IS '到货状态机：PENDING=待发货/SHIPPED=在途/ARRIVED=到货/ACCEPTED=验收合格/REJECTED=拒收';
COMMENT ON COLUMN G_ORDER.converted_asset IS '到货转资产标记：ACCEPTED 后置 1 表示已推送模块 10 生成 A_ASSET/A_CONSUMABLE，防重复录入';


-- -----------------------------------------------------------------------------
-- G-09 · G_OUTSOURCE 外协台账（从属于 contract_type=外协分包 的合同，联动 F-22 外拨）
-- -----------------------------------------------------------------------------
CREATE TABLE G_OUTSOURCE (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- 外协台账编号（沿用 OSC 合同号）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 外协合规（禁止整体转包/外拨限额）制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'EXECUTING'
                    CHECK (status IN ('EXECUTING','SETTLING','COMPLETED','TERMINATED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）——从属 G_CONTRACT(contract_type=外协分包)，1:1
  contract_id       BIGINT       NOT NULL REFERENCES G_CONTRACT(id),         -- 同模块物理外键（1:1 外协合同）
  outsource_unit_id BIGINT       NOT NULL REFERENCES G_SUPPLIER(id),         -- 外协单位（type=外协单位）同模块物理外键
  scope             TEXT,                                       -- 外协任务范围
  outsource_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 外拨总额（受合同额约束）
  disbursed_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 已拨金额（联动 F-22 累计）
  progress          NUMERIC(6,4)  NOT NULL DEFAULT 0,           -- 外协进度（0-1）
  deliverable_check VARCHAR(16)   NOT NULL DEFAULT 'PENDING'
                    CHECK (deliverable_check IN ('PENDING','PASSED','FAILED')),  -- 成果验收
  compliance_note   TEXT                                         -- 合规说明（不得整体转包、单一来源需说明等）
);
CREATE UNIQUE INDEX uk_outs_code ON G_OUTSOURCE(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_outs_contract ON G_OUTSOURCE(contract_id) WHERE deleted = 0;  -- 与外协合同 1:1
CREATE INDEX idx_outs_tenant_entity_status ON G_OUTSOURCE(tenant_id, legal_entity_id, status);
CREATE INDEX idx_outs_unit ON G_OUTSOURCE(outsource_unit_id);
CREATE INDEX idx_outs_security ON G_OUTSOURCE(tenant_id, security_level, status);
COMMENT ON TABLE  G_OUTSOURCE IS '外协台账（G-09）：从属于外协分包合同(1:1)，禁止整体转包、外拨额度联动 F-22 剩余额拦截';
COMMENT ON COLUMN G_OUTSOURCE.contract_id      IS '同模块物理外键→G_CONTRACT；仅 contract_type=外协分包 的合同派生，1:1';
COMMENT ON COLUMN G_OUTSOURCE.outsource_unit_id IS '外协单位（同模块物理外键→G_SUPPLIER，须 type=外协单位 且入库非黑名单）';
COMMENT ON COLUMN G_OUTSOURCE.disbursed_amount IS '已拨累计；本次外拨 > (outsource_amount - disbursed_amount) 即硬拦截（F-22）';
COMMENT ON COLUMN G_OUTSOURCE.compliance_note  IS '整体转包禁用/单一来源说明等合规校验记录，命中规则升级审批';


-- =============================================================================
-- 备注：
--   1) 单号前缀 REQ/ORD/SUP/SOSC/CON/OSC 已在 00-common.sql `seq_prefix_registry` 登记（owner=G），
--      业务取号一律走 svc-numbering，作废不回收、重试幂等（PRD 2.11）。
--   2) 跨模块引用（project_id / budget_subject_code / expense_id / archive_checklist_id /
--      policy_pack_id / applicant_id 等人员）不建物理外键，仅存对方主键 id；
--      一致性走 Kafka 事件 + Saga（TECH_ARCH §八）。
--   3) G 模块全部表携带治理三列 legal_entity_id / security_level / policy_pack_id（PRD 2.12/2.13/2.10）；
--      方式判定/合同红线/外拨限额均落 policy_pack_id 快照供复算。
--   4) 达梦部署：JSONB→CLOB + 应用解析；BOOLEAN→SMALLINT(0/1)（本模块 blacklist/outsource_flag/
--      converted_asset 已用 SMALLINT）；部分唯一索引以 (tenant_id,code,deleted) 普通唯一索引替代；
--      TIMESTAMPTZ→TIMESTAMP WITH TIME ZONE。
-- =============================================================================


-- ===== 10-资产与耗材管理-A.ddl.sql =====
-- =============================================================================
-- 10-资产与耗材管理-A.ddl.sql · 模块 A（Asset & Consumable）建表脚本
-- 版本 v1.1 · 2026-10-13
-- 方言：PostgreSQL 15（默认）
-- 上游：design/README.md §2/§4/§5；PRD/10-资产与耗材管理.md §5.1
-- 单号前缀：资产卡 AST、处置单 DSP（见 00-common.sql seq_prefix_registry，per_entity=TRUE 按法人分号段）
--
-- ┌─ 信创达梦差异注记（design/README.md §2.4，达梦部署时按此替换）──────────────┐
-- │ 自增主键  GENERATED ALWAYS AS IDENTITY → IDENTITY(1,1)                      │
-- │ 时间戳    TIMESTAMPTZ → TIMESTAMP WITH TIME ZONE                            │
-- │ 布尔      BOOLEAN → SMALLINT（0/1）；本脚本 share_flag/open_flag/is_hazard   │
-- │           /posted 达梦下改用 SMALLINT CHECK (0,1)                            │
-- │ JSON      JSONB → CLOB/VARCHAR 存 JSON 文本 + 应用层解析                      │
-- │ 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0                          │
-- │           → 达梦用普通唯一索引 + (tenant_id,code,deleted) 复合键替代          │
-- │ 枚举      统一 VARCHAR + CHECK (IN (...))，不用原生 ENUM，便于灰度扩值        │
-- │ 可配枚举  asset_type/depr_method/source_type/category/hazard_level/method     │
-- │           取值以 sys_dict 为准（PRD 2.8 禁止硬编码），CHECK 仅为基线守卫        │
-- └────────────────────────────────────────────────────────────────────────────┘
--
-- 治理列：A 模块所有业务表均携带 legal_entity_id / security_level（v1.1，README §2.1）；
--         折旧/资产表 A_ASSET / A_DEPRECIATION 另携带 policy_pack_id（折旧政策快照，可复算）。
-- 外键：同模块物理外键 REFERENCES；跨模块（E_PROJECT/F_EXPENSE/G_CONTRACT/sys_policy_pack）
--       仅以 *_id 逻辑外键注释表达，不建物理外键（微服务库隔离，一致性走事件，README §2.3/§3.1）。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) A_ASSET 资产卡（固定资产 / 无形资产台账；单号 AST-年-序）
-- -----------------------------------------------------------------------------
CREATE TABLE A_ASSET (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- 资产编号 AST-{yyyy}-{seq6}（统一编号中心，按法人分号段）
  tenant_id       BIGINT       NOT NULL,              -- 多租户隔离键（总院法人边界）
  legal_entity_id BIGINT       NOT NULL,              -- 法人细分（PRD 2.12；主责法人建卡）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密资产（PRD 2.13）
  policy_pack_id  BIGINT,                             -- 命中折旧政策制度包快照（逻辑引用 sys_policy_pack.id，可复算）

  asset_type      VARCHAR(16)  NOT NULL
                  CHECK (asset_type IN ('FIXED','INTANGIBLE')),   -- 固定资产/无形资产（走字典 asset_type）
  category_code   VARCHAR(64)  NOT NULL,              -- 资产分类字典编码（逻辑引用 sys_dict_item：asset_category 树）
  name            VARCHAR(256) NOT NULL,              -- 资产名称
  brand           VARCHAR(128),                        -- 品牌
  model           VARCHAR(128),                        -- 型号
  serial_no       VARCHAR(128),                        -- 出厂序列号（一物一码，A-04 条码/RFID 关联键）

  value           NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 入账原值（元）
  purchase_date   DATE,                               -- 购置日期
  in_date         DATE,                               -- 入账/启用日期
  depr_method     VARCHAR(16)  NOT NULL DEFAULT 'STRAIGHT_LINE'
                  CHECK (depr_method IN ('STRAIGHT_LINE','WORKLOAD','ACCELERATED','NONE')), -- 直线/工作量/加速/不计提
  depr_years      SMALLINT     CHECK (depr_years IS NULL OR depr_years BETWEEN 0 AND 100),   -- 折旧年限
  depr_accum      NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 累计折旧
  net_value       NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 净值 = value - depr_accum（生成/应用维护）

  custodian_id    BIGINT,                             -- 责任人 user_id（逻辑引用 sys_user.id）
  dept_id         BIGINT,                             -- 存放部门（逻辑引用 sys_org.id）
  location        VARCHAR(256),                       -- 存放地点
  source_type     VARCHAR(16)  NOT NULL DEFAULT 'PURCHASE'
                  CHECK (source_type IN ('PURCHASE','SELF_DEV','DONATION','TRANSFER')), -- 采购/自研/捐赠/调拨
  source_ref      BIGINT,                             -- 来源引用（跨模块逻辑引用 G_CONTRACT.id / 订单/验收单）
  project_id      BIGINT,                             -- 形成/占用项目，成本归属（跨模块逻辑引用 E_PROJECT.id）

  usage_rate      NUMERIC(5,4),                        -- 使用率 0~1（大型仪器共享 A-13）
  share_flag      BOOLEAN      NOT NULL DEFAULT FALSE, -- 是否纳入共享台账
  open_flag       BOOLEAN      NOT NULL DEFAULT FALSE, -- 是否对外开放共享

  status          VARCHAR(32)  NOT NULL DEFAULT 'PENDING_RECEIPT'
                  CHECK (status IN ('PENDING_RECEIPT','IN_USE','IDLE','UNDER_MAINT','TRANSFERRING','PENDING_DISPOSE','DISPOSED')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_asset_code     ON A_ASSET(tenant_id, code) WHERE deleted = 0;              -- 部分唯一（软删后编号不复用）
CREATE INDEX        idx_asset_tenant ON A_ASSET(tenant_id, legal_entity_id, status);              -- 查询主路径
CREATE INDEX        idx_asset_proj   ON A_ASSET(project_id);                                       -- 成本归属
CREATE INDEX        idx_asset_custd  ON A_ASSET(custodian_id);                                     -- 名下资产
CREATE INDEX        idx_asset_dept   ON A_ASSET(dept_id);                                          -- 存放部门
CREATE INDEX        idx_asset_serial ON A_ASSET(tenant_id, serial_no);                            -- 一物一码扫码/盘点比对
CREATE INDEX        idx_asset_cat    ON A_ASSET(tenant_id, category_code);                        -- 分类统计/重复购置识别

COMMENT ON TABLE  A_ASSET                 IS '资产卡台账（固定/无形资产，单号 AST-年-序），资产全生命周期主表';
COMMENT ON COLUMN A_ASSET.code            IS '资产编号，AST-{yyyy}-{seq6}，统一编号中心按法人分号段分配';
COMMENT ON COLUMN A_ASSET.legal_entity_id IS '主责法人；跨法人在使用法人登记领用（README 2.12）';
COMMENT ON COLUMN A_ASSET.security_level  IS '密级；>=SECRET 为涉密资产，仅涉密网登记与查看（联动 11）';
COMMENT ON COLUMN A_ASSET.policy_pack_id  IS '命中的折旧政策制度包快照 id，用于按月折旧复算与审计';
COMMENT ON COLUMN A_ASSET.asset_type      IS 'FIXED=固定资产 / INTANGIBLE=无形资产';
COMMENT ON COLUMN A_ASSET.category_code   IS '资产分类字典编码（sys_dict_item:asset_category，树形，可扩）';
COMMENT ON COLUMN A_ASSET.value           IS '入账原值（元，NUMERIC(18,2)）；缺失则整卡置 PENDING_RECEIPT 待确认';
COMMENT ON COLUMN A_ASSET.depr_method     IS '折旧方法：STRAIGHT_LINE 直线/WORKLOAD 工作量/ACCELERATED 加速/NONE 不计提';
COMMENT ON COLUMN A_ASSET.depr_accum      IS '累计折旧，由 A_DEPRECIATION 按月汇总回写';
COMMENT ON COLUMN A_ASSET.net_value       IS '净值 = value - depr_accum';
COMMENT ON COLUMN A_ASSET.usage_rate      IS '使用率(0~1)，来自 A-13 机时登记，供闲置/重复购置看板';
COMMENT ON COLUMN A_ASSET.source_ref      IS '来源单据引用（跨模块逻辑外键：G_CONTRACT/验收单），不建物理外键';
COMMENT ON COLUMN A_ASSET.project_id      IS '形成/占用项目（跨模块逻辑外键 E_PROJECT.id）';
COMMENT ON COLUMN A_ASSET.status          IS 'PENDING_RECEIPT 待验收/IN_USE 在用/IDLE 闲置/UNDER_MAINT 维修/TRANSFERRING 调拨中/PENDING_DISPOSE 待处置/DISPOSED 已处置';


-- -----------------------------------------------------------------------------
-- 2) A_CONSUMABLE 耗材/试剂库存（批次+效期+危化；sku 为业务主键）
-- -----------------------------------------------------------------------------
CREATE TABLE A_CONSUMABLE (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- 库存记录编号（内部编号中心）
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT       NOT NULL,
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),

  sku             VARCHAR(64)  NOT NULL,              -- 物料主编码（跨模块登记表被引列名 ref_sku）
  name            VARCHAR(256) NOT NULL,
  category        VARCHAR(32)  NOT NULL
                  CHECK (category IN ('REAGENT','CONSUMABLE','COMPONENT','OFFICE')), -- 试剂/耗材/元器件/办公（走字典 consumable_category）
  is_hazard       BOOLEAN      NOT NULL DEFAULT FALSE,-- 危化品标识（A-08）
  hazard_level    VARCHAR(16),                        -- 危化管理级别（走字典 hazard_level；管制类触发硬拦截）
  msds_url        VARCHAR(512),                       -- 安全技术说明书 MSDS 文档地址（对象存储）

  stock_qty       NUMERIC(18,3) NOT NULL DEFAULT 0,   -- 现存量（数量 NUMERIC(18,3)）
  unit            VARCHAR(16),                        -- 计量单位（瓶/kg/mL…）
  batch_no        VARCHAR(64),                        -- 批次号（效期/追溯/FIFO 依据）
  produce_date    DATE,                               -- 生产日期
  expire_date     DATE,                               -- 有效期至（效期预警 A-16）
  safe_stock      NUMERIC(18,3),                       -- 安全库存水位（规则引擎，低于则 LOW_STOCK）
  location        VARCHAR(256),                       -- 存放位置（危化专区双锁）
  custodian_id    BIGINT,                             -- 库管员 user_id（逻辑引用 sys_user.id）

  status          VARCHAR(32)  NOT NULL DEFAULT 'IN_STOCK'
                  CHECK (status IN ('IN_STOCK','LOW_STOCK','NEAR_EXPIRY','EXPIRED','STAGNANT')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_consumable_code ON A_CONSUMABLE(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_consumable_sku  ON A_CONSUMABLE(tenant_id, batch_no, sku) WHERE deleted = 0; -- 同租户同批次同 SKU 唯一库存记录
CREATE INDEX        idx_consumable_tenant ON A_CONSUMABLE(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_consumable_expiry ON A_CONSUMABLE(sku, expire_date);                         -- 效期扫描（临期/过期批处理）
CREATE INDEX        idx_consumable_hazard ON A_CONSUMABLE(tenant_id, is_hazard);                      -- 危化专区检索

COMMENT ON TABLE  A_CONSUMABLE             IS '耗材/试剂库存（批次+效期+危化），SKU 维度库存台账';
COMMENT ON COLUMN A_CONSUMABLE.sku         IS '物料主编码；A_STOCK_TXN.ref_sku 以 (tenant_id,batch_no,sku) 定位库存';
COMMENT ON COLUMN A_CONSUMABLE.is_hazard   IS '危化品：出库领用强制双人双锁+双人确认（A-08）';
COMMENT ON COLUMN A_CONSUMABLE.hazard_level IS '危化管理级别；管制类超额/单锁硬拦截并告警安全管理员';
COMMENT ON COLUMN A_CONSUMABLE.safe_stock  IS '安全库存水位，由规则引擎（制度包）配置，驱动 LOW_STOCK';
COMMENT ON COLUMN A_CONSUMABLE.expire_date IS '有效期；过期批次自动冻结不可领用，走危废/报废处置';
COMMENT ON COLUMN A_CONSUMABLE.status      IS 'IN_STOCK 在库/LOW_STOCK 低库存/NEAR_EXPIRY 临期/EXPIRED 过期/STAGNANT 呆滞';


-- -----------------------------------------------------------------------------
-- 3) A_STOCK_TXN 出入库/领用流水（不可篡改台账，记录余额快照）
-- -----------------------------------------------------------------------------
CREATE TABLE A_STOCK_TXN (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,             -- 流水编号（领用单等，内部编号中心）
  tenant_id        BIGINT       NOT NULL,
  legal_entity_id  BIGINT       NOT NULL,
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),

  type             VARCHAR(24)  NOT NULL
                   CHECK (type IN ('STOCK_IN','STOCK_OUT','REQUISITION','RETURN','RETURN_TO_STOCK','HAZARD_DISPOSE','COUNT_GAIN','COUNT_LOSS')),
                                                          -- 入库/出库/领用/归还/退库/危废处置/盘盈/盘亏（走字典 stock_txn_type）
  ref_asset_id     BIGINT,                              -- 资产流水：同模块物理外键 A_ASSET(id)
  ref_sku          VARCHAR(64),                          -- 耗材流水：定位 A_CONSUMABLE（逻辑引用 sku+batch_no）
  ref_batch_no     VARCHAR(64),                          -- 耗材批次（效期/FIFO 校验）
  qty              NUMERIC(18,3) NOT NULL,              -- 数量（正/负按方向由 type 决定）
  amount           NUMERIC(18,2),                       -- 金额（元）

  project_id       BIGINT,                              -- 领用归属项目（跨模块逻辑引用 E_PROJECT.id）
  operator_id      BIGINT       NOT NULL,               -- 经办/操作人 user_id
  double_confirm_by BIGINT,                             -- 危化第二确认人 user_id（A-08 双人双锁，管制类必填）
  related_expense_id BIGINT,                            -- 关联报销/经费（跨模块逻辑引用 F_EXPENSE.id）
  txn_time         TIMESTAMPTZ  NOT NULL DEFAULT now(), -- 发生时间
  balance_after    NUMERIC(18,3),                       -- 交易后余额快照（对账/追溯）
  fifo_exempt      BOOLEAN      NOT NULL DEFAULT FALSE, -- FIFO 违反授权豁免留痕（A-07/§11）

  status           VARCHAR(32)  NOT NULL DEFAULT 'ISSUED'
                   CHECK (status IN ('REQUESTED','DOUBLE_CONFIRM','ISSUED')),  -- 领用状态机 token（README §4）
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,

  CONSTRAINT fk_stocktxn_asset FOREIGN KEY (ref_asset_id) REFERENCES A_ASSET(id)
);
CREATE UNIQUE INDEX uk_stocktxn_code ON A_STOCK_TXN(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_stocktxn_tenant ON A_STOCK_TXN(tenant_id, legal_entity_id, status);
CREATE INDEX idx_stocktxn_asset  ON A_STOCK_TXN(ref_asset_id);
CREATE INDEX idx_stocktxn_sku    ON A_STOCK_TXN(tenant_id, ref_sku, ref_batch_no);
CREATE INDEX idx_stocktxn_proj   ON A_STOCK_TXN(project_id);
CREATE INDEX idx_stocktxn_time   ON A_STOCK_TXN(tenant_id, txn_time);

COMMENT ON TABLE  A_STOCK_TXN                IS '资产/耗材出入库与领用流水，账实一致与追溯的明细底稿';
COMMENT ON COLUMN A_STOCK_TXN.type           IS 'STOCK_IN 入库/STOCK_OUT 出库/REQUISITION 领用/RETURN 归还/RETURN_TO_STOCK 退库/HAZARD_DISPOSE 危废处置/COUNT_GAIN 盘盈/COUNT_LOSS 盘亏';
COMMENT ON COLUMN A_STOCK_TXN.ref_asset_id   IS '资产流水关联 A_ASSET.id（同模块物理外键）';
COMMENT ON COLUMN A_STOCK_TXN.ref_sku        IS '耗材流水关联 A_CONSUMABLE.sku（+ ref_batch_no 定位批次）';
COMMENT ON COLUMN A_STOCK_TXN.double_confirm_by IS '危化品第二确认人；管制类缺失则拒绝出库（双人双锁不可绕过）';
COMMENT ON COLUMN A_STOCK_TXN.related_expense_id IS '关联费用单据（跨模块逻辑外键 F_EXPENSE.id）';
COMMENT ON COLUMN A_STOCK_TXN.balance_after  IS '本次交易后库存余额快照';
COMMENT ON COLUMN A_STOCK_TXN.fifo_exempt    IS '未按 FIFO 出库时须授权豁免并留痕';
COMMENT ON COLUMN A_STOCK_TXN.status         IS '领用状态机：REQUESTED 领用申请/DOUBLE_CONFIRM 双人确认/ISSUED 已出库';


-- -----------------------------------------------------------------------------
-- 4) A_DEPRECIATION 折旧记录（按月计提；携带 policy_pack_id 复算；(asset_id,period) 唯一）
-- -----------------------------------------------------------------------------
CREATE TABLE A_DEPRECIATION (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,              -- 折旧记录编号
  tenant_id        BIGINT       NOT NULL,
  legal_entity_id  BIGINT       NOT NULL,
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id   BIGINT,                            -- 本次计提所用折旧政策快照（逻辑引用 sys_policy_pack.id，可复算）

  asset_id         BIGINT       NOT NULL,              -- 资产：同模块物理外键 A_ASSET(id)
  period           VARCHAR(7)   NOT NULL,              -- 计提期间 YYYY-MM
  depr_amount      NUMERIC(18,2) NOT NULL,             -- 本期折旧额（元）
  alloc_project_ids JSONB       NOT NULL DEFAULT '[]', -- 分摊明细 [{project_id,ratio,amount}]，成本分摊依据（A-12）
  voucher_id       BIGINT,                            -- 生成财务凭证（跨模块逻辑引用 F，凭证/F-11）
  posted           SMALLINT     NOT NULL DEFAULT 0     -- 是否已过账（0 未过账 / 1 已过账）
                   CHECK (posted IN (0,1)),

  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','CALCULATED','POSTED','REVERSED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,

  CONSTRAINT fk_depreciation_asset FOREIGN KEY (asset_id) REFERENCES A_ASSET(id),
  CONSTRAINT uk_depr_asset_period  UNIQUE (asset_id, period)   -- 同一资产同月只计提一次（幂等重算基础）
);
CREATE UNIQUE INDEX uk_depr_code   ON A_DEPRECIATION(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_depr_tenant ON A_DEPRECIATION(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_depr_period ON A_DEPRECIATION(tenant_id, period);

COMMENT ON TABLE  A_DEPRECIATION                IS '资产按月折旧计提记录，是财务凭证与项目成本分摊的数据源';
COMMENT ON COLUMN A_DEPRECIATION.policy_pack_id IS '计提所用折旧政策快照 id，支持审计复算（README 2.10）';
COMMENT ON COLUMN A_DEPRECIATION.period         IS '计提期间 YYYY-MM；与 asset_id 组合物理唯一，防止重复计提';
COMMENT ON COLUMN A_DEPRECIATION.alloc_project_ids IS '分摊到项目的明细 JSON 数组：[{project_id,ratio,amount}]；跨法人按使用比例拆分避免重复计入';
COMMENT ON COLUMN A_DEPRECIATION.voucher_id     IS '回调财务生成的凭证 id（跨模块逻辑外键 F-11）';
COMMENT ON COLUMN A_DEPRECIATION.posted         IS '过账标志（0/1，达梦 SMALLINT）';


-- -----------------------------------------------------------------------------
-- 5) A_DISPOSAL 资产处置单（报废/变卖/转让/销毁；单号 DSP-年-序）
-- -----------------------------------------------------------------------------
CREATE TABLE A_DISPOSAL (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,             -- 处置单号 DSP-{yyyy}-{seq6}（按法人分号段）
  tenant_id        BIGINT       NOT NULL,
  legal_entity_id  BIGINT       NOT NULL,
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),

  asset_id         BIGINT       NOT NULL,             -- 处置对象：同模块物理外键 A_ASSET(id)
  method           VARCHAR(16)  NOT NULL
                   CHECK (method IN ('SCRAP','SELL','TRANSFER','DESTROY')),  -- 报废/变卖/转让/销毁（走字典 disposal_method）
  appraisal        JSONB,                             -- 技术鉴定意见 {conclusion,expert_ids,attachment_ref,opinion}
  residual_value   NUMERIC(18,2),                     -- 残值（元）；>原值或<0 转财务复核（A-10）
  approval_chain   JSONB        NOT NULL DEFAULT '[]', -- 审批链 [{node,approver_id,action,at,comment}] 全程留痕
  related_voucher  BIGINT,                            -- 残值入账凭证（跨模块逻辑引用 F）
  archive_ref      VARCHAR(64),                       -- 归档引用（跨模块逻辑引用 E_PROJECT_DOC/档案 E-05）

  status           VARCHAR(32)  NOT NULL DEFAULT 'APPLIED'
                   CHECK (status IN ('APPLIED','APPRAISED','APPROVED','EXECUTING','BOOKED','ARCHIVED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,

  CONSTRAINT fk_disposal_asset FOREIGN KEY (asset_id) REFERENCES A_ASSET(id)
);
CREATE UNIQUE INDEX uk_disposal_code  ON A_DISPOSAL(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_disposal_tenant ON A_DISPOSAL(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_disposal_asset  ON A_DISPOSAL(asset_id);

COMMENT ON TABLE  A_DISPOSAL               IS '资产处置单（报废/变卖/转让/销毁），技术鉴定→审批→残值入账→归档（A-10）';
COMMENT ON COLUMN A_DISPOSAL.method        IS 'SCRAP 报废/SELL 变卖/TRANSFER 转让/DESTROY 销毁';
COMMENT ON COLUMN A_DISPOSAL.appraisal     IS '技术鉴定意见（JSONB）；进入 APPROVED 前须完成鉴定（APPRAISED）';
COMMENT ON COLUMN A_DISPOSAL.residual_value IS '残值；合理性校验：残值>资产原值或为负则转财务复核';
COMMENT ON COLUMN A_DISPOSAL.approval_chain IS '审批链留痕（JSONB 数组），支持审计追溯';
COMMENT ON COLUMN A_DISPOSAL.archive_ref   IS '档案封存引用（跨模块逻辑外键，E-05 项目归档/档案系统）';
COMMENT ON COLUMN A_DISPOSAL.status        IS 'APPLIED 申请/APPRAISED 鉴定/APPROVED 审批/EXECUTING 执行/BOOKED 入账/ARCHIVED 归档';


-- ===== 11-涉密管理与多法人治理-X.ddl.sql =====
-- =============================================================================
-- 11-涉密管理与多法人治理-X.ddl.sql · 模块 X（Confidentiality & Multi-legal-entity Governance）建表脚本
-- 版本 v1.1 · 日期 2026-10-13
-- 方言：PostgreSQL 15（默认）
-- 上游：design/README.md §2/§3/§4/§5；PRD/11-涉密管理与多法人治理.md §5.1；TECH_ARCHITECTURE.md §七/§八
--
-- ┌─ 一、与 00-common.sql 的表映射与复用说明（本模块【不重复建表】）────────────────┐
-- │  ① 法人主体 / 法人树（X_LEGAL_ENTITY，PRD 名）  ==>  已建 sys_legal_entity（common §1）  │
-- │     · sys_legal_entity 提供 code(LE-年-序)/name/credit_code/entity_type/short_code/       │
-- │       consolidated/status(ACTIVE|DEREGISTERED)/tenant_id；PRD 的 parent_id 法人树层级由     │
-- │       sys_org(parent_id,org_type=TOTAL_INSTITUTE|BRANCH_INSTITUTE) 承载，法人↔组织 1:1。    │
-- │     · 本模块对法人只做【读写编排 + 分级授权 + 并表口径】，DDL 不重复定义法人表。            │
-- │  ② 涉密输出 / 跨网流向审批（X_FLOW_AUDIT，PRD 名） ==>  已建 x_flow_audit（common §7）      │
-- │     · x_flow_audit 提供 code(EXF-年-序)/direction(DOWN|UP)/from_domain/to_domain/          │
-- │       applicant_id/second_verifier_id/status(APPLIED|PRE_REVIEW|SEC_REVIEW|RELEASED|        │
-- │       REJECTED|RECORDED)/security_level。PRD §5.1 的 payload_digest/desensitize_note/       │
-- │       approver1/approver2/release_scope 等扩展位由本模块 X_SEC_LOG + sys_audit_log 补齐。    │
-- │     · 本模块【不重复建】流向审批表，POST /security/export 落到 x_flow_audit。               │
-- │  ③ 通用审计日志 sys_audit_log（common §6，含 prev_sig/sig 哈希链）已存在                    │
-- │     · 分工：sys_audit_log = 全系统通用操作审计（CRUD/审批/导出/打印，字段级 diff + SM2 签名）；│
-- │       X_SEC_LOG = 涉密网【专用安全日志】，增加 network_zone / granted_level 校验结果          │
-- │       (result ALLOW|DENY) / risk_flag 语义与独立 SM3 哈希链，服务越权探测/跨域告警稽核。        │
-- │     · 二者不互斥：涉密域判定事件写 X_SEC_LOG，业务数据变更仍写 sys_audit_log，traceId 关联。   │
-- │  ④ 三员职责 sys_admin_duty（common §1，uk_admin_duty_user(user_id) 唯一）为三员分立的物理约束， │
-- │     本模块据此做“禁止兼任 / 兼任即冻结”的裁决，不重复建三员表。                                │
-- │  ⑤ 制度包 sys_policy_pack（common §3）：X_SECURITY_POLICY 是“密级/流向”专用制度包的一种，      │
-- │     通过 policy_pack_id 逻辑联动，不重复建制度包主表。                                          │
-- └──────────────────────────────────────────────────────────────────────────────┘
--
-- ┌─ 二、信创达梦差异注记（design/README.md §2.4，达梦部署时按此替换）───────────────┐
-- │ 自增主键  GENERATED ALWAYS AS IDENTITY → IDENTITY(1,1)                            │
-- │ 时间戳    TIMESTAMPTZ → TIMESTAMP WITH TIME ZONE                                  │
-- │ 布尔      BOOLEAN → SMALLINT（0/1）；本脚本 mfa_bound/risk_flag/secret_eligible     │
-- │           已达梦风格用 SMALLINT + CHECK (0,1[,2])                                   │
-- │ JSON      JSONB（matrix_json/field_diff_json/training_records/leave_clearance）     │
-- │           → CLOB/VARCHAR 存 JSON 文本 + 应用层解析；高频判定字段提升为生成列         │
-- │ 数组      applied_modules VARCHAR(128)[] → 达梦不支持数组，改用 VARCHAR 存 ',' 分隔 │
-- │           或 JSON 文本 + 应用层展开（对齐 sys_policy_pack.applied_modules 同规则）   │
-- │ 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0 → 普通唯一索引 + deleted 复合键 │
-- │ 枚举      统一 VARCHAR + CHECK (IN (...))，不用原生 ENUM，便于灰度扩值              │
-- └──────────────────────────────────────────────────────────────────────────────┘
--
-- ┌─ 三、国产密码算法（等保三级 / 涉密信息系统分级保护 BMB）─────────────────────────┐
-- │ SM3（摘要/哈希）：X_SEC_LOG.hash_prev / hash_self 构成哈希链，逐条 SM3 链式摘要，   │
-- │                  防篡改；断裂即触发最高级安全告警并转只读取证模式。                  │
-- │ SM2（数字签名）：涉密输出放行 / 定密解密等关键操作的审批签名与 sys_audit_log.sig     │
-- │                  采用 SM2 椭圆曲线签名（替代 RSA/ECDSA）。                            │
-- │ SM4（对称加密）：SECRET/TOP_SECRET 对象的正文与附件在涉密网内以 SM4 密文落库；        │
-- │                  matrix_json 中的敏感策略项可按需 SM4 列加密。                        │
-- │ 说明：哈希链/签名字段仅存算法输出（hex/base64），密钥由信创密码机/HSM 托管，         │
-- │       不落应用配置；具体字段注释标注所用算法。                                        │
-- └──────────────────────────────────────────────────────────────────────────────┘
--
-- 【通用列（§2.1，所有业务表内联，列名列型完全一致，DDL 不再逐表注释）】
--   id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--   code VARCHAR(64), tenant_id BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
--   deleted SMALLINT NOT NULL DEFAULT 0, creator_id BIGINT NOT NULL, modifier_id BIGINT,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--   remark TEXT
--
-- 【治理三字段（§2.1 v1.1 / PRD 2.12/2.13）】本模块所有独有风险表默认携带：
--   legal_entity_id BIGINT NOT NULL（法人细分，逻辑引用 sys_legal_entity.id）
--   security_level  VARCHAR(16) NOT NULL DEFAULT 'INTERNAL' CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
--   （policy_pack_id 见 X_SECURITY_POLICY，联动 sys_policy_pack）
--
-- 【密级 token 与 PRD §6.2 密级状态机对齐 —— 两套取值切勿混淆】
--   · 对象/可见密级集合（security_level / granted_level）：PUBLIC / INTERNAL / SECRET / TOP_SECRET（静态分级，README 2.13）。
--   · 定/降/解密【工作态】（classify_status，落 X_PERSONNEL_SEC 及单据）：UNCLASSIFIED=待定密 / DOWN_CLASSIFY=降密中 / DECLASSIFY=解密中；
--     这是审批流程的过渡态，不表示对象密级；对象密级始终以 security_level 为准，工作态走完再回写 security_level。
--
-- 【外键】同底座物理外键 REFERENCES sys_user(id)（common 与 X 共库可建）；
--   跨微服务库（S_STAFF/07、E_PROJECT/02、sys_policy_pack 引用值等）仅以 *_id 逻辑外键注释表达，不建物理外键（README §2.3/§3.1）。
--
-- 【单号前缀（PRD 2.11 / design/README.md §2.3）】
--   · LE（法人）、EXF（输出/流向审批）已登记于 00-common.sql seq_prefix_registry，分别归 sys_legal_entity / x_flow_audit，本模块直接复用。
--   · SEC（涉密事项：策略/授权/人员涉密档案）——本模块使用 SEC-{yyyy}-{seq6}；PRD 声明前缀为 SEC，但 2.11 注册表当前【未登记 SEC】，
--     故本脚本仅声明 code 列不强约束前缀，正式下发前须先在 seq_prefix_registry 登记 SEC（owner_module='X'），避免规则漂移。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) X_SECURITY_POLICY 密级/流向策略（制度包的一种；版本化；单号 SEC-年-序）
--    定义 security_level → 可见网络域 / 角色白名单 / 可否导出 / 可否跨网 的判定矩阵
-- -----------------------------------------------------------------------------
CREATE TABLE X_SECURITY_POLICY (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- SEC-{yyyy}-{seq6}（待 2.11 登记 SEC 后由编号中心下发）
  tenant_id       BIGINT       NOT NULL,              -- 总院法人边界
  legal_entity_id BIGINT       NOT NULL,              -- 法人细分（逻辑引用 sys_legal_entity.id；默认总院法人）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 本策略自身密级

  version         INT          NOT NULL DEFAULT 1,    -- 策略版本号（同 code 多版本并存，历史留快照）
  effective_from  DATE         NOT NULL,              -- 生效起
  effective_to    DATE,                               -- 生效止（NULL=当前有效）
  matrix_json     JSONB        NOT NULL,              -- 判定矩阵：每 security_level 的 visible_zones/role_whitelist/can_export/can_cross_net/desensitize；SM3 摘要校验完整性
  applied_modules VARCHAR(128) [] NOT NULL,           -- 生效模块集合 {P,E,F,R,T,G,A,C,D...}（达梦改 ','分隔/JSON 文本）
  policy_pack_id  BIGINT,                            -- 逻辑联动 sys_policy_pack.id（等同制度包的一种，可复算/可解释）

  status          VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                  CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),  -- 草稿/生效/被取代（对齐 sys_policy_pack token）
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_secpolicy_code_ver ON X_SECURITY_POLICY(tenant_id, code, version) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_secpolicy_active   ON X_SECURITY_POLICY(tenant_id, applied_modules) WHERE status = 'ACTIVE' AND deleted = 0; -- 同租户同模块集合仅一套 ACTIVE
CREATE INDEX        idx_secpolicy_ent     ON X_SECURITY_POLICY(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_secpolicy_pack    ON X_SECURITY_POLICY(policy_pack_id);

COMMENT ON TABLE  X_SECURITY_POLICY                IS '密级/流向策略（版本化制度包的一种）：security_level×网络域×角色可见性矩阵，联动 sys_policy_pack';
COMMENT ON COLUMN X_SECURITY_POLICY.matrix_json    IS '判定矩阵 JSONB：{"SECRET":{"visible_zones":["SECRET_NET"],"role_whitelist":[...],"can_export":false,"can_cross_net":false,"desensitize":"placeholder"},...}；网关 zone-guard 据此判定';
COMMENT ON COLUMN X_SECURITY_POLICY.applied_modules IS '生效模块集合 {P,E,F,R,T,G,A,C,D...}；决定哪些业务对象的 security_level 走本策略';
COMMENT ON COLUMN X_SECURITY_POLICY.policy_pack_id IS '逻辑引用 sys_policy_pack.id；策略与制度包同源，命中写 sys_rule_hit 可复算';
COMMENT ON COLUMN X_SECURITY_POLICY.status         IS 'DRAFT 草稿/ACTIVE 生效（同集合唯一）/SUPERSEDED 被新版本取代';
COMMENT ON COLUMN X_SECURITY_POLICY.code           IS 'SEC-年-序；SEC 前缀须先在 2.11 注册表登记方可由编号中心正式下发';


-- -----------------------------------------------------------------------------
-- 2) X_ACCESS_GRANT 授权与密级许可（谁，在哪个网络域，最高可见到什么密级；SEC-年-序）
--    ABAC 属性源：subject_user_id + scope(法人/部门/项目/密级) + granted_level + network_zone
-- -----------------------------------------------------------------------------
CREATE TABLE X_ACCESS_GRANT (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- SEC-{yyyy}-{seq6}
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT       NOT NULL,              -- 授权归属法人（逻辑引用 sys_legal_entity.id）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 本授权记录自身密级

  subject_user_id BIGINT       NOT NULL REFERENCES sys_user(id), -- 被授权人（同底座物理外键）
  scope_type      VARCHAR(16)  NOT NULL
                  CHECK (scope_type IN ('LEGAL_ENTITY','DEPT','PROJECT','SECURITY_LEVEL')), -- 法人|部门|项目|密级
  scope_ref       BIGINT,                            -- 范围对象 id：法人 sys_legal_entity.id / 部门 sys_org.id / 项目 E_PROJECT.id（逻辑引用）；scope_type=SECURITY_LEVEL 时可空
  granted_level   VARCHAR(16)  NOT NULL
                  CHECK (granted_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 可见最高密级
  network_zone    VARCHAR(16)  NOT NULL
                  CHECK (network_zone IN ('INTERNET','OFFICE','SECRET_NET')),           -- 授权生效网络域：互联网/办公内网/涉密网
  mfa_bound       SMALLINT     NOT NULL DEFAULT 0
                  CHECK (mfa_bound IN (0,1)),        -- 是否绑定硬件 Key/生物（达梦 SMALLINT）；SECRET+ 强制 1
  valid_from      TIMESTAMPTZ  NOT NULL,             -- 授权生效起
  valid_to        TIMESTAMPTZ,                       -- 授权到期（NULL=长期；到期自动失效）

  status          VARCHAR(32)  NOT NULL DEFAULT 'EFFECTIVE'
                  CHECK (status IN ('EFFECTIVE','FROZEN','REVOKED')),  -- 生效/冻结/吊销
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_grant_code      ON X_ACCESS_GRANT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_grant_subject  ON X_ACCESS_GRANT(subject_user_id, status);          -- 取当前有效授权（判定主路径）
CREATE INDEX        idx_grant_level_zn ON X_ACCESS_GRANT(granted_level, network_zone);      -- zone-guard 按密级×域过滤
CREATE INDEX        idx_grant_ent      ON X_ACCESS_GRANT(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_grant_scope    ON X_ACCESS_GRANT(scope_type, scope_ref);

COMMENT ON TABLE  X_ACCESS_GRANT               IS '授权与密级许可（ABAC 属性源）：subject_user 在指定网络域/范围内可见的最高密级';
COMMENT ON COLUMN X_ACCESS_GRANT.scope_type    IS 'LEGAL_ENTITY 法人/DEPT 部门/PROJECT 项目/SECURITY_LEVEL 按密级授权';
COMMENT ON COLUMN X_ACCESS_GRANT.scope_ref     IS '范围对象 id（法人/部门/项目逻辑引用，不建物理外键）；SECURITY_LEVEL 范围时可空';
COMMENT ON COLUMN X_ACCESS_GRANT.granted_level IS '授予可见最高密级；判定 actor.granted_level >= object.security_level';
COMMENT ON COLUMN X_ACCESS_GRANT.network_zone  IS 'INTERNET 互联网/OFFICE 办公内网/SECRET_NET 涉密网；跨域授权需二次鉴别';
COMMENT ON COLUMN X_ACCESS_GRANT.mfa_bound     IS '0 未绑定/1 已绑定硬件 Key 或生物；SECRET/TOP_SECRET 授权强制 1';
COMMENT ON COLUMN X_ACCESS_GRANT.valid_to      IS '到期时间；客座/访问学者短期许可到期自动失效（联动 07 S-11）';
COMMENT ON COLUMN X_ACCESS_GRANT.status        IS 'EFFECTIVE 生效/FROZEN 冻结（离岗未清退降为只读占位）/REVOKED 吊销';


-- -----------------------------------------------------------------------------
-- 3) X_SEC_LOG 涉密网专用安全日志（append-only，SM3 哈希链防篡改；越权/跨域/流向稽核）
--    分工：与 common.sys_audit_log 互补——本表专管三网访问判定结果(allow/deny)、risk、zone、granted_level 校验语义。
--    【设计取舍】作为不可篡改追加日志，有意省略 status/deleted/creator_id/modifier_id/updated_at/remark 等可编辑列
--                （与 sys_audit_log 同为特例），仅保留追加所需列；任何 UPDATE/DELETE 应由数据库权限禁止。
-- -----------------------------------------------------------------------------
CREATE TABLE X_SEC_LOG (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id       BIGINT       NOT NULL,              -- 总院法人边界
  legal_entity_id BIGINT       NOT NULL,              -- 事件归属法人（逻辑引用 sys_legal_entity.id）

  actor_id        BIGINT       NOT NULL,              -- who：操作人 user_id（逻辑引用 sys_user.id）
  actor_role      VARCHAR(32),                         -- 操作时角色（R-*，快照）
  network_zone    VARCHAR(16)  NOT NULL
                  CHECK (network_zone IN ('INTERNET','OFFICE','SECRET_NET')), -- 请求来源网络域
  action          VARCHAR(32)  NOT NULL,              -- READ/CREATE/UPDATE/DELETE/EXPORT/PRINT/GRANT/CLASSIFY/CROSS_NET/LOGIN ...
  object_type     VARCHAR(32)  NOT NULL,              -- 表名或单据类型（E_PROJECT/F_EXPENSE/DOC/...）
  object_id       BIGINT       NOT NULL,              -- 被访问对象主键
  field_diff_json JSONB,                               -- 字段级前后值（what/why，达梦 CLOB 存 JSON 文本）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 被访问对象密级
  granted_level   VARCHAR(16)
                  CHECK (granted_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 校验时 actor 的授权最高密级快照（NULL 表示未命中授权）
  result          VARCHAR(8)   NOT NULL
                  CHECK (result IN ('ALLOW','DENY')),  -- 判定结果：放行/拒绝
  risk_flag       SMALLINT     NOT NULL DEFAULT 0
                  CHECK (risk_flag IN (0,1,2)),        -- 0 常规/1 风险（跨域尝试）/2 高危（越权探测/哈希链断裂）
  hash_prev       VARCHAR(128),                        -- 前一条 SM3 链摘要（哈希链，SM3）
  hash_self       VARCHAR(128) NOT NULL,               -- 本条 SM3 链式摘要（SM3），覆盖上列业务字段，防篡改
  occurred_at     TIMESTAMPTZ  NOT NULL,              -- when：事件发生时间
  source_ip       VARCHAR(64),                         -- where：来源 IP
  device_id       VARCHAR(128)                         -- where：设备指纹/终端 ID
);
CREATE INDEX idx_seclog_time     ON X_SEC_LOG(occurred_at);                              -- 时序稽核/窗口扫描
CREATE INDEX idx_seclog_risk     ON X_SEC_LOG(risk_flag, occurred_at) WHERE risk_flag > 0; -- 风险事件（告警检索，达梦去 WHERE 用 risk_flag 普通索引）
CREATE INDEX idx_seclog_obj      ON X_SEC_LOG(object_type, object_id);                   -- 对象访问追溯
CREATE INDEX idx_seclog_ent      ON X_SEC_LOG(legal_entity_id, occurred_at);             -- 分法人稽核
CREATE INDEX idx_seclog_actor    ON X_SEC_LOG(tenant_id, actor_id, occurred_at);         -- 行为人轨迹
CREATE INDEX idx_seclog_zone_lvl ON X_SEC_LOG(network_zone, security_level, result);     -- 跨域拒绝分析

COMMENT ON TABLE  X_SEC_LOG               IS '涉密网专用安全审计日志（追加不可改，SM3 哈希链防篡改）；与 common.sys_audit_log 分工：本表专管三网判定/越权/流向，通用数据变更走 sys_audit_log，traceId 关联';
COMMENT ON COLUMN X_SEC_LOG.network_zone  IS '请求来源网络域；与对象 security_level 的可见域比对，不匹配即 DENY+risk';
COMMENT ON COLUMN X_SEC_LOG.granted_level IS '判定时 actor 的授权最高密级快照（来自 X_ACCESS_GRANT），用于事后复算为何放行/拒绝';
COMMENT ON COLUMN X_SEC_LOG.result        IS 'ALLOW 放行/DENY 拒绝；对 DENY 不向前端暴露对象细节（防探测）';
COMMENT ON COLUMN X_SEC_LOG.risk_flag     IS '0 常规/1 风险/2 高危；哈希链断裂或连续越权探测置 2，触发最高级告警与只读取证';
COMMENT ON COLUMN X_SEC_LOG.hash_prev     IS '前一条链摘要（SM3）；首条为 NULL 或创世常量';
COMMENT ON COLUMN X_SEC_LOG.hash_self     IS '本条 SM3 摘要，覆盖业务字段+hash_prev，构成不可篡改哈希链';


-- -----------------------------------------------------------------------------
-- 4) X_PERSONNEL_SEC 涉密人员（联动 07 S_STAFF；入职审查/在岗复审/离岗清退/密级许可）
-- -----------------------------------------------------------------------------
CREATE TABLE X_PERSONNEL_SEC (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- SEC-{yyyy}-{seq6}（人员涉密档案号）
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT       NOT NULL,              -- 人员归属法人（逻辑引用 sys_legal_entity.id）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 档案记录密级

  user_id         BIGINT       NOT NULL REFERENCES sys_user(id), -- 登录态（同底座物理外键）
  staff_id        BIGINT,                            -- 逻辑引用 S_STAFF.id（07 模块，跨库不建物理外键）
  secret_eligible SMALLINT     NOT NULL DEFAULT 0
                  CHECK (secret_eligible IN (0,1)),  -- 是否具备涉密岗资格（达梦 SMALLINT）
  granted_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (granted_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 当前密级许可（与 X_ACCESS_GRANT 对齐）
  classify_status VARCHAR(16)  NOT NULL DEFAULT 'UNCLASSIFIED'
                  CHECK (classify_status IN ('UNCLASSIFIED','DOWN_CLASSIFY','DECLASSIFY')), -- 定/降/解密【工作态】（≠ security_level）
  review_date     DATE,                              -- 最近一次在岗复审日期
  next_review_date DATE,                             -- 下次复审到期日（逾期触发复审提醒/冻结）
  training_records JSONB       NOT NULL DEFAULT '[]', -- 保密培训记录 [{type,training_date,result,trainer,cert_ref}]（达梦 CLOB 存 JSON）
  leave_clearance  JSONB,                            -- 离岗清退 {carrier_returned:0/1,access_revoked:0/1,undertaking_signed:0/1,closed_by,closed_at}；未完成则权限收敛

  status          VARCHAR(32)  NOT NULL DEFAULT 'PENDING_REVIEW'
                  CHECK (status IN ('PENDING_REVIEW','GRANTED','RE_REVIEW','FROZEN','CLEARED_OUT')), -- 待审/已授权在岗/复审中/冻结/已清退
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_personnel_sec_user ON X_PERSONNEL_SEC(user_id) WHERE deleted = 0;  -- 一人一份涉密档案
CREATE UNIQUE INDEX uk_personnel_sec_code ON X_PERSONNEL_SEC(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_personnel_sec_ent ON X_PERSONNEL_SEC(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_personnel_sec_lvl ON X_PERSONNEL_SEC(granted_level);
CREATE INDEX        idx_personnel_sec_rev ON X_PERSONNEL_SEC(next_review_date);           -- 复审到期扫描

COMMENT ON TABLE  X_PERSONNEL_SEC               IS '涉密人员管理（联动 07）：入职审查→在岗复审→离岗清退；承载密级许可与定/降/解密工作态';
COMMENT ON COLUMN X_PERSONNEL_SEC.user_id       IS '登录态 sys_user.id（同底座物理外键）；与 S_STAFF.user_id 一致';
COMMENT ON COLUMN X_PERSONNEL_SEC.staff_id      IS '科研人员档案（跨微服务库逻辑引用 S_STAFF.id，07 模块）';
COMMENT ON COLUMN X_PERSONNEL_SEC.granted_level IS '当前密级许可；与 X_ACCESS_GRANT.granted_level 对齐，判定取交集';
COMMENT ON COLUMN X_PERSONNEL_SEC.classify_status IS '定/降/解密工作态：UNCLASSIFIED 待定密/DOWN_CLASSIFY 降密中/DECLASSIFY 解密中；此为流程过渡态，不覆盖对象 security_level';
COMMENT ON COLUMN X_PERSONNEL_SEC.leave_clearance IS '离岗清退：载体归还/权限回收/保密承诺 三项全 1 方视为完成；否则权限收敛为只读占位';
COMMENT ON COLUMN X_PERSONNEL_SEC.status        IS 'PENDING_REVIEW 待审查/GRANTED 已授权在岗/RE_REVIEW 复审中/FROZEN 冻结/CLEARED_OUT 已清退';


-- ===== 13-学术活动管理-V.ddl.sql =====
-- =============================================================================
-- 13-学术活动管理-V.ddl.sql · 模块 V（学术活动）建表脚本
-- 版本 v1.0 · 2026-10-14
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4）
-- 约定：金额 NUMERIC(18,2)；时间 TIMESTAMPTZ；枚举 VARCHAR+CHECK；字典走 sys_dict；
--       跨模块只存 *_id 逻辑外键（organizer_dept→sys_org、project→E_PROJECT、budget_subject→F），
--       同模块内 participant/review 对 v_activity 建物理外键。
-- 编号：v_activity.code 前缀 ACT（svc-numbering 分配，见 00-common seq_prefix_registry）。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- V_ACTIVITY · 活动主表（申报→审批→举办→归档；状态机见 detail.md）
--   DRAFT→SUBMITTED→DEPT_REVIEW→APPROVED→HELD→ARCHIVED；分支 REJECTED/RETURNED/CANCELLED
-- -----------------------------------------------------------------------------
CREATE TABLE v_activity (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               VARCHAR(64),
  tenant_id          BIGINT NOT NULL,
  status             VARCHAR(32) NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','SUBMITTED','DEPT_REVIEW','APPROVED','HELD',
                                       'ARCHIVED','REJECTED','RETURNED','CANCELLED')),
  deleted            SMALLINT NOT NULL DEFAULT 0,
  creator_id         BIGINT NOT NULL,
  modifier_id        BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  remark             TEXT,
  security_level     VARCHAR(16) NOT NULL DEFAULT 'INTERNAL'
                     CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  -- 业务列 ─────────────────────────────────────────────
  activity_type      VARCHAR(32) NOT NULL
                     CHECK (activity_type IN ('CONFERENCE','LECTURE','SEMINAR','TRAINING','OTHER')),
  level              VARCHAR(16)
                     CHECK (level IN ('INTERNATIONAL','NATIONAL','PROVINCIAL','CAMPUS')),
  host_mode          VARCHAR(16)
                     CHECK (host_mode IN ('HOST','ATTEND','SPONSOR')),
  title              VARCHAR(256) NOT NULL,
  theme              VARCHAR(256),
  start_at           TIMESTAMPTZ,
  end_at             TIMESTAMPTZ,
  venue              VARCHAR(256),
  online_url         VARCHAR(512),
  host_unit          VARCHAR(128),
  organizer_dept_id  BIGINT,                        -- 逻辑外键 → sys_org(id)
  invited_experts    JSONB        NOT NULL DEFAULT '[]'::jsonb, -- [{name,org,title}]
  est_attendees      INT,
  project_id         BIGINT,                        -- 逻辑外键 → e_project(id)
  budget_subject_code VARCHAR(64),                  -- 逻辑引用 F 科目 / sys_dict
  budget_amount      NUMERIC(18,2),                 -- 登记用，不联动 F 冻结（YAGNI §7）
  agenda             JSONB        NOT NULL DEFAULT '[]'::jsonb, -- [{title,speaker,startAt,endAt,venue}]
  attachment_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb,
  minutes_rich       TEXT,                          -- 纪要（归档时填）
  sign_in_count      INT,                           -- 实到人数
  hold_proof_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb, -- 举办凭证对象 id
  submit_at          TIMESTAMPTZ,
  approve_at         TIMESTAMPTZ,
  archive_at         TIMESTAMPTZ,
  cancel_at          TIMESTAMPTZ,
  cancel_reason      VARCHAR(512)
);
CREATE UNIQUE INDEX uk_v_activity_code     ON v_activity(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_v_activity_tenant_st      ON v_activity(tenant_id, status);
CREATE INDEX idx_v_activity_type           ON v_activity(tenant_id, activity_type);
CREATE INDEX idx_v_activity_level          ON v_activity(tenant_id, level);
CREATE INDEX idx_v_activity_dept           ON v_activity(organizer_dept_id);
CREATE INDEX idx_v_activity_project        ON v_activity(project_id);
CREATE INDEX idx_v_activity_start          ON v_activity(start_at);

COMMENT ON TABLE  v_activity IS '学术活动主表：会议/讲座/研讨/培训申报审批举办归档（模块 V）';
COMMENT ON COLUMN v_activity.status             IS '状态机 token：DRAFT/SUBMITTED/DEPT_REVIEW/APPROVED/HELD/ARCHIVED/REJECTED/RETURNED/CANCELLED';
COMMENT ON COLUMN v_activity.security_level     IS '密级；读取按网络域/密级过滤（复用 X 治理谓词），默认 INTERNAL';
COMMENT ON COLUMN v_activity.organizer_dept_id  IS '主办部门，逻辑外键 → sys_org(id)，不建物理 FK';
COMMENT ON COLUMN v_activity.project_id         IS '关联项目，逻辑外键 → e_project(id)';
COMMENT ON COLUMN v_activity.budget_amount      IS '活动预算（登记），NUMERIC(18,2)，不联动经费冻结';


-- -----------------------------------------------------------------------------
-- V_ACTIVITY_PARTICIPANT · 参与人（内部 user 或外部 guest）
-- -----------------------------------------------------------------------------
CREATE TABLE v_activity_participant (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  activity_id   BIGINT NOT NULL REFERENCES v_activity(id),
  user_id       BIGINT,                            -- 逻辑外键 → sys_user(id)；空=外部专家
  guest_name    VARCHAR(64),                       -- 外部人员姓名快照
  role          VARCHAR(16) NOT NULL
                CHECK (role IN ('SPEAKER','CHAIR','MEMBER','ATTENDEE')),
  report_title  VARCHAR(256),
  tenant_id     BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_v_participant_user ON v_activity_participant(activity_id, user_id, role) WHERE user_id IS NOT NULL;
CREATE INDEX idx_v_participant_activity   ON v_activity_participant(activity_id);

COMMENT ON TABLE v_activity_participant IS '活动参与人：内部 user_id 或外部 guest_name，含角色与报告题目';


-- -----------------------------------------------------------------------------
-- V_ACTIVITY_REVIEW · 多级审核留痕（1=部门 2=院所/主管）
-- -----------------------------------------------------------------------------
CREATE TABLE v_activity_review (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  activity_id  BIGINT NOT NULL REFERENCES v_activity(id),
  review_level SMALLINT NOT NULL,
  reviewer_id  BIGINT NOT NULL,                    -- 逻辑外键 → sys_user(id)
  action       VARCHAR(16) NOT NULL
               CHECK (action IN ('APPROVE','REJECT','RETURN')),
  opinion      VARCHAR(512),
  acted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  tenant_id    BIGINT NOT NULL
);
CREATE INDEX idx_v_review_activity ON v_activity_review(activity_id, review_level);

COMMENT ON TABLE v_activity_review IS '活动审核留痕：每级审批动作/意见/时间，可追溯';

