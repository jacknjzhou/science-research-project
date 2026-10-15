-- T15 经费预警配置（规则引擎数据源；T18/T21 扫描任务消费）
CREATE TABLE F_WARN_CONFIG (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id           BIGINT NOT NULL,
    status              VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    deleted             SMALLINT NOT NULL DEFAULT 0,
    creator_id          BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    remark              TEXT,
    -- 业务列
    project_category_id BIGINT,                          -- 逻辑引用 E_PROJECT_CATEGORY(id)，空=全部分类
    warn_kind           VARCHAR(32) NOT NULL,            -- EXEC_RATE | DEADLINE | ANNUAL_FEE | MIDCHECK | CLOSING
    threshold_pct       NUMERIC(6,4),                    -- 执行率阈值（0-1，如 0.75）；日期类预警为空
    ahead_days          INT,                             -- 日期类预警提前天数（年费/中检/结项）
    level               VARCHAR(8) NOT NULL DEFAULT 'P2' CHECK (level IN ('P1','P2','P3')),
    channel             VARCHAR(16) NOT NULL DEFAULT 'INBOX' CHECK (channel IN ('INBOX','CRON','BOTH')),
    cron_expr           VARCHAR(64),                     -- CRON/BOTH 时必填
    template            TEXT,                            -- 消息模板（{project} {amount} {deadline} 占位）
    enabled             BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_warn_cfg_tenant ON F_WARN_CONFIG (tenant_id, warn_kind, enabled);
