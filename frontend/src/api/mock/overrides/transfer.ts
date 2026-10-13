/**
 * Curated overrides —— 转化看板屏（module T）
 * 契约：05-科技成果转化-T.openapi.yaml
 *  - GET  /disclosure          披露列表（待转化成果）
 *  - GET  /deal                交易列表（进行中的交易 / 管道阶段）
 *  - POST /ai/opportunity      AI 转化机会识别（潜在买家匹配）
 *  - POST /deal/{id}/ai-pricing AI 定价参考
 * 命中键为 `METHOD /模板路径`；未命中仍由 generator 现场造数。
 */

// —— 待转化成果（披露）——
interface DiscCard {
  id: number
  code: string
  title: string
  output_code: string
  maturity_level: number
  expected_value: number
  status: string
  is_core_tech: boolean
}

// —— 进行中的交易 ——
interface DealRow {
  id: number
  code: string
  subject: string
  subject_code: string
  deal_type: string
  partner_name: string
  amount_text: string
  status: string
  stage: number // 0..5 对应 披露/评估/谈判/签约/到账/分配
  risk?: string
}

// —— AI 撮合推荐 ——
interface Opp {
  enterpartner_id: number
  company_name: string
  match_score: number
  confidence: number
  reason: string
  suggestion: string
  budget?: string
}

const disclosures: DiscCard[] = [
  { id: 7001, code: 'DISC-2026-0031', title: '电磁超声检测 + 智能磨抛专利族（3 件）', output_code: 'PAT-FAMILY-0114', maturity_level: 7, expected_value: 600, status: 'UNDER_EVAL', is_core_tech: true },
  { id: 7002, code: 'DISC-2026-0028', title: '曲面曲率实时估计与抛光机器人化算法', output_code: '软著 2026SR…', maturity_level: 6, expected_value: 120, status: 'SUBMITTED', is_core_tech: false },
  { id: 7003, code: 'DISC-2026-0019', title: '自适应减振结构专利族（授权）', output_code: '3 件 · 已授权', maturity_level: 8, expected_value: 300, status: 'DEALING', is_core_tech: true },
]

const deals: DealRow[] = [
  { id: 8101, code: 'DEAL-2026-0007', subject: '自适应磨抛执行器', subject_code: 'PAT-2025-0114', deal_type: '普通许可', partner_name: '沈阳某重装集团', amount_text: '¥180万+提成3%', status: 'UNDER_APPROVAL', stage: 3, risk: '合同审批 ⚠ · 改进成果归属条款冲突' },
  { id: 8102, code: 'DEAL-2026-0005', subject: '曲面曲率估计算法', subject_code: '软著 2026SR…', deal_type: '转让', partner_name: '苏州某智能制造', amount_text: '¥95万', status: 'PUBLICIZED', stage: 4 },
  { id: 8103, code: 'DEAL-2026-0002', subject: '减振结构专利族', subject_code: '3 件', deal_type: '作价投资', partner_name: 'Spinoff 筹备', amount_text: '评估 ¥600万', status: 'VALUATED', stage: 1 },
]

const opportunities: Opp[] = [
  { enterpartner_id: 9001, company_name: '某风电集团 · 「叶片修复自动化」技术需求榜', match_score: 0.91, confidence: 0.87, reason: '与你「电磁超声检测+磨抛」专利族语义相似 · 发布于 9-21', suggestion: '优先推介专利族，预算区间 ¥500-800万', budget: '¥500-800万' },
  { enterpartner_id: 9002, company_name: '某汽车模具厂 · 公开技改指南', match_score: 0.78, confidence: 0.71, reason: '曲面抛光工位机器人化改造意向 · 历史同类成交 ¥120 万', suggestion: '匹配抛光算法软著许可', budget: '¥120万' },
]

export const overrides: Record<string, unknown> = {
  // 披露列表（待转化成果池）
  'GET /disclosure': { list: disclosures, total: 6, page: 1, size: 20 },

  // 交易列表（进行中的交易 / 状态机阶段）
  'GET /deal': { list: deals, total: 3, page: 1, size: 20 },

  // AI 转化机会识别（潜在买家推荐清单）
  'POST /ai/opportunity': { list: opportunities },

  // AI 定价参考（供看板按钮 toast 展示区间）
  'POST /deal/{id}/ai-pricing': {
    price_low: 160,
    price_high: 240,
    currency: '万元',
    confidence: 0.82,
    basis: '标的技术 + 3 笔可比许可交易 + 行业指标',
    comparables: [
      { deal_code: 'DEAL-2024-0019', amount: 180, year: 2024 },
      { deal_code: 'DEAL-2023-0102', amount: 210, year: 2023 },
    ],
    disclaimer: '最终定价以评估机构报告与谈判为准',
  },

  // 转化看板顶部统计（本年到账 / 奖励到人，无独立契约端点，用 /distribution/mine 承载）
  'GET /distribution/mine': {
    list: [],
    total: 0,
    page: 1,
    size: 20,
    summary: { year_income: 412, year_distributed: 247, split: '团队 70 / 院所 15 / 个人 15' },
  },
}
