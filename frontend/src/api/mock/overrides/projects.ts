/**
 * Curated overrides — 我的项目（module E · GET /project/mine）
 * 英雄屏：卡片墙。字段名对齐 EProject（camelCase）。
 * 金额单位为"元"（NUMERIC(18,2)），视图侧 /10000 展示为"万"。
 */

const list = [
  {
    id: 90001, code: 'PRJ-2024-00087', tenantId: 1, legalEntityId: 1, status: 'EXECUTING',
    title: '面向高端装备的复杂曲面自适应磨抛关键技术研究', projectType: '国家重点研发计划',
    piUserId: 90001, departmentId: 10, startDate: '2024-01-01', endDate: '2027-12-31',
    totalBudget: '6800000.00', receivedAmount: '6100000.00', spentAmount: '4120000.00',
    healthScore: 58, riskLevel: 'HIGH', securityLevel: 'INTERNAL',
  },
  {
    id: 90002, code: 'PRJ-2025-00103', tenantId: 1, legalEntityId: 1, status: 'EXECUTING',
    title: '机器人柔性抓取中的触觉-视觉融合感知机制', projectType: '国自然面上',
    piUserId: 90001, departmentId: 10, startDate: '2025-01-01', endDate: '2028-12-31',
    totalBudget: '500000.00', receivedAmount: '500000.00', spentAmount: '310000.00',
    healthScore: 86, riskLevel: 'LOW', securityLevel: 'PUBLIC',
  },
  {
    id: 90003, code: 'PRJ-2026-00012', tenantId: 1, legalEntityId: 1, status: 'EXECUTING',
    title: '院所自立「探索者计划」· 数字孪生装配质量追溯', projectType: '院自立 · 包干制',
    piUserId: 90001, departmentId: 10, startDate: '2026-03-01', endDate: '2028-02-28',
    totalBudget: '800000.00', receivedAmount: '800000.00', spentAmount: '220000.00',
    healthScore: 91, riskLevel: 'LOW', securityLevel: 'PUBLIC',
  },
  {
    id: 90004, code: 'PRJ-2024-00559', tenantId: 1, legalEntityId: 1, status: 'CHANGING',
    title: '某型航空结构件搅拌摩擦焊工艺开发（横向）', projectType: '横向委托',
    piUserId: 90001, departmentId: 12, startDate: '2024-06-01', endDate: '2026-12-31',
    totalBudget: '1800000.00', receivedAmount: '1800000.00', spentAmount: '1560000.00',
    healthScore: 72, riskLevel: 'MED', securityLevel: 'INTERNAL',
  },
  {
    id: 90005, code: 'PRJ-2025-00230', tenantId: 1, legalEntityId: 1, status: 'EXECUTING',
    title: '在役风电主轴焊根缺陷的电磁超声检测', projectType: '省重点 · 参与（非PI）',
    piUserId: 90077, departmentId: 11, startDate: '2025-05-01', endDate: '2027-04-30',
    totalBudget: '880000.00', receivedAmount: '480000.00', spentAmount: '264000.00',
    healthScore: 83, riskLevel: 'LOW', securityLevel: 'PUBLIC',
  },
  {
    id: 90006, code: 'PRJ-2021-00044', tenantId: 1, legalEntityId: 1, status: 'CLOSED',
    title: '薄壁件低应力制造机理（已结题）', projectType: '国自然面上',
    piUserId: 90001, departmentId: 10, startDate: '2021-01-01', endDate: '2025-12-31',
    actualEndDate: '2025-11-20',
    totalBudget: '5200000.00', receivedAmount: '5200000.00', spentAmount: '5080000.00',
    healthScore: 0, riskLevel: 'LOW', securityLevel: 'PUBLIC',
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
