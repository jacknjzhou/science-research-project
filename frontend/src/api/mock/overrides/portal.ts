/**
 * Curated overrides · 机构注册 / 门户 / 资质审核（M2-a C1）
 * 真实契约：12-用户与权限-U.openapi.yaml（6 路径，全 snake_case）
 *   POST /portal/register（公开）、GET|PUT /portal/org、GET /portal/home、
 *   GET /partner-orgs、POST /partner-orgs/{id}/audit
 */

import { portalM2cOverrides } from './portalM2c'

interface MockOrg {
  id: number
  code: string
  tenant_id: number
  name: string
  short_name: string | null
  credit_code: string
  org_type: string
  contact_name: string
  contact_phone: string
  contact_email: string
  address: string | null
  status: string
  audit_user_id: number | null
  audited_at: string | null
  reject_reason: string | null
  created_at: string
}

const ORGS: MockOrg[] = [
  {
    id: 1, code: 'PTN-2026-000001', tenant_id: 1, name: '合作示例大学',
    short_name: '示例大', credit_code: '91310000MA1K3XY12A', org_type: 'UNIVERSITY',
    contact_name: '张联系', contact_phone: '13800000001', contact_email: 'partner@example.edu.cn',
    address: '上海市杨浦区示例路 1 号', status: 'APPROVED', audit_user_id: 2,
    audited_at: '2026-11-01T02:00:00Z', reject_reason: null, created_at: '2026-10-28T02:00:00Z',
  },
  {
    id: 2, code: 'PTN-2026-000002', tenant_id: 1, name: '待审核协作单位',
    short_name: null, credit_code: '91110000MA2C4AB34B', org_type: 'COLLAB',
    contact_name: '李经办', contact_phone: '13800000002', contact_email: 'pending@example.com',
    address: null, status: 'PENDING', audit_user_id: null,
    audited_at: null, reject_reason: null, created_at: '2026-11-17T06:00:00Z',
  },
]

const HOME = {
  org: ORGS[0],
  announcements: [
    {
      id: 9001, typ: 'ANNOUNCE', title: '机构资质审核通过',
      content: '贵单位资质已通过审核，账号已激活，可查看本单位相关数据与申报指南。',
      created_at: '2026-11-01T02:00:00Z',
    },
    {
      id: 9002, typ: 'ANNOUNCE', title: '2026 年度开放课题征集启动',
      content: '本年度开放课题指南已发布，请在申报期内在线填报。',
      created_at: '2026-11-10T01:00:00Z',
    },
  ],
  guidelines: [
    {
      id: 3003, title: '启元研究院 2026 年度「探索者计划」自立项目（第三批）',
      project_type: 'ZIGE', apply_start_at: '2026-09-20T00:00:00Z',
      apply_end_at: '2026-12-18T00:00:00Z', publish_at: '2026-09-18T00:00:00Z',
    },
    {
      id: 3001, title: '2027 年度国家自然科学基金 · 面上项目 / 青年科学基金',
      project_type: 'NSFC', apply_start_at: '2026-09-01T00:00:00Z',
      apply_end_at: '2026-12-25T00:00:00Z', publish_at: '2026-08-30T00:00:00Z',
    },
  ],
  todos: { unread_notifications: 2 },
}

function idOf(url: string): number {
  const m = url.match(/partner-orgs\/(\d+)/)
  return Number(m?.[1] || 0)
}

