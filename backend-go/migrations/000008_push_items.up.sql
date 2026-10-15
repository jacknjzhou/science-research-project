-- T17 网推成果认领 + 去重（推送池）
CREATE TABLE R_PUSH_ITEM (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  BIGINT NOT NULL,
    type       VARCHAR(16) NOT NULL CHECK (type IN ('PAPER','PATENT')),
    source_db  VARCHAR(32) NOT NULL,          -- WOS/CNKI/CNIPA...
    title      VARCHAR(512) NOT NULL,
    authors    JSONB NOT NULL DEFAULT '[]',
    year       INT,
    raw_doi    VARCHAR(128),
    status     VARCHAR(16) NOT NULL DEFAULT 'PUSHED' CHECK (status IN ('PUSHED','IMPORTED','IGNORED')),
    pushed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    dedup_key  VARCHAR(64) NOT NULL,          -- 规范化标题哈希（精确去重键）
    output_id  BIGINT,                        -- 导入后指向 R_OUTPUT
    deleted    SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_push_item_tenant ON R_PUSH_ITEM (tenant_id, status, pushed_at DESC);
