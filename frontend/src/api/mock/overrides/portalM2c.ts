/**
 * M2-c 门户 mock（C3 专家 / C4 供应商 / C5 通知）：
 *   POST /portal/expert-apply、GET /portal/expert/credit|reviews|activities、
 *   GET /expert-applications、POST /expert-applications/{id}/audit、
 *   GET /portal/supplier/inquiries、POST /portal/supplier/inquiries/{id}:quote、
 *   GET /portal/supplier/contracts
 */
function nowIso(): string {
  return new Date().toISOString()
}

function num2(v: unknown): string {
  const n = Number(v)
  return (isNaN(n) ? 0 : n).toFixed(2)
}

function pathId(url: string, re: RegExp): number {
  const m = url.match(re)
  return m ? Number(m[1]) : 0
}

interface MockExpertApp {
  id: number
  code: string
  status: string
  name: string
  title: string | null
  org_name: string | null
  phone: string | null
  email: string | null
  field_tags: string[]
  created_at: string
  audited_at: string | null
  reject_reason: string | null
}

const EXPERT_APPS: MockExpertApp[] = [
  {
    id: 1, code: 'NEX-2026-000001', status: 'CANDIDATE', name: '李外部',
    title: '教授', org_name: '合作示例大学', phone: '13800000011',
    email: 'li@example.edu.cn', field_tags: ['人工智能', '数据治理'],
    created_at: '2026-11-17T02:00:00Z', audited_at: null, reject_reason: null,
  },
  {
    id: 2, code: 'NEX-2026-000002', status: 'ACTIVE', name: '王已审',
    title: '研究员', org_name: '外部研究院', phone: null,
    email: 'wang@example.org', field_tags: ['材料科学'],
    created_at: '2026-11-10T02:00:00Z', audited_at: '2026-11-11T02:00:00Z', reject_reason: null,
  },
]

interface MockInquiry {
  id: number
  code: string
  method: string
  status: string
  title: string
  category: string
  open_at: string | null
  quoted: boolean
  my_amount: string | null
}

const INQUIRIES: MockInquiry[] = [
  {
    id: 1, code: 'BID-2026-000011', method: '询价', status: 'PUBLICIZING',
    title: '高性能服务器', category: '设备', open_at: '2026-11-25T02:00:00Z',
    quoted: false, my_amount: null,
  },
  {
    id: 2, code: 'BID-2026-000012', method: '竞争性谈判', status: 'AWARDED',
    title: '实验试剂耗材', category: '试剂耗材', open_at: '2026-11-12T02:00:00Z',
    quoted: true, my_amount: '48200.00',
  },
]

const CONTRACTS = [
  {
    id: 1, code: 'CON-2026-000201', name: '高性能服务器采购', amount: '100000.00',
    signed_at: '2026-10-01', end_date: '2027-09-30', status: 'ACTIVE',
    pay_phase_count: 2, paid_amount: '40000.00', paid_ratio: '0.40',
  },
]

const CREDIT = {
  expert_id: 2, name: '王已审', review_count: 6, invited_count: 8,
  accepted_count: 6, declined_count: 2, expired_count: 0,
  accept_rate: '0.75', on_time_rate: '0.83', abstain_count: 0,
  avg_score: '88.20', last_review_at: '2026-11-15T08:00:00Z',
}

const REVIEWS = [
  {
    id: 11, task_id: 501, title: '2026 年度开放课题结题评审', biz_type: 'FINAL_ACCEPT',
    task_status: 'CONCLUDED', response: 'ACCEPT',
    invited_at: '2026-11-08T02:00:00Z', responded_at: '2026-11-08T04:00:00Z',
  },
  {
    id: 12, task_id: 502, title: '中期检查评审（机构 A）', biz_type: 'MID_CHECK',
    task_status: 'SCORING', response: 'PENDING',
    invited_at: '2026-11-16T02:00:00Z', responded_at: null,
  },
]

const ACTIVITIES = [
  {
    id: 21, title: '前沿技术学术沙龙', activity_type: 'SEMINAR', status: 'APPROVED',
    start_at: '2026-12-01T01:00:00Z', venue: '综合楼报告厅', role: 'SPEAKER',
  },
]

export const portalM2cOverrides: Record<string, unknown> = {
  'POST /portal/expert-apply': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    const id = EXPERT_APPS.length + 1
    const row: MockExpertApp = {
      id, code: `NEX-2026-${String(id).padStart(6, '0')}`, status: 'CANDIDATE',
      name: b.name || '未填姓名', title: b.title ?? null, org_name: b.org_name ?? null,
      phone: b.phone ?? null, email: b.email ?? null,
      field_tags: Array.isArray(b.field_tags) ? b.field_tags : [],
      created_at: nowIso(), audited_at: null, reject_reason: null,
    }
    EXPERT_APPS.unshift(row)
    return row
  }) as unknown,

  'GET /expert-applications': ((url: string) => {
    const q = url.includes('?') ? new URLSearchParams(url.slice(url.indexOf('?') + 1)) : null
    const status = q?.get('status') || 'CANDIDATE'
    const rows = status === 'ALL' ? EXPERT_APPS : EXPERT_APPS.filter((x) => x.status === status)
    return { list: [...rows].sort((a, b) => b.id - a.id), total: rows.length, page: 1, size: 50 }
  }) as unknown,

  'POST /expert-applications/{id}/audit': ((url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    const row = EXPERT_APPS.find((x) => x.id === pathId(url, /expert-applications\/(\d+)\/audit/))
    if (row) {
      row.status = b.action === 'APPROVE' ? 'ACTIVE' : 'SUSPENDED'
      row.audited_at = nowIso()
      row.reject_reason = b.action === 'REJECT' ? (b.reason ?? null) : null
    }
    return row || {}
  }) as unknown,

  'GET /portal/expert/credit': CREDIT,

  'GET /portal/expert/reviews': { list: REVIEWS, total: REVIEWS.length },

  'GET /portal/expert/activities': { list: ACTIVITIES, total: ACTIVITIES.length },

  'GET /portal/supplier/inquiries': { list: INQUIRIES, total: INQUIRIES.length },

  'POST /portal/supplier/inquiries/{id}:quote': ((url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    const id = pathId(url, /inquiries\/(\d+):quote/)
    const row = INQUIRIES.find((x) => x.id === id)
    if (row) {
      row.quoted = true
      row.my_amount = num2(b.totalAmount)
    }
    return { id, totalAmount: num2(b.totalAmount), quoted: true }
  }) as unknown,

  'GET /portal/supplier/contracts': { list: CONTRACTS, total: CONTRACTS.length },
}
