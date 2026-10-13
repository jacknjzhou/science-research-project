-- 裁剪 schema：仅 P 仓储所需的表（p_application 及其物理外键引用的 p_guideline、p_template）。
-- 由 migrations/000001_init.up.sql 原样摘录 CREATE TABLE 语句，保持与线上同构。
-- 原因：sqlc v1.27.0 的 wazero pg_query 解析器无法处理 ~394KB 的完整拼接迁移（out of bounds memory access）。

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
