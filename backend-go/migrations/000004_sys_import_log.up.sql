-- T13 Excel 导入导出底座：导入日志（snapshot 存成功行原始键，支持撤销）。
CREATE TABLE sys_import_log (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    module        VARCHAR(64) NOT NULL,           -- funding.income | project.e | output.r
    row_count     INT NOT NULL DEFAULT 0,
    success_count INT NOT NULL DEFAULT 0,
    fail_count    INT NOT NULL DEFAULT 0,
    operator_id   BIGINT NOT NULL,
    snapshot      JSONB NOT NULL DEFAULT '[]',    -- 成功行的业务键（undo 依据）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_import_log_tenant ON sys_import_log (tenant_id, module, created_at DESC);
