/**
 * Curated overrides —— 成果认领屏（module R）
 * 契约：04-科研成果管理-R.openapi.yaml
 *  - GET  /output/pending-claim  待认领成果列表
 *  - GET  /output/mine           我的成果汇总（成果统计）
 * 命中键为 `METHOD /模板路径`；未命中仍由 generator 现场造数。
 */

interface ClaimCard {
  id: number
  code: string
  output_type: 'PAPER' | 'PATENT' | 'SOFTWARE'
  title: string
  authors: string
  venue: string
  year: number
  source: string
  match_confidence: number
  claim_status: string
  doubt?: string
  badges?: { label: string; cls: string }[]
  suggest?: string
  suggest_id?: number
}

const pending: ClaimCard[] = [
  {
    id: 5101,
    code: 'OUT-2026-05101',
    output_type: 'PAPER',
    title: 'Diffusion-guided trajectory priors for robotic surface finishing',
    authors: 'Mingyuan Zhou*, Li K., Wang H.',
    venue: 'Robotics and Computer-Integrated Manufacturing',
    year: 2026,
    source: 'WOS',
    match_confidence: 0.96,
    claim_status: 'PENDING_CLAIM',
    badges: [
      { label: 'SCI Q1', cls: 'ok' },
      { label: 'IF 7.6', cls: 'info' },
      { label: '通讯作者', cls: 'warn' },
    ],
    suggest: 'PRJ-2024-00087（论文致谢含项目号）',
    suggest_id: 87,
  },
  {
    id: 5102,
    code: 'PAT-2025-0114',
    output_type: 'PATENT',
    title: '自适应磨抛末端执行器及其力位混合控制方法',
    authors: '周明远，李工，王同学',
    venue: 'CN 119xxxxxx · 实审 · 代理机构协同',
    year: 2025,
    source: 'CNIPA',
    match_confidence: 0.88,
    claim_status: 'PENDING_CLAIM',
    badges: [{ label: '发明专利', cls: 'info' }],
  },
  {
    id: 5103,
    code: 'OUT-2026-05103',
    output_type: 'PAPER',
    title: 'On chatter suppression with generative priors',
    authors: '—',
    venue: 'Journal of Sound and Vibration · 单位地址含 "Qiyuan…" · ORCID 未匹配',
    year: 2026,
    source: 'SCOPUS',
    match_confidence: 0.61,
    claim_status: 'DOUBTFUL',
    doubt: '同名歧义："M. Zhou" 与本院 3 位学者重名',
    badges: [{ label: '需人工确认', cls: 'warn' }],
  },
]

export const overrides: Record<string, unknown> = {
  // 待认领列表（首次登录强引导）
  'GET /output/pending-claim': {
    list: pending,
    total: 12,
    page: 1,
    size: 20,
  },

  // 我的成果汇总（成果统计：total 作为本年度成果数）
  'GET /output/mine': {
    list: [],
    total: 23,
    page: 1,
    size: 20,
    summary: { yearly_outputs: 23, total_cited: 186, pending_claim: 12 },
  },
}
