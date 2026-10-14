/**
 * Curated overrides —— 绩效评价屏（module M）
 * 契约：14-科研绩效评价-M.openapi.yaml（tag performance）
 * 分数/金额是字符串（NUMERIC 承载）。calculate/迁移类改写内存 store，使前端 reload 后可见状态流转。
 * 注意：override 函数只拿 url、拿不到请求体，calculate 覆写按固定样例补记录；真后端才按周期/范围实算 R/F/E/T。
 */

interface SchemeRec { id: number; code: string; name: string; period_type: string; effective_period: string; version: number; active: boolean; status: string; scope_dept_id?: number; scope_staff_type?: string }
interface FactorRec { id: number; scheme_id: number; factor_code: string; factor_name: string; weight: string; max_score?: string; data_source: string; sort_no: number }
interface ItemRec { id: number; record_id: number; factor_code: string; factor_name: string; metric_value: string; raw_score: string; weighted_score: string }
interface RecRec { id: number; scheme_id: number; scheme_name: string; staff_user_id: number; staff_name: string; period: string; dept_id?: number; total_score: string; rank?: number; status: string }
interface PayRec { id: number; code: string; record_id: number; payee_user_id: number; payee_name: string; amount: string; period: string; status: string; voucher_code?: string }

const schemes: SchemeRec[] = [
  { id: 1, code: 'PERF-2026-Q3', name: '2026 三季度科研绩效方案', period_type: 'QUARTER', effective_period: '2026Q3', version: 1, active: true, status: 'ACTIVE', scope_dept_id: 10 },
  { id: 2, code: 'PERF-2026-Y', name: '2026 年度综合绩效方案（草拟）', period_type: 'YEAR', effective_period: '2026', version: 1, active: false, status: 'DRAFT' },
]
const factors: FactorRec[] = [
  { id: 11, scheme_id: 1, factor_code: 'R_OUTPUT', factor_name: '论文/专利产出', weight: '40', max_score: '40', data_source: 'R_OUTPUT', sort_no: 1 },
  { id: 12, scheme_id: 1, factor_code: 'E_PROJECT', factor_name: '在研项目', weight: '20', max_score: '20', data_source: 'E_PROJECT', sort_no: 2 },
  { id: 13, scheme_id: 1, factor_code: 'F_INCOME', factor_name: '到账经费', weight: '30', max_score: '30', data_source: 'F_INCOME', sort_no: 3 },
  { id: 14, scheme_id: 1, factor_code: 'T_DEAL', factor_name: '转化合同额', weight: '10', max_score: '10', data_source: 'T_DEAL', sort_no: 4 },
]

let recSeq = 1200
const records: RecRec[] = [
  { id: 1001, scheme_id: 1, scheme_name: '2026 三季度科研绩效方案', staff_user_id: 100, staff_name: '周明远', period: '2026Q3', dept_id: 10, total_score: '20.80', rank: 1, status: 'CALCULATED' },
  { id: 1002, scheme_id: 1, scheme_name: '2026 三季度科研绩效方案', staff_user_id: 101, staff_name: '李工', period: '2026Q3', dept_id: 10, total_score: '17.50', rank: 2, status: 'CONFIRMED' },
  { id: 1003, scheme_id: 1, scheme_name: '2026 三季度科研绩效方案', staff_user_id: 102, staff_name: '王研究员', period: '2026Q3', dept_id: 11, total_score: '12.30', rank: 3, status: 'APPROVED' },
]
const itemsByRecord: Record<number, ItemRec[]> = {
  1001: [
    { id: 1, record_id: 1001, factor_code: 'R_OUTPUT', factor_name: '论文/专利产出', metric_value: '6', raw_score: '40', weighted_score: '16.00' },
    { id: 2, record_id: 1001, factor_code: 'E_PROJECT', factor_name: '在研项目', metric_value: '500000', raw_score: '20', weighted_score: '4.00' },
    { id: 3, record_id: 1001, factor_code: 'F_INCOME', factor_name: '到账经费', metric_value: '200000', raw_score: '30', weighted_score: '0.00' },
    { id: 4, record_id: 1001, factor_code: 'T_DEAL', factor_name: '转化合同额', metric_value: '150000', raw_score: '8', weighted_score: '0.80' },
  ],
}
const payouts: PayRec[] = [
  { id: 5001, code: 'PAY-2026-5001', record_id: 1003, payee_user_id: 102, payee_name: '王研究员', amount: '12300.00', period: '2026Q3', status: 'DRAFT' },
]
let paySeq = 5900

