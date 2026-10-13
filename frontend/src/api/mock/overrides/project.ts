/**
 * Curated overrides — 项目详情（module E）
 * 英雄项目：PRJ-2024-00087。键用模板路径 `METHOD /project/{id}...`，函数入参为完整请求 URL。
 * 字段名对齐 EProjectDetail / ETask / EMilestone / ERiskWarning / EArchiveChecklist（camelCase）。
 * 额外扩展（契约未单列端点，视图内以可选字段消费）：fundingLines / members / ethics。
 */

function detail(url: string) {
  // 从 /api/v1/project/{id} 解析 id，缺省回落英雄项目 90001
  const id = Number(decodeURIComponent(url.split('/project/')[1]?.split('?')[0] || '')) || 90001
  return {
    id,
    code: 'PRJ-2024-00087',
    status: 'EXECUTING',
    title: '面向高端装备的复杂曲面自适应磨抛关键技术研究',
    projectType: '国家重点研发计划',
    piUserId: 90001,
    departmentId: 10,
    startDate: '2024-01-01',
    endDate: '2027-12-31',
    totalBudget: '6800000.00',
    receivedAmount: '6100000.00',
    spentAmount: '4120000.00',
    healthScore: 64,
    riskLevel: 'HIGH',
    securityLevel: 'INTERNAL',
    ethicsCaseId: 7011,

    kpi: { budgetExecRate: '0.6754', milestoneCompletionRate: '0.625', outputCount: 9 },

    aiSummary:
      '项目处于中后期攻关阶段，健康度较上月下降 14 分，主因经费执行偏离与个别任务逾期；建议优先推进 M6 样机集成，并在年内完成设备采购以拉平执行率。',

    timeline: [
      { node: '任务书签发', occurredAt: '2024-01-08T00:00:00Z', actor: 90001 },
      { node: '年度自查通过', occurredAt: '2024-12-20T00:00:00Z', actor: 90001 },
      { node: '中检查报告提交', occurredAt: '2025-08-30T00:00:00Z', actor: 90001 },
      { node: '参与单位变更批复', occurredAt: '2025-11-04T00:00:00Z', actor: 90002 },
      { node: 'M5 里程碑达成', occurredAt: '2026-03-15T00:00:00Z', actor: 90001 },
    ],

    // —— 视图扩展：经费概览科目行 ——
    fundingLines: [
      { subject: '设备费', approved: '280.0', used: '121.4', frozen: '18.0', rate: '0.43', status: 'warn' },
      { subject: '材料 / 测试化验加工', approved: '160.0', used: '118.9', frozen: '4.2', rate: '0.74', status: 'ok' },
      { subject: '差旅 / 会议 / 国际合作', approved: '68.0', used: '52.1', frozen: '0', rate: '0.77', status: 'ok' },
      { subject: '劳务费', approved: '96.0', used: '63.4', frozen: '1.1', rate: '0.66', status: 'ok' },
      { subject: '间接费用（计提）', approved: '76.0', used: '45.6', frozen: '—', rate: '0.60', status: 'info' },
    ],
    // —— 视图扩展：课题组成员头像 ——
    members: [
      { name: '周明远', role: 'PI' },
      { name: '李思远', role: '博后' },
      { name: '王振', role: '博士' },
      { name: '赵敏', role: '博士' },
      { name: '陈昊', role: '博士' },
      { name: '孙悦', role: '硕士' },
      { name: '周涛', role: '硕士' },
      { name: '吴磊', role: '硕士' },
    ],
    ethics: { caseId: 'ETH-2026-011', status: '有效' },
  }
}

const tasks = [
  {
    id: 8101, projectId: 90001, parentTaskId: null, name: 'T6.1 磨抛样机机械集成',
    ownerUserId: 90003, plannedStart: '2026-04-01', plannedEnd: '2026-12-31',
    actualStart: '2026-04-10', actualEnd: null, progressPercent: 55, weight: '0.1667', status: 'OVERDUE',
  },
  {
    id: 8102, projectId: 90001, parentTaskId: null, name: 'T6.2 力位混合控制器开发',
    ownerUserId: 90004, plannedStart: '2026-02-01', plannedEnd: '2027-03-31',
    actualStart: '2026-02-05', actualEnd: null, progressPercent: 70, weight: '0.1667', status: 'IN_PROGRESS',
  },
  {
    id: 8103, projectId: 90001, parentTaskId: null, name: 'T6.3 曲面曲率在线估计算法',
    ownerUserId: 90005, plannedStart: '2025-06-01', plannedEnd: '2026-06-30',
    actualStart: '2025-06-01', actualEnd: '2026-06-18', progressPercent: 100, weight: '0.1667', status: 'COMPLETED',
  },
  {
    id: 8104, projectId: 90001, parentTaskId: null, name: 'T7.1 三类典型件试验矩阵',
    ownerUserId: 90006, plannedStart: '2027-01-01', plannedEnd: '2027-09-30',
    actualStart: null, actualEnd: null, progressPercent: 0, weight: '0.1667', status: 'PENDING',
  },
  {
    id: 8105, projectId: 90001, parentTaskId: null, name: 'T7.2 一致性指标验证与结题',
    ownerUserId: 90001, plannedStart: '2027-06-01', plannedEnd: '2027-12-31',
    actualStart: null, actualEnd: null, progressPercent: 0, weight: '0.1667', status: 'PENDING',
  },
]

