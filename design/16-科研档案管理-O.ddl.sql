-- ============================================================
-- 16 · 科研档案管理（模块 O）
-- PG15；达梦差异：IDENTITY/JSONB/TIMESTAMPTZ/GIN/to_tsvector 需适配（见 00-common 注记）
-- 跨模块仅存 source_module + source_id 逻辑外键，不建物理 FK（同模块内 o_* 可建）
-- 全文检索依赖 00-common §0 已前置 CREATE EXTENSION pg_trgm
-- 索引一律 idx_o_/uk_o_ 前缀避免跨模块 schema namespace 冲突
-- ============================================================

CREATE TABLE o_document (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'UPLOADING'
                    CHECK (status IN ('UPLOADING','STORED','MISSING')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  name              VARCHAR(256) NOT NULL,
  doc_type          VARCHAR(64),                               -- mime / 扩展名
  size_bytes        BIGINT,
  bucket            VARCHAR(64),                               -- MinIO bucket
  object_key        VARCHAR(512),                              -- MinIO object key
  checksum_sha256   VARCHAR(64),                               -- 真实性校验源
  uploader_id       BIGINT,
  uploaded_at       TIMESTAMPTZ,
  source_module     VARCHAR(8),                                -- E/R/F/P/G/V/N/O…（可空=独立上传）
  source_id         BIGINT,                                    -- 逻辑→来源对象 id
  text_content      TEXT                                       -- 抽取正文，供全文检索
);
CREATE UNIQUE INDEX uk_o_doc_key ON o_document(tenant_id, bucket, object_key) WHERE deleted = 0 AND object_key IS NOT NULL;
CREATE UNIQUE INDEX uk_o_doc_code ON o_document(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_o_doc_source ON o_document(source_module, source_id);
CREATE INDEX idx_o_doc_tenant_status ON o_document(tenant_id, status);
CREATE INDEX idx_o_doc_fts ON o_document USING GIN (to_tsvector('simple', coalesce(text_content,'')));
CREATE INDEX idx_o_doc_trgm ON o_document USING GIN (text_content gin_trgm_ops);

CREATE TABLE o_archive (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                               -- ARC-年-序
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'PENDING_SUBMIT'
                    CHECK (status IN ('PENDING_SUBMIT','SUBMITTED','CHECKING','PASSED','ARCHIVED','REJECTED','DESTROYED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  title             VARCHAR(256) NOT NULL,
  archive_type      VARCHAR(24)  NOT NULL DEFAULT 'OTHER'
                    CHECK (archive_type IN ('PROJECT','OUTPUT','EXPENSE','CONTRACT','ACTIVITY','OTHER')),
  source_module     VARCHAR(8),
  source_id         BIGINT,
  source_code       VARCHAR(64),
  owner_dept_id     BIGINT,                                    -- 逻辑→sys_org
  retention_years   INT          NOT NULL DEFAULT 10,
  submitter_id      BIGINT,
  submit_at         TIMESTAMPTZ,
  archivist_id      BIGINT,
  filed_at          TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_o_arc_code ON o_archive(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_o_arc_tenant_status ON o_archive(tenant_id, status);
CREATE INDEX idx_o_arc_source ON o_archive(source_module, source_id);
CREATE INDEX idx_o_arc_type ON o_archive(tenant_id, archive_type);

CREATE TABLE o_archive_item (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  archive_id        BIGINT       NOT NULL REFERENCES o_archive(id),
  doc_id            BIGINT       REFERENCES o_document(id),   -- 可空 = 缺
  status            VARCHAR(16)  NOT NULL DEFAULT 'MISSING'
                    CHECK (status IN ('MISSING','FILLED','CHECKED')),
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  category_code     VARCHAR(64)  NOT NULL,                      -- 门类，sys_dict
  category_name     VARCHAR(128),
  required          BOOLEAN      NOT NULL DEFAULT TRUE,
  sort_no           INT          NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uk_o_item ON o_archive_item(archive_id, category_code);
CREATE INDEX idx_o_item_archive ON o_archive_item(archive_id, status);

CREATE TABLE o_archive_check (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         BIGINT       NOT NULL,
  archive_id        BIGINT       NOT NULL REFERENCES o_archive(id),
  result            VARCHAR(8)   NOT NULL DEFAULT 'WARN'
                    CHECK (result IN ('PASS','FAIL','WARN')),
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  check_type        VARCHAR(16)  NOT NULL
                    CHECK (check_type IN ('AUTHENTICITY','INTEGRITY','USABILITY','SECURITY')),
  detail            JSONB        NOT NULL DEFAULT '{}'::jsonb,
  checked_at        TIMESTAMPTZ,
  checker_id        BIGINT
);
CREATE UNIQUE INDEX uk_o_check ON o_archive_check(archive_id, check_type);
CREATE INDEX idx_o_check_archive ON o_archive_check(archive_id);

CREATE TABLE o_borrow (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                               -- BORROW-年-序
  tenant_id         BIGINT       NOT NULL,
  status            VARCHAR(32)  NOT NULL DEFAULT 'SUBMITTED'
                    CHECK (status IN ('SUBMITTED','APPROVED','REJECTED','RETURNED','EXPIRED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  archive_id        BIGINT       NOT NULL REFERENCES o_archive(id),
  borrower_user_id  BIGINT       NOT NULL,
  purpose           VARCHAR(512),
  borrow_type       VARCHAR(16)  NOT NULL DEFAULT 'READ'
                    CHECK (borrow_type IN ('READ','COPY')),
  approved_by       BIGINT,
  approved_at       TIMESTAMPTZ,
  due_at            TIMESTAMPTZ,
  returned_at       TIMESTAMPTZ
);
CREATE UNIQUE INDEX uk_o_borrow_code ON o_borrow(tenant_id, code) WHERE deleted = 0 AND code IS NOT NULL;
CREATE INDEX idx_o_borrow_archive ON o_borrow(archive_id, status);
CREATE INDEX idx_o_borrow_user ON o_borrow(borrower_user_id, status);
