/**
 * Curated overrides —— 成果台账 / 认领屏（module R）
 * 契约：04-科研成果管理-R.openapi.yaml
 *  - GET  /output            成果台账分页（多条件过滤）
 *  - GET  /output/pending-claim  待认领卡片（首次登录强引导）
 *  - GET  /output/mine        我的成果
 * 命中键为 `METHOD /模板路径`；未命中仍由 generator 现场造数。
 *
 * 「真实化」要点：mock 行严格对齐后端 mapper.go ToAPIOutput 的 snake_case 契约字段
 * （authors/affiliations/project_ids 为数组；match_confidence 为 number；无 venue/year/suggest
 * 这类视图态字段——展示层从 publish_date / source / claim_status 派生）。
 */

interface AuthorItem {
  user_id: number | null
  name: string
  order?: number
  is_corresponding?: boolean
  share_pct?: number
  orcid?: string | null
}

/** 契约 Output（对齐 design/04 components.schemas.Output）。 */
interface Output {
  id: number
  code: string | null
  tenant_id: number
  status: string
  output_type: string
  title: string
  title_en: string | null
  abstract: string | null
  publish_date: string | null
  authors: AuthorItem[]
  external_author_names: { name: string; inst: string }[]
  affiliations: { user_id: number | null; inst_id: number | null; is_primary: boolean }[]
  project_ids: number[]
  language: string | null
  source: string
  is_claimed: boolean
  claim_status: string
  match_confidence: number | null
  department_id: number | null
  legal_entity_id: number
  security_level: string
  created_at: string
  updated_at: string
  remark: string | null
}

// 当前登录演示用户（与 seed 的 authors.user_id 对齐，用于「命中本人」的认领/我的列表）。
const ME = 100

function mk(o: Partial<Output> & Pick<Output, 'id' | 'output_type' | 'title' | 'status'>): Output {
  const ts = '2026-03-01T08:00:00Z'
  return {
    code: null,
    tenant_id: 1,
    title_en: null,
    abstract: null,
    publish_date: null,
    authors: [],
    external_author_names: [],
    affiliations: [],
    project_ids: [],
    language: 'zh',
    source: 'MANUAL',
    is_claimed: false,
    claim_status: 'UNCLAIMED',
    match_confidence: null,
    department_id: null,
    legal_entity_id: 1,
    security_level: 'INTERNAL',
    created_at: ts,
    updated_at: ts,
    remark: null,
    ...o,
  }
}

// —— 成果台账（GET /output）：跨类型/状态混合，供筛选与统计演示 ——
const ledger: Output[] = [
  mk({
    id: 5001, code: 'OUT-2026-05001', status: 'COUNTED_FOR_PERFORMANCE', output_type: 'PAPER',
    title: '面向高端装备复杂曲面的自适应磨抛轨迹规划方法', title_en: 'Adaptive Trajectory Planning for Complex Surface Polishing',
    publish_date: '2026-02-18', source: 'WOS', is_claimed: true, claim_status: 'CLAIMED',
    match_confidence: 0.94, project_ids: [90001],
    authors: [
      { user_id: ME, name: '周明远', order: 1, is_corresponding: true },
      { user_id: 102, name: '李工', order: 2 },
    ],
    affiliations: [{ user_id: ME, inst_id: 10, is_primary: true }],
    remark: 'SCI Q1 · IF 7.6 · 已计入 2026 绩效',
  }),
  mk({
    id: 5002, code: 'PAT-2025-0114', status: 'ASSIGNED_TO_PROJECT', output_type: 'PATENT',
    title: '自适应磨抛末端执行器及其力位混合控制方法',
    publish_date: '2025-11-03', source: 'CNIPA', is_claimed: true, claim_status: 'CLAIMED',
    language: 'zh', project_ids: [90001, 90004],
    authors: [{ user_id: ME, name: '周明远', order: 1, is_corresponding: true }, { user_id: 103, name: '王同学', order: 2 }],
    external_author_names: [],
    remark: '发明专利 · 实审中',
  }),
  mk({
    id: 5003, status: 'CLAIMED', output_type: 'SOFTWARE',
    title: '数字孪生装配质量追溯系统 V1.0', publish_date: '2026-01-20', source: 'MANUAL',
    is_claimed: true, claim_status: 'CLAIMED', project_ids: [90003],
    authors: [{ user_id: 104, name: '赵敏', order: 1 }, { user_id: ME, name: '周明远', order: 2 }],
    remark: '软著登记号 2026SR0xxxxx',
  }),
  mk({
    id: 5004, status: 'PENDING_CLAIM', output_type: 'PAPER',
    title: 'On chatter suppression with generative priors',
    publish_date: '2026-03-05', source: 'SCOPUS', claim_status: 'DOUBTFUL', match_confidence: 0.61,
    language: 'en',
    authors: [{ user_id: null, name: 'M. Zhou', order: 1 }],
    external_author_names: [{ name: 'M. Zhou', inst: 'Univ. of Sound & Vibration' }],
    remark: '同名歧义，待人工确认',
  }),
  mk({
    id: 5005, status: 'AUTO_FETCHED', output_type: 'AWARD',
    title: '省科技进步三等奖（磨抛工艺团队）', publish_date: '2025-06-01', source: 'FETCH',
    claim_status: 'PENDING', match_confidence: 0.41,
    authors: [{ user_id: ME, name: '周明远', order: 5 }],
    remark: '批量抓取 · 低置信',
  }),
  mk({
    id: 5006, code: 'OUT-2025-05006', status: 'CLAIMED', output_type: 'STANDARD',
    title: '《精密磨削表面质量评定规范》（参与起草）', publish_date: '2025-09-12', source: 'MANUAL',
    is_claimed: true, claim_status: 'CLAIMED', project_ids: [90002],
    authors: [{ user_id: 105, name: '陈立', order: 1 }, { user_id: ME, name: '周明远', order: 3 }],
  }),
  mk({
    id: 5007, status: 'MANUAL_DRAFT', output_type: 'PAPER',
    title: '触觉-视觉融合柔性抓取感知机制（在投）', publish_date: null, source: 'MANUAL',
    is_claimed: true, claim_status: 'CLAIMED', language: 'en',
    authors: [{ user_id: ME, name: 'Zhou Mingyuan', order: 1, is_corresponding: true }],
    security_level: 'SECRET', remark: '手稿录入 · 未发表',
  }),
  mk({
    id: 5008, code: 'DAT-2026-05008', status: 'ASSIGNED_TO_PROJECT', output_type: 'DATASET',
    title: '复杂曲面磨抛工艺参数数据集', publish_date: '2026-02-01', source: 'MANUAL',
    is_claimed: true, claim_status: 'CLAIMED', project_ids: [90003],
    authors: [{ user_id: 106, name: '孙博', order: 1 }, { user_id: ME, name: '周明远', order: 2 }],
    security_level: 'PUBLIC',
  }),
]

