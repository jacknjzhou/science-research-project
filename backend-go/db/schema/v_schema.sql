-- 裁剪 schema：仅 V 仓储所需的 3 张自有表；语句原样摘自 000001_init.up.sql。
-- 原因：sqlc v1.27 wazero 解析器无法吃 ~394KB 全量迁移。V 不跨读他模块表，故无额外只读表。

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
  organizer_dept_id  BIGINT,
  invited_experts    JSONB        NOT NULL DEFAULT '[]'::jsonb,
  est_attendees      INT,
  project_id         BIGINT,
  budget_subject_code VARCHAR(64),
  budget_amount      NUMERIC(18,2),
  agenda             JSONB        NOT NULL DEFAULT '[]'::jsonb,
  attachment_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb,
  minutes_rich       TEXT,
  sign_in_count      INT,
  hold_proof_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb,
  submit_at          TIMESTAMPTZ,
  approve_at         TIMESTAMPTZ,
  archive_at         TIMESTAMPTZ,
  cancel_at          TIMESTAMPTZ,
  cancel_reason      VARCHAR(512)
);

CREATE TABLE v_activity_participant (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  activity_id   BIGINT NOT NULL REFERENCES v_activity(id),
  user_id       BIGINT,
  guest_name    VARCHAR(64),
  role          VARCHAR(16) NOT NULL
                CHECK (role IN ('SPEAKER','CHAIR','MEMBER','ATTENDEE')),
  report_title  VARCHAR(256),
  tenant_id     BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE v_activity_review (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  activity_id  BIGINT NOT NULL REFERENCES v_activity(id),
  review_level SMALLINT NOT NULL,
  reviewer_id  BIGINT NOT NULL,
  action       VARCHAR(16) NOT NULL
               CHECK (action IN ('APPROVE','REJECT','RETURN')),
  opinion      VARCHAR(512),
  acted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  tenant_id    BIGINT NOT NULL
);