function seg(url: string, re: RegExp): number { const m = url.match(re); return m ? Number(m[1]) : 0 }
function withFactors(s: SchemeRec) { return { ...s, factors: factors.filter((f) => f.scheme_id === s.id) } }

export const overrides: Record<string, unknown> = {
  'GET /perf/schemes': { list: schemes, total: schemes.length, page: 1, size: 100 },
  'GET /perf/schemes/{id}': (url: string) => { const s = schemes.find((x) => x.id === seg(url, /\/schemes\/(\d+)/)); return s ? withFactors(s) : null },
  'POST /perf/schemes/{id}/activate': (url: string) => {
    const s = schemes.find((x) => x.id === seg(url, /\/schemes\/(\d+)/))
    if (s) { schemes.forEach((o) => { if (o.period_type === s.period_type && o.status === 'ACTIVE') { o.status = 'SUPERSEDED'; o.active = false } }); s.status = 'ACTIVE'; s.active = true }
    return s ? withFactors(s) : null
  },

  'POST /perf/schemes/{id}/calculate': (url: string) => {
    const id = seg(url, /\/schemes\/(\d+)/)
    const s = schemes.find((x) => x.id === id)
    // 固定补一条新记录演示（真后端按周期/范围实算 R/F/E/T）
    if (s) records.unshift({ id: ++recSeq, scheme_id: s.id, scheme_name: s.name, staff_user_id: 103, staff_name: '赵研究员', period: '2026Q3', dept_id: s.scope_dept_id ?? 10, total_score: '9.60', status: 'CALCULATED' })
    return { calc_batch: `BATCH-${id}-${Date.now()}`, period: '2026Q3', computed: 1, inserted: 1, updated: 0 }
  },

  'GET /perf/records': { list: records, total: records.length, page: 1, size: 100 },
  'GET /perf/records/{id}': (url: string) => records.find((r) => r.id === seg(url, /\/records\/(\d+)/)) ?? null,
  'GET /perf/records/{id}/detail': (url: string) => {
    const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/))
    return r ? { ...r, items: itemsByRecord[r.id] ?? [] } : null
  },
  'POST /perf/records/{id}/confirm': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'CONFIRMED'; return r ?? null },
  'POST /perf/records/{id}/appeal': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'APPEAL'; return r ?? null },
  'POST /perf/records/{id}/approve': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'APPROVED'; return r ?? null },
  'POST /perf/records/{id}/void': (url: string) => { const r = records.find((x) => x.id === seg(url, /\/records\/(\d+)/)); if (r) r.status = 'VOID'; return r ?? null },

  'GET /perf/me': (url: string) => ({ list: records.filter((r) => r.staff_user_id === 100).map((r) => ({ ...r, items: itemsByRecord[r.id] ?? [] })) }),

  'GET /perf/payouts': { list: payouts, total: payouts.length, page: 1, size: 100 },
  'POST /perf/payouts': () => { const p: PayRec = { id: ++paySeq, code: `PAY-2026-${paySeq}`, record_id: 1003, payee_user_id: 102, payee_name: '王研究员', amount: '12300.00', period: '2026Q3', status: 'DRAFT' }; payouts.unshift(p); return p },
  'POST /perf/payouts/{id}/approve': (url: string) => { const p = payouts.find((x) => x.id === seg(url, /\/payouts\/(\d+)/)); if (p) p.status = 'APPROVED'; return p ?? null },
  'POST /perf/payouts/{id}/pay': (url: string) => { const p = payouts.find((x) => x.id === seg(url, /\/payouts\/(\d+)/)); if (p) { p.status = 'PAID'; p.voucher_code = `VC-${p.id}` } return p ?? null },
  'POST /perf/payouts/{id}/reject': (url: string) => { const p = payouts.find((x) => x.id === seg(url, /\/payouts\/(\d+)/)); if (p) p.status = 'REJECTED'; return p ?? null },

  'GET /perf/ranking': (url: string) => {
    const u = new URL(url, 'http://x.local')
    const sid = Number(u.searchParams.get('scheme_id') || 1)
    const list = records.filter((r) => r.scheme_id === sid && r.status !== 'VOID')
      .sort((a, b) => Number(b.total_score) - Number(a.total_score))
      .slice(0, 20)
      .map((r, i) => ({ rank: i + 1, staff_user_id: r.staff_user_id, staff_name: r.staff_name, dept_id: r.dept_id, total_score: r.total_score }))
    return { list }
  },
}
