-- T14 经费外拨 + 结转 + 预算追加
CREATE TABLE F_OUTWARD (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code               VARCHAR(64),
    tenant_id          BIGINT NOT NULL,
    status             VARCHAR(16) NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    deleted            SMALLINT NOT NULL DEFAULT 0,
    creator_id         BIGINT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    remark             TEXT,
    -- 业务列
    project_id         BIGINT NOT NULL,                 -- 逻辑引用 E_PROJECT(id)
    budget_id          BIGINT,                          -- 逻辑引用 F_BUDGET(id)
    budget_line_id     BIGINT,                          -- 扣减的预算行
    amount             NUMERIC(18,2) NOT NULL,
    to_unit            VARCHAR(256) NOT NULL,           -- 外拨单位
    reason             TEXT,
    first_approved_by  BIGINT,                          -- 一级（R-MANAGER）
    first_approved_at  TIMESTAMPTZ,
    approved_by        BIGINT,                          -- 二级（R-LEADER）
    approved_at        TIMESTAMPTZ
);

CREATE TABLE F_CARRYOVER (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         VARCHAR(64),
    tenant_id    BIGINT NOT NULL,
    status       VARCHAR(16) NOT NULL DEFAULT 'PENDING'
                 CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    deleted      SMALLINT NOT NULL DEFAULT 0,
    creator_id   BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    remark       TEXT,
    -- 业务列
    project_id   BIGINT NOT NULL,
    fiscal_year  INT NOT NULL,                        -- 结转来源年度
    target_year  INT NOT NULL,                        -- 结转目标年度
    amount       NUMERIC(18,2) NOT NULL,
    income_id    BIGINT                               -- 批复后生成的 F_INCOME 行
);

-- 预算追加：pending_delta 审批中金额（批复入账时并入总额/行调整额）
ALTER TABLE F_BUDGET ADD COLUMN IF NOT EXISTS pending_delta NUMERIC(18,2) NOT NULL DEFAULT 0;
ALTER TABLE F_BUDGET_LINE ADD COLUMN IF NOT EXISTS pending_delta NUMERIC(18,2) NOT NULL DEFAULT 0;
