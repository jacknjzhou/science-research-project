-- 000014_page_grant.up.sql · 页面可见性矩阵在线配置（PRD 2.9 / plan 2026-10-16-page-grant-matrix）
-- 单表白名单制：page_name × role_code；role_code='*' 表示所有已登录角色可见。
-- 种子 = 当前 router meta.roles + App.vue 菜单 roles 的并集（部署后零行为变化）；
-- 未配置的 (page, role) 即不可见；R-ADMIN 恒可见由前端硬编码兜底（防自锁），不入库。

CREATE TABLE IF NOT EXISTS sys_page_grant (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  page_name  VARCHAR(64)  NOT NULL,
  role_code  VARCHAR(64)  NOT NULL,
  tenant_id  BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_page_grant ON sys_page_grant(tenant_id, page_name, role_code);

-- ---- 种子（幂等；与既有静态 meta.roles 完全一致）----
INSERT INTO sys_page_grant (tenant_id, page_name, role_code) VALUES
  -- 所有已登录可见（原 meta.roles 空/缺省）
  (1, 'dash',          '*'),
  (1, 'guide',         '*'),
  (1, 'project',       '*'),
  -- 经费监督大屏
  (1, 'bigscreen',     'R-LEADER'),
  (1, 'bigscreen',     'R-FINANCE'),
  (1, 'bigscreen',     'R-AUDITOR'),
  (1, 'bigscreen',     'R-ADMIN'),
  -- 申报书撰写
  (1, 'editor',        'R-STAFF'),
  (1, 'editor',        'R-MANAGER'),
  (1, 'editor',        'R-LEADER'),
  -- 评审工作台
  (1, 'review',        'R-MANAGER'),
  (1, 'review',        'R-EXPERT'),
  (1, 'review',        'R-ETHICS'),
  (1, 'review',        'R-LEADER'),
  (1, 'review',        'R-ADMIN'),
  -- 我的项目
  (1, 'projects',      'R-STAFF'),
  (1, 'projects',      'R-MANAGER'),
  (1, 'projects',      'R-LEADER'),
  -- 报销填单
  (1, 'expense',       'R-STAFF'),
  (1, 'expense',       'R-MANAGER'),
  (1, 'expense',       'R-FINANCE'),
  -- 成果认领 / 成果台账
  (1, 'claim',         'R-STAFF'),
  (1, 'claim',         'R-MANAGER'),
  (1, 'claim',         'R-LEADER'),
  (1, 'output',        'R-STAFF'),
  (1, 'output',        'R-MANAGER'),
  (1, 'output',        'R-LEADER'),
  -- 转化看板
  (1, 'transfer',      'R-MANAGER'),
  (1, 'transfer',      'R-LEADER'),
  (1, 'transfer',      'R-ADMIN'),
  -- 采购与合同 / 资产与耗材
  (1, 'procurement',   'R-MANAGER'),
  (1, 'procurement',   'R-FINANCE'),
  (1, 'procurement',   'R-ADMIN'),
  (1, 'asset',         'R-MANAGER'),
  (1, 'asset',         'R-FINANCE'),
  (1, 'asset',         'R-ADMIN'),
  -- PI 画像
  (1, 'portrait',      'R-LEADER'),
  (1, 'portrait',      'R-MANAGER'),
  (1, 'portrait',      'R-ADMIN'),
  -- 学术活动
  (1, 'activity',      'R-STAFF'),
  (1, 'activity',      'R-MANAGER'),
  (1, 'activity',      'R-LEADER'),
  (1, 'activity',      'R-AUDITOR'),
  -- 科研绩效评价
  (1, 'performance',   'R-STAFF'),
  (1, 'performance',   'R-MANAGER'),
  (1, 'performance',   'R-LEADER'),
  (1, 'performance',   'R-FINANCE'),
  (1, 'performance',   'R-AUDITOR'),
  -- 专家与评审
  (1, 'expert-review', 'R-EXPERT'),
  (1, 'expert-review', 'R-MANAGER'),
  (1, 'expert-review', 'R-LEADER'),
  (1, 'expert-review', 'R-AUDITOR'),
  -- 科研档案
  (1, 'archive',       'R-ADMIN'),
  (1, 'archive',       'R-MANAGER'),
  (1, 'archive',       'R-AUDITOR'),
  -- 系统管理
  (1, 'admin-users',   'R-ADMIN'),
  (1, 'admin-roles',   'R-ADMIN'),
  (1, 'admin-roles',   'R-AUDITOR'),
  (1, 'admin-dicts',   'R-ADMIN')
ON CONFLICT (tenant_id, page_name, role_code) DO NOTHING;
