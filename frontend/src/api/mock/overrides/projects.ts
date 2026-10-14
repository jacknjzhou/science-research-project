/**
 * Curated overrides — 我的项目（module E · GET /project/mine）
 * 英雄屏：卡片墙。字段名对齐后端 mapper.go ToAPIProject（snake_case，NUMERIC→string）。
 * 金额单位为"元"（NUMERIC(18,2)），视图侧 toWan /10000 展示为"万"。
 */

const list = [
  {
    id: 90001, code: 'PRJ-2024-00087', tenant_id: 1, legal_entity_id: 1, status: 'EXECUTING',
    title: '面向高端装备的复杂曲面自适应磨抛关键技术研究', project_type: '国家重点研发计划',
    pi_user_id: 90001, department_id: 10, start_date: '2024-01-01', end_date: '2027-12-31',
    total_budget: '6800000.00', received_amount: '6100000.00', spent_amount: '4120000.00',
    health_score: 58, risk_level: 'HIGH', security_level: 'INTERNAL',
  },
  {
    id: 90002, code: 'PRJ-2025-00103', tenant_id: 1, legal_entity_id: 1, status: 'EXECUTING',
    title: '机器人柔性抓取中的触觉-视觉融合感知机制', project_type: '国自然面上',
    pi_user_id: 90001, department_id: 10, start_date: '2025-01-01', end_date: '2028-12-31',
    total_budget: '500000.00', received_amount: '500000.00', spent_amount: '310000.00',
    health_score: 86, risk_level: 'LOW', security_level: 'PUBLIC',
  },
  {
    id: 90003, code: 'PRJ-2026-00012', tenant_id: 1, legal_entity_id: 1, status: 'EXECUTING',
    title: '院所自立「探索者计划」· 数字孪生装配质量追溯', project_type: '院自立 · 包干制',
    pi_user_id: 90001, department_id: 10, start_date: '2026-03-01', end_date: '2028-02-28',
    total_budget: '800000.00', received_amount: '800000.00', spent_amount: '220000.00',
    health_score: 91, risk_level: 'LOW', security_level: 'PUBLIC',
  },
  {
    id: 90004, code: 'PRJ-2024-00559', tenant_id: 1, legal_entity_id: 1, status: 'CHANGING',
    title: '某型航空结构件搅拌摩擦焊工艺开发（横向）', project_type: '横向委托',
    pi_user_id: 90001, department_id: 12, start_date: '2024-06-01', end_date: '2026-12-31',
    total_budget: '1800000.00', received_amount: '1800000.00', spent_amount: '1560000.00',
    health_score: 72, risk_level: 'MED', security_level: 'INTERNAL',
  },
  {
    id: 90005, code: 'PRJ-2025-00230', tenant_id: 1, legal_entity_id: 1, status: 'EXECUTING',
    title: '在役风电主轴焊根缺陷的电磁超声检测', project_type: '省重点 · 参与（非PI）',
    pi_user_id: 90077, department_id: 11, start_date: '2025-05-01', end_date: '2027-04-30',
    total_budget: '880000.00', received_amount: '480000.00', spent_amount: '264000.00',
    health_score: 83, risk_level: 'LOW', security_level: 'PUBLIC',
  },
  {
    id: 90006, code: 'PRJ-2021-00044', tenant_id: 1, legal_entity_id: 1, status: 'CLOSED',
    title: '薄壁件低应力制造机理（已结题）', project_type: '国自然面上',
    pi_user_id: 90001, department_id: 10, start_date: '2021-01-01', end_date: '2025-12-31',
    actual_end_date: '2025-11-20',
    total_budget: '5200000.00', received_amount: '5200000.00', spent_amount: '5080000.00',
    health_score: 0, risk_level: 'LOW', security_level: 'PUBLIC',
  },
]

export const overrides: Record<string, unknown> = {
  'GET /project/mine': {
    list,
    total: list.length,
    page: 1,
    size: 20,
  },
}
