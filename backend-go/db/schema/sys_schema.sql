-- 裁剪 schema：仅 U 仓储所需 sys_user(+password_hash)/sys_role/sys_user_role。
-- 原因同 P：sqlc v1.27.0 的 wazero 解析器无法处理完整拼接迁移。列定义与 000001 一致。
CREATE TABLE sys_role (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code         VARCHAR(32) NOT NULL,
  name         VARCHAR(64) NOT NULL,
  is_builtin   BOOLEAN     NOT NULL DEFAULT TRUE,
  tenant_id    BIGINT      NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sys_user (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username        VARCHAR(64)  NOT NULL,
  real_name       VARCHAR(64)  NOT NULL,
  email           VARCHAR(128),
  phone           VARCHAR(32),
  staff_no        VARCHAR(64),
  employment_status VARCHAR(16) NOT NULL DEFAULT 'ONBOARD'
                  CHECK (employment_status IN ('ONBOARD','RESIGNED','RETIRED','VISITING','GUEST','REHIRE')),
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                  CHECK (status IN ('ACTIVE','LOCKED','DISABLED')),
  password_hash   VARCHAR(100),
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT,
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);

CREATE TABLE sys_user_role (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES sys_user(id),
  role_id    BIGINT NOT NULL REFERENCES sys_role(id),
  tenant_id  BIGINT NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);
