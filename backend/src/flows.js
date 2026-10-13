/**
 * 核心写流程（状态机）。每个 handler 返回 { status, code, message, data }；
 * data 缺省时由 server 依契约 200 schema 生成后再叠加实体字段。
 * 业务错误码沿用 design/README §4：40001 校验 / 40401 不存在 / 40901+ 冲突。
 */
import { table, nextId } from './store.js'

const now = () => new Date().toISOString()

function fail(code, message, status = 400) { return { status, code, message, data: null } }

// —— 申报（P）——
const APP_FLOW = {
  DRAFT: ['SUBMITTED'],
  SUBMITTED: ['FORMAL_CHECK', 'WITHDRAWN'],
  FORMAL_CHECK: ['RECOMMENDED', 'UNDER_REVIEW', 'WITHDRAWN'],
  RECOMMENDED: ['UNDER_REVIEW'],
  UNDER_REVIEW: ['INTERVIEWING', 'DECIDED'],
  INTERVIEWING: ['DECIDED'],
  DECIDED: ['PUBLISHED'],
  PUBLISHED: ['SIGNED'],
  SIGNED: ['EXECUTING'],
}
function canTransit(from, to) { return (APP_FLOW[from] || []).includes(to) }

export const flows = {
  'POST /apply/applications': (req) => {
    const t = table('applications')
    const id = nextId()
    const rec = { id, status: 'DRAFT', creator_id: 90001, created_at: now(), updated_at: now(), ...(req.body || {}) }
    rec.id = id
    t.set(id, rec)
    return { status: 200, data: rec }
  },
  'POST /apply/applications/{id}/submit': (req, p) => {
    const t = table('applications')
    const rec = t.get(Number(p.id)) || { id: Number(p.id), status: 'DRAFT' }
    if (rec.status !== 'DRAFT' && rec.status !== 'FORMAL_CHECK') {
      return fail(40905, `当前状态 ${rec.status} 不允许提交/撤回`, 409)
    }
    rec.status = 'SUBMITTED'
    rec.submitted_at = now()
    rec.updated_at = now()
    t.set(rec.id, rec)
    return { status: 200, data: rec }
  },
  'POST /apply/applications/{id}:withdraw': (req, p) => {
    const t = table('applications')
    const rec = t.get(Number(p.id))
    if (!rec) return fail(40401, '申报不存在', 404)
    if (!canTransit(rec.status, 'WITHDRAWN')) {
      return fail(40905, '已进入评审，禁止撤回', 409)
    }
    rec.status = 'WITHDRAWN'
    rec.updated_at = now()
    return { status: 200, data: rec }
  },
  'POST /apply/review/tasks/{id}:score': (req, p) => {
    const t = table('reviewTasks')
    const id = Number(p.id)
    const rec = t.get(id) || { id, status: 'ASSIGNED' }
    rec.scores = req.body?.scores || req.body || {}
    rec.status = 'SUBMITTED'
    rec.scored_at = now()
    t.set(id, rec)
    return { status: 200, data: rec }
  },

  // —— 经费（F）——
  'POST /expenses': (req) => {
    const t = table('expenses')
    const id = nextId()
    const rec = { id, status: 'DRAFT', created_at: now(), ...(req.body || {}) }
    rec.id = id
    t.set(id, rec)
    return { status: 200, data: rec }
  },
  'POST /expenses/{expenseId}/submit': (req, p) => {
    const t = table('expenses')
    const id = Number(p.expenseId)
    const rec = t.get(id) || { id, status: 'DRAFT' }
    if (rec.status !== 'DRAFT' && rec.status !== 'AI_REJECTED') {
      return fail(40901, `报销单状态 ${rec.status} 不可提交`, 409)
    }
    rec.status = 'SUBMITTED'
    rec.submitted_at = now()
    t.set(id, rec)
    return { status: 200, data: rec }
  },

  // —— 成果认领（R）——
  'POST /output/claim': (req) => {
    const t = table('outputs')
    const ids = req.body?.outputIds || (req.body?.outputId ? [req.body.outputId] : [])
    const claimed = []
    for (const oid of ids) {
      const id = Number(oid)
      const rec = t.get(id) || { id, claim_status: 'UNCLAIMED' }
      rec.claim_status = 'CLAIMED'
      rec.claimed_at = now()
      t.set(id, rec)
      claimed.push(id)
    }
    return { status: 200, data: { claimed_count: claimed.length, claimed_ids: claimed } }
  },

  // —— 转化（T）——
  'POST /disclosure': (req) => {
    const t = table('disclosures')
    const id = nextId()
    const rec = { id, status: 'DRAFT', created_at: now(), ...(req.body || {}) }
    rec.id = id
    t.set(id, rec)
    return { status: 200, data: rec }
  },
  'POST /disclosure/{id}/submit': (req, p) => {
    const t = table('disclosures')
    const id = Number(p.id)
    const rec = t.get(id) || { id, status: 'DRAFT' }
    rec.status = 'PUBLISHED'
    rec.published_at = now()
    t.set(id, rec)
    return { status: 200, data: rec }
  },
  'POST /deal': (req) => {
    const t = table('deals')
    const id = nextId()
    const rec = { id, status: 'DRAFT', created_at: now(), ...(req.body || {}) }
    rec.id = id
    t.set(id, rec)
    return { status: 200, data: rec }
  },
  'POST /deal/{id}/sign': (req, p) => {
    const t = table('deals')
    const id = Number(p.id)
    const rec = t.get(id) || { id, status: 'NEGOTIATING' }
    rec.status = 'SIGNED'
    rec.signed_at = now()
    t.set(id, rec)
    return { status: 200, data: rec }
  },
}

// GET-by-id 命中已写实体时的映射：模板路径 -> { table, idParam }
export const READ_BACK = {
  'GET /apply/applications/{id}': { table: 'applications', idParam: 'id' },
  'GET /expenses/{expenseId}': { table: 'expenses', idParam: 'expenseId' },
  'GET /deal/{id}': { table: 'deals', idParam: 'id' },
}
