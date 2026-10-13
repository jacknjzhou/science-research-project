-- =============================================================================
-- 00-common.sql · 横切平台表（多模块共用底座）
-- 版本 v1.0 · 2026-10-13
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4）
-- 约定：金额 NUMERIC(18,2)；时间 TIMESTAMPTZ；枚举 VARCHAR+CHECK；字典禁止硬编码（PRD 2.8）
-- =============================================================================

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
  ('EXF','涉密外传/输出审计','X','v1.1',TRUE);
