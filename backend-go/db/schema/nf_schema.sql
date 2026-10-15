-- NF sqlc schema：sys_notification 全量 + sys_user/sys_role/sys_user_role 最小定义（PushRole 扇出 join 用）。

CREATE TABLE sys_notification (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id  BIGINT       NOT NULL,
  user_id    BIGINT       NOT NULL,
  typ        VARCHAR(16)  NOT NULL DEFAULT 'TODO',
  title      VARCHAR(200) NOT NULL,
  content    TEXT,
  biz_ref    VARCHAR(128),
  read_at    TIMESTAMPTZ,
  created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 最小角色/用户定义（仅编译期解析，运行时打真库）
CREATE TABLE sys_user (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id  BIGINT NOT NULL,
  username   VARCHAR(64) NOT NULL,
  status     VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
);
CREATE TABLE sys_role (
  id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code     VARCHAR(32) NOT NULL,
  tenant_id BIGINT NOT NULL
);
CREATE TABLE sys_user_role (
  id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id  BIGINT NOT NULL,
  role_id  BIGINT NOT NULL,
  tenant_id BIGINT NOT NULL,
  expires_at TIMESTAMPTZ
);

-- T13 导入日志（dataio 模块；snapshot=成功行业务键 JSON 数组，undo 依据）
CREATE TABLE sys_import_log (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     BIGINT NOT NULL,
  module        VARCHAR(64) NOT NULL,
  row_count     INT NOT NULL DEFAULT 0,
  success_count INT NOT NULL DEFAULT 0,
  fail_count    INT NOT NULL DEFAULT 0,
  operator_id   BIGINT NOT NULL,
  snapshot      JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
