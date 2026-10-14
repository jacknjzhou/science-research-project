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
