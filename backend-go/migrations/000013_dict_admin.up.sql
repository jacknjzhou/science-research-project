-- 000013_dict_admin.up.sql · 数据字典管理（PRD 2.8 / plan 2026-10-16-sysdict-admin）
-- 1) sys_dict 增软删/审计列，uk_dict_code 改 deleted=0 部分唯一索引（软删后同码可重建）
-- 2) 种子：迁移自前端硬编码枚举（GuideView/OutputView/ClaimView/ActivityView/ExpenseView）

ALTER TABLE sys_dict
  ADD COLUMN IF NOT EXISTS deleted SMALLINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS creator_id BIGINT,
  ADD COLUMN IF NOT EXISTS modifier_id BIGINT;

DROP INDEX IF EXISTS uk_dict_code;
CREATE UNIQUE INDEX IF NOT EXISTS uk_dict_code ON sys_dict(tenant_id, code) WHERE deleted = 0;

-- ---- 字典目录（幂等）----
INSERT INTO sys_dict (tenant_id, code, name, remark, creator_id) VALUES
  (1, 'project_type',   '项目类型',     '申报/立项的项目类型（原 GuideView 硬编码）', 1),
  (1, 'output_source',  '成果来源',     '成果抓取/录入来源（原 OutputView/ClaimView 硬编码）', 1),
  (1, 'activity_type',  '学术活动类型', '原 ActivityView 硬编码', 1),
  (1, 'activity_level', '学术活动级别', '原 ActivityView 硬编码', 1),
  (1, 'pay_method',     '支付方式',     '报销支付（原 ExpenseView 硬编码）', 1)
ON CONFLICT (tenant_id, code) WHERE deleted = 0 DO NOTHING;

-- ---- 字典条目（幂等；ext_json 承载展示扩展：icon/color）----
INSERT INTO sys_dict_item (dict_id, item_code, item_label, ext_json, sort_no, active, tenant_id)
SELECT d.id, v.item_code, v.item_label, v.ext::jsonb, v.sort_no, TRUE, 1
FROM sys_dict d
JOIN (VALUES
  ('project_type', 'NSFC',      '国家自然科学基金', '{"icon":"自","color":"#2C6E49"}', 1),
  ('project_type', 'KJBP',      '重点研发计划',     '{"icon":"重","color":"#A8842F"}', 2),
  ('project_type', 'ZIGE',      '院自立项目',       '{"icon":"院","color":"#41598C"}', 3),
  ('project_type', 'PROV',      '省部级',           '{"icon":"省","color":"#5B4FA0"}', 4),
  ('project_type', 'HENGXIANG', '横向委托',         '{"icon":"横","color":"#C2402C"}', 5),
  ('output_source', 'WOS',       'WoS',            NULL, 1),
  ('output_source', 'SCOPUS',    'Scopus',         NULL, 2),
  ('output_source', 'CNKI',      '知网',           NULL, 3),
  ('output_source', 'WANFANG',   '万方',           NULL, 4),
  ('output_source', 'CNIPA',     '国家知识产权局', NULL, 5),
  ('output_source', 'CROSSREF',  'CrossRef',       NULL, 6),
  ('output_source', 'FETCH',     '增量抓取',       NULL, 7),
  ('output_source', 'MANUAL',    '手动录入',       NULL, 8),
  ('output_source', 'ALTMETRIC', 'Altmetric',      NULL, 9),
  ('activity_type', 'CONFERENCE', '学术会议', NULL, 1),
  ('activity_type', 'LECTURE',    '讲座报告', NULL, 2),
  ('activity_type', 'SEMINAR',    '研讨班',   NULL, 3),
  ('activity_type', 'TRAINING',   '培训',     NULL, 4),
  ('activity_type', 'OTHER',      '其他',     NULL, 5),
  ('activity_level', 'INTERNATIONAL', '国际', NULL, 1),
  ('activity_level', 'NATIONAL',     '国家', NULL, 2),
  ('activity_level', 'PROVINCIAL',   '省级', NULL, 3),
  ('activity_level', 'CAMPUS',       '校内', NULL, 4),
  ('pay_method', 'GWC', '公务卡转账（默认）', NULL, 1),
  ('pay_method', 'DG',  '对公转账',           NULL, 2),
  ('pay_method', 'XJ',  '现金/备用金',        NULL, 3)
) AS v(dict_code, item_code, item_label, ext, sort_no)
  ON v.dict_code = d.code AND d.tenant_id = 1
ON CONFLICT (dict_id, item_code, COALESCE(effective_from, DATE '1970-01-01')) DO NOTHING;
