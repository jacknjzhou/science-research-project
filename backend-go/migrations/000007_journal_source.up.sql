-- T16 期刊源库 + 刊物级别 + 转载登记
CREATE TABLE R_JOURNAL_SOURCE (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    name      VARCHAR(256) NOT NULL,
    issn      VARCHAR(32),
    year_from INT,
    year_to   INT,
    deleted   SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_journal_source_tenant ON R_JOURNAL_SOURCE (tenant_id, name);

CREATE TABLE R_JOURNAL_LEVEL (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  BIGINT NOT NULL,
    code       VARCHAR(32) NOT NULL,           -- SCI一区 / CCFA / CORE-A ...
    name       VARCHAR(128) NOT NULL,
    paper_type VARCHAR(32),                    -- 期刊论文/会议论文
    indexed    BOOLEAN NOT NULL DEFAULT TRUE,  -- 是否索引源（SCI/EI/SSCI）
    deleted    SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE R_JOURNAL_LEVEL_SOURCE (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    level_id  BIGINT NOT NULL REFERENCES R_JOURNAL_LEVEL(id),
    source_id BIGINT NOT NULL REFERENCES R_JOURNAL_SOURCE(id),
    year_from INT,
    year_to   INT
);

-- 转载登记（报纸转载/文摘转载等）
CREATE TABLE R_PAPER_REPRINT (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL,
    output_id    BIGINT NOT NULL REFERENCES R_OUTPUT(id),
    name         VARCHAR(256) NOT NULL,        -- 转载刊物名（人大复印资料/新华文摘…）
    type         VARCHAR(32),                  -- 全文转载/观点摘编/索引收录
    reprint_date DATE,
    remark       TEXT,
    deleted      SMALLINT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 刊物级别冗余快照（论文新增时按期刊名+年度 resolve）
ALTER TABLE R_PAPER_EXT ADD COLUMN IF NOT EXISTS level_code VARCHAR(32);