export const overrides: Record<string, unknown> = {
  // 注册：返回新建的 PENDING 机构（mock 不回写 ORGS，避免污染演示数据）
  'POST /portal/register': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    return {
      ...ORGS[1],
      id: 99,
      code: 'PTN-2026-000099',
      name: b.org_name || '新注册机构',
      short_name: null,
      credit_code: b.credit_code || '91310000MA1K3XY99Z',
      org_type: b.org_type || 'COLLAB',
      contact_name: b.contact_name || '—',
      contact_phone: b.contact_phone || null,
      contact_email: b.contact_email || null,
      status: 'PENDING',
      created_at: new Date().toISOString(),
    }
  }) as unknown,

  'GET /portal/home': HOME,

  'GET /portal/org': ORGS[0],

  'PUT /portal/org': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    // 只接受四个联系字段（镜像后端白名单）
    for (const k of ['contact_name', 'contact_phone', 'contact_email', 'address']) {
      if (b[k] !== undefined) (ORGS[0] as any)[k] = b[k]
    }
    return ORGS[0]
  }) as unknown,

  'GET /partner-orgs': ((url: string) => {
    // 与后端一致：status/keyword 过滤，-id 倒序
    const q = url.includes('?') ? new URLSearchParams(url.slice(url.indexOf('?') + 1)) : null
    const status = q?.get('status') || ''
    const kw = (q?.get('keyword') || '').toLowerCase()
    let rows = ORGS.filter((o) => !status || o.status === status)
    if (kw) {
      rows = rows.filter(
        (o) => o.name.toLowerCase().includes(kw) || o.credit_code.includes(kw),
      )
    }
    rows = [...rows].sort((a, b) => b.id - a.id)
    return { list: rows, total: rows.length, page: 1, size: 20 }
  }) as unknown,

  'POST /partner-orgs/{id}/audit': ((url: string, ctx: { body: unknown }) => {
    const id = idOf(url)
    const o = ORGS.find((x) => x.id === id) || ORGS[1]
    const b = (ctx.body || {}) as Record<string, any>
    if (o.status !== 'PENDING') {
      // 与后端一致：同动作重放幂等；冲突动作不改变状态
      // （mock 层只能回 200，真后端此处是 409/40901，演示模式下仅提示不改数据）
      if ((b.action === 'APPROVE' && o.status === 'APPROVED') ||
          (b.action === 'REJECT' && o.status === 'REJECTED')) return o
      console.warn('[mock] 机构已审核完成，真后端返回 409/40901')
      return o
    }
    if (b.action === 'APPROVE') {
      o.status = 'APPROVED'
      o.audit_user_id = 2
      o.audited_at = new Date().toISOString()
      o.reject_reason = null
    } else if (b.action === 'REJECT') {
      o.status = 'REJECTED'
      o.audit_user_id = 2
      o.audited_at = new Date().toISOString()
      o.reject_reason = b.reason || '资质不符'
    }
    return o
  }) as unknown,
}

// ===========================================================================
// M2-b 开放课题全流程（C2）：指南建议 / 申报 / 任务书 / 阶段汇报 / 验收
// 契约：01-P（guide-suggestions、applications、task-books）+ 02-E（progress-report、final-accept）
// 全部 snake_case；mock 仅演示主流程（提交/采纳/签章/汇报），不含权限与冲突校验。
// ===========================================================================
interface MockSuggestion {
  id: number; code: string; tenant_id: number; title: string; content_rich: string | null
  org_id: number; status: string; guideline_id: number | null
  reject_reason: string | null; created_at: string
}
interface MockApplication {
  id: number; code: string; tenant_id: number; title: string; project_type: string
  status: string; applicant_org_id: number; applicant_type: string
  total_budget: string; duration_months: number; abstract: string | null
  pi_user_id: number; updated_at: string
}
interface MockTaskBook {
  id: number; code: string; application_id: number; status: string
  content_snapshot: Record<string, any>; sign_records: Array<Record<string, any>>
  effective_date: string | null; project_id: number | null; print_template_code: string
}
interface MockReport {
  id: number; project_id: number; period: string; report_type: string
  progress_percent: number; content_rich: string | null; submitted_at: string
}
interface MockFinalAccept {
  id: number; project_id: number; status: string; output_summary: string | null
  apply_at: string; accept_at: string | null; approval_doc_id: number | null
}

