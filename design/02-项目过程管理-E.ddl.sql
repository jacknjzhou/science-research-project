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
