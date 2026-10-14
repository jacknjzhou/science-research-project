/**
 * Curated overrides —— 学术活动屏（module V）
 * 契约：13-学术活动管理-V.openapi.yaml（tag activity）
 * 键 = `METHOD /模板路径`（mock 用 matchRoute 命中的模板路径查表；带 {id} 的键用函数按 url 解析）。
 * 迁移类（submit/approve/hold/archive/cancel/delete）改写内存 store，使 reload 后状态可见；
 * 注意：override 函数只能拿到 url、拿不到请求体，故 approve 覆写统一置 APPROVED（真后端才区分 action）。
 */

type Status =
  | 'DRAFT' | 'SUBMITTED' | 'DEPT_REVIEW' | 'APPROVED'
  | 'HELD' | 'ARCHIVED' | 'REJECTED' | 'RETURNED' | 'CANCELLED'

interface ActRec {
  id: number; code: string; tenant_id: number; status: Status; security_level: string
  activity_type: string; level: string; host_mode: string; title: string; theme?: string
  start_at?: string; end_at?: string; venue?: string; host_unit?: string
  organizer_dept_id?: number; est_attendees?: number; budget_amount?: string
  creator_id: number; created_at: string; updated_at: string
}

const now = '2026-09-01T08:00:00Z'
const store: ActRec[] = [
  { id: 9001, code: 'ACT-2026-9001', tenant_id: 1, status: 'DRAFT', security_level: 'INTERNAL', activity_type: 'LECTURE', level: 'INTERNATIONAL', host_mode: 'HOST', title: '生成式模型在精密磨抛中的前沿进展', theme: '邀请 IEEE Fellow 做主题报告', start_at: '2026-10-15T01:30:00Z', venue: '行政楼报告厅', host_unit: '启元研究院', organizer_dept_id: 10, est_attendees: 180, budget_amount: '42000.00', creator_id: 100, created_at: now, updated_at: now },
  { id: 9002, code: 'ACT-2026-9002', tenant_id: 1, status: 'SUBMITTED', security_level: 'PUBLIC', activity_type: 'CONFERENCE', level: 'NATIONAL', host_mode: 'ATTEND', title: '中国机械工程学会年会（参会）', start_at: '2026-11-03T00:00:00Z', venue: '合肥', host_unit: '中国机械工程学会', organizer_dept_id: 10, est_attendees: 20, budget_amount: '96000.00', creator_id: 101, created_at: now, updated_at: now },
  { id: 9003, code: 'ACT-2026-9003', tenant_id: 1, status: 'DEPT_REVIEW', security_level: 'INTERNAL', activity_type: 'SEMINAR', level: 'CAMPUS', host_mode: 'HOST', title: '周五学术研讨：力位混合控制专题', start_at: '2026-09-26T07:00:00Z', venue: 'A3-205', host_unit: '智能制造研究室', organizer_dept_id: 11, est_attendees: 35, creator_id: 100, created_at: now, updated_at: now },
  { id: 9004, code: 'ACT-2026-9004', tenant_id: 1, status: 'APPROVED', security_level: 'INTERNAL', activity_type: 'TRAINING', level: 'PROVINCIAL', host_mode: 'SPONSOR', title: '省级科研仪器共享平台使用培训', start_at: '2026-10-08T00:30:00Z', venue: '测试中心', host_unit: '省科技厅', organizer_dept_id: 12, est_attendees: 60, budget_amount: '15000.00', creator_id: 102, created_at: now, updated_at: now },
  { id: 9005, code: 'ACT-2026-9005', tenant_id: 1, status: 'HELD', security_level: 'PUBLIC', activity_type: 'LECTURE', level: 'NATIONAL', host_mode: 'HOST', title: '院士讲坛：高端制造的中国路径', start_at: '2026-08-20T01:00:00Z', venue: '大礼堂', host_unit: '启元研究院', organizer_dept_id: 10, est_attendees: 500, creator_id: 103, created_at: now, updated_at: now },
  { id: 9006, code: 'ACT-2026-9006', tenant_id: 1, status: 'ARCHIVED', security_level: 'PUBLIC', activity_type: 'CONFERENCE', level: 'INTERNATIONAL', host_mode: 'ATTEND', title: 'ICRA 国际机器人大会（已归档）', start_at: '2026-06-01T00:00:00Z', venue: '维也纳', host_unit: 'IEEE RAS', organizer_dept_id: 10, est_attendees: 8, creator_id: 100, created_at: now, updated_at: now },
]