const SUGGESTIONS: MockSuggestion[] = [
  {
    id: 1, code: 'SUG-2026-000001', tenant_id: 1,
    title: '面向产业场景的大模型评测方法',
    content_rich: '建议围绕行业大模型的可信评测建立方法体系与基准数据集。',
    org_id: 1, status: 'PENDING', guideline_id: null, reject_reason: null,
    created_at: '2026-11-12T03:00:00Z',
  },
]
const APPLICATIONS: MockApplication[] = [
  {
    id: 1, code: 'APP-2026-000001', tenant_id: 1, title: '开放数据可信治理研究',
    project_type: '开放课题', status: 'DRAFT', applicant_org_id: 1,
    applicant_type: 'EXTERNAL', total_budget: '100000.00', duration_months: 12,
    abstract: '研究开放数据共享中的可信治理机制。', pi_user_id: 9,
    updated_at: '2026-11-17T02:00:00Z',
  },
]
const TASK_BOOKS: MockTaskBook[] = []
const REPORTS: MockReport[] = []
const FINAL_ACCEPTS: MockFinalAccept[] = []

const nowIso = () => new Date().toISOString()
/** M2-b 段专用：取路径末段的数字 id（本段 URL 形如 /apply/task-books/3:sign）。 */
const bId = (url: string): number =>
  Number(url.split('?')[0].split('/').filter(Boolean).slice(-1)[0].split(':')[0]) || 0

function page<T>(rows: T[]) {
  return { list: rows, total: rows.length, page: 1, size: 20 }
}

