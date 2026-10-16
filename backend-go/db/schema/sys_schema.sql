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

-- 数据字典（PRD 2.8 / design 00-common.sql §2；migration 000013 追加 deleted/creator/modifier
-- 并将 uk_dict_code 改为 deleted=0 部分唯一索引——此处为迁移后形态，运行时打真库）。
CREATE TABLE sys_dict (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        VARCHAR(64) NOT NULL,
  name        VARCHAR(128) NOT NULL,
  tenant_id   BIGINT NOT NULL,
  remark      TEXT,
  deleted     SMALLINT NOT NULL DEFAULT 0,
  creator_id  BIGINT,
  modifier_id BIGINT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sys_dict_item (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dict_id      BIGINT NOT NULL REFERENCES sys_dict(id) ON DELETE CASCADE,
  item_code    VARCHAR(64) NOT NULL,
  item_label   VARCHAR(128) NOT NULL,
  parent_id    BIGINT REFERENCES sys_dict_item(id),
  ext_json     JSONB,
  sort_no      INT NOT NULL DEFAULT 0,
  i18n_json    JSONB,
  effective_from DATE,
  effective_to   DATE,
  active       BOOLEAN NOT NULL DEFAULT TRUE,
  tenant_id    BIGINT NOT NULL
);

-- 页面可见性矩阵（PRD 2.9 / migration 000014）：page_name × role_code 白名单制，
-- role_code='*' 表示所有已登录角色；全量替换保存，uk_page_grant 防重。
CREATE TABLE sys_page_grant (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  page_name  VARCHAR(64)  NOT NULL,
  role_code  VARCHAR(64)  NOT NULL,
  tenant_id  BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
