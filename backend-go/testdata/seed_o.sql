-- O 域种子：2 文档（STORED，供全文检索/四性用）、1 案卷（ARCHIVED, PROJECT, 源 E/PRJ-2024-0001）、
-- 3 门类（required：2 FILLED 挂 doc、1 MISSING）、对应 4 项四性检测（均 PASS）。
-- id 列为 GENERATED ALWAYS AS IDENTITY，不可显式赋值，跨表引用一律用子查询（object_key/title 反查）。
-- 约定同 seed_e.sql：tenant_id=1、creator/uploader/archivist=1001、bucket='ark-docs'。

INSERT INTO o_document
  (code, tenant_id, status, creator_id, security_level, name, doc_type, size_bytes,
   bucket, object_key, checksum_sha256, uploader_id, uploaded_at, source_module, source_id, text_content)
VALUES
  ('DOC-2024-0001', 1, 'STORED', 1001, 'INTERNAL', '医学影像分割论文', 'pdf', 4096,
   'ark-docs', 'tenant/1/doc-cnn.pdf',
   'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
   1001, now(), 'O', NULL, '卷积神经网络 医学图像 分割'),
  ('DOC-2024-0002', 1, 'STORED', 1001, 'INTERNAL', '项目结题报告', 'pdf', 8192,
   'ark-docs', 'tenant/1/doc-final-report.pdf',
   '0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0',
   1001, now(), 'E', NULL, '项目结题报告 经费决算');

INSERT INTO o_archive
  (code, tenant_id, status, creator_id, security_level, title, archive_type,
   source_module, source_id, source_code, owner_dept_id, retention_years,
   submitter_id, submit_at, archivist_id, filed_at)
VALUES
  ('ARC-2024-0001', 1, 'ARCHIVED', 1001, 'INTERNAL', 'O 项目科研档案-已入库', 'PROJECT',
   'E', NULL, 'PRJ-2024-0001', NULL, 10,
   1001, now(), 1001, now());

-- 3 门类：C1/C2 已挂载文档(FILLED)，C3 缺(MISSING)。uk_o_item(archive_id, category_code) 唯一。
INSERT INTO o_archive_item (tenant_id, archive_id, doc_id, status, category_code, category_name, required, sort_no)
SELECT a.tenant_id, a.id, d.id, 'FILLED', 'C1', '结题材料', TRUE, 1
  FROM o_archive a, o_document d
 WHERE a.title='O 项目科研档案-已入库' AND d.object_key='tenant/1/doc-cnn.pdf';

INSERT INTO o_archive_item (tenant_id, archive_id, doc_id, status, category_code, category_name, required, sort_no)
SELECT a.tenant_id, a.id, d.id, 'FILLED', 'C2', '经费决算', TRUE, 2
  FROM o_archive a, o_document d
 WHERE a.title='O 项目科研档案-已入库' AND d.object_key='tenant/1/doc-final-report.pdf';

INSERT INTO o_archive_item (tenant_id, archive_id, doc_id, status, category_code, category_name, required, sort_no)
SELECT a.tenant_id, a.id, NULL, 'MISSING', 'C3', '补充附件', TRUE, 3
  FROM o_archive a WHERE a.title='O 项目科研档案-已入库';

-- 4 项四性检测（均 PASS）。uk_o_check(archive_id, check_type) 唯一。
INSERT INTO o_archive_check (tenant_id, archive_id, check_type, result, detail, checker_id)
SELECT a.tenant_id, a.id, 'AUTHENTICITY', 'PASS', '{"mismatch_doc_ids":[],"checked":2}'::jsonb, 1001
  FROM o_archive a WHERE a.title='O 项目科研档案-已入库';
INSERT INTO o_archive_check (tenant_id, archive_id, check_type, result, detail, checker_id)
SELECT a.tenant_id, a.id, 'INTEGRITY', 'PASS', '{"required_total":3,"required_filled":3}'::jsonb, 1001
  FROM o_archive a WHERE a.title='O 项目科研档案-已入库';
INSERT INTO o_archive_check (tenant_id, archive_id, check_type, result, detail, checker_id)
SELECT a.tenant_id, a.id, 'USABILITY', 'PASS', '{"total":2,"unusable":0}'::jsonb, 1001
  FROM o_archive a WHERE a.title='O 项目科研档案-已入库';
INSERT INTO o_archive_check (tenant_id, archive_id, check_type, result, detail, checker_id)
SELECT a.tenant_id, a.id, 'SECURITY', 'PASS', '{"security_ok":true}'::jsonb, 1001
  FROM o_archive a WHERE a.title='O 项目科研档案-已入库';