export const portalM2bOverrides: Record<string, unknown> = {
  'GET /apply/guide-suggestions': ((url: string) => {
    const q = url.includes('?') ? new URLSearchParams(url.slice(url.indexOf('?') + 1)) : null
    const status = q?.get('status') || ''
    const rows = SUGGESTIONS.filter((s) => !status || s.status === status)
    return page([...rows].sort((a, b) => b.id - a.id))
  }) as unknown,

  'POST /apply/guide-suggestions': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    const s: MockSuggestion = {
      id: SUGGESTIONS.length + 1,
      code: `SUG-2026-${String(SUGGESTIONS.length + 1).padStart(6, '0')}`,
      tenant_id: 1, title: b.title || '未命名建议', content_rich: b.content_rich ?? null,
      org_id: 1, status: 'PENDING', guideline_id: null, reject_reason: null, created_at: nowIso(),
    }
    SUGGESTIONS.unshift(s)
    return s
  }) as unknown,

  'POST /apply/guide-suggestions/{id}:accept': ((url: string) => {
    const s = SUGGESTIONS.find((x) => x.id === bId(url))
    if (s) {
      s.status = 'ACCEPTED'
      s.guideline_id = 3100 + s.id // 演示：真实后端会建 PGuideline(DRAFT) 并回填
    }
    return { guideline_id: s?.guideline_id ?? null }
  }) as unknown,

  'POST /apply/guide-suggestions/{id}:reject': ((url: string, ctx: { body: unknown }) => {
    const s = SUGGESTIONS.find((x) => x.id === bId(url))
    const b = (ctx.body || {}) as Record<string, any>
    if (s) {
      s.status = 'REJECTED'
      s.reject_reason = b.reason || '与本年征集方向不匹配'
    }
    return s || {}
  }) as unknown,

  'GET /apply/applications': (() => page([...APPLICATIONS].sort((a, b) => b.id - a.id))) as unknown,

  'POST /apply/applications': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    const a: MockApplication = {
      id: APPLICATIONS.length + 1,
      code: `APP-2026-${String(APPLICATIONS.length + 1).padStart(6, '0')}`,
      tenant_id: 1, title: b.title || '未命名申报', project_type: b.project_type || '开放课题',
      status: 'DRAFT', applicant_org_id: 1, applicant_type: 'EXTERNAL',
      total_budget: b.total_budget || '0.00', duration_months: b.duration_months || 12,
      abstract: b.abstract ?? null, pi_user_id: 9, updated_at: nowIso(),
    }
    APPLICATIONS.unshift(a)
    return a
  }) as unknown,

  'POST /apply/applications/{id}/submit': ((url: string) => {
    const a = APPLICATIONS.find((x) => x.id === bId(url))
    if (a) {
      a.status = 'SUBMITTED'
      a.updated_at = nowIso()
    }
    return a || {}
  }) as unknown,

  'POST /apply/task-books': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    const aid = Number(b.application_id) || 0
    const exist = TASK_BOOKS.find((t) => t.application_id === aid)
    if (exist) return exist
    const a = APPLICATIONS.find((x) => x.id === aid)
    const tb: MockTaskBook = {
      id: TASK_BOOKS.length + 1,
      code: `PRJ-2026-${String(TASK_BOOKS.length + 1).padStart(6, '0')}`,
      application_id: aid, status: 'DRAFT', print_template_code: 'TASK_BOOK',
      content_snapshot: {
        title: a?.title || '未命名课题', project_type: a?.project_type || '开放课题',
        pi_user_id: a?.pi_user_id || 9, applicant_org_id: a?.applicant_org_id ?? 1,
        total_budget: a?.total_budget || '0.00', duration_months: a?.duration_months || 12,
        abstract: a?.abstract ?? null, frozen_at: nowIso(),
      },
      sign_records: [], effective_date: null, project_id: null,
    }
    TASK_BOOKS.unshift(tb)
    return tb
  }) as unknown,

  'GET /apply/task-books/{id}': ((url: string) =>
    TASK_BOOKS.find((t) => t.id === bId(url)) || TASK_BOOKS[0] || {}) as unknown,

  'POST /apply/task-books/{id}:sign': ((url: string, ctx: { body: unknown }) => {
    const tb = TASK_BOOKS.find((t) => t.id === bId(url))
    const b = (ctx.body || {}) as Record<string, any>
    if (!tb) return {}
    const role = String(b.role || '').toUpperCase()
    if (!tb.sign_records.some((r) => r.role === role)) {
      tb.sign_records.push({ role, signerId: role === 'PI' ? tb.content_snapshot.pi_user_id : 2, signedAt: nowIso(), result: 'OK' })
    }
    const roles = new Set(tb.sign_records.map((r) => r.role))
    if (tb.status === 'DRAFT' && roles.has('PI') && (roles.has('MANAGER') || roles.has('LEADER'))) {
      tb.status = 'SIGNED'
      tb.effective_date = nowIso().slice(0, 10)
      tb.project_id = 9000 + tb.id // 演示：真实后端同事务建 E_PROJECT
    }
    return tb
  }) as unknown,

  'GET /project/{id}/progress-report': ((url: string) => {
    const pid = bId(url)
    return page(REPORTS.filter((r) => r.project_id === pid).sort((a, b) => b.id - a.id))
  }) as unknown,

  'POST /project/{id}/progress-report': ((url: string, ctx: { body: unknown }) => {
    const pid = bId(url)
    const b = (ctx.body || {}) as Record<string, any>
    const r: MockReport = {
      id: REPORTS.length + 1, project_id: pid, period: b.period || '2026Q1',
      report_type: b.report_type || 'QUARTERLY', progress_percent: Number(b.progress_percent) || 0,
      content_rich: b.content_rich ?? null, submitted_at: nowIso(),
    }
    REPORTS.unshift(r)
    return r
  }) as unknown,

  'GET /project/{id}/final-accept': ((url: string) => {
    const pid = bId(url)
    return FINAL_ACCEPTS.find((f) => f.project_id === pid) || {}
  }) as unknown,

  'POST /project/{id}/final-accept': ((url: string, ctx: { body: unknown }) => {
    const pid = bId(url)
    const b = (ctx.body || {}) as Record<string, any>
    const exist = FINAL_ACCEPTS.find((f) => f.project_id === pid)
    if (exist) return exist
    const fa: MockFinalAccept = {
      id: FINAL_ACCEPTS.length + 1, project_id: pid, status: 'APPLIED',
      output_summary: b.output_summary ?? null, apply_at: nowIso(),
      accept_at: null, approval_doc_id: null,
    }
    FINAL_ACCEPTS.unshift(fa)
    return fa
  }) as unknown,
}

Object.assign(overrides, portalM2bOverrides)
Object.assign(overrides, portalM2cOverrides)
