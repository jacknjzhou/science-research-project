/**
 * Curated overrides · 申报书撰写（View V3）
 * 命中真实契约路径：
 *   GET  /apply/applications                → PageResult<Application>
 *   GET  /apply/applications/{id}           → Application
 *   GET  /apply/applications/{id}/documents → ApplicationDoc[]
 *   GET  /apply/applications/{id}/budget    → BudgetDraft[]
 *   POST /apply/ai/draft                    → AiDraftResult
 * {id} 模板路径经 matchRoute 归一后命中；此处值与具体 id 无关，直接静态返回英雄屏语义数据。
 */

const APPLICATION = {
  id: 412,
  code: 'PRJ-APPLY-2026-00412',
  status: 'DRAFT',
  title: '基于扩散模型的复杂曲面自适应磨抛机理研究',
  project_type: '国家自然科学基金 · 面上项目',
  apply_code: 'E0513',
  pi_name: '周明远 · 研究员',
  member_count: 5,
  duration_months: 48,
  total_budget: '486000',
  ai_draft_marked: true,
  guideline_id: 3001,
  template_id: 88,
  updated_at: '2026-10-13T10:42:17Z',
}

const DOCUMENTS = [
  {
    id: 5001, application_id: 412, section_code: 'background', doc_version: 3, is_current: true, status: 'DRAFT',
    content_rich:
      '复杂大型曲面的高效高一致性磨抛是高端装备制造的共性瓶颈。现有刚性/恒力柔轮工具缺乏对曲面曲率时变特征的自适应能力，导致表面完整性不一致……本项目拟解决的关键科学问题是：材料去除率与接触载荷-曲率-转速的多场耦合映射机理，及其在线自整定边界。\n\n（本节由 AI 参考 3 项已中标同类项目辅助起草，PI 已修订 40%）',
    word_count: 612,
  },
  {
    id: 5002, application_id: 412, section_code: 'objective', doc_version: 2, is_current: true, status: 'DRAFT',
    content_rich:
      '建立曲面磨抛自适应调控理论模型 1 套；研制原理样机并在 3 类典型件验证，表面粗糙度 Ra≤0.2μm 一致性提升 30%；发表 SCI 论文 5-8 篇，授权发明专利 4 项。',
    word_count: 128,
  },
  { id: 5003, application_id: 412, section_code: 'content', doc_version: 1, is_current: true, status: 'DRAFT', content_rich: '', word_count: 0 },
  { id: 5004, application_id: 412, section_code: 'route', doc_version: 1, is_current: true, status: 'DRAFT', content_rich: '', word_count: 0 },
  { id: 5005, application_id: 412, section_code: 'innovation', doc_version: 1, is_current: true, status: 'DRAFT', content_rich: '', word_count: 0 },
  {
    id: 5006, application_id: 412, section_code: 'foundation', doc_version: 2, is_current: true, status: 'DRAFT',
    content_rich: '申请人长期从事机器人化磨抛与在位测量研究，主持面上项目 2 项，搭建了半物理仿真与力位混合控制实验平台，具备扎实研究基础。',
    word_count: 340,
  },
  { id: 5007, application_id: 412, section_code: 'schedule', doc_version: 1, is_current: true, status: 'DRAFT', content_rich: '', word_count: 0 },
  { id: 5008, application_id: 412, section_code: 'budget_note', doc_version: 1, is_current: true, status: 'DRAFT', content_rich: '预算科目与合规审查见下表（直接经费 48.6 万，间接费用按政策 20% 计提）。', word_count: 42 },
  { id: 5009, application_id: 412, section_code: 'attachments', doc_version: 1, is_current: true, status: 'DRAFT', content_rich: '', word_count: 0 },
]

const BUDGET = [
  { id: 6001, application_id: 412, subject_code: 'A1', subject_name: '设备费', fiscal_year: 2027, amount: '180000', ai_compliance_flag: 'OK', ai_compliance_reason: '', status: 'CHECKED' },
  { id: 6002, application_id: 412, subject_code: 'A2', subject_name: '材料/测试化验', fiscal_year: 2027, amount: '126000', ai_compliance_flag: 'OK', ai_compliance_reason: '', status: 'CHECKED' },
  { id: 6003, application_id: 412, subject_code: 'A3', subject_name: '劳务费（研究生）', fiscal_year: 2027, amount: '90000', ai_compliance_flag: 'WARN', ai_compliance_reason: '接近上限 20%', status: 'CHECKED' },
  { id: 6004, application_id: 412, subject_code: 'A4', subject_name: '差旅/会议', fiscal_year: 2027, amount: '60000', ai_compliance_flag: 'OK', ai_compliance_reason: '', status: 'CHECKED' },
  { id: 6005, application_id: 412, subject_code: 'A5', subject_name: '间接费用', fiscal_year: 2027, amount: '', ai_compliance_flag: 'UNKNOWN', ai_compliance_reason: '按政策计提', status: 'DRAFT' },
]

const AI_DRAFT_RESULT = {
  content:
    '§3 研究内容建议分三条主线：①多场耦合去除模型（理论）——建立材料去除率与接触载荷-曲率-转速的映射；②曲率在线估计与力位混合控制（方法）——以扩散模型生成轨迹先验，在线自整定边界；③典型件实验验证（验证）——面向 3 类复杂曲面件闭环验证。差异化点：去年资助的 12 项同类课题均基于传统阻抗控制，未引入生成式模型做轨迹先验，可作为创新点表述。',
  mode: 'FULL_DRAFT',
  confidence: '0.8600',
  references: [
    { project_code: 'PRJ-2024-00087', title: '在研，通过会议评审' },
    { project_code: '某工大 2025 面上', title: '自适应磨抛中标' },
    { project_code: 'E05 学部 2025', title: '资助清单（公开）' },
  ],
  watermark: 'AI 生成',
}

export const overrides: Record<string, unknown> = {
  'GET /apply/applications': { list: [APPLICATION], total: 1, page: 1, size: 20 },
  'GET /apply/applications/{id}': APPLICATION,
  'GET /apply/applications/{id}/documents': DOCUMENTS,
  'GET /apply/applications/{id}/budget': BUDGET,
  'POST /apply/ai/draft': AI_DRAFT_RESULT,
}