// —— 待认领（GET /output/pending-claim）：命中本人 authors，含高置信与存疑 ——
const pendingClaim: Output[] = [
  mk({
    id: 5001, code: 'OUT-2026-05001', status: 'PENDING_CLAIM', output_type: 'PAPER',
    title: '面向高端装备复杂曲面的自适应磨抛轨迹规划方法', publish_date: '2026-02-18',
    source: 'WOS', claim_status: 'PENDING', match_confidence: 0.96,
    authors: [{ user_id: ME, name: '周明远', order: 1, is_corresponding: true }, { user_id: 102, name: '李工', order: 2 }],
    affiliations: [{ user_id: ME, inst_id: 10, is_primary: true }],
    remark: 'SCI Q1 · IF 7.6 · 论文致谢含项目号 PRJ-2024-00087',
  }),
  mk({
    id: 5002, code: 'PAT-2025-0114', status: 'PENDING_CLAIM', output_type: 'PATENT',
    title: '自适应磨抛末端执行器及其力位混合控制方法', publish_date: '2025-11-03',
    source: 'CNIPA', claim_status: 'PENDING', match_confidence: 0.88,
    authors: [{ user_id: ME, name: '周明远', order: 1, is_corresponding: true }],
    remark: '发明专利 · 实审',
  }),
  mk({
    id: 5005, status: 'AUTO_FETCHED', output_type: 'AWARD',
    title: '省科技进步三等奖（磨抛工艺团队）', publish_date: '2025-06-01', source: 'FETCH',
    claim_status: 'DOUBTFUL', match_confidence: 0.41,
    authors: [{ user_id: ME, name: '周明远', order: 5 }],
    remark: '团队奖 · 排名靠后，请确认是否计入个人',
  }),
  mk({
    id: 5004, status: 'PENDING_CLAIM', output_type: 'PAPER',
    title: 'On chatter suppression with generative priors', publish_date: '2026-03-05',
    source: 'SCOPUS', claim_status: 'DOUBTFUL', match_confidence: 0.61, language: 'en',
    authors: [{ user_id: null, name: 'M. Zhou', order: 1 }],
    external_author_names: [{ name: 'M. Zhou', inst: 'Univ. of Sound & Vibration' }],
    remark: '同名歧义："M. Zhou" 与本院 3 位学者重名',
  }),
]

// —— 我的成果（GET /output/mine）：已认领/已归属项目 ——
const mine: Output[] = ledger.filter((o) => o.is_claimed)

function pageWrap(rows: Output[], total: number, params: Record<string, string>) {
  const list = rows
  return {
    list,
    total: total ?? rows.length,
    page: Number(params.page || 1),
    size: Number(params.size || 20),
  }
}

function query(url: string): Record<string, string> {
  try {
    const u = new URL(url, 'http://x.local')
    const out: Record<string, string> = {}
    u.searchParams.forEach((v, k) => (out[k] = v))
    return out
  } catch {
    return {}
  }
}

export const overrides: Record<string, unknown> = {
  // 台账：按 output_type/status/source/claim_status 组合过滤（演示仅类型/状态维度），命中本人可见全集
  'GET /output': (url: string) => {
    const q = query(url)
    let rows = ledger
    if (q.output_type) rows = rows.filter((r) => r.output_type === q.output_type)
    if (q.status) rows = rows.filter((r) => r.status === q.status)
    if (q.claim_status) rows = rows.filter((r) => r.claim_status === q.claim_status)
    if (q.source) rows = rows.filter((r) => r.source === q.source)
    if (q.keyword) rows = rows.filter((r) => r.title.includes(q.keyword) || (r.code || '').includes(q.keyword))
    if (q.year) rows = rows.filter((r) => (r.publish_date || '').startsWith(q.year))
    return pageWrap(rows, rows.length, q)
  },

  'GET /output/pending-claim': (url: string) => {
    const q = query(url)
    let rows = pendingClaim
    if (q.min_confidence) rows = rows.filter((r) => (r.match_confidence ?? 0) >= Number(q.min_confidence))
    if (q.output_type) rows = rows.filter((r) => r.output_type === q.output_type)
    return pageWrap(rows, 12, q)
  },

  'GET /output/mine': (url: string) => {
    const q = query(url)
    let rows = mine
    if (q.output_type) rows = rows.filter((r) => r.output_type === q.output_type)
    if (q.year) rows = rows.filter((r) => (r.publish_date || '').startsWith(q.year))
    return pageWrap(rows, rows.length, q)
  },
}
