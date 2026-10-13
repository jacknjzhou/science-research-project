/**
 * Curated overrides — 经费监督大屏（F-18 聚合 + D-06 大屏配置）
 * 命中真实契约：
 *   GET /dashboard/funding  经费监督大屏聚合数据（一图一舱三预警，F 模块 FundingDashboard）
 *   GET /dash/screens       大屏配置（D 模块 Screen：标题/主题/数据截至）
 * 注意：/dash/metrics/{code} 已由 dash.ts 接管，本文件不重复覆盖以免合并冲突；
 *      大屏的 D 指标一律复用 dash.ts 已知 code。F 字段 camelCase、D 字段 snake_case。
 */

// —— F-18 大屏聚合（含少量演示扩展字段，供 KPI/热力/预警渲染）——
const FUNDING = {
  totalBudget: '214830000.00', // 元 → 21483 万
  yearIncome: '133194600.00',
  executionRate: 68.4,
  violationCount: 23,
  // 扩展演示字段（schema 外，仅本屏使用）
  verticalRatio: 62, // 纵向占比 %
  horizontalRatio: 24, // 横向
  selfRatio: 14, // 自立
  expectedRate: 76, // 应达执行率
  deviatedProjects: 9,
  aiRejectedAmount: '612000.00', // 拒付 ¥61.2 万
  auditTraceRate: 99.6,
  evidenceMissing: 14,
  evidenceFixed: 11,
  aiBreakdown: [
    { name: '拆分报销', count: 7 },
    { name: '连号发票', count: 4 },
    { name: '类目异常', count: 12 },
  ],
  deptHeatmap: [
    { departmentId: 1, deptName: '制造所', executionRate: 88, amount: '38200000.00' },
    { departmentId: 2, deptName: '机器人所', executionRate: 74, amount: '30100000.00' },
    { departmentId: 3, deptName: '传感所', executionRate: 31, amount: '12600000.00' },
    { departmentId: 4, deptName: '材料所', executionRate: 66, amount: '21400000.00' },
    { departmentId: 5, deptName: '信息室', executionRate: 79, amount: '17800000.00' },
    { departmentId: 6, deptName: '工艺', executionRate: 42, amount: '9300000.00' },
    { departmentId: 7, deptName: '联合', executionRate: 71, amount: '15400000.00' },
  ],
  trend12Months: [
    { month: '1月', executionRate: 12 }, { month: '2月', executionRate: 18 },
    { month: '3月', executionRate: 27 }, { month: '4月', executionRate: 35 },
    { month: '5月', executionRate: 42 }, { month: '6月', executionRate: 55 },
    { month: '7月', executionRate: 35 }, { month: '8月', executionRate: 70 },
    { month: '9月', executionRate: 62 }, { month: '10月', executionRate: 88 },
    { month: '11月', executionRate: 94 }, { month: '12月', executionRate: 98 },
  ],
  // 全成本分摊（F-20 ↔ A-12）：折旧 / 耗材 / 仪器工时
  costPool: [
    { name: 'PRJ-2024-00087 全成本', direct: 72, indirect: 28, amount: '5120000.00', tone: '' },
    { name: '设备折旧归集', direct: 84, indirect: 16, amount: '386000.00', tone: 'blue' },
    { name: '耗材 · 危化品', direct: 46, indirect: 54, amount: '76000.00', tone: 'gold' },
    { name: '大型仪器共享工时', direct: 61, indirect: 39, amount: '42000.00', tone: '' },
  ],
  alerts: {
    during: [
      { level: 'p1', tag: '事中·高', text: 'PRJ-2024-00087 月均支出需达历史 2.3 倍（突击支出风险）→ PI 已确认关注' },
      { level: 'p1', tag: '事中·高', text: 'PRJ-2023-00042 差旅费 92% 集中于 12 月 → 财务复核' },
      { level: 'p1', tag: 'AI识别', text: '「同商家 3 日内连号 4 张发票」命中 EXP-2026-1193 → 拆分嫌疑，已转人工' },
    ],
    pre: [
      { level: 'p2', tag: '事前·中', text: '4 个在研项目劳务费科目执行超序时 30% → 已提示预算调剂' },
    ],
    post: [
      { level: 'p3', tag: '事后·低', text: '2 笔决算间接费用计提尾差 <1% → 自动豁免归档' },
    ],
  },
}

// —— D-06 大屏配置（标题 / 主题 / 数据截至）——
const SCREENS = {
  list: [
    {
      id: 5001,
      code: 'SCR-FUND-SUPERVISION',
      name: '科研经费监督 · 一舱三预警',
      theme: 'FUNDING',
      layout_json: { cols: 4 },
      widgets: [
        { widgetId: 'w1', type: 'KPI', dataMetricId: 'total_budget' },
        { widgetId: 'w2', type: 'BARS', dataMetricId: 'dept_execution' },
      ],
      rotation_seconds: 30,
      data_as_of_expr: 'T+1',
      status: 'PUBLISHED',
      legal_entity_id: null,
      created_at: '2026-09-01T00:00:00Z',
    },
  ],
  total: 1,
  page: 1,
  size: 20,
}

export const overrides: Record<string, unknown> = {
  'GET /dashboard/funding': FUNDING,
  'GET /dash/screens': SCREENS,
}
