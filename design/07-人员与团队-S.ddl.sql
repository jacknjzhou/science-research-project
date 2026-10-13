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