const milestones = [
  { id: 9101, projectId: 90001, name: 'M1 需求与方案论证', dueDate: '2024-06-30', actualDate: '2024-06-20', deliverableType: '方案报告', weight: '0.125', status: 'ACHIEVED' },
  { id: 9102, projectId: 90001, name: 'M2 关键算法原型', dueDate: '2024-12-31', actualDate: '2024-12-15', deliverableType: '算法原型', weight: '0.125', status: 'ACHIEVED' },
  { id: 9103, projectId: 90001, name: 'M3 力位混合控制仿真', dueDate: '2025-06-30', actualDate: '2025-06-10', deliverableType: '仿真报告', weight: '0.125', status: 'ACHIEVED' },
  { id: 9104, projectId: 90001, name: 'M4 曲率估计在线验证', dueDate: '2025-12-31', actualDate: '2025-12-05', deliverableType: '试验数据', weight: '0.125', status: 'ACHIEVED' },
  { id: 9105, projectId: 90001, name: 'M5 半物理平台联调', dueDate: '2026-03-31', actualDate: '2026-03-15', deliverableType: '联调记录', weight: '0.125', status: 'ACHIEVED' },
  { id: 9106, projectId: 90001, name: 'M6 样机集成', dueDate: '2026-12-31', actualDate: null, deliverableType: '样机', weight: '0.125', status: 'PENDING' },
  { id: 9107, projectId: 90001, name: 'M7 典型件试验验证', dueDate: '2027-06-30', actualDate: null, deliverableType: '试验报告', weight: '0.125', status: 'PENDING' },
  { id: 9108, projectId: 90001, name: 'M8 结题验收', dueDate: '2027-12-31', actualDate: null, deliverableType: '验收材料', weight: '0.125', status: 'PENDING' },
]

const riskWarnings = [
  {
    warningId: 1, projectId: 90001, level: 'HIGH', source: 'XGBOOST', ruleCode: 'R-BUDGET-RUSH',
    title: '突击支出风险',
    suggestion: '剩余 14 个月需支出 268 万，月均 19 万为历史均值 2.3 倍，建议尽快启动设备采购计划。',
    detectedAt: '2026-10-08T03:00:00Z', disposition: 'PENDING',
  },
  {
    warningId: 2, projectId: 90001, level: 'MED', source: 'RULE', ruleCode: 'R-TASK-OVERDUE',
    title: '任务逾期',
    suggestion: 'T6.1 磨抛样机机械集成逾期 12 天，建议复核外协加工排期并重设基线。',
    detectedAt: '2026-10-05T03:00:00Z', disposition: 'ACK',
  },
]

function archiveChecklist(url: string) {
  const id = Number(decodeURIComponent(url.split('/project/')[1]?.split('?')[0] || '')) || 90001
  return {
    id: 60001, projectId: id, projectType: '国家重点研发计划', stage: 'FINAL',
    checklistJson: [
      { item: '重点研发计划任务书（含签章）', required: true, mime: 'application/pdf', docId: 50001, uploaded: true },
      { item: '2025 年中检查报告与专家意见', required: true, mime: 'application/pdf', docId: 50002, uploaded: true },
      { item: '关于课题参与单位调整的批复', required: true, mime: 'application/pdf', docId: 50003, uploaded: true },
      { item: '专项经费到位通知 / 财务凭证包', required: true, mime: 'application/zip', docId: 50004, uploaded: true },
      { item: '代表性论文与知识产权清单', required: true, mime: 'application/pdf', docId: null, uploaded: false },
      { item: '结题自评价报告', required: true, mime: 'application/pdf', docId: null, uploaded: false },
    ],
    requiredCount: 6, completedCount: 4, completeness: '0.6667',
    blockedItems: ['代表性论文与知识产权清单', '结题自评价报告'], status: 'IN_PROGRESS',
  }
}

export const overrides: Record<string, unknown> = {
  'GET /project/{id}': detail,
  'GET /project/{id}/tasks': { tasks, milestones },
  'GET /project/{id}/risk-warnings': riskWarnings,
  'GET /project/{id}/archive-checklist': archiveChecklist,
}
