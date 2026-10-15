-- N 域（专家与评审）种子：4 条 n_expert（tenant=1，全 ACTIVE、field_tags 含"物理"）。
-- 其中「PI镜像专家」user_id=100、「承担单位专家」org_name='承担单位' 专供抽取回避用例反查：
--   review.draw_rule = {exclude_user_ids:[100], exclude_orgs:["承担单位"]} 时，二者不得入名单。
-- id 由 GENERATED ALWAYS AS IDENTITY 自增，勿显式给出。status/source/expertise_level/security_level
-- 均取 DDL 合法枚举（design/15 n_expert CHECK 约束）。code 走 EXR-年-序 形态演示唯一索引。

INSERT INTO n_expert
  (code, tenant_id, status, creator_id, name, gender, title, org_name, user_id,
   source, field_tags, expertise_level, avoid_orgs, avoid_person_ids, security_level)
VALUES
  ('EXR-2026-0001', 1, 'ACTIVE', 1, '王工',     'M', '教授',   'A大学',    201,
   'EXTERNAL', '["物理","材料"]'::jsonb, 'SENIOR', '[]'::jsonb, '[]'::jsonb, 'INTERNAL'),

  ('EXR-2026-0002', 1, 'ACTIVE', 1, '赵研',     'F', '研究员', 'B研究所',  202,
   'EXTERNAL', '["物理"]'::jsonb,        'EXPERT', '[]'::jsonb, '[]'::jsonb, 'INTERNAL'),

  -- PI 镜像：与项目 PI 同 user_id=100 → exclude_user_ids 命中，抽取应回避
  ('EXR-2026-0003', 1, 'ACTIVE', 1, 'PI镜像专家', 'M', '副教授', 'C公司',   100,
   'EXTERNAL', '["物理"]'::jsonb,        'EXPERT', '[]'::jsonb, '[]'::jsonb, 'INTERNAL'),

  -- 承担单位：org_name='承担单位' → exclude_orgs 命中，抽取应回避
  ('EXR-2026-0004', 1, 'ACTIVE', 1, '承担单位专家', 'M', '高工', '承担单位', 204,
   'EXTERNAL', '["物理"]'::jsonb,        'SENIOR', '[]'::jsonb, '[]'::jsonb, 'INTERNAL');
