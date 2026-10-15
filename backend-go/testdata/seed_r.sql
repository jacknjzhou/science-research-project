-- R 域（科研成果）种子：4 条 tenant=1（覆盖 PENDING_CLAIM/CLAIMED/ASSIGNED_TO_PROJECT/AUTO_FETCHED
-- 四态 + PAPER/PATENT/AWARD 类型），其中 authors 命中 user_id=100 供 /output/mine 与
-- /output/pending-claim 集成用例反查；1 条 tenant=2 演示跨租户隔离（REJECTED，勿混入 tenant=1 断言）。
--
-- claim_status/status/is_claimed 均取 DDL 合法枚举（design/04 R_OUTPUT CHECK 约束）。
-- authors/affiliations/project_ids 是 jsonb，默认 '[]'，此处显式给出以便 @> 匹配用例可命中。
-- match_confidence NUMERIC(6,4)：高置信(0.92)与可疑(0.41)各覆盖一条，验证 min_confidence 过滤分支。

INSERT INTO R_OUTPUT
  (code, tenant_id, status, creator_id, output_type, title, title_en,
   publish_date, authors, external_author_names, affiliations, project_ids,
   language, source, is_claimed, claim_status, match_confidence,
   department_id, legal_entity_id, security_level)
VALUES
  -- 1) 知网抓取、高置信、待本人认领 → /output/pending-claim 命中
  ('OUT-2026-0001', 1, 'PENDING_CLAIM', 100, 'PAPER',
   '基于深度学习的农作物病害识别研究', 'Deep Learning Crop Disease Recognition',
   DATE '2026-01-15',
   '[{"user_id":100,"name":"张三","order":1,"is_corresponding":true}]'::jsonb,
   '[]'::jsonb,
   '[{"user_id":100,"inst_id":1,"is_primary":true}]'::jsonb,
   '[]'::jsonb,
   'zh', 'CNKI', FALSE, 'UNCLAIMED', 0.9200,
   1, 1, 'INTERNAL'),

  -- 2) WOS 抓取、已认领 → /output/mine 命中（CLAIMED/is_claimed=true）
  ('OUT-2026-0002', 1, 'CLAIMED', 100, 'PAPER',
   'A Survey on Federated Learning Privacy', NULL,
   DATE '2025-11-03',
   '[{"user_id":100,"name":"Zhang San","order":2}]'::jsonb,
   '[{"name":"John Doe","inst":"MIT"}]'::jsonb,
   '[{"user_id":100,"inst_id":1,"is_primary":false}]'::jsonb,
   '[9001]'::jsonb,
   'en', 'WOS', TRUE, 'CLAIMED', 0.8500,
   1, 1, 'PUBLIC'),

  -- 3) 专利、已认领并关联项目 → /output/mine + LinkProjects 起点
  ('OUT-2026-0003', 1, 'ASSIGNED_TO_PROJECT', 100, 'PATENT',
   '一种农业无人机喷洒装置', NULL,
   DATE '2025-08-20',
   '[{"user_id":100,"name":"张三","order":1,"is_corresponding":true}]'::jsonb,
   '[]'::jsonb,
   '[{"user_id":100,"inst_id":1,"is_primary":true}]'::jsonb,
   '[9001,9002]'::jsonb,
   'zh', 'CNIPA', TRUE, 'CLAIMED', NULL,
   1, 1, 'INTERNAL'),

  -- 4) 批量抓取、可疑低置信 → /output/pending-claim（DOUBTFUL）命中
  ('OUT-2026-0004', 1, 'AUTO_FETCHED', 100, 'AWARD',
   '省科技进步三等奖（团队奖）', NULL,
   DATE '2025-06-01',
   '[{"user_id":100,"name":"张三","order":5}]'::jsonb,
   '[]'::jsonb,
   '[]'::jsonb,
   '[]'::jsonb,
   'zh', 'FETCH', FALSE, 'DOUBTFUL', 0.4100,
   NULL, 1, 'INTERNAL'),

  -- 5) 跨租户（tenant=2）、手动录入被拒 → 隔离验证，不应出现在 tenant=1 任何列表
  ('OUT-2026-0005', 2, 'REJECTED', 200, 'PAPER',
   '别租户成果-勿混入', NULL,
   DATE '2025-12-31',
   '[{"user_id":200,"name":"李四","order":1}]'::jsonb,
   '[]'::jsonb,
   '[]'::jsonb,
   '[]'::jsonb,
   'zh', 'MANUAL', FALSE, 'REJECTED', NULL,
   NULL, 2, 'INTERNAL');

-- 认领流水：output_id 用 code 子查询反查，避免硬编码自增主键。
-- action/status 均取 DDL 合法枚举（R_CLAIM_RECORD CHECK）。
INSERT INTO R_CLAIM_RECORD
  (tenant_id, creator_id, output_id, user_id, action, reason, confidence, batch_id)
SELECT 1, 100, id, 100, 'CLAIM', NULL, 0.8500, 'SEED-BATCH-1'
  FROM R_OUTPUT WHERE code = 'OUT-2026-0002'
UNION ALL
SELECT 1, 100, id, 100, 'MARK_NOT_MINE', '非本人署名，误匹配', 0.4100, 'SEED-BATCH-2'
  FROM R_OUTPUT WHERE code = 'OUT-2026-0004';
