/**
 * Curated overrides — 报销填单（F 模块 科研经费管理）
 * 命中真实契约：
 *   GET  /subjects                     预算科目树（支出科目下拉，F Subject）
 *   GET  /budgets/{budgetId}/lines     预算行余额（"我的经费水位" 进度条）
 *   GET  /expenses                     报销单分页（近 N 单状态列表）
 *   POST /expenses                     创建报销单 → 返回 DRAFT Expense（含 id，驱动 submit 链）
 *   POST /expense/ai-invoice-review    AI 发票预审建议（合规提示卡）
 * 值可为静态对象或 (url)=>data 函数；F 模块字段为 camelCase。
 */

// —— 预算科目：叶子科目用于报销表单下拉 ——
const SUBJECTS = [
  { id: 3001, code: 'F-MAT', name: '材料费', parentId: 3000, level: 2, category: 'DIRECT', isLeaf: true, ratioLimit: 0.6, status: 'ENABLED' },
  { id: 3002, code: 'F-TEST', name: '测试化验加工费', parentId: 3000, level: 2, category: 'DIRECT', isLeaf: true, ratioLimit: 0.3, status: 'ENABLED' },
  { id: 3003, code: 'F-EQP', name: '设备费', parentId: 3000, level: 2, category: 'DIRECT', isLeaf: true, ratioLimit: 0.5, status: 'ENABLED' },
  { id: 3004, code: 'F-TRAVEL', name: '差旅费', parentId: 3000, level: 2, category: 'DIRECT', isLeaf: true, ratioLimit: 0.15, status: 'ENABLED' },
  { id: 3005, code: 'F-LABOR', name: '劳务费', parentId: 3000, level: 2, category: 'DIRECT', isLeaf: true, ratioLimit: 0.2, status: 'ENABLED' },
  { id: 3006, code: 'F-IND', name: '间接费用', parentId: 3000, level: 2, category: 'INDIRECT', isLeaf: true, ratioLimit: 0.2, status: 'ENABLED' },
]

// —— 磨抛项目 (BUD 8801) 预算行余额，供"经费水位"条形 ——
const BUDGET_LINES = [
  { id: 88011, budgetId: 8801, subjectId: 3001, subjectName: '磨抛项目 · 材料费', amountPlanned: '1200000.00', amountAdjusted: '0.00', amountUsed: '888000.00', amountFrozen: '0.00', amountReleased: '0.00', remaining: '312000.00' },
  { id: 88012, budgetId: 8801, subjectId: 3003, subjectName: '磨抛项目 · 设备费', amountPlanned: '2600000.00', amountAdjusted: '0.00', amountUsed: '1118000.00', amountFrozen: '0.00', amountReleased: '0.00', remaining: '1482000.00' },
  { id: 88013, budgetId: 8801, subjectId: 3004, subjectName: '差旅包干', amountPlanned: '300000.00', amountAdjusted: '0.00', amountUsed: '231000.00', amountFrozen: '0.00', amountReleased: '0.00', remaining: '69000.00' },
]

// —— 近 4 单报销状态（右侧动态）——
const RECENT_EXPENSES = [
  { id: 1187, code: 'EXP-2026-1187', projectId: 87, amount: '23400.00', expenseType: 'MATERIAL', status: 'PAID', aiVerdict: 'PASS', aiConfidence: 0.97 },
  { id: 1190, code: 'EXP-2026-1190', projectId: 87, amount: '8200.00', expenseType: 'OTHER', status: 'HUMAN_REVIEW', aiVerdict: 'PASS', aiConfidence: 0.91 },
  { id: 1191, code: 'EXP-2026-1191', projectId: 103, amount: '1860.00', expenseType: 'TRAVEL', status: 'HUMAN_REVIEW', aiVerdict: 'REVIEW', aiConfidence: 0.82 },
  { id: 1193, code: 'EXP-2026-1193', projectId: 87, amount: '12000.00', expenseType: 'MATERIAL', status: 'REJECTED', aiVerdict: 'REJECT', aiConfidence: 0.95 },
]

export const overrides: Record<string, unknown> = {
  'GET /subjects': SUBJECTS,

  'GET /budgets/{budgetId}/lines': BUDGET_LINES,

  'GET /expenses': { list: RECENT_EXPENSES, total: RECENT_EXPENSES.length, page: 1, size: 20 },

  // 创建报销单：返回 DRAFT，id 供 submit / ai-review 串联
  'POST /expenses': {
    id: 1204,
    code: 'EXP-2026-1204',
    projectId: 87,
    budgetLineId: 88011,
    applicantUserId: 1001,
    amount: '25260.00',
    expenseType: 'MATERIAL',
    submitMode: '预算制',
    invoiceIds: [9004412317, 9020260928],
    status: 'DRAFT',
    aiVerdict: null,
    aiConfidence: null,
    invoiceCheckStatus: 'PENDING',
    submittedAt: null,
  },

  // AI 发票预审建议（F-15，仅出建议、可解释）
  'POST /expense/ai-invoice-review': {
    verdict: 'REVIEW',
    confidence: 0.82,
    issues: [
      { rule: 'TRIP_DATE_MISMATCH', reason: '行程单出发日期（9-28）早于出差审批起始日（9-30）2 天，请补充说明或修改出差单。', evidence: { invoice: '20260928', tripStart: '2026-09-30' }, clauseRef: '《院内差旅管理办法》第 8 条' },
      { rule: 'CONSECUTIVE_INVOICE', reason: '同一商家 3 日内连号发票已纳入查重，未见拆分报销嫌疑，放行。', evidence: { seller: 'XX精密工具公司', count: 2 }, clauseRef: '《科研经费支出内控细则》第 4 条' },
    ],
  },
}
