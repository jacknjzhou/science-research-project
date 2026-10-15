-- T19 通用两级审核：审核动作流水（域无关，任何业务单据的提交/审批/驳回均落此表）
CREATE TABLE sys_approval_log (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  BIGINT NOT NULL,
    biz_type   VARCHAR(32) NOT NULL,   -- EXPENSE/CHANGE_REQUEST/CLAIM/APPLY...
    biz_id     BIGINT NOT NULL,
    step       INT NOT NULL DEFAULT 1, -- 0=提交 1=首审 2=终审
    actor_id   BIGINT NOT NULL,
    actor_role VARCHAR(32),
    action     VARCHAR(16) NOT NULL CHECK (action IN ('SUBMIT','APPROVE','REJECT','RETURN')),
    comment    TEXT,
    acted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_approval_log_biz ON sys_approval_log (tenant_id, biz_type, biz_id, acted_at);
