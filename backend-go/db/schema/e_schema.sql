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
