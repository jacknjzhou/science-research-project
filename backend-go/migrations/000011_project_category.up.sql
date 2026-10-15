-- T21 项目分类管理 + 中检/结项日期范围预警 + 认领管理费
CREATE TABLE E_PROJECT_CATEGORY (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      BIGINT NOT NULL,
    code           VARCHAR(32) NOT NULL,
    name           VARCHAR(128) NOT NULL,
    level          VARCHAR(16) NOT NULL DEFAULT 'NORMAL'
                   CHECK (level IN ('NORMAL','PROVINCIAL','MINISTERIAL','NATIONAL','KEY')),
    budget_template JSONB NOT NULL DEFAULT '[]',
    mgmt_fee_pct   NUMERIC(5,2) NOT NULL DEFAULT 0,          -- 认领入账管理费率（%）
    midcheck_from  DATE,                                      -- 中检窗口（NULL=无中检）
    midcheck_to    DATE,
    closing_from   DATE,                                      -- 结项窗口（NULL=无结项窗口）
    closing_to     DATE,
    deleted        SMALLINT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);
ALTER TABLE E_PROJECT ADD COLUMN IF NOT EXISTS category_id BIGINT;
ALTER TABLE F_INCOME  ADD COLUMN IF NOT EXISTS mgmt_fee NUMERIC(18,2) NOT NULL DEFAULT 0;
