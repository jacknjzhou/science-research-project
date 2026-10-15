-- T25 申报计划 + 申报单（两级审批 → 通过后转立项草稿）
CREATE TABLE E_APPLY_PLAN (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    name          VARCHAR(256) NOT NULL,
    category_id   BIGINT,                                  -- 逻辑引用 E_PROJECT_CATEGORY(id)
    source        VARCHAR(64),                             -- 申报来源（国自然/省科技厅…）
    start_at      DATE NOT NULL,
    end_at        DATE NOT NULL,
    need_review   BOOLEAN NOT NULL DEFAULT TRUE,           -- 是否需要形式审查
    guide_file_id BIGINT,                                  -- 申报指南附件（O 域 file_id 逻辑引用）
    status        VARCHAR(16) NOT NULL DEFAULT 'DRAFT'
                  CHECK (status IN ('DRAFT','OPEN','STOPPED')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_apply_plan_tenant ON E_APPLY_PLAN (tenant_id, status, end_at);

CREATE TABLE E_APPLICATION (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      BIGINT NOT NULL,
    plan_id        BIGINT NOT NULL REFERENCES E_APPLY_PLAN(id),
    project_name   VARCHAR(512) NOT NULL,
    apply_amount   NUMERIC(18,2) NOT NULL DEFAULT 0,
    applicant_id   BIGINT NOT NULL,                        -- 申报人（sys_user.id）
    attachment_ids JSONB NOT NULL DEFAULT '[]',
    status         VARCHAR(32) NOT NULL DEFAULT 'SUBMITTED'
                   CHECK (status IN ('SUBMITTED','COLLEGE_PASSED','COLLEGE_REJECTED','SCHOOL_PASSED','SCHOOL_REJECTED')),
    project_id     BIGINT,                                 -- to-project 幂等回填（生成的 E_PROJECT 草稿 id）
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_application_plan ON E_APPLICATION (tenant_id, plan_id, status);