const participants: Record<number, { id: number; user_id?: number; guest_name?: string; role: string; report_title?: string }[]> = {
  9001: [
    { id: 7001, guest_name: 'Prof. Alan Reeves', role: 'SPEAKER', report_title: 'Diffusion priors for surface finishing' },
    { id: 7002, user_id: 100, role: 'CHAIR' },
  ],
  9005: [{ id: 7101, guest_name: '李院士', role: 'SPEAKER', report_title: '高端制造的中国路径' }],
}
let pidSeq = 7900

const reviews: Record<number, { id: number; review_level: number; reviewer_id: number; action: string; opinion?: string; acted_at: string }[]> = {
  9002: [{ id: 8001, review_level: 1, reviewer_id: 200, action: 'APPROVE', opinion: '同意，纳入年度计划', acted_at: now }],
  9003: [{ id: 8002, review_level: 1, reviewer_id: 201, action: 'RETURN', opinion: '请补充预算明细', acted_at: now }],
}
let ridSeq = 8900

function idFrom(url: string): number {
  const m = url.match(/\/activities\/(\d+)/)
  return m ? Number(m[1]) : 0
}
function find(id: number): ActRec | undefined {
  return store.find((a) => a.id === id)
}

export const overrides: Record<string, unknown> = {
  'GET /activities': { list: store, total: store.length, page: 1, size: 100 },

  'GET /activities/{id}': (url: string) => {
    const a = find(idFrom(url))
    const id = idFrom(url)
    return a ? { ...a, participants: participants[id] ?? [], reviews: reviews[id] ?? [] } : null
  },

  'GET /activities/{id}/participants': (url: string) => ({ list: participants[idFrom(url)] ?? [] }),

  'GET /activities/calendar': (url: string) => {
    const month = new URL(url, 'http://x.local').searchParams.get('month') || '2026-10'
    return { month, list: store.filter((a) => (a.start_at || '').startsWith(month)) }
  },

  'GET /activities/stats': (url: string) => {
    const gb = new URL(url, 'http://x.local').searchParams.get('group_by') || 'activity_type'
    const map: Record<string, number> = {}
    for (const a of store) {
      const key = String((a as any)[gb] ?? '未知')
      map[key] = (map[key] || 0) + 1
    }
    return { buckets: Object.entries(map).map(([key, count]) => ({ key, count })) }
  },

  // —— 迁移（改写内存 store；override 拿不到请求体，approve 统一 APPROVE）——
  'POST /activities': (url: string) => {
    const nid = Math.max(...store.map((a) => a.id)) + 1
    const rec: ActRec = { id: nid, code: `ACT-2026-${nid}`, tenant_id: 1, status: 'DRAFT', security_level: 'INTERNAL', activity_type: 'LECTURE', level: 'CAMPUS', host_mode: 'HOST', title: '新建活动（mock）', creator_id: 100, created_at: now, updated_at: now }
    store.push(rec)
    return rec
  },
  'POST /activities/{id}/submit': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'SUBMITTED'; a.updated_at = now } return a ?? null },
  'POST /activities/{id}/approve': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'APPROVED'; (reviews[a.id] ||= []).push({ id: ++ridSeq, review_level: 1, reviewer_id: 200, action: 'APPROVE', opinion: 'mock 通过', acted_at: now }); a.updated_at = now } return a ?? null },
  'POST /activities/{id}/hold': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'HELD'; a.updated_at = now } return a ?? null },
  'POST /activities/{id}/archive': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'ARCHIVED'; a.updated_at = now } return a ?? null },
  'POST /activities/{id}/cancel': (url: string) => { const a = find(idFrom(url)); if (a) { a.status = 'CANCELLED'; a.updated_at = now } return a ?? null },
  'DELETE /activities/{id}': (url: string) => { const id = idFrom(url); const i = store.findIndex((a) => a.id === id); if (i >= 0) store.splice(i, 1); return { id, deleted: i >= 0 } },

  'POST /activities/{id}/participants': (url: string) => { const id = idFrom(url); const p = { id: ++pidSeq, user_id: 100, role: 'MEMBER' }; (participants[id] ||= []).push(p); return p },
  'DELETE /activities/{id}/participants/{pid}': (url: string) => {
    const id = idFrom(url)
    const pm = url.match(/\/participants\/(\d+)/)
    const pid = pm ? Number(pm[1]) : 0
    const arr = participants[id] || []
    const i = arr.findIndex((p) => p.id === pid)
    if (i >= 0) arr.splice(i, 1)
    return { id: pid, deleted: i >= 0 }
  },
}
